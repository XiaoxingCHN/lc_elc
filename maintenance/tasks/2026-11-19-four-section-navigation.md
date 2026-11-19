# 任务：把客户端拆成四个分区（库存速览 / 仓位速览 / 器件库 / 库存管理）

- Status: implemented（源码完成，488 测试通过；未提交、未发布）
- 目标/用户场景：用户认为当前「所有功能挤在一个器件库页面」太集中，要求用菜单分流：
  **库存速览**、**仓位速览**、**库存管理**三个界面（后追加：**器件库**单独一区，共四个）。
  切换控件沿用现有 `GlassSegmentedControl`：**桌面在顶部，手机在底部**。
- 当前问题及复现方法：登录后唯一落点是 `/catalog`（器件库），
  入库/领料/归还/标签/历史只能从目录页 FAB、详情页按钮或已废弃的 `HomeScreen` 进入；
  仓位没有任何页面（只有下拉选择器）；客户端连 `/lab/api/inventory/bags` 都没接。
- 验收标准：
  1. 登录后进入带四个分区的外壳，分区可切换且各自保留页面栈；
  2. 库存速览给出真实数字（器件数 / 有库存数 / 仓位总数 / 在库总数量），失败时显示错误而不是 0；
  3. 仓位速览列出每个仓位的袋数、袋内数量、在库数量，可进仓位内容页；
  4. 仓位内容页按仓位分页列出实物袋（袋码 / 器件 / 数量 / 库位），可打印该仓位标签；
  5. 库存管理一页收齐入库（制袋+扫码上架）、领料、归还、标签打印、历史追溯；
  6. 原有深链（`/catalog/item`、`/receipt?item_key=`、`/labels?kind=bag&ids=` 等）全部照常工作。
- 允许修改目录/接口：`clients/app`。**不改服务端**：`/inventory/bags`（`location_id`/`has_stock`/
  `next_cursor`/`limit≤100`）与 `locations(with_stats=1)`（`bag_count`/`bag_quantity`/`quantity`）已就绪。
- 业务不变量/依赖：库存以 `stock.quant`/`stock.move` 为权威；`lab_quantity` 与 `catalog_stock`
  不得混用；离线只读入口仍只允许 `/catalog`、`/catalog/item`；不新增未登记接口。
- 分支/起始commit/源码manifest：`feat/receipt-param-search`；客户端清单
  `source-client-1.3.3-17-20261119.json`。
- 环境与凭据获取方式：不涉及（不读真实凭据）。
- 实施步骤：见下。
- 测试命令、实际结果与退出码：见「验证」。
- 未验证项及风险：见下。
- 发布文件、hash和回滚点：无（本轮只改源码，未构建）。

## 一、分区与路由

外壳 `WarehouseShell`（新），四个分区，各自一个 `StatefulShellBranch` 风格的栈
（go_router 12 有 `StatefulShellRoute`；若不引入则用 `IndexedStack` + 每区自己的 `Navigator`，
但优先用 `StatefulShellRoute.indexedStack`，避免自造）。

| 分区 | 根路径 | 内容 |
|---|---|---|
| 库存速览 | `/stock` | 统计卡片 + 有库存器件前 N 条 + 快捷入口 |
| 仓位速览 | `/stock/locations` | 仓位列表（袋数/数量）+ 仓位内容页 `/stock/locations/:id` |
| 器件库 | `/catalog` | **现有 `UnifiedCatalogScreen` 原样搬入** |
| 库存管理 | `/stock/manage` | 入库 / 领料 / 归还 / 标签 / 历史 五个入口卡 |

- 登录后落点从 `/catalog` 改为 `/stock`；`/home`、`/products`、`/products/:id` 重定向保持指向 `/catalog`
  （器件库仍是一级入口，只是不再是落点）。
- 现有作业路由 `/receipt`、`/receipt/prepare`、`/issue`、`/return`、`/labels`、`/history`
  **保持在根级**（深链、扫码 intent、返回栈都不受影响），只在「库存管理」页里作为入口列出。
  即：分区只负责**发现**，作业页面仍是全屏 push，不改它们的 `LabPageFrame` 返回语义。
- 切换控件：`GlassSegmentedControl<WarehouseSection>`，`wide`（≥900）放在外壳 `AppBar.bottom`；
  窄屏放在 `Scaffold.bottomNavigationBar` 位置。两处都渲染同一个控件，只是位置不同。

