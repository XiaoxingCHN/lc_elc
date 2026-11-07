# 任务：客户端业务界面 Liquid Glass 化（WorkBuddy 执行）

- 目标/用户场景：把 `clients/app` 的业务屏幕与浮层从浅色卡片适配到已批准的「深色玻璃 + 荧光绿」Liquid Glass 体系，让三端操作员在仓库/实验室弱光环境下看到统一的玻璃材质、清晰的状态与可读的文字。视觉重构，不改业务。
- 当前问题及复现方法：`pending_receipt_screen.dart` 使用不透明 `Scaffold` 底色与局部 `Theme` 覆盖、`CupertinoSlidingSegmentedControl` 分段控件；`camera_scan_screen.dart` 用 `white70`/`black54` 硬编码遮罩；`label_preview.dart` 用 `Colors.white` 纸面；多数屏幕用字面 `Card(` 且少数显式设色，深色主题下会出现白底/低对比。
- 验收标准：①结构、路由、文案、业务行为、输入顺序与 `onPressed` 语义完全不变；②无硬编码白底/Material 调色板残留于本轮负责文件；③滚动列表内不逐卡片 `BackdropFilter`；④320/1280 宽 × 深/浅主题 × 200% 文字不溢出，触控目标 ≥44×44；⑤A4 标签纸与 PDF 保持白底黑字；相机取景遮罩保持高对比；⑥错误/成功/状态不只靠颜色区分；⑦`flutter analyze` 无新增 error/warning，`flutter test --no-pub --reporter compact` 不低于基线（主会话基线 296 passed / 5 skipped）。
- 允许修改目录/接口：`clients/app/lib/screens/**`、`clients/app/lib/features/unified/screens/**`、`clients/app/lib/features/unified/widgets/**`、`clients/app/lib/updates/update_ui.dart`；`clients/app/test/**` 仅限对应界面的视觉/布局测试；本任务单。禁止修改 `lib/ui/glass/**`、`lib/widgets/lab_ui.dart`、`main.dart`、providers/services/models/routes、`pubspec.yaml`、服务端与版本/登记表/CHANGELOG。
- 业务不变量/依赖：库存以 Odoo `stock.quant`/`stock.move` 为权威；供应商库存不混入；领用人必须是系统账号、归还关联原领料；一个实物袋仅一个追溯 QR；离线只读公开缓存；本任务不触达任何业务写入或网络。
- 负责人/协作者及分工：WorkBuddy 负责业务屏幕与浮层实现与组件测试；Qoder 负责 `lib/ui/glass/**`、`lib/widgets/lab_ui.dart`、`main.dart`；主会话负责最终审查、视觉验收与重大决策。两份实现位于不同 worktree，不互相覆盖源码。
- 分支/起始commit/源码manifest：分支 `claude/dazzling-visvesvaraya-2ec760`，起始 `0e14ffa`（PR #1 合并点）；客户端版本仍 `1.1.3+6`；本轮不冻结、不升版、不 commit/push。
- 环境与凭据获取方式（只写位置，绝不写值）：本机 PATH 上的 Flutter 3.47.7 / Dart 3.13.5；所有测试为离线假实现，不读取任何真实凭据。
- 实施步骤：读计划与基线源码 → 记录任务单 → 对齐 Qoder 玻璃 API → 逐屏改造（外壳/流程/浮层）→ 补必要 widget 测试 → `flutter analyze` + `flutter test --no-pub --reporter compact` → 生成 `LAB_UI_EVIDENCE` 截图 → 汇报主会话审查。
- 测试命令、实际结果与退出码：见文末主会话终审结果；旧分支报告仅作过程记录。
- 未验证项及风险：本 worktree 基线早于 `feat/receipt-param-search` 未提交改动，`pending_receipt_screen.dart`/`unified_catalog_screen.dart`/`filter_panel.dart`/`item_picker.dart`/`login_screen.dart` 与主会话版本不同，合并时需按主会话版本复核；真实设备视觉/触控、读屏、实体打印未验证。
- 发布文件、hash和回滚点：本轮不产出安装包；回滚点为 `git checkout --` 恢复本轮文件，或回到 `0e14ffa`。

## 结果（2026-11-06，未提交）

改动 13 个文件 + 2 个新文件，业务逻辑、路由、文案、`onPressed` 语义未改：

