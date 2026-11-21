# EDA 插件：免登录持久化 + BOM 等效件检索 设计

- Status: proposed
- Date: 2026-11-20
- 影响目录：`plugins/jlc-eda/`（bridge + src）、`server/ubuntu22.04/odoo_addons/lab_catalog/`
- 不改动：`clients/app`、`lab_workflow` 的领用/出库状态机、任何 Odoo 原生界面

## 一、为什么要做

### 1.1 免登录

用户原话：「我们的 EDA 插件功能要求要能保存账号密码啊，不然我每次都要重新登录」。

现状（已核实）：

| 层 | 凭证存放 | 重启后 |
|---|---|---|
| 插件 iframe（`src/iframe/app.js`） | `state.settings.password` 仅内存 | 丢 |
| 插件主模块（`src/main/index.js`） | `globalThis.__LAB_ODOO_V3_RUNTIME__` 仅内存 | 丢 |
| 本机桥接（`bridge/server.mjs`） | `CookieJar` 仅进程内存 | 丢 |
| `sys_Storage` | 只存 `serverUrl`/`db`/`login`/`panel` | 保留，但**没有密码** |

`src/main/config.js:2` 明写「The password is NEVER written here」，`README.md:129` 也写「插件端密码和配对码只通过私有 MessageBus 传递，不写入 `sys_Storage`」。这是既有设计，不是缺陷。

所以「每次重登」的真正原因是**桥接和插件两处都是内存态**，而 Odoo 会话 Cookie 只有桥接拿得到。

### 1.2 等效件

用户原话：「与当前PCB对应的BOM对比，不是说我们没有完全对应的就不选了，你应该把对应的符合要求的器件展示出来让我们能够选择替换」。

现状（已核实）：

- `src/shared/bom.js:77 compareLine()` 只做 C 编号精确匹配，返回 `NOT_IN_CATALOG` / `SHORT`，**不带任何候选**。
- `grep -rn "equivalent|等效|替代|substitut"` 在 `src/` 下零命中 —— 功能完全未实现。
- `REQUIREMENTS.md:53-68` 已写死 S5 规则，但从未落地。

服务端原料齐备（已核实）：

- `lab.catalog.item.package`（有索引 `lab_catalog_item_pkg_idx`）
- `lab.catalog.param`（`code` / `name` / `value`，四组复合索引）
- `lab.catalog.item.search_params` + `pg_trgm` GIN 索引
- `lab_inventory/tools/param_search.py:343 normalize_value()` 已把 阻值/容值/耐压/精度/功率 归一化成别名（`0.1uF` 与 `100nF` 互认）
- `lab.catalog.item.search_unified()` 已支持 `packages` + `parameters` + `stock_only` 组合过滤

唯一缺口：`search` 返回的 `parameters` 是空数组（`lab_catalog_item.py:_decorate()` 里写死 `'parameters': []`），所以纯客户端方案拿不到「哪些参数一致」。

## 二、非目标

- 不做插件端密码存储（`sys_Storage` 无加密能力，自加密等于没加密）。
- 不做「自动替换」：等效件必须逐行勾选才进分配（S5 规则 3）。
- 不改 `lab_workflow` 的出库状态机；替代关系只写进 `note`。
- 不为 Linux 桥接实现密码存储（无 DPAPI 对应物）。
- 不做 Odoo API Key 方案（P3），本轮不选。

## 三、方案 A：免登录（P1 会话持久化 + P2 DPAPI 密码）

### 3.1 为什么在桥接侧而不是插件侧

插件 iframe 只有 `sys_Storage`（明文键值）。若在那里加密，密钥也只能存在 `sys_Storage`，拷贝存储即可还原——这是编码不是加密，且违反 `AGENTS.md`「凭据使用 OS 安全存储」。

桥接是原生 Node 进程（`bridge/runtime/node.exe` v24.19.0），可以调用 Windows DPAPI。已实测：

