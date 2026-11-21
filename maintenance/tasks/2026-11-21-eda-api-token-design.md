# EDA 插件认证改造：去掉本机桥接，改用专用 API Token

- Status: proposed
- Date: 2026-11-21
- 影响目录：`plugins/jlc-eda/`、新增 `server/ubuntu22.04/odoo_addons/lab_eda/`、`lab_team_web`（管理页入口）
- 不改动：现有 50 个 `auth='user'` 路由、权限模型、网页端任何行为

## 一、为什么

用户要求：**只装插件，不装别的东西。**

现状包里带 `node.exe`（92 MB）和一个必须双击启动的本机桥接进程，包体积 89 MB。这不是插件，是插件加一个常驻服务。

根因（已查官方文档确认）：EDA 的 `sys_ClientUrl.request()` 的 `options` 只暴露 `headers` 和 `integrity`，**没有 `credentials`**；而 `Cookie` 是 [Fetch 规范的禁止请求头](https://developer.mozilla.org/en-US/docs/Glossary/Forbidden_request_header)，浏览器层面设不进去。**Cookie 会话在 EDA 插件里物理上不可能。**

而 `Authorization` 不是禁止头，可以自由设置。Odoo 19 原生支持 bearer 认证。

## 二、为什么用独立模块

网页端（`lab_team_web`）和 EDA 插件共用现有 `/lab/api/*` 路由。改它们的 `auth` 会让网页端登录行为跟着变，没必要承担这个风险。

而且插件不需要网页端那套：`bootstrap` 返回的 `borrowers`（全部可领用人）、`can_receipt` / `can_return` / `can_manage_labels` 等权限，插件都用不上。

所以新建 `lab_eda` 模块，独立端点，内部转发到现有业务方法——**业务逻辑只有一套**，不在 EDA 模块里重写。

## 三、认证设计

### 3.1 为什么不用 Odoo 原生 API Key

Odoo 原生 `res.users.apikeys` 做不到「发放权锁在管理员」：普通用户在自己的偏好设置里**仍能自己生成 Key**（`res_users.py` 的 `check_access_make_key()` 只检查 `_is_internal()`）。这是原生行为，不改源码改不掉。

而用户明确要求：**API 发放权必须锁在管理员身上，且每个 Key 的权属要清楚。**

所以自建 `lab.eda.token`。

### 3.2 `lab.eda.token` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | Many2one `res.users`，required | 绑定的 Odoo 用户；出库时 `env.uid` 就是它 |
| `token_hash` | Char，required，index | `sha256(token)`；**明文不落库** |
| `name` | Char | 备注，如「张三的 EDA 插件」 |
| `active` | Boolean，default True | 吊销开关 |
| `expires_at` | Datetime | 默认发放时 +1 年，管理员可改 |
| `create_uid` / `create_date` | 原生 | 谁发的、什么时候 |
| `last_used_at` | Datetime | 最近一次使用，便于清理僵尸 Key |

**不存明文 token**：生成时显示一次，之后只存哈希。管理员丢了只能重发。

### 3.3 权限（ACL + ir.rule）

```
lab.eda.token   group_lab_manager: read=1, write=1, create=1, unlink=1
lab.eda.token   group_user:        read=1, write=0, create=0, unlink=0
```

ir.rule：
- `group_lab_manager` → 全公司可见（要能替任何人发/吊销）
- 其他用户 → `[('user_id', '=', user.id)]`，只能看到自己的（用于插件里显示「这个 Key 是谁的」）

**发放权只在 `group_lab_manager`**。系统管理员如果要发，需要被加入该组——这是用户明确选择的边界（「api 发放权给库存管理员」）。

### 3.4 Token 格式与校验

- 格式：`eda_` + 32 字节 `secrets.token_urlsafe(32)`，带前缀便于在日志/代码里识别和脱敏
- 校验：`sha256(token)` 查表 → 检查 `active` 且 `expires_at` 未过期 → 取 `user_id`
- 恒定时间比较（`hmac.compare_digest`）

### 3.5 认证装饰器

```python
def eda_auth(handler):
    @functools.wraps(handler)
    def wrapper(self, *args, **kwargs):
        header = request.httprequest.headers.get('Authorization', '')
        if not header.lower().startswith('bearer '):
            return _error(401, 'MISSING_TOKEN', '请在插件里填写 EDA 密钥。')
        token = header[7:].strip()
        rec = request.env['lab.eda.token'].sudo()._resolve(token)
        if not rec:
            return _error(401, 'INVALID_TOKEN', 'EDA 密钥无效、已过期或已吊销。')
        request.update_env(user=rec.user_id.id)
        rec._touch()
        return handler(self, *args, **kwargs)
    return wrapper
```

`request.update_env(user=...)` 是 Odoo 19 的公开 API（`http.py:1856`），`_auth_method_bearer` 自己就是这么用的（`ir_http.py:241`）。

## 四、端点清单

插件实际调用 8 个联网接口，全部在 `lab_eda` 里转发：

| EDA 端点 | 转发到 | 说明 |
|---|---|---|
| `POST /lab/api/eda/bootstrap` | `lab.workflow.common.lab_bootstrap()` | 只取权限和本人信息，**不返回全部领用人** |
| `POST /lab/api/eda/catalog/search` | `lab.catalog.item.search_unified()` | |
| `POST /lab/api/eda/catalog/detail` | `lab.catalog.item.detail()` | |
| `POST /lab/api/eda/catalog/categories` | 同现有实现 | |
| `POST /lab/api/eda/catalog/equivalents` | `lab.catalog.item.equivalents()` | |
| `POST /lab/api/eda/inventory/locations` | `lab.workflow.common.lab_locations()` | |
| `POST /lab/api/eda/inventory/issue` | `lab.workflow.common.lab_issue()` | 出库 |
| `POST /lab/api/eda/inventory/issue_preview` | dry-run，不写库 | 见 §5.3 |

**不提供**：`receipt` / `return` / `history` / `resolve` / `asset`（图片）。

`/lab/api/eda/bootstrap` 与现有 `/inventory/bootstrap` 的差别：只返回

```json
{
  "permissions": {"can_issue": true, "can_issue_for_others": false, "is_manager": false},
  "user": {"id": 7, "name": "张三"},
  "inventory_revision": "..."
}
```

**不返回 `borrowers` 全量列表**——普通操作员本来就只能领自己，管理员才需要选人。需要时单独调 `GET /lab/api/eda/borrowers`（仅 manager 可用）。

## 五、出库

### 5.1 权限沿用现有规则

不新增任何权限判断。`lab_can_issue_for_others()` 已经写好：

```python
def lab_can_issue_for_others(self):
    return (has_group('lab_workflow.group_lab_manager')
            or has_group('stock.group_stock_manager'))
```

- 操作员 → `lab_authorized_borrowers()` 只返回本人，`borrower_id` 强制为自己
- 管理员 → 可选他人

### 5.2 记录权属

`lab.issue` 有两个独立字段（已核实 `lab_issue.py:42-43`）：

- `actor_id` = `env.uid` = **Token 绑定的用户**（`lab_workflow_api.py:547`）
- `borrower_id` = 提交时选的领用人

所以「谁操作的」和「算谁头上」天然分开，且**操作人一定是 Key 的主人**，不会变成管理员。

### 5.3 保留 dry-run 预览

现有桥接模式有「先预览分配，再确认提交」。这个环节保留：

- `POST /lab/api/eda/inventory/issue_preview` → 返回按袋分配方案，**不写任何数据**
- 插件展示后，用户确认 → `POST /lab/api/eda/inventory/issue` 真实提交
- 四态结果（SUCCESS / RECONFIRM / UNKNOWN / FAILED）沿用 `shared/outbound.js`，不改

## 六、插件改动

**删除**：
- `bridge/` 整个目录（含 `node.exe` 92 MB、`credentials.mjs`、`relay-token.txt` 逻辑）
- `src/main/relay.js`
- 配对码相关的一切
- `src/main/odoo.js` 的 Cookie 会话逻辑
- `catalog.image` 调用与详情页图片框

**新增**：
- `src/main/odoo.js` 改成 bearer：每个请求带 `Authorization: bearer <token>`
- 设置页：服务器地址 + EDA 密钥（两个输入框）
- token 存 `sys_Storage`（**明文**，见 §8）

**包体积**：89 MB → 约 100 KB（只剩 `.eext`）。

## 七、管理入口

「管理」页（`lab_team_web` 的 `/team/lab/settings`，已确认只有 `group_lab_manager` 可见）新增「EDA 密钥」区块：

```
┌─ EDA 密钥 ─────────────────────────────────────┐
│ 成员        备注              有效期      状态   │
│ 张三        EDA 插件          2027-11-21  有效   │
│ 李四        EDA 插件          2026-12-01  已吊销 │
│                                                │
│ [选择成员 ▾] [备注____] [有效期 1 年 ▾] [发放]  │
└────────────────────────────────────────────────┘
```

发放后弹窗显示 token **一次**，附「关闭后无法再查看，请立即复制」。

## 八、安全边界（必须写进文档和 UI）

**Token 明文存在插件配置里。** 插件端只有 `sys_Storage`（明文键值），拿不到 Windows DPAPI。这和浏览器保存密码同一水位。

- 防的是：别人看到你的屏幕、拷走配置文件（可接受，token 可吊销）
- 防不住：能读你 Windows 账户下文件的其他程序

**缓解**：
- Token 绑定到具体用户，吊销即时生效
- 管理页能看到每个 token 的 `last_used_at`，异常使用可发现
- 离职流程：管理员吊销该用户的 token → 插件立即 401

## 九、实施顺序

1. `lab_eda` 模块骨架 + `lab.eda.token` 模型 + ACL/ir.rule + 测试（TDD）
2. `eda_auth` 装饰器 + 8 个转发端点 + 测试
3. `lab_team_web` 管理页「EDA 密钥」区块
4. 插件：删桥接、改 bearer、改设置页
5. 打包验证：`credentials.mjs` 不在包里、`node.exe` 不在包里、包体积 < 1 MB
6. 文档：`CURRENT_STATE.md`、插件 `README`/`CHANGELOG`/`MAINTENANCE`、`AGENTS.md` 安全边界

## 十、验收

**服务端**
- 无 token → 401 `MISSING_TOKEN`
- 错误 token → 401 `INVALID_TOKEN`
- 过期 token → 401
- 已吊销 token → 401
- 有效 token → 200，且 `env.uid` 等于 token 绑定用户
- 操作员用 token 出库 → `actor_id` = 操作员，`borrower_id` = 操作员
- 管理员用 token 出库选他人 → `actor_id` = 管理员，`borrower_id` = 所选人
- 普通用户访问 `/lab/api/eda/borrowers` → 403

**插件**
- 只填地址 + token 即可登录，不启动任何外部进程
- 包内不含 `node.exe`、`bridge/`、`credentials.mjs`
- 包体积 < 1 MB

**未验证项要如实记录**：EDA 宿主实机未测。

## 十一、风险

| 风险 | 处理 |
|---|---|
| Token 泄露 | 可即时吊销；`last_used_at` 可发现异常；建议每年轮换 |
| 用户把 token 发给别人共用 | 管理员可从 `actor_id` 发现异常；必要时吊销重发 |
| 插件端明文存储 | 已在 §8 写明；与浏览器保存密码同水位 |
| 新增模块增加部署面 | 只新增一个模块，不改现有 50 个路由 |
| 图片功能丢失 | 详情页显示「无图片」，主流程不受影响 |