- 新增 `lib/features/unified/widgets/status_banner.dart`：`StatusBanner`（tone=error/warning/notice/success/info）——12% 语义色填充 + 0.5px 同色边 + 图标 + `onSurface` 正文，替代「不透明 `errorContainer`/`tertiaryContainer` 卡片」。状态不再只靠颜色。
- `pending_receipt_screen.dart`：删掉局部 `inputDecorationTheme` 覆盖（避免深色背景下出现不透明浅色输入框）、`_section` 不再设 Card 颜色、`Scaffold` 改透明并改用 `LabAppBar`。
- `login_screen.dart`：Material 调色板硬编码改语义主题色；`_Banner` 只接收 tone 颜色并派生填充/描边/图标/文字；`ElevatedButton` → `FilledButton`；记住密码开关按可用性取 `primary`/`error`。
- `splash_screen.dart`：图标与副标题改主题色。
- `category_sidebar.dart`：改为 55% 半透明导轨。
- `offline_views.dart`：离线横幅改 14% `tertiary` + 同色图标 + `onSurface` 文字。
- `receipt/return/issue/labels/unified_catalog`：错误/通知统一走 `StatusBanner`（目录「加载下一页失败」保留「重试」按钮，走 `action`）。
- `camera_scan_screen.dart`、`label_preview.dart`：为刻意保留的相机高对比遮罩与 A4 白纸补注释，防止后续被误改。
- `test/features/unified/pending_receipt_test.dart`：截图用的 Material 图标字体路径改为从当前目录向上查找 SDK 载荷（原来写死 `../../dependencies/...`，在所有 worktree 下都找不到而让截图用例失败）。找不到时不加载字体、不判失败。
- 新增 `test/features/unified/status_banner_test.dart`：五种 tone × 320/1280 × 深/浅 × 200% 文字不溢出，错误态保留「重试」动作，状态均有文字而非仅靠颜色。

验证（`clients/app`，`PUB_CACHE=F:/lc_elc/dependencies/pub-cache-windows`，全部 `--no-pub`）：

- `flutter test --no-pub --reporter compact` → exit 0，**+246 ~5**（本 worktree 基线为 242/5，新增 4 例横幅测试；主会话的 296 来自更新的 `main`，两者不可直接比较）。
- `flutter analyze --no-pub lib` → 0 error / 0 warning（34 info 均为既有）；新增与改动的测试文件同样 0 error / 0 warning。
- 截图：`LAB_UI_EVIDENCE=<worktree>/local/build/glass-20261106` 单跑 `pending_receipt_test.dart` → exit 0，产出 `scan-confirm.png`（390×1000，无溢出、图标与中文正常）。

## 主会话终审结果（2026-11-06）

上述“阻塞”是集成前的工作树时点，现已解除。主会话保留参数搜索、待入库服务端筛选、登录固定服务器/数据库切换入口与更新宿主，通过局部编辑完成集成，没有覆盖当前工作区的未提交业务源码。

- 待入库普通文字模式已接入 `GlassSegmentedControl`；200% 文本沿用既有可展开选择器。队列筛选在窄屏上下排列，350ms 去抖、过期响应丢弃和服务端 query/state 逻辑不变。
- 登录表单使用无模糊 `GlassPanel`；搜索建议、筛选抽屉与器件选择浮层显式使用 overlay blur。内容卡片保持无模糊填充。
- Material 主操作保留，以统一主题呈现荧光绿、圆角与最小触控尺寸；没有为了换肤机械替换全部按钮。
- 错误/通知继续使用 `StatusBanner`；详情离线提示保留“重连”；A4 排版预览固定白底黑字。

### 实际验证

- `flutter analyze --no-pub lib test`：exit 1，**0 error / 0 warning / 118 info**，不记为命令 exit 0。
- `flutter test --no-pub --reporter compact`：exit 0，**319 passed / 5 skipped / 0 failed**。
- `LAB_UI_EVIDENCE=<Git排除的本机输出目录> flutter test --no-pub test/features/unified/glass_screens_evidence_test.dart`：exit 0，2 个用例，生成登录、1280 宽器件库、移动详情、待入库准备/扫码和 A4 排版共 6 张深色 PNG；主会话已逐张查看，未发现溢出。
- `test/features/unified/status_banner_test.dart` 覆盖五种 tone × 320/1280 × 深/浅 × 200% 文本；基础层测试覆盖高对比度、减少动态效果、prominent 前景色与默认无模糊面板。

未执行 Windows / Android / Linux 真机、profile 性能、真实摄像头/扫码枪、读屏和实体打印；PNG 是离屏渲染证据，不是这些项目的通过证明。未构建、发布安装包，未部署生产。