```
ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString
→ 01000000d08c9ddf0115d1118c7a00c04fc297eb...   (标准 DPAPI blob)
→ 解密往返一致
```

DPAPI 的性质：密文绑定当前 Windows 账户；文件被拷到别的机器、或被别的账户打开都解不开。这与 Chrome/Edge 保存密码同一水位。**它防不住以同一 Windows 账户身份运行的恶意程序**——这一点必须在 UI 上写明，不能声称「绝对安全」。

### 3.2 存储内容

新增 `plugins/jlc-eda/bridge/lab-credentials.dat`（与已有的 `relay-token.txt` 同目录，`.gitignore` 排除）。

内容为 **DPAPI 加密后的 JSON**：

```json
{
  "version": 1,
  "upstream": "https://team.l-creation.club",
  "db": "LcHardwareHouse",
  "login": "warehouse01",
  "password": "……",
  "cookies": [["session_id", "……"]],
  "savedAt": "2026-11-20T10:00:00.000Z"
}
```

Cookie 和密码**走同一个加密文件**。理由：Odoo 的 `session_id` 本身就是 bearer 凭证，明文落盘与明文密码等价，没有理由只加密一个。

`upstream` / `db` / `login` 也一起加密，避免「换个账号但 cookie 还是旧的」这类错配。

### 3.3 桥接新增能力

`bridge/server.mjs`：

1. **启动时**：`loadCredentials()` —— 读 `.dat`，DPAPI 解密，把 `cookies` 灌回 `CookieJar`，密码留在闭包里（不打印、不进日志）。
2. **登录成功时**：`saveCredentials()` —— 把当前 jar + 本次登录的密码加密写盘。
3. **新路由 `POST /session/restore`**（需配对码）：
   - 先拿恢复的 jar 调上游 `/web/session/get_session_info`
   - 200 且 `uid` 有效 → `{ok: true, data: {restored: 'cookie', uid, name, username, db}}`
   - 失效且**有保存的密码** → 用保存的密码重新 `/web/session/authenticate`，成功后 `saveCredentials()` 刷新 jar → `{restored: 'password', ...}`
   - 都失败 → `{ok: true, data: {restored: 'none'}}`（**不是错误**，让插件回落到登录表单）
4. **`POST /logout` 时**：清 jar 并**删除保存的密码**（保留 `upstream`/`db`/`login`），下次必须手动输密码。这是「注销」应有的语义。
5. **`--no-save-credentials` 启动参数**：完全不写盘，供公用机器使用。

日志约束：`log()` 只输出事件名与 `uid`/`db`，绝不输出密码、cookie 值或 `.dat` 内容。

### 3.4 插件侧改动

`src/main/index.js`：

- `session.login` 成功后调用一次 `session.restore` 之前不需要改；改为在 `app.init` 之后、UI 渲染前尝试 `client.restoreSession()`。
- `src/main/relay.js` 新增 `restoreSession()` → `POST /session/restore`，把结果映射成 `publicSession()`。
- `src/main/odoo.js`（直连模式）不实现 restore，直接返回 `{restored: 'none'}`——直连模式本来就拿不到 cookie。

`src/iframe/app.js`：

- 初始化流程里，`app.init` 之后若 `session.active === false` 且模式是 relay，调一次 `session.restore`；成功则跳过登录页。
- 设置页的「Odoo 密码」输入框占位文字改为「已保存；留空则沿用保存的密码」，并在下面加一行说明：
  - Windows：「密码经 Windows DPAPI 加密保存在本机桥接目录，绑定当前 Windows 账户。它不能防止以该账户身份运行的其他程序读取。」
  - 非 Windows：「本平台不支持密码保存，每次需手动登录。」
- 「注销」按钮的确认文案加一句「注销会同时删除本机保存的密码」。

### 3.5 安全边界（写进 `plugins/jlc-eda/MAINTENANCE.md`）

