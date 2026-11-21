# 维护交接：登录后拆成四个分区

- 任务单：`maintenance/tasks/2026-11-19-four-section-navigation.md`
- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 未提交；本轮改源码 + 构建，未接触生产。

## 用户目标与已确认决策

用户认为功能太集中，要求用菜单分流。经确认：

1. **四个分区**（不是三个）：库存速览 / 仓位速览 / **器件库单独一区** / 库存管理；
2. **库存管理**里放：入库（制袋+扫码上架）、领料 / 归还、标签打印、历史追溯；
3. 切换控件沿用 `GlassSegmentedControl`：**桌面顶部、手机底部**。

## 新增文件

- `lib/features/warehouse/warehouse_section.dart` — 四分区枚举（短标签 + 长描述 + 图标 + branch 序号）。
- `lib/features/warehouse/warehouse_shell.dart` — 外壳；只决定切换器位置，从不画 AppBar；无会话时不渲染切换器。
- `lib/features/warehouse/warehouse_routes.dart` — 四个 `StatefulShellBranch` 与路径常量。
- `lib/features/warehouse/widgets/warehouse_section_switcher.dart` — 分段控件 + 大字号下拉回退。
- `lib/features/warehouse/widgets/stat_tile.dart` — `StatTile` / `StatRow` / `NavCard`。
- `lib/features/warehouse/providers/warehouse_providers.dart` — `stockOverviewProvider`、`locationBagsProvider`（键集分页 + 过期响应丢弃）。
- `lib/features/warehouse/screens/stock_overview_screen.dart`
- `lib/features/warehouse/screens/location_overview_screen.dart`
- `lib/features/warehouse/screens/location_contents_screen.dart`
- `lib/features/warehouse/screens/inventory_manage_screen.dart`

## 改动文件

- `lib/routes/app_router.dart` — 登录落点 `/catalog → /stock`；新增 `StatefulShellRoute.indexedStack`；`unifiedRoutes` 仍以根级全屏 push 存在。
- `lib/services/lab_api_client.dart` — `locations({withStats})`；新增 `bags()`（`limit` 夹 1..100）；新增路由常量 `inventoryBags`。
- `lib/features/unified/models/detail_models.dart` — `LabStockLocation` 增 `bagCount`/`bagQuantity`/`usage`/`hasStats`；`LabBag` 增 `availableQuantity`/`outstandingQuantity`/`locationPath`/`uom`/`hasStock`；新增 `BagPage`。
- `lib/features/unified/providers/inventory_providers.dart` — 新增 `inventoryLocationsWithStatsProvider`（下拉选择器仍用不带统计的那个）。
- `lib/features/unified/screens/receipt_screen.dart` + `unified_routes.dart` — 入库页接受 `?location_id=`，预选（不锁定）该仓位。
- `lib/widgets/lab_ui.dart` — 去掉「本应用刻意没有全局导航外壳」的过时注释。
- `docs/development/CLIENT.md`、`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`。

## 关键设计决定

- **作业页不属于任何分区**。`/receipt`、`/issue`、`/return`、`/labels`、`/history` 仍在根级，全屏 push，返回语义不变；库存管理页只是入口。这样深链、扫码 intent 与 `LabPageFrame` 的返回都不受影响。
- **`/home`、`/products` 仍重定向到 `/catalog`**：这些旧链接的意思是「看器件」，不是「看汇总」。
- **统计数字一律来自服务端**：器件数/有库存数取 `/catalog/search` 的 `total`（两次查询）；仓位数与在库数量取 `locations(with_stats:1)`。客户端不累加一页数据冒充总数。
- **`bag_count` 缺失时是 null 不是 0**：显示 `—`。给一个从未统计过的仓位显示「0 袋」会误导。
- **离线浏览不显示切换器**：`/catalog?offline=1` 在无会话时也在外壳里，切换器会把访客引向路由会拒绝的页面。有专门测试钉住。

## 实测

- `flutter test --no-pub` → **488 passed / 5 skipped / 0 failed**。
  新增：`test/features/warehouse/warehouse_data_test.dart`（11 条）、
  `test/features/warehouse/warehouse_shell_test.dart`（7 条）、
  `test/widget_test.dart` 新增「器件库一跳可达」「离线不显示切换器」两条，并改写落点断言。
- `flutter analyze --no-pub lib test` → 0 error / 0 warning。
- `tools/build_client.py --platform windows --test` → 三步 **exit 0 / 0 / 0**（构建内 488 passed）。
- `python tools/repo_check.py` → **PASS 53 项 / 0 errors**。
- **产物**：`clients/windows/releases/1.3.4+18/LC_ELC-Windows-1.3.4+18-x64.zip`，
  37,731,644 B，sha256 `6cd4ca0e…c2472317`，30 文件，exe sha256 `74c53bf9…df7a6f`，
  `NotSigned`；`client-install.json` = 1.3.4 / build 18 / windows；冒烟 RUNNING → STOPPED。
- **登记**：`source-client-1.3.4-18-20261119.json`（218 文件，已 `--activate`）；
  `artifact-client-windows-1.3.4-18-20261119.json`。

## 构建命令（本工作树没有 dependencies/，必须显式传路径）

```
PDFIUM_LOCAL_ARCHIVE=F:/lc_elc/dependencies/windows/pdfium-win-x64-5200.tgz \
python tools/build_client.py --platform windows --test --work-root C:/lcw \
  --flutter   F:/lc_elc/dependencies/sdk/windows/flutter/bin/flutter.bat \
  --pub-cache F:/lc_elc/dependencies/pub-cache-windows
```

## 未验证

- 真实登录后的四区切换手感（尤其手机底部栏在 320px 下的高度占用）。
- 仓位内容页在真实袋数（>100，需翻页）下的表现。
- 真实打印仓位标签、真实扫码。
- Android 实机布局。
- 未 commit / 未 push。
