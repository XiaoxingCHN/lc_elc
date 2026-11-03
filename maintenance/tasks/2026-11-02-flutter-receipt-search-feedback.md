# 任务：Flutter 客户端收据搜索反馈（对齐已验收的 Web 版本）

- 目标/用户场景：网页端「来料编号/关键词即时真实下拉候选」已完成并验收（51 pass / 0 fail / 3 blocked）；Flutter 客户端仍是用模态 ItemPickerDialog 选档，缺少与网页一致的即时搜索反馈、统一同 C 展示、竞态防护与提交锁。
- 当前问题及复现方法：`clients/app/lib/features/unified/screens/receipt_screen.dart:88` 与 `pending_receipt_screen.dart:191` 直接 `ItemPickerDialog.show(...)`；`item_picker.dart:95` 防抖 400ms 且为一次性弹窗检索，无内联候选、无显式 loading/empty/error+retry、无键鼠导航与竞争防护。
- 验收标准：①裸 C / `lcsc:` 前缀 / 关键词（名称·型号）输入即出现服务端候选，防抖 ~250ms，IME 组字期间不触发；②同一 C 的本地档案与供应商条目统一分组展示，本地库存优先且不与供应商库存混淆，显示 C/名称/型号/封装与「已有档案」标识，不出现 `lab:`/`lcsc:` 内部前缀；③每次输入立即作废前一次请求与已选值；乱序响应、清空、失焦、页面跳转不得覆盖新输入或重新打开下拉；④loading / 空结果（保留手工建档入口）/ 错误+重试 三种显式状态，绝不伪造结果；⑤上下键/Enter/Esc/Tab、焦点可见、下拉不被裁剪、窄屏与宽屏可用、沿用现有深色主题 token；⑥选中提交真实 `item_key` 与 `product_template_id`；同 C 多本地档案必须显式选择；扫码路径与手工建档保持可用；⑦提交中搜索与选择只读且不可重复提交；搜索/选择不产生任何库存或袋写入。
- 允许修改目录/接口：`clients/app/lib/features/unified/screens/receipt_screen.dart`、`.../screens/pending_receipt_screen.dart`、`.../widgets/item_picker.dart`，以及严格必要的同组件小助手与 `clients/app/test/**` 测试；不改 Web/Odoo 源码、`maintenance/`、`local/build/` 产物与无关文件；不新增第三方依赖。
- 业务不变量/依赖：库存以 Odoo `stock.quant`/`stock.move` 为权威，供应商库存不得混入本地库存；领用人必须是系统账号、归还关联原领料；一个实物袋仅一个追溯 QR；搜索/选档只读；沿用现有 catalog search 服务与 `/lab/api/catalog/search`，不新增 HTTP 端点。
- 负责人/协作者及分工：Main（Lead，DeepSeek）负责范围与验收闸门、最终复跑；子代理负责三文件实现与组件测试；不调用任何 Codex/GPT 模型（用户 2026-11-02 指令：仅允许 DeepSeek）。
- 分支/起始commit/源码manifest：分支 `codex/receipt-search-feedback`，基线 `b3bcbf244e44939c6d481e3f97f11579cdf9ee99`；客户端源码为 `clients/app`（三端共享），版本仍 `1.1.3+6`；开工时未冻结、未提交、未推送（后续已冻结客户端源码并重跑 repo_check，见文末「结果」；仍未提交、未推送）。
- 环境与凭据获取方式（只写位置，绝不写值）：本机 Flutter SDK `F:/lc_elc/dependencies/sdk/windows/flutter/bin/flutter.bat`；`clients/app/.dart_tool` 已存在，按既有日志使用 `--no-pub` 与项目内 `PUB_CACHE`；组件测试全部离线假实现，不读取任何真实凭据。
- 实施步骤：读 `clients/README.md` → 复用现有 catalog 搜索服务改造三文件 → 增加竞态/锁/键鼠/无障碍处理 → 补 widget 测试 → `flutter test` 与 `flutter analyze` → Main 复核差异并复跑。
- 测试命令、实际结果与退出码：已执行（子代理与 Main 各跑一次；`flutter test` exit 0、`+295 ~5`，`flutter analyze` exit 1 但 0 error / 0 warning / 119 info，明细见文末「验证」）。
- 未验证项及风险：真实设备（Android/Windows/Linux 实机）视觉与触控未验证；扫码枪连续输入、实体打印不在本任务；Flutter 与 Web 行为一致性仅以组件测试与代码复核为准，不能宣称三端实机通过。
- 发布文件、hash和回滚点：本轮不产出安装包；源码已按计划冻结（见「结果」，旧客户端清单未改写）；回滚点为对三文件的新增差异 `git checkout --` 恢复，或回到基线 `b3bcbf244e44939c6d481e3f97f11579cdf9ee99` 的客户端源。

## 结果