- `.dat` 只由桥接读写，插件永远拿不到解密后的密码。
- 插件与桥接之间仍只传配对码；配对码仍是 `relay-token.txt` 固定值。
- DPAPI 的保护范围是「文件被拷走 / 别的账户读取」，不是「本账户内的恶意程序」。
- 公用机器用 `--no-save-credentials` 启动。

## 四、方案 B：BOM 等效件（E3 服务端批量端点）

### 4.1 接口

`POST /lab/api/catalog/equivalents`（`type='jsonrpc'`, `auth='user'`）

请求：

```json
{
  "lines": [
    {"item_key": "lcsc:C14663", "quantity": 4},
    {"item_key": "lcsc:C25804", "quantity": 1}
  ],
  "limit_per_line": 5
}
```

响应：

```json
{
  "lines": [
    {
      "item_key": "lcsc:C14663",
      "source": {"package": "0402", "category_name": "贴片电容", "parameters": [...]},
      "basis": "params",
      "candidates": [
        {
          "item_key": "lcsc:C1525",
          "catalog_code": "C1525",
          "name": "0.1uF ±10% 50V X7R 0402",
          "brand": "国巨",
          "package": "0402",
          "available": 320,
          "locations": [...],
          "bags": [...],
          "matched": [{"name": "容值", "value": "0.1uF"}, {"name": "封装", "value": "0402"}],
          "conflicts": [],
          "confidence": "strong"
        }
      ]
    }
  ]
}
```

`basis` 取值：`params`（封装 + 关键参数全命中）/ `package_category`（参数不足，退化为同封装同类别，标注依据弱）/ `none`（无候选）。

`confidence` 取值：`strong` / `weak`（对应 S5 规则 5 的「疑似等效」）。

### 4.2 判定规则

对每条 BOM 行：

1. 取源器件的 `package`、`category_id`、`key_pairs(parameters)`。
2. 调 `search_unified(packages=[pkg], category_id=cat, parameters={...}, stock_only=True)`。
   - 参数为空或 `param_count == 0` → 退化到 `packages=[pkg]` + `category_id`，`basis='package_category'`。
3. 对每个候选，**排除同 C 编号**，逐项比对：
   - **容值 / 阻值 / 精度 / 介质**：`normalize_value()` 归一化后必须完全一致，否则记为 `conflicts`。
   - **耐压 / 功率**：解析数值比较，候选 **低于** 需求 → `conflicts`。
   - 其余参数：不一致只记 `conflicts`，不直接排除（可能是无关参数）。
4. `conflicts` 非空 → 该候选标 `confidence: 'weak'`，UI 仍展示但提示「参数有差异」。
5. 有 `conflicts` 且冲突项属于耐压/容值/阻值 → **直接丢弃**（S5 规则 4「不能判定为等效的不猜」）。
6. 按 `available` 降序，取前 `limit_per_line` 条。

实现放在 `lab_catalog_item.py` 新增 `equivalents(lines, limit_per_line)`，复用 `_workflow_overlay()` 拿库位/袋，复用 `param_search.normalize_value()` 做归一化。控制器只做参数转换。

### 4.3 批量语义

一次请求处理整张 BOM（上限 200 行），内部循环但**共享一次 `_live_state()`**（库存快照），避免 100 行 BOM 触发 100 次库存查询。

`ALLOWED_RPC_PATHS`（`bridge/server.mjs`）加入 `/lab/api/catalog/equivalents`。

### 4.4 UI

主表**完全不变**——C 编号精确匹配仍是唯一主行（S5 规则 1）。

在每个 `SHORT` 或 `NOT_IN_CATALOG` 行下方，追加一个可展开的「等效候选」子行：

