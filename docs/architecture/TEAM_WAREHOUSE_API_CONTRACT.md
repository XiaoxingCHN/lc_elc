# 战队仓库前端 · 服务接口契约（第一批盘点）

日期：2026-10-25。范围：为 lab_team_web 首批只读页面盘点并确认可复用接口，
不新增业务规则、不改动既有 API 行为。基线代码：lab_catalog 19.0.2.0.4、
lab_workflow 19.0.1.2.0、lab_inventory 19.0.1.0.0。

## 1. 传输与会话

| 项 | 约定 |
|---|---|
| 传输 | Odoo 19 `type='jsonrpc'`，POST，`Content-Type: application/json` |
| 外层 | Odoo 自动包 `{"jsonrpc":"2.0","id":X,"result":<控制器返回值>}`；控制器**直接返回** `{ok,data,error}`，不自己再套壳 |
| 认证 | 与 `/web/session/authenticate` 同一会话 cookie；控制器内部只认 `request.env.uid` |
| 信封 | 成功 `{"ok":true,"data":{…},"error":null}`；失败 `{"ok":false,"data":null,"error":{"code","message","fields"}}` |
| 错误码 | VALIDATION_ERROR / NOT_FOUND / FORBIDDEN / CONFLICT / INTERNAL_ERROR / AMBIGUOUS_MATERIAL |

前端首发页**没有**新增任何业务接口：列表/详情直接用同一批模型的同一份实现
（`lab.catalog.item.search_unified` / `.detail`），与 `/lab/api/catalog/*` 完全同源。

## 2. 复用接口清单

### 2.1 器件库（lab_catalog）

| 接口 | 方法/路由 | 权限 | 关键参数 | 返回要点 |
|---|---|---|---|---|
| 统一检索 | POST `/lab/api/catalog/search` | lab_catalog 读取组 / lab_catalog 管理组 / system | query, category_id, brands[], packages[], parameters{}, stock_only, cursor, limit(1..200) | items[], next_cursor, total, inventory_revision, catalog_revision |
| 器件详情 | POST `/lab/api/catalog/detail` | 同上 | item_key（`lcsc:C123` / `lab:42`） | item, parameters[], files[], lab_templates[], locations[], bags[], issues[], history[] |
| 分类树 | POST `/lab/api/catalog/categories` | 同上 | — | categories[]（id/parent_id 均为 PG id，另给 catalog_id） |
| 分面 | POST `/lab/api/catalog/facets` | 同上 | query/category_id/brands/packages/parameters | brands[], packages[], parameters{}（含 total/has_more/timing_ms） |
| 绑定 | POST `/lab/api/catalog/bind` | 同上 | product_template_id, catalog_code | item_key, product_template_id |
| 建档绑定 | POST `/lab/api/catalog/create_material` | 同上 | item_key, sn?, product_template_id? | 只建档案，不复制库存 |
| 资源代理 | GET `/lab/api/asset?url=` | 登录用户 | url（白名单校验） | 图片/手册字节流，磁盘缓存，受参数 lab_catalog.asset_cache_enabled 控制 |

检索排序语义：**有库存优先**（rank），同 rank 按 sort_key；游标 keyset 分页，
不含"上一页"游标。首批页面照此实现"加载更多"。

### 2.2 库存与作业（lab_workflow）

| 接口 | 方法/路由 | 权限 | 首批用途 |
|---|---|---|---|
| 引导 | POST `/lab/api/inventory/bootstrap` | 登录 + lab 角色 | **未用于页面鉴权**；其权限位与目录读取角色不同，不能因它失败而挡住只有目录权限的用户 |
| 库位 | POST `/lab/api/inventory/locations` | lab 角色 | 第二批 |
| 条码解析 | POST `/lab/api/inventory/resolve_code` | lab 角色 | 第二批 |
| 入库 | POST `/lab/api/inventory/receipt` | operator | 第二批（当前为直接 receipt，新网页将走 pending 两阶段） |
| 待入库 | POST `/lab/api/inventory/pending/{list,create,update,resolve,confirm}` | lab 角色 | 第二批 |
| 领用/归还 | POST `/lab/api/inventory/{issue,return,issues,history}` | operator | 第二批 |
| 历史遗留库存 | POST `/lab/api/inventory/{legacy_stock,adopt_stock}` | manager | 第三批 |
| 标签排版/PDF | POST `/lab/api/labels/{plan,preview}` | operator | 第二批 |
| 客户端更新 | GET `/lab/client/updates/manifest` 等 | none/user | 不涉及 |

### 2.3 会话

| 接口 | 用途 |
|---|---|
| POST `/web/session/authenticate` | 原生认证（前端表单调用，不重写认证） |
| POST `/web/session/destroy` | 原生登出（本站退出走自己的 POST /team/logout + CSRF） |

### 2.4 本批新增（仅会话态，非业务）

| 接口 | 说明 |
|---|---|
| POST `/team/api/session`（别名 `/api/team/session`） | 只读返回 {authenticated, uid, name, login, base, permissions{can_catalog,can_lab,is_manager}, urls{...}}；匿名也返回 ok=true，权限位全 false。业务数据一律走 2.1/2.2，不在此复制。 |

## 3. 权限归属（服务端为唯一权威）

| 能力 | 组 |
|---|---|
| 器件库读取 | `lab_catalog.group_lab_catalog_user` / `group_lab_catalog_manager` / `base.group_system` |
| 实验室操作 | `lab_workflow.group_lab_user` / `group_lab_operator` / `group_lab_manager` |
| 入库/领用/标签 | `group_lab_operator`（服务端再校验一次） |
| 库位管理 | `group_lab_manager` |

前端只做显示层收敛；页面 403/404 与接口 FORBIDDEN 都由服务端判定。

## 4. 缺口清单（供第二批）

1. 检索接口无显式 `order/sort` 参数，仅"有库存优先 + sort_key"；如需"最近入库/按品牌"要扩参。
2. 分页只有 `next_cursor`，没有上一页/跳页；首批用"加载更多"。
3. 分面接口已就绪但首批页面未渲染筛选面板（品牌/封装/参数）——属 UI 缺口，不是 API 缺口。
4. 详情里的 `files[]` 结构未在契约文档中固定键名；本站按 `url/name/label` 宽松读取并做白名单。
5. 新前端未暴露标签打印、两阶段入库、领用归还；对应 API 已存在，属后续批次接线。
6. `inventory/bootstrap` 需要 lab 角色，不能作为"是否可看目录"的判据（本批已避免）。
7. 图片依赖 `lab_catalog.asset_cache_enabled`；关闭时 `/lab/api/asset` 返回 404，页面显示占位而非伪造图。
8. 尚无"服务端渲染 + 客户端导航"的统一错误码映射接口；首批在前端复用本地错误文案表。

## 5. 兼容性

- 旧 Flutter / EDA 调用的路由、参数、信封均未改动。
- 新增模块只注册自己的页面路由与会话态接口，不改 `/lab/api/*` 行为。
