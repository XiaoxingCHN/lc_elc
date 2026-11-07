# 任务：Flutter 客户端 Liquid Glass 设计系统（基础层）

- 目标/用户场景：用户要求「用 flutter-liquid-glass 重构整个 UI」。本任务只交付**设计系统基础层与全局外壳**（`lib/ui/glass/**`、`lab_ui.dart`、`main.dart`），供后续业务屏幕改造复用；业务屏幕由另一位执行者在独立 worktree 负责，互不覆盖源码。
- 当前问题及复现方法：客户端主题集中在 `clients/app/lib/widgets/lab_ui.dart`（浅色渐变 + 半透明白卡片 + 唯一一处 sigma 18 的 `BackdropFilter`），没有深色主题、没有统一玻璃组件、没有主题扩展；`main.dart` 只挂 `LabTheme.light`。
- 验收标准：
  1. `GlassTokens`（`ThemeExtension`）提供深/浅两套色板、圆角、sigma、间距、动效；`Theme` 未注册扩展时按 `Theme.brightness` 安全回退。
  2. `GlassSurface` 是全仓唯一允许出现 `BackdropFilter` 的组件；`blur <= 0` 时不产生 `BackdropFilter`，仍保留填充与 0.5px 边缘；支持 capsule / rounded / circle、`radius`、`tint`、`prominent`、`padding`。
  3. `highContrast`（`MediaQuery.highContrastOf`）提高填充不透明度并去掉模糊；`disableAnimations`（`MediaQuery.disableAnimationsOf`）关闭按压缩放。
  4. `GlassBackdrop` 提供静态深色底 + 荧光绿/青色光晕，令玻璃有内容可折射；不使用全屏模糊。
  5. `GlassButton` / `GlassIconButton` 触控目标 ≥44×44、按压缩放 0.97、禁用态正确且不改动业务 `onPressed` 语义；`GlassSegmentedControl<T>` 为受控组件，窄屏与大文字不溢出。
  6. `buildGlassTheme(Brightness)` 输出完整 Material 3 深/浅主题：卡片 `blur = 0`（半透明填充 + 0.5px 边缘）、Input / Dialog / BottomSheet / SnackBar / Chip / Divider / Drawer / Switch / Progress / 按钮 / Scrollbar 统一。
  7. `LabTheme.light` / `LabTheme.dark` / `LabTheme.background` / `LabGlassSurface` / `LabAppBar` / `LabBackButton` / `LabPageFrame` 名称与构造签名不变，返回按钮 tooltip 仍为「返回」，`LabAppBar.flexibleSpace` 仍是 `LabGlassSurface` 实例（`test/routes/warehouse_navigation_test.dart:53` 依赖）。
  8. `main.dart` 挂 `theme` + `darkTheme` + `themeMode: ThemeMode.dark`，背景换 `GlassBackdrop`，保留全部 Provider 覆盖。
  9. `flutter analyze` 0 error / 0 warning；`flutter test --no-pub` 全量不回归（主会话基线 296 passed / 5 skipped）。
- 允许修改目录/接口：`clients/app/lib/ui/glass/**`（新建）、`clients/app/lib/widgets/lab_ui.dart`、`clients/app/lib/main.dart`、`clients/app/test/ui/glass/**`（新建）。**不改**其它业务屏幕、providers、API、服务端、版本号、`CHANGELOG.md`、`maintenance/registry/**`。
- 业务不变量/依赖：纯视觉层，不改路由、协议、库存语义、登录记忆与离线只读；无新增 pub 依赖；不声称与原生 iOS 26 材质等价（无折射 / 无边缘弯折 / 无逐元素形变）。
- 负责人/协作者及分工：Qoder（本 worktree，设计系统与全局外壳）；WorkBuddy（另一 worktree，业务屏幕）；主会话负责代码终审、视觉验收与重大方向决策。
- 分支/起始commit/源码manifest：分支 `claude/lucid-mclaren-143ba6`，起始 `0e14ffa`（main 基线；不含主会话 `feat/receipt-param-search` 上未提交的服务端与 Flutter 改动）。本任务不冻结源码、不提交、不推送。
- 环境与凭据获取方式（只写位置，绝不写值）：本机 PATH 上 Flutter 3.47.7 / Dart 3.13.5；`clients/app/.dart_tool` 已存在，全部命令使用 `--no-pub`；测试不读取任何真实凭据。
- 实施步骤：读方案与基线接口 → 建 `lib/ui/glass/` 五个文件 → 改写 `lab_ui.dart` 兼容壳与 `main.dart` → 补基础层 widget 测试 → `flutter analyze` + `flutter test` → 汇报真实结果与未验证项。
- 测试命令、实际结果与退出码：见文末「结果」。
- 未验证项及风险：未在 Windows / Android / Linux 实机运行；未做 profile 性能测量；玻璃折射与原生 iOS 26 不等价；业务屏幕的最终观感由后续批次决定。
- 发布文件、hash和回滚点：本任务不产出安装包、不改版本与登记表；回滚为删除 `lib/ui/glass/**`、`git checkout -- lib/widgets/lab_ui.dart lib/main.dart` 并移除新增测试。

## 结果

基础层已由 Qoder fork 实现并经主会话审查集成。分支 `claude/lucid-mclaren-143ba6` 的 `b9e4a63` 只提供基础源码；主会话在当前工作区恢复了 `UpdateHost`/`markUpdateReady`，修正 prominent accent 背景与 `onAccent` 前景配对、分段选中态对比度，以及 `GlassPanel` 默认使用真实模糊的问题。最终没有新增依赖，业务路由、API、库存与登录语义未改。

主工作区最终验证（Windows 11、Flutter 3.47.7 / Dart 3.13.5、全部 `--no-pub`）：`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 118 info**；`flutter test --no-pub --reporter compact` exit 0，**319 passed / 5 skipped / 0 failed**。5 个 skip 是既有的真实 Odoo 集成用例。

Windows / Android / Linux 真机运行、profile 滚动性能、实际读屏与 OS 安全存储未验证。源码版本与维护登记由主会话统一收口；本任务不构建、发布或部署。