```
┌────────┬──────────┬──────────────┬──────┬──────┬──────┬────────────────────┐
│ 缺料   │ C14663   │ 0.1uF 0402   │ C1.. │  4   │  0   │ 无库存             │
│        │ ▸ 等效 2 │              │      │      │      │                    │
├────────┴──────────┴──────────────┴──────┴──────┴──────┴────────────────────┤
│ ☐ C1525  国巨  0.1uF 0402   可用 320   A-01-03  袋 T0001,T0002            │
│        一致：容值 0.1uF、封装 0402、耐压 50V                                │
│ ☐ C7711  三星  0.1uF 0402   可用 45    A-02-01  袋 T0031                  │
│        一致：容值 0.1uF、封装 0402                                          │
│        差异：耐压 25V < 需求 50V  ← 标灰，不可勾选                          │
└────────────────────────────────────────────────────────────────────────────┘
```

交互：

- 勾选一条候选 → 该候选进入出库分配（`item_key` 换成候选的 C 编号，数量取该行的缺口 `gap`）。
- 勾选后主行状态改为「已选替代」，并显示 `C14663 → C1525`。
- 同一行只能勾一条候选（勾第二条自动取消第一条）。
- `confidence: 'weak'` 的候选可以勾，但勾选框旁有黄色提示。
- 有硬冲突（耐压/容值/阻值）的候选**不可勾选**，置灰。

`openBomOutbound()` 的 `bomOutboundSourceLines(rows)` 改为：主行用自身 C 编号，已勾选的替代行用候选 C 编号，数量为 `gap`。

`note` 拼装：`BOM 一键出库；替代：C14663 → C1525 ×2`。

### 4.5 出库流程不变

服务端 `inventory/issue` 本来就按 `item_key` + 袋分配，替代件只是换了个 `item_key`，**领用状态机、四态结果、幂等键全部不动**。这是选 E3 而不是改出库接口的关键理由。

## 五、实施顺序

1. **服务端** `equivalents()` + 控制器 + 测试（TDD：先写 `test_equivalents_*`，看它红，再实现）。
2. **桥接** DPAPI 存取 + `/session/restore` + `/logout` 清密码 + `--no-save-credentials`。
3. **插件主模块** `restoreSession()` 接线。
4. **插件 UI** 等效栏 + 勾选 + note 拼装 + 设置页文案。
5. `npm run build` 重建 `dist/`，`npm test` 全绿。
6. 更新 `REQUIREMENTS.md` S5 状态、`CHANGELOG.md`、`MAINTENANCE.md` 安全边界。

## 六、验收

**免登录**
- 桥接重启后，插件打开即已登录（cookie 仍有效）。
- 手动让 cookie 失效（Odoo 端注销），桥接重启，插件仍自动登录（走保存的密码）。
- 点「注销」后，`.dat` 里的密码被清除，下次必须手输。
- 用 `--no-save-credentials` 启动，目录下不产生 `.dat`。
- 把 `.dat` 拷到另一台 Windows 机器，桥接启动后解密失败并**明确报错**，不静默降级。

**等效件**
- 按 `REQUIREMENTS.md:68` 的验收场景：0.1uF 0402 的 BOM 行，实验室只有另一个 C 编号的同规格电容 → 主行「缺料」，等效栏列出该电容 + 库位 + 袋码 + 一致项。
- 勾选后出库，领用单备注含 `C14663 → C1525 替代`。
- 耐压低于需求的候选置灰、不可勾选。
- 100 行 BOM 只发一次 `/equivalents` 请求。

## 七、风险

| 风险 | 处理 |
|---|---|
| DPAPI 依赖 PowerShell 可用 | 启动时探测；不可用则禁用密码保存并在日志写明，不影响桥接其他功能 |
| 加密文件被同账户恶意程序读取 | 在设计文档和 UI 都写明；提供 `--no-save-credentials` |
| 参数缺失导致误判等效 | `confidence: 'weak'` + 显式「依据较弱」；硬冲突直接丢弃 |
| 等效检索拖慢 BOM 刷新 | 批量端点 + 共享 `_live_state()` + `limit_per_line` 上限 |
| 用户勾了替代但候选库存刚好被领走 | 出库仍是 dry-run → 确认 → 提交，`RECONFIRM` 四态照常生效 |