- 新增 `clients/app/lib/features/unified/widgets/catalog_suggest_search.dart`（818 行，格式化后）：OverlayPortal + CompositedTransformFollower 的内联建议浮层；防抖 `Duration(milliseconds: 250)`；每键 `_seq` 递增使旧请求作废；IME 组合期（`_controller.value.composing.isValid`）不查询；状态 loading/empty/error+retry；Up/Down/Enter/Escape/Tab 键操作；48dp 行高；TapRegion 外点关闭；不裁切。
- 新增测试 `clients/app/test/features/unified/catalog_suggest_search_test.dart`（739 行，20 个用例）。
- 改 `clients/app/lib/features/unified/screens/receipt_screen.dart`（+66/-4）：扫码行下加内联建议字段；档案加载中显示「正在读取本地档案…」并禁用提交（`archivesLoading = itemKey 非空且 materials 空且 detail.isLoading`）；选中走 `ReceiptController.setItem`；再次键入时 `_releaseSuggestion` 撤销上一次由建议提交的卡（仅当当前 `itemKey` 仍等于该卡时才清）。
- 改 `clients/app/lib/features/unified/screens/pending_receipt_screen.dart`（+129/-16）：用建议字段替换原「选择元器件」ListTile，保留「从器件库选择」「资料库没有？新建器件」两个入口；已选卡用带「清除选择」按钮的 ListTile 展示；同一 C 多档案时显示「此编号对应多个本地档案，请先选择本次制袋的档案。」并禁用「生成袋码并加入待打印」；`_selectionSeq` 令牌防止在途档案查询复活已撤销的选择。
- 改 `clients/app/lib/features/unified/providers/inventory_providers.dart`（+20/-1）：`ReceiptController.setItem` 在切换到不同卡时清 `resolved`/`materials`/`templateId`/`sn`（`copyWith` 用 `_unset` 哨兵，传 `null` 真能清空），同一张卡重选保留已选档案。
- 改 `clients/app/test/features/unified/item_picker_test.dart`（1 行）：点击目标文案「选择元器件」→「从器件库选择」。
- 实现决策：复用既有 `LabApiClient.search(CatalogQuery)`/`detail()`，无新接口；同 C 分组在客户端按规范化的 C 码合并，本地变体排主位，只有供应商独有组才显示供应商库存，绝不把供应商库存当本地库存；`lab:`/`lcsc:`/`LABB:`/`LABL:` 等内部前缀由 `catalogSuggestTerm` 剥掉，`LABB`/`LABL` 不作为文本上送；扫码与手工建档路径未改。
- 客户端源码冻结（Lead 执行，EXIT=0）：`python tools/release.py snapshot --component client --output maintenance/registry/source-client-receipt-search-feedback-20261102.json --activate` → `file_count=169`、`tree_sha256=ee5adebdaa0c3e81dfa616b8dc55243d6419790422b93b010f9126f3aaa70072`、清单 sha256 `d703e507cd04bbe6bad648a3bf263b79d6626bf34ae77bba45cae88d6d37952f`；`active-sources.client` 已指向它，旧 `source-client-android-install-fix-final-20261019.json` 未改写。版本仍 `1.1.3+6`（未升版、未构建签名 APK、未发布；Android stable 仍 `1.1.3+6`）。

## 验证

工作目录 `F:/lc_elc/clients/app`，`PUB_CACHE=F:/lc_elc/dependencies/pub-cache-windows`、`FLUTTER_SUPPRESS_ANALYTICS=true`、`F:/lc_elc/dependencies/sdk/windows/flutter/bin/flutter.bat`，所有命令均 `--no-pub`、无 `pub get`：

- `flutter test --no-pub --reporter compact` → exit 0，`+295 ~5`：295 passed / 5 skipped（5 个 skip 是既有需要真实 Odoo 账号的 live 集成用例，本轮同样跳过）；Lead 已自行复跑确认同一结果。
- 单跑新测试文件 → exit 0，20/20。
- `flutter analyze --no-pub` → **exit 1**，但 **0 error / 0 warning / 119 info**（全部为改动前既有 info：deprecated `DropdownButtonFormField.value`、curly braces、1 个多余 import；新文件 0 新增）；输出存 `local/web-ui-implementation/evidence/flutter-analyze-20261102.txt`。
- `dart format --output=none --set-exit-if-changed` 两个新文件 → exit 0，无改动；三个既有文件故意没跑新 SDK 格式化（会把 ~435 行无关行重排，仓库本就不是该格式化基线）。
- 冻结后 `python tools/repo_check.py --output local/web-ui-implementation/evidence/repo-check-20261102-r2-flutter.json` → PASS / 52 项 / 0 errors / 1 既有 warning（`production-py312-rebuild`），exit 0。冻结前的 FAIL / 51 项 / 1 error `frozen-source:client` 是因客户端改动尚未冻结，不是回归。

## 未做/阻塞

- 没有 emulator/真机运行，UI 只有 widget 测试与静态分析证据，**不构成三端实机通过**。
- receipt 页没有专门的提交锁 widget 测试（pending 页有），**不声称已测**。
- 未构建/发布 APK；扫码枪连续输入、实体打印、三端实机视觉与触控不在本轮。
- 遗留：`git stash@{0}`（format-churn-revert，仅含三个文件被新格式化器重排的副本）因安全策略不允许删除，保留未动。
