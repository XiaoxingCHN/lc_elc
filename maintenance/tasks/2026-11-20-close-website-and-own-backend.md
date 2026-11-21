# 任务：下个版本——关闭 Odoo 门户，后台管理改造成自有风格

- Status: proposed（方案待确认，未改任何源码）
- 目标/用户场景：用户明确两件事：
  1. **关闭 Odoo 的 website 门户**（公网 `https://team.l-creation.club/` 现在返回一个
     Odoo 网站页 `website.page(4)`，应该关掉）；
  2. **后台管理全部改造成自有风格**，不要 Odoo 原生 WebClient 界面。
- 允许修改目录：`server/ubuntu22.04/odoo_addons/`（主要 `lab_team_web`）、
  `clients/app`、`server/ubuntu22.04/` 运维脚本。不动数据库结构。
- 业务不变量：库存以 `stock.quant`/`stock.move` 为权威；权限门槛、CSRF、
  `request_key` 幂等、行锁、未知结果保护全部沿用现有模型方法，不因换页面而放宽。

## 一、现状（已勘察）

### 1.1 公网暴露面

| 路径 | 公网 | 说明 |
|---|---|---|
| `/` | **200** | Odoo website 首页（`website.page(4)`），**这是要关的** |
| `/about-us`、`/contactus` | 可达 | website 页面 |
| `/web`、`/odoo`、`/web/login` | 404 | 原生后台公网已屏蔽 ✅ |
| `/team/*`、`/lab/*` | 可达 | 自有业务前端 |

**关键更正（本轮勘察发现）**：`bore` 服务已 **inactive**，公网链路现在是
**Cloudflare Tunnel → nginx `127.0.0.1:18443` → Odoo**。
仓库里的 `server/ubuntu22.04/bore/nginx/bore-public-allowlist.conf.template`
（第 266 行 `location / { return 404; }` 的默认拒绝）**已经不在请求路径上**，
所以那份「公网默认拒绝」的保护目前是失效的——这正是 `/` 返回 200 的原因。

要关门户，改的是**现役的 18443 vhost**（`/etc/nginx/sites-enabled/team-l-creation-club`），
不是那份 bore 模板。

website 模块现有内容：**6 个网站页**（首页 ×2、联系我们、关于我们 ×2、感谢页）、
**9 个菜单**、722 条 `website.%` 视图记录。

依赖 `website` 的已装模块：`lab_site`（我们自己的）、`theme_default`、
`website_mail`、`website_sms`（后三个 Odoo 自带）。

### 1.2 自有 UI 已覆盖的（`lab_team_web`）

| 页面 | 路由 | 覆盖的管理任务 |
|---|---|---|
| 采购入库 | `/team/lab/receipts` | 两阶段入库、制袋、标签 |
| 扫码 | `/team/scan` | 只读解析 |
| 实物袋 / 单袋 | `/team/lab/bags`、`/team/lab/bags/<id>` | 袋追溯 |
| 标签中心 | `/team/lab/labels` | 标签版式与 PDF |
| 领用 / 领用记录 | `/team/lab/issue`、`/team/lab/issues` | 领用、归还 |
| 作业流水 | `/team/lab/history` | 只读流水 |
| 库位 | `/team/lab/locations` | **新建/改名/停用库位** |
| 类别映射 | `/team/lab/location-mappings` | 类别→库位推荐映射 |
| 管理 | `/team/lab/settings` | **成员三个库存角色开关**（仅此） |
| 器件档案 | `/team/lab/materials` | 检索、绑 C 码、建档 |
| 我的账号 | `/team/account` | 只读身份与权限 |

Flutter 客户端另有：库存速览、仓位速览（含新建仓位）、仓位内容、库存管理入口。

### 1.3 **完全没有自有 UI 的后台任务**（这是工作量的主体）

| 任务 | 现状 | 缺口 |
|---|---|---|
| **建用户** | 无。`members` 只列用户和改角色，全仓无 `res.users.create` | 需新建 |
| **改密码 / 重置密码** | 明确排除（`workflow_account.xml:22,138`） | 需新建 |
| **公司设置** | 无任何 `res.company` / `res_config_settings` 写入口 | 需新建 |
| **产品 / 分类编辑** | 只有绑 C 码和建档；`lab_catalog` 的 item 表单是 `create="false" edit="false"` | 需新建 |
| **库存数量调整 / 盘点 / 报废** | 无。`locations.js:15` 明确写「本页没有改数量/删库存入口」 | 需新建 |
| **系统/ERP 权限组** | 明确排除（`workflow_inventory.xml:354-356`） | 需新建 |
| **模块安装 / 数据库管理** | 无（运维脚本） | 建议保留 CLI |
| **备份 / 恢复** | 只有 CLI（`odoo_backup.py` / `odoo_restore.py`） | 建议保留 CLI |
| 幂等请求日志 | 保留原生（文档明示） | 可保留 |
| 分类树 / 导入批次 | 保留原生（文档明示） | 可保留 |

### 1.4 已有但无 UI 的 JSON-RPC（可直接复用）

`location_create`、`location_update`、`mapping_list/set/remove`、`members`、
`member_set_role`、`legacy_stock`、`adopt_stock`、`catalog/bind`、
`catalog/create_material`、`labels/pdf`。