## 二、数据层（先做，纯增量）

1. `LabStockLocation`（`models/detail_models.dart:80`）增字段：`usage`、`bagCount`、`bagQuantity`、
   `hasStats`；`fromJson` 解析 `usage`/`bag_count`/`bag_quantity`（缺失为 null，不默认 0，
   以便区分「没有统计」和「确实是 0」）。
2. `LabApiClient.locations({bool withStats = false})`：把 `with_stats` 传下去（服务端已支持）。
   现有调用方不传 → 行为不变。
3. 新增 `LabApiClient.bags({String? query, String? itemKey, int? locationId, bool hasStock = true,
   String? cursor, int limit = 50})` → `BagPage(bags, nextCursor)`；`limit` 夹到 1..100
   （服务端上限 100，与 `maxPageSize=200` 不同，按服务端来）。
4. 新增模型 `BagPage`；`LabBag.fromJson` 补齐 `availableQuantity`、`locationPath`、
   `outstandingQuantity`（现在都躺在 `raw` 里）。
5. `inventoryLocationsProvider` 改为 `withStats: true`（仓位速览要用）；给下拉选择器另留
   一个不带统计的 provider，避免给每个选择器都多算一次聚合。
6. 新增 `stockOverviewProvider`：并发取「有库存器件首页」与「仓位统计」，
   汇总成 `StockOverview{ itemCount, inStockItemCount, locationCount, totalQuantity, topItems }`。
   `totalQuantity` = 各仓位 `quantity` 之和（与 Odoo 库位口径一致）。
7. 新增 `locationBagsProvider.family<int>`：按仓位分页取袋（`next_cursor`），
   与 `catalogProvider` 一样做「过期响应丢弃」。

## 三、页面

- **库存速览** `StockOverviewScreen`：四个统计块（复用详情页 `_Metric` 的样式，抽成公共
  `StatTile`）+ 「有库存器件」前 10 条（复用 `ItemListTile`）+ 三个快捷按钮
  （入库 / 仓位速览 / 器件库）。错误用 `ErrorView`，空用 `EmptyView`。
- **仓位速览** `LocationOverviewScreen`：每行 = 库码 + 名称 + 袋数 + 数量，
  点进 `LocationContentsScreen`；顶部「新建库位」沿用现有 `createLocation`。
- **仓位内容** `LocationContentsScreen`：仓位头（库码/名称/合计）+ 袋分页列表 +
  动作「录入库存（带 location_id）/ 打印仓位标签（`labelsForLocation`）/ 刷新」。
- **库存管理** `InventoryManageScreen`：五个入口卡（复用 `_ActionCard` 样式，抽成公共
  `NavCard`），按 `InventoryPermissions` 决定是否可点。
- **器件库**：`UnifiedCatalogScreen` 不动，只是不再是自己 `Scaffold` 的唯一根——
  它已有自己的 `Scaffold`/`LabAppBar`，放进 shell 时用 `shell 内不重复画 bar` 的方式处理
  （shell 的 bar 只在四个根页显示；作业页仍各自有 bar）。

## 四、风险与取舍

- **引入 shell 是本项目刻意的架构变更**：`lab_ui.dart:47` 明确写着「没有全局导航外壳」。
  这一条要随之更新注释与 `docs/development/CLIENT.md`。
- `StatefulShellRoute` 与现有 `appRouterProvider` 的 `redirect` 逻辑要一起改：
  登录态判断不变，但「已登录访问 `/login`」要跳到 `/stock` 而不是 `/catalog`。
- `widget_test.dart:211,262` 断言 `find.text('仓库')`；落点改 `/stock` 后这些断言要改到新落点，
  并保留一条「`/home` 仍重定向到器件库」的用例。
- 仓位内容页不进离线缓存（离线只允许 `/catalog`、`/catalog/item`）。

## 五、验证

- `flutter analyze --no-pub lib test` → 0 error / 0 warning。
- `flutter test --no-pub` → 全绿；新增用例：
  分区切换保留各自栈、`/stock` 落点、`/home` 仍到 `/catalog`、
  `bags()` 分页与 `limit` 夹取、`locations(withStats)` 解析、
  仓位内容页空/错/有数据三态。
- 手工：Windows 包跑一遍，登录 → 四区切换 → 仓位内容 → 打印仓位标签。
