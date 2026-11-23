# 客户端开发与环境恢复

当前共享源码与本机成品为 `1.4.0+26`，stable 状态见[发布交接](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。仓位树只在仓位速览请求 `with_tree`，普通作业的库位选择器仍读取内部库位。

## 改哪里

lib/features/warehouse是登录后的四个分区（库存速览/仓位速览/器件库/库存管理）与外壳；lib/features/unified是统一器件展示、详情和收/领/还/标签；lib/services/lab_api_client.dart是业务API；odoo_client.dart是登录和HTTP会话；login_memory_store.dart/secret_backend.dart是安全登录；providers/auth_provider.dart负责状态；routes负责返回/离线访问边界。修改共享源码同时考虑三端行为。

## 登录后的分区外壳

登录落点是 `/stock`（库存速览），不是器件库。四个分区由 `StatefulShellRoute.indexedStack` 承载，各自保留页面栈：

| 分区 | 根路径 | 页面 |
|---|---|---|
| 库存速览 | `/stock` | 器件数 / 有库存数 / 仓位数 / 实物袋 / 在库数量 + 仓位分布 + 有库存器件 |
| 仓位速览 | `/stock/locations` | 库位树、库码或路径搜索，以及管理员创建和调整上级。`/stock/locations/:id` 打开实物袋列表 |
| 器件库 | `/catalog` | 原 `UnifiedCatalogScreen`，未改动 |
| 库存管理 | `/stock/manage` | 入库 / 领料 / 归还 / 标签打印 / 历史追溯 五个入口 |

- 切换用 `GlassSegmentedControl`：**宽度 ≥900 放顶部，窄屏放底部**；200% 文本时换成下拉（阈值与入库页步骤切换一致）。
- 作业页（`/receipt`、`/receipt/prepare`、`/issue`、`/return`、`/labels`、`/history`）**仍在根级、全屏 push**，不属于任何分区，深链、扫码 intent 与返回栈不变。库存管理页只是入口。
- `/home`、`/products`、`/products/:id` 仍重定向到 `/catalog`：这些旧链接的意思是「给我看器件」，不是「给我看汇总」。
- 数字来源：器件数/有库存数取 `/catalog/search` 的 `total`（一次不带 `stock_only`、一次带）；仓位数与在库数量取 `locations(with_stats:1)` 的 `stock.quant` 合计。客户端不自己累加一页数据来冒充总数。
- 仓位速览读取 `locations(with_stats: true, with_tree: true)`，单节点统计只算本库位，视图祖先用于分组。内容页使用 `/lab/api/inventory/bags`，按 `location_id` 查该分支及子仓位，通过 `next_cursor` 分页，服务端 `limit` 上限为 100。详情和标签仍使用原库位 ID、库码。

## 热敏标签版式（40 × 20 mm）

`lib/services/niimbot_layout.dart` 是纯 Dart 排版，Windows FFI 与 Android 桥接共用同一份几何。
**两种标签用两套版式，不要合并**：

| | 器件追溯标签（`bag`） | 库位标签（`location`） |
|---|---|---|
| 二维码 | 11 mm @ (1,1) | 11 mm @ (1,1) |
| 码下方 | — | **库码**（6 pt，宽度限制在 11 mm 码列内） |
| 右侧列 | 标题 + 最多 4 行正文，自适应字号 | **名称**，17 pt |
| 取值 | `title` 是 SN | 名称取 `名称：` 行；**`title` 是库码，不能当名称用** |

- 库码取自 `payload`（`LABL:K000003` → `K000003`），保证打出来的与二维码编码的是同一个串。
- 适配两遍：先找「放得下且一行不丢」的最大字号，找不到才退到「放得下就行」并如实上报丢弃项。
- `GlassSurface.prominent` 每屏最多一个；正文压在上面只有 1.2:1，**不可读**（`warehouse_contrast_test.dart` 钉住）。

## 玻璃设计系统

1.2.0 源码候选以深色玻璃和荧光绿为默认外观，只改视觉层，保留业务路由、文案、协议和交互语义。`lib/ui/glass/` 是统一实现，`lib/widgets/lab_ui.dart` 保留 `LabTheme`、`LabAppBar`、`LabGlassSurface` 等兼容入口。

- `GlassTokens` 管理深浅色板、圆角、模糊强度与动效；裸 `ThemeData` 按 brightness 回退。
- 只有 `GlassSurface` 创建 `BackdropFilter`。AppBar、抽屉、搜索建议和对话框等浮层使用真实模糊；`GlassPanel` 和滚动卡片默认无模糊，不逐项创建滤镜。
- 主操作沿用 Material `FilledButton` 的统一主题，不为换肤机械替换业务按钮。高亮 accent 背景必须配 `onAccent` 文字；高对比度提高不透明度并关闭模糊，减少动态效果时关闭按压缩放。
- 错误、警告、成功与通知使用 `StatusBanner`，保留图标和文字，不只靠颜色区分。标签 A4 预览及 PDF 保持白底黑字。
- 320/1280 宽、深/浅主题、200% 文本由 widget 测试覆盖；PNG 离屏渲染不等于真机性能、读屏、触控或实体打印验收。

这是 Flutter 对 Liquid Glass 的近似实现：没有原生材质的真实折射、边缘弯折和自适应光照。零新增 pub 依赖，不改变 `--enforce-lockfile --offline` 的依赖闭包。

## 器件库按需抓取

搜索零结果且服务端在 `fetch_suggestion` 中给出可抓取项时，**三个入口**都能当场抓取：整库搜索的空结果页、入库/待入库表单的搜索建议面板（“立即从立创商城抓取”）、以及器件详情页的「刷新资料」（只对带 C 码的卡片显示）。可抓取项有两种：精确 C 码/完整 MPN（直接抓取），以及**规范化后至少 5 个字符且含字母的关键词**（只换候选，选定后才抓取）。

- `CatalogFetchController`（`providers/catalog_fetch_controller.dart`）负责一次请求：`POST /lab/api/catalog/fetch`（`sync` 默认 true，服务端在 15 秒预算内当场抓），非终态才每秒轮询 `fetch_status`（最多 60 次）。`done` 后由页面自己重查：整库搜索走 `CatalogNotifier.refresh()`；入库/待入库重跑建议检索（`CatalogSuggestFieldState.research()`），新行由操作员自己点选，不自动填入；详情页 `ref.invalidate(catalogDetailProvider/catalogRowProvider)`。
- 页面各自持有控制器：整库搜索用 `CatalogNotifier.startFetch(query:, catalogCode:, refresh:)`，入库/待入库/详情各自创建；换查询或销毁时取消轮询，互不影响。
- 「刷新资料」只刷新当前打开的这一个 C 码（`refresh: true` + `catalog_code`）；没有列表级/全库刷新按钮，服务端也没有批量刷新接口。内容未变化时服务端不写库、不 bump revision，面板显示“资料未变化，无需更新。”。
- 关键词候选只来自立创**搜索接口**：`CatalogFetchCandidate` 显示 `name`（立创显示名，如 `TI TLV9001IDBVR`）、品牌、封装和 C 码；服务端在候选阶段不打开中文详情页、不写库。`candidates` 是终态，必须由用户点「选这个」后带 `catalog_code` 重新提交，不能自动取第一条。短关键词（少于 5 字符）、纯数字、名称片段不发请求，也不由客户端自行判断。失败、非电子、待复核、未找到都显示服务端中文原因，状态卡同时带图标与文字，不只靠颜色。
- 抓取只影响器件资料与供应商库存，不创建本地档案、不改实验室库存；离线模式下不出现该按钮。
- 客户端测试 `catalog_fetch_test.dart`（显式 query/refresh、关键词候选、候选名称）、`catalog_suggest_search_test.dart`（零结果按钮只在服务端建议时出现）、`pending_receipt_test.dart`（表单内进度与完成）用 `FakeLabApi` 覆盖，不访问网络。

## 依赖与路径

默认离线Flutter在dependencies/sdk/<windows或linux>/flutter；缓存dependencies/pub-cache-<host>。源码锁文件pubspec.lock提交Git。Windows/Android恢复入口 `powershell -File dependencies/restore_client_tools.ps1 -TargetRoot <新工具目录> -AndroidProject clients/app -Verify`；已知原包布局在dependencies/README。

恢复脚本产生的Flutter可用 `--flutter <工具目录>/flutter`，JDK/Android分别用--jdk和--android-sdk传给build_client.py。脚本只改子进程环境，不全局改PATH。`--online`允许pubget联网；默认offline和enforce-lockfile，失败应查日志而不是抹掉锁重新解析。

Linux 在开发机按平台 README 恢复原生构建依赖、`flutter_linux_3.47.7-stable.tar.xz` 与 pub 缓存。当前 EDA 4.x 在构建阶段使用 Node，安装扩展时没有 Node 或本机网桥依赖。

## 隔离构建与验收

build_client.py以脚本自身推导仓库根，复制源码到local/build/client-<平台>-<时间>/source，写独立日志和results.json；最多2个原生并行job。不会覆盖已发布文件。仅适配普通可用本机工具链，portable VS及旧WSL私有sysroot需要对应环境适配，历史配方可参考但不能盲跑旧绝对路径。

先dry-run核对计划，再实际--test。客户端测试必须记录非零数量；实体打印/扫码和OS安全存储按平台区分，没有执行就记未验证。Android必须核对最终APK公开证书，匹配local/private受控key；不允许自动生成新签名。

Windows 原生构建的三个已知前提（2026-11-08 实测）：

1. **pdfium 离线包**：`printing` 插件默认从 GitHub release 下载 pdfium，国内网络不可达。把本机包路径传给 `PDFIUM_LOCAL_ARCHIVE`（例如 `F:/…/dependencies/windows/pdfium-win-x64-5200.tgz`），插件 CMake 会直接解压、跳过 ExternalProject；不要在 URL 里写 `file:///`，Windows 上会被解析成 `/F:/…`。
2. **短工作根**：MSBuild 的 tlog 路径会超过 260 字符（`FTK1011`）。用 `--work-root` 指一个短目录（如 `C:/lcw`），产物再拷回 `local/build/`；默认仍是 `local/build`。
3. **ATL**：`flutter_secure_storage_windows` 引用了 `atlstr.h` 与 `CA2W/CW2A`，需要 VS 的「C++ ATL for v143」组件；未安装时只能在本机 pub 缓存副本里用 Win32 转换替换（仅本机补丁，不入 Git）。

当前业务源的66文件与各平台原构建副本一致；完整源树由归档新manifest另冻，非66文件包含项不要冒称原构建证据已覆盖。归档本轮不全量重编译三端，具体当前状态见CURRENT_STATE。

## 原实际WSL工具已归档

原Android的Linux JDK/SDK/Flutter/pubcache/Gradle wrapper及模块缓存、Linux sysroot/Pdfium和私有适配bin已只读导出为dependencies/wsl-build-tools/wsl-build-tools-20261019.tar.gz（约4.4GB），SHA和成员原路径在maintenance/registry/wsl-toolchain.json。签名、代理gradle.properties、运行锁/日志不包含。可在WSL新私有目录解包，用明确路径传给构建入口；历史adapter中可能残留原绝对路径，应先按新解包根调整，不能冒称解包即实机验收通过。
