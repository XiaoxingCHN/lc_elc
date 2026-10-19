# 实验室库存联动（嘉立创 EDA 专业版 × Odoo 19）

版本 **3.0.3**，扩展 UUID 沿用旧版 `1329a87d576b4b8cbb8592b1c1012b8b`，可在扩展管理器中按同一扩展升级。

3.0.3 修复：真机 BOM 对比报「消息总线调用失败：undefined」——改为按当前编辑器优先用 `sch_ManufactureData.getBomFile`（原理图 BOM 导出）再试 `pcb_ManufactureData`，每次导出限时 7 秒，超时即回退原理图读取，绝不再卡死面板；桥接错误信息改为带方法名与超时秒数。
3.0.2 新增：BOM 页签默认读取**当前工程完整 BOM**（EDA 制造数据导出，覆盖全部图页）并与云端库存对比；对比结果支持**一键出库**（按袋 FIFO 分配 → 预览 → 真实领用单）；界面改为**Apple 液态玻璃**风格；登录会话在切换菜单后保持。
3.0.1 修复：扩展主模块改为读取 EDA 注入的 `eda` 绑定（真实宿主不会给扩展入口设置 `window.eda` / `globalThis.eda`），此前在真机点击「库存联动」菜单不会打开面板。

推荐使用 **本机桥接**：EDA 插件 → `127.0.0.1:49621` 本机 relay → 现有 Odoo。
relay 是零 npm 依赖的 Node 程序，自己管理 Odoo 会话 Cookie，因此不需要修改 Odoo 服务器，也不依赖 EDA 网络层是否保留 Cookie/CORS。

## 1. 功能

- **统一器件库**：C 编号/型号/名称/品牌/分类检索，实时库存、可用库存、参数、详情、图片、库位、袋/批次、未归还记录。
- **BOM 数量对比（只读）**：选中器件或原理图已加载图页，按 C 编号归并需求，对比 Odoo 实时可用库存；不修改原理图、BOM 或库存。
- **袋追溯**：解析 `LABB:` 袋码、`LABL:` 库位码、物料 SN、C 编号、立创原厂袋二维码。
- **入库**：选择库位、数量、供应商二维码，创建真实新袋和 Odoo 库存移动；有确认步骤和幂等请求号。
- **领用**：必须选择系统账号领用人 + 项目，按 `bag_id` 明细领用；操作人由服务器取登录会话。
- **归还**：必须选择原领用明细 `issue_line_id`，不得超过未归还余额；不能按器件总量归还。
- **标签**：只打开现有 Odoo 标签入口，不在前端虚构二维码/PDF。

## 2. 兼容性

| 项目 | 要求 |
| --- | --- |
| 嘉立创 EDA 专业版 | `engines.eda = ^3.2.0`；以扩展管理器导入结果为准 |
| Odoo | 19（`type='jsonrpc'`、POST、`auth='user'`） |
| Odoo 模块 | `lab_inventory`、`lab_catalog`、`lab_workflow` 已安装 |
| 本机桥接 | Windows 一键包内置 Node.js v24.19.0；Linux 需 Node.js >= 20.5 |
| 网络 | EDA 可访问 `127.0.0.1:49621`；relay 可访问 `http://lc.rm.com` |

## 3. 安装与首次连接（推荐流程）

### 3.1 解压完整包

使用 `lab-inventory-odoo_v3.0.3-bundle.zip`，解压后应有：

```
lab-inventory-odoo_v3.0.3.eext
bridge/
  start-windows.cmd
  start-linux.sh
  server.mjs
  runtime/node.exe
  runtime/NODE-LICENSE.txt
安装说明.txt
README.md
```

### 3.2 安装 EDA 插件

1. EDA 专业版 → **高级 → 扩展管理器 → 导入**（旧入口：设置 → 扩展 → 扩展管理器）。
2. 导入 `lab-inventory-odoo_v3.0.3.eext`。
3. 启用「实验室库存联动（Odoo 19）」，并开启 **外部交互** 权限。
4. 顶部菜单出现 **库存联动**。

### 3.3 启动本机桥接

Windows：双击 `bridge/start-windows.cmd`。

窗口会显示：

```
地址: http://127.0.0.1:49621
上游: http://lc.rm.com / LcHardwareHouse
配对码: 一串随机字符
```

使用期间不要关闭窗口。relay 只绑定 `127.0.0.1`，只接受本机请求；配对码每次启动都会变化，只存在进程内存中。

Linux：`chmod +x bridge/start-linux.sh && bridge/start-linux.sh`。

### 3.4 连接

1. 打开 **库存联动 → 连接与账户**。
2. 连接方式选 **本机桥接（推荐）**。
3. 本机地址保持 `http://127.0.0.1:49621`。
4. 复制桥接窗口中的配对码，填入「配对码」。
5. 填写 Odoo 登录名和密码，点击「连接并登录」。

登录状态只在当前 EDA 会话内保持；插件不保存密码和配对码，关闭 EDA 或重载扩展后需要重新输入。

