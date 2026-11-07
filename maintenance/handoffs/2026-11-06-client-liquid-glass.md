# 维护交接：2026-11-06 Flutter Liquid Glass 源码候选

## 用户目标与已确认边界

- 用户要求用 Liquid Glass 风格重构整个 Flutter UI，并选定深色玻璃 + 荧光绿。主会话负责审查两个用户创建的 fork、最终实现决策和视觉验收。
- 保留路由、业务文案、协议、库存与登录语义；不把全部 Material 按钮机械替换成自定义按钮。没有新增 pub 依赖，没有构建/发布安装包，没有部署、生产写入或推送。

## 当前权威源码、分支和版本

- `clients/app`，当前工作分支 `feat/receipt-param-search`；包含此前未提交的参数搜索、待入库筛选和登录配置改动，未重置或覆盖它们。
- 客户端源码版本 `1.1.3+6 → 1.2.0+7`，`pubspec.yaml` 与 `maintenance/registry/components.json` 已同步。该版本不代表已发布 stable。
- 客户端冻结源 `maintenance/registry/source-client-liquid-glass-20261106.json`：177 文件，tree SHA256 `a19e0ddf2f7cdba420ae7605763c40926c3745d3ab5de60387c8aab7da1d0e4e`，清单 SHA256 `930b53e17d189a0b5ab1fb1a507aa74ce7d2be7c57d1cad91892f07486c6b11c`，已 `--activate`；旧清单未改写。
- 基础层来自 Qoder fork 的 `b9e4a63`，WorkBuddy fork 提供业务屏适配参考；最终代码由主会话逐文件集成审查。本任务没有新的 Git commit/push。

## 已完成工作与实际证据

- `lib/ui/glass/`：色板、玻璃表面、背景/chrome、交互控件与完整深浅主题。`lab_ui.dart` 兼容 `LabTheme`、`LabAppBar`、`LabGlassSurface` 等既有接口。
- 真实模糊仅用于 AppBar、抽屉、搜索建议与浮层；`GlassPanel` 和滚动卡片默认无模糊。全仓只有 `glass_surface.dart` 直接创建 `BackdropFilter`。
- 修复 prominent 按钮和分段选中态的 accent/onAccent 配对，保留 `UpdateHost`、`markUpdateReady` 和登录/更新业务生命周期。
- 待入库服务端 query/state 筛选、350ms 去抖、过期响应丢弃、200% 文本回退与取消记录排除逻辑保持不变；窄屏筛选改为上下排列。
- `StatusBanner` 统一状态提示，有图标与文字；A4 排版预览固定白底黑字。荧光绿高亮使用 Material `FilledButton` 统一主题，而非逐按钮替换。

### 实际执行的检查

| 命令 / 环境 | 结果 |
|---|---|
| Windows 11，Flutter 3.47.7 / Dart 3.13.5，`flutter analyze --no-pub lib test` | exit 1；0 error / 0 warning / 118 info，不记为命令成功 |
| `flutter test --no-pub --reporter compact` | exit 0；319 passed / 5 skipped / 0 failed；skip 为既有真实 Odoo 集成用例 |
| `LAB_UI_EVIDENCE=<Git排除的输出目录> flutter test --no-pub test/features/unified/glass_screens_evidence_test.dart` | exit 0；2 用例；登录、桌面器件库、移动详情、入库准备/扫码、A4 排版共 6 张 PNG |
| `python tools/generate_routes.py --check` | exit 0，92 条既有路由，未新增路由 |
| `git diff --check` | exit 0；仅有 Git 的 CRLF 转换提示 |
| `python tools/repo_check.py` | exit 1；51 项通过，唯一错误 `frozen-source:server`（9 个服务端文件晚于 active r2）；客户端冻结检查通过，16 条既有离线载荷警告 |

已逐屏查看深色离屏 PNG，未发现文字溢出。高对比度、减少动态效果、44×44 控件、prominent 配色、默认无模糊面板、320/1280 与 200% 文本由 widget 测试覆盖。色板静态计算：dark muted 7.57:1、dark accent 17.05:1、dark onAccent 16.64:1、light muted 5.36:1、light onAccent 5.27:1。

## 剩余工作与阻塞

- 未运行 Windows / Android / Linux 真机，未测 profile 滚动性能、真实触控、读屏、摄像头/扫码枪、OS 安全存储或实体打印；离屏 PNG 不代表这些项目通过。
- Flutter 实现近似 Liquid Glass，不具备原生材质的真实折射、边缘弯折和自适应光照。
- `python tools/repo_check.py` 原先的本机 `clients/app/t.obj` 缺失现已消失；最终仍有上节服务端冻结差异。`--verify-payloads` 未执行，离线载荷缺口未声称关闭。
- 工作区还有已登记版本 `lab_catalog 19.0.2.0.9`、`lab_workflow 19.0.2.0.2` 的服务端改动，晚于 active 的 11 月 4 日 r2 清单。该服务端差异不属于本轮 UI；不得用客户端快照将其算作已冻结或已部署。
- 客户端 `1.2.0+7` 未生成 artifact 登记，未构建/签名/发布任何平台包，未推送。

## 依赖和产物

- 源码入口：`clients/app`；设计说明：`docs/development/CLIENT.md`。
- 客户端 source manifest 见上；无安装包、签名公证书或发布 artifact。
- 截图与原始测试输出在 Git 排除的 `clients/local/build/glass-20261106/`，仅为本机证据，未包含凭据或真实业务数据。

## 生产状态和回滚

- 本轮没有连接或写入生产，没有升级/重启/导入/恢复，未执行历史数据修复脚本。
- 源码回滚只针对本轮客户端视觉文件和 `1.2.0+7` 客户端清单指针，不能整体 reset 工作区，否则将丢失先前未提交的服务端与业务功能。
- 旧 source manifest、stable 安装包、发布登记均保持不变。