**不存在**的端点：建用户、改密码、公司配置、产品编辑、库存调整、模块安装、备份。

## 二、方案

### 阶段 A：关闭 website 门户（小、可逆、先做）

推荐 **不卸载模块，只关公网入口**——卸载会丢 6 个页面和 9 个菜单的数据，将来想恢复很麻烦。

1. **现役 18443 vhost**（`/etc/nginx/sites-enabled/team-l-creation-club`）增加规则：
   `/`、`/about-us`、`/contactus`、`/website/*` 返回 404 或 301 到 `/team/login`；
   **不要**去改 `bore/nginx/bore-public-allowlist.conf.template`（bore 已停用，改了没效果）；
2. 保留 `/team/*`、`/lab/*`、`/web/session/*`（登录必需）、`/lab/client/updates/*`；
3. `lab_site` 模块保留在库里但不再对外服务。它是**全仓唯一** `depends: ["website"]`
   的模块（`lab_site/__manifest__.py:20`），作用是把 Odoo 默认首页换成静态官网
   （`views/homepage.xml` 继承 `website.homepage`）。不卸它，website 就会一直装着。
   若确认官网永久不要了，卸载 `lab_site` + `website` 是更彻底的做法（另立任务）。
4. 若确认官网永久不需要，再单独做一次卸载（另立任务）。

**注意**：需要先确认 `l-creation.club` 主域是否链接到 `team.l-creation.club/`，
避免挡掉后主域断链。

### 阶段 B：后台管理改造成自有风格（大，需分批）

按「业务频率与责任面」排序，不是按模块：

**B1 账号管理（最高优先，当前完全缺失）**
- 新建用户页：登录名、姓名、初始密码、实验室角色
- 改密码 / 重置密码
- 停用账号
- 需要新增 JSON-RPC：`/lab/api/admin/user_create`、`user_set_password`、
  `user_toggle_active`（全部 manager 门禁 + 审计日志）

**B2 器件档案维护**
- 编辑产品名称/型号/封装/品牌/参数
- 分类树维护
- 需要新增：`/lab/api/admin/product_update`、`category_*`

**B3 库存调整**
- 盘点、报废、库位调拨
- 这是**风险最高**的一块：直接改 `stock.quant`，必须走 `stock.move`，
  不能直接写数量
- 需要新增：`/lab/api/admin/adjust_stock`（走 stock.scrap / inventory adjustment）

**B4 公司设置与系统权限**
- 公司信息、站点标题、管理 Host
- 系统管理员 / ERP 管理员授权
- 需要新增：`/lab/api/admin/company_update`、`group_set`

**B5 保留原生的**
- 模块安装、数据库管理、备份恢复 → 继续用 CLI 脚本
- 幂等请求日志、导入批次 → 低频诊断，可保留原生（内网可达）

## 二·五、勘察补充（第二个探索的结果）

### `lab_team_web` 的路由形态

每个业务页都注册了**两条**路由：canonical `/team/...` 加根别名 `/lab/...`。
根别名有开关：参数 `lab_team_web.root_aliases`，**生产当前设为 0**
（`docs/operations/CURRENT_STATE.md:477`）。

### 旧入口兼容

`controllers/legacy_entries.py` 有 **13 条** `/odoo/action-<xmlid>` 的 GET 路由，
全部 303 跳到自有页面；其它 xmlid 一律 404。`views/legacy_entry_menu.xml` 里
9 个 `ir.actions.act_url` + 12 个菜单被改写指向自有页。

### 内网仍然全裸

内网 `192.168.31.105:8069` 完全绕过任何 allowlist：`/web`、`/odoo`、`/website/*`、
`/web/database`、`/jsonrpc`、`/web/dataset/call_kw` 全部可达。
「改造成自有风格」要覆盖的就是这一面。

### 有意保留原生的（文档已定）

`lab_workflow.menu_lab_request_log`（幂等日志）、
`lab_catalog.menu_lab_catalog_index/category/import_run`、
`lab_inventory.menu_lab_move`、原生标签向导。

### `lab_site` 的一个死文件

`lab_site/views/body_fragment.html`（399 行）是首页正文的副本，**没有任何地方引用**，
可以随本次一起删掉。

## 三、风险与必须先确认的点

1. **B3 库存调整是真正危险的部分**：现有设计刻意不给任何 UI 改库存数量
   （`locations.js:15` 明写「后端也不提供」）。一旦开放，误操作会直接破坏
   `stock.quant` 与流水的一致性。建议：只做「按 stock.move 的盘点/报废」，
   不做「直接改数量」，且需要二次确认 + 审计。
2. **卸载 website 与只关入口的区别**：只关入口可随时恢复；卸载会丢页面数据。
3. **公网主域依赖**：`l-creation.club` 是否链到 `team.l-creation.club/`。
4. **工作量**：B1–B4 等于重写一个 ERP 后台的核心部分，不是一轮能做完的。
   建议先做 A + B1，其余分批。

## 四、建议的下一步

先确认三件事，然后从 **A（关门户）+ B1（账号管理）** 开始：

1. 公网 `/` 关掉后，是 404 还是跳到 `/team/login`？
2. `l-creation.club` 主域有没有依赖这个首页？
3. B1 之后先做 B2（器件档案）还是 B3（库存调整）？