### 3.5 直接连接 Odoo（高级，可选）

如果不想运行本机 relay，可以把连接方式切到「直接连接 Odoo（高级）」，填写 Odoo 地址/数据库/账号密码。

注意：Odoo 19 只从 `session_id` Cookie 读取会话，而 EDA 的 `sys_ClientUrl` 不提供 credentials 选项，也无法可靠读取/设置 Cookie。直接连接只有在 EDA 客户端确实保留 Odoo Cookie 时才能工作；插件登录后会强制探测，失败会提示改用本机桥接。生产环境推荐始终使用本机桥接。

## 4. Odoo 权限与数据库

| 能力 | 组 / 条件 |
| --- | --- |
| 访问器件库 | `lab_catalog.group_lab_catalog_user` 或 manager，或系统管理员 |
| 访问库存接口 | `lab_workflow.group_lab_user` 及以上 |
| 入库 / 领用 / 归还 / 标签 | `lab_workflow.group_lab_operator` |
| 新建库位 / 标签管理 / 历史库存适配 | `lab_workflow.group_lab_manager` |

领用人必须是已建立且启用的系统账号（`res.users`），由 `/lab/api/inventory/bootstrap` 返回；插件不接受手填姓名。

默认数据库为 `LcHardwareHouse`，默认上游为 `http://lc.rm.com`。relay 启动时可用 `--port/--upstream/--db` 覆盖默认值，但请求体不能选择任意 URL 或数据库；启动后固定使用该配置。

## 5. 网络模型与安全

```
EDA iframe
  └─ 私有 SYS_MessageBus（nonce 校验）
       └─ EDA 主模块（配对码仅内存）
            └─ sys_ClientUrl → http://127.0.0.1:49621
                 └─ relay（原生 node:http/https，CookieJar 仅内存）
                      └─ http://lc.rm.com / LcHardwareHouse
```

- relay 对 EDA 只返回业务数据，**不返回 Odoo `session_id` 或 Set-Cookie**。
- relay 以 `Authorization: Bearer <配对码>` 校验所有 login/rpc/logout/asset 请求。
- relay 响应 `Access-Control-Allow-Origin: *`，不使用 credentials；允许 `Authorization, Content-Type`；处理 OPTIONS 和 Private Network Access。
- relay 只允许固定接口路径：catalog search/detail/categories/facets、inventory bootstrap/locations/resolve_code/receipt/issue/return/issues/history、`/web/session/get_session_info`。
- 不跟随上游重定向；限制请求体 256KB、登录体 16KB、JSON 响应 8MB、图片 5MB、超时 20/30 秒。
- 密码只用于 relay 登录请求，不落盘、不写日志；Cookie 只在 relay 进程内存中。
- 插件端密码和配对码只通过私有 MessageBus 传递，不写入 `sys_Storage`；`sys_Storage` 只保存初始化 nonce/tab 和 server/db/login。

## 6. 接口映射

所有业务接口均为 `POST`、`Content-Type: application/json`、Odoo 19 `type='jsonrpc'`、`auth='user'`。relay 转发时保持 Odoo JSON-RPC 信封：

```json
{"jsonrpc":"2.0","method":"call","id":"...","params":{}}
```

| 功能 | 真实接口 |
| --- | --- |
| 登录 | relay `/login` → Odoo `/web/session/authenticate` |
| 会话探测 | `/web/session/get_session_info` |
| 注销 | relay `/logout` → Odoo `/web/session/destroy` |
| 器件检索/分页 | `/lab/api/catalog/search` |
| 器件详情 | `/lab/api/catalog/detail` |
| 分类 / facets | `/lab/api/catalog/categories` / `facets` |
| 权限、库位、领用人 | `/lab/api/inventory/bootstrap` |
| 库位列表 | `/lab/api/inventory/locations` |
| 扫码解析 | `/lab/api/inventory/resolve_code` |
| 入库 | `/lab/api/inventory/receipt` |
| 领用 | `/lab/api/inventory/issue` |
| 归还 | `/lab/api/inventory/return` |
| 未归还列表 | `/lab/api/inventory/issues` |
| 作业历史 | `/lab/api/inventory/history` |
| 图片 | `/lab/api/asset?url=...`（Odoo 服务端白名单） |

### 6.1 幂等与确认

- 入库/领用/归还提交前都有确认弹窗。
- 每次提交生成 `request_key`；网络超时等“可能已送达”的情况，界面提示用**同一请求号**重试，服务端按 `request_key + 用户 + 公司 + payload 指纹` 返回原结果或拒绝冲突。
- 修改表单内容自动换新请求号。
- 服务器返回 `replayed=true` 时界面标注“服务器重放，未重复记账”。

### 6.2 BOM 范围

- 使用真实 SDK `sch_PrimitiveComponent.getAll('part', true)`；EDA 文档说明 `allSchematicPages=true` **只返回已加载图页**，未打开图页不会被读取。
- 只统计 `getState_AddIntoBom() !== false` 的器件；数量按 1 块板计算。
- 器件身份只认有效 C 编号；无 C 编号的器件单独列出，不猜测、不合并。
- 对比使用 canonical `catalog.detail` 精确查询，不取模糊搜索结果的第一项。
- 查询失败显示“库存未知”，不会显示 0。

### 6.3 图片

catalog detail 的 `image_url` 通常是外部商城 CDN。插件会把它转换为 Odoo 现有 `/lab/api/asset?url=...` 白名单接口，再经 relay 带会话取回；不直接代理任意 URL，不把 Odoo 会话暴露给 iframe。

### 6.4 标签

标签 PDF/二维码由 Odoo 现有功能生成。插件只打开已知入口：

- `/odoo/action-lab_workflow.action_lab_bag`
- `/odoo/action-lab_workflow.action_lab_issue_line`
- `/odoo/action-lab_workflow.action_lab_label_open`
- `/odoo/action-lab_workflow.action_lab_location`
- `/odoo/action-lab_workflow.action_lab_operation`

标签入口通常仅库存管理员可用；插件不伪造前端二维码。

## 7. 与旧版 2.0.1 的不兼容

旧包使用 `/api/auth/login` + 硬编码 `admin/admin123` + Bearer token + `LAB-` 内部码，和当前 Odoo 19 的 `lcsc:C123` / `lab:42` 契约完全不同，不能复用其登录或 token。

升级到 3.0.3 后：

- 不导入旧 token 或旧服务器配置；插件忽略旧 `lab_inventory_token`。
- 旧版默认管理员登录已移除；必须用真实 Odoo 账号。
- 旧版按器件总量扣减已移除；领用按袋、归还按原领用明细。
- UUID 保留，扩展管理器可识别为同一扩展升级。

## 8. 构建与测试

要求 Node.js >= 20.5（本项目使用 Node 24）。

```bash
npm install
npm test              # 单元测试 + relay loopback 集成测试
npm run test:package  # 构建 + 包内容测试
npm run test:all      # 全部测试
npm run build         # 生成 eext 和完整 bundle zip
npm run verify        # 校验 eext/bundle、资源、禁止项、hash
```

产物：

- `build/lab-inventory-odoo_v3.0.3.eext`
- `build/lab-inventory-odoo_v3.0.3-bundle.zip`（含 eext、relay、node.exe、启动脚本、中文安装说明）
- `build/package-manifest.json`
- `build/bundle-manifest.json`

构建使用官方同构 esbuild（`format=iife`、`globalName=edaEsbuildExportName`、入口 `src/main/index.js`、输出 `dist/index.js`）；iframe JS/CSS 构建时内联。eext 使用固定 ZIP 时间和排序，构建脚本会构建两次并比较 SHA。bundle 额外包含随包 Windows Node 运行时和 `NODE-LICENSE.txt`。

## 9. 目录

```
src/main/       EDA 入口、配置、transport、relay/Odoo 会话、API、SDK 适配、MessageBus 桥
src/iframe/     自包含面板 UI（无直接网络请求）
src/shared/     身份规范、JSON-RPC 解码、幂等、BOM 归并、校验、detail 形状
bridge/         零依赖 loopback relay、Windows/Linux 启动脚本、runtime
src/tests/      Node 单元测试 + loopback relay 集成测试 + 包测试
scripts/        构建、bundle、校验
```

## 10. 常见问题

| 现象 | 处理 |
| --- | --- |
| 连接失败 / `RELAY_UNAVAILABLE` | 先启动 `start-windows.cmd`，确认窗口仍打开 |
| `RELAY_AUTH` | 复制当前桥接窗口里的新配对码；每次启动都会变化 |
| 端口被占用 | 关闭重复的 relay 窗口，或 `server.mjs --port <端口>` 后同步修改插件本机地址 |
| 登录失败 | 检查 Odoo 登录名/密码；账号启用 MFA 时先在 Odoo 网页端处理 |
| 权限不足 | 联系管理员加入 lab_workflow / lab_catalog 对应组 |
| 图片不显示 | 服务器可能未收录该资源；插件只走 Odoo 白名单，不直接抓外部 URL |
| 直接连接失败 | 改用本机桥接；直接连接依赖 EDA 客户端保留 Odoo Cookie |

诊断入口：**库存联动 → 诊断日志**。日志会脱敏 `password`、`token`、`session_id`、`cookie`、`authorization`。

## 11. 未验证范围

- 未在真实嘉立创 EDA 专业版中安装运行 `.eext`。
- 未连接生产 Odoo 执行真实入库/领用/归还（只读核对另见 `ACCEPTANCE.md`）。
- 已完成真实服务器经 relay 登录、器件搜索/详情、领用账号列表和退出的只读联调（5 项通过，见 review/root-live-relay-results.json）。真实 EDA 安装、图片资源及生产库存写操作尚未验收。

实现者记录见 `ACCEPTANCE.md`；最终独立验收和交付 hash 以 `FINAL_ACCEPTANCE.md` 为准。
