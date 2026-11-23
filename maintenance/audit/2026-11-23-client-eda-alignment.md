# Flutter 库位树与 EDA 跨端界面审查

审查日期为 2026-11-23。范围为共享 Flutter 客户端 `1.3.5+25`、嘉立创 EDA 插件 `4.1.4` 和已上线的网页仓位管理。以下矩阵是修改前的审查基线。后续实施情况见文末，实际发布和待验范围见[正式发布记录](../handoffs/2026-11-23-client-stable-release.md)。

## 结论

Flutter 的「仓位速览」仍是平铺列表，还没有接收服务端返回的目录节点和父级关系。新建仓位按钮出现在普通用户界面，创建表单也无法指定上级。Windows、Android 和 Linux 共用同一份 Dart 源码，可以在一个页面和一套 API 中解决。

EDA 需要优先修出库未决状态和主按钮对比度。源码表明，出库结果未知后仍可发起新操作，重扫或切换范围会清空原请求。已发行的 4.1.4 主按钮白字最低约 **1.83:1**。界面应复用现有跨端色彩、术语和反馈规则，同时保留设计师专用的 BOM 表格、范围选择、替代料和按袋出库预览。

### 审查证据与范围

- Flutter、网页和 EDA 采用源码审查。用于视觉核对的两张既有截图来自浏览器隔离测试。截图涉及模拟库存和 EDA 宿主。
- 对主仓发行目录中的 `lab-inventory-odoo_v4.1.4.eext` 解包复核，内嵌 CSS 与本轮审查的 `app.css` 一致。包 SHA-256 为 `3a3c4a53f7cd85888be3e35876341bfc7da237418259b5b3b5fe50b4b3821a2f`。对比度按有效颜色计算，渐变逐色标取值。
- Web 生产基线的 M/R 归属以最近一次只读复核为准。`WH/库存/M区` 与 `WH/库存/R区` 并列，分别有 60 和 18 个子库位。本轮未重跑生产账号、真实 EDA 工程或三端安装流程。 [仓位树交接](../handoffs/2026-11-22-warehouse-location-tree.md)

## Flutter 修改清单

| 编号 | 优先级 | 实际发现 | 修改要求 |
| --- | --- | --- | --- |
| FL-01 | P1 | `LabApiClient.locations()` 只提交 `with_stats`。`LabStockLocation` 未保留父级。 | 加独立的库位树读方法，申请 `with_stats: true` 和 `with_tree: true`。分别解析 `locations` 和 `ancestors`，用记录 `id` 建树，`parent_id: false/null` 视为根。旧响应缺少层级时仍能显示可用库位和完整路径。入库、打印等库位选择器继续走原来仅含内部库位的接口。 |
| FL-02 | P1 | 「仓位速览」逐行平铺，没有目录展开和搜索。 | 在当前分区内展示多级树。每层按名称自然排序，`M(2,1)` 在 `M(10,1)` 之前。分支可展开和折叠。按库码、名称、完整路径搜索，显示命中的节点及祖先，清空搜索恢复原展开状态。刷新维持展开状态。保持桌面顶部和手机底部的现有分区导航。 |
| FL-03 | P0 | 页面直接向所有登录用户提供「新建仓位」，空列表也会出现创建按钮。新建只发 `name`。 | 解析 bootstrap 的 `can_manage_locations`，在加载、权限未知、退出或离线状态隐藏写操作。库存管理员能在新建时选上级，也能在当前节点下建子库位。成功后刷新树、统计及已有库位选择器，展开新节点的祖先。失败时保留输入。结果未知时先刷新并核对，当前创建接口没有明确的服务端幂等回放契约，禁止自动再建一次。 |
| FL-04 | P0 | 客户端没有「更改上级」，也没有移动后的路径刷新。 | 给有权限的用户提供「更改上级」。显示当前路径和新路径，排除自身、后代、当前父级和已失效目标。提交使用现有会话、`location_update`、`update_parent: true` 与 `request_key`，移至根层时明确发 `parent_id: false`。超时保留原键和冻结参数，只用原键重试；再次打开页面后仍能处理未决。服务端拒绝时刷新树并给出原因。保持库位 ID、库码和库存关联。 |
| FL-05 | P1 | 速览统计是本库位口径，袋详情包含子树，容易误解为同一统计。 | 明标「本库位」或「含下级」。结构节点只作目录，库存统计和总仓位数只计算真实内部库位且每个 ID 只计一次。用 `—` 表示缺数据，确认无库存时才显示 `0`。内部库位继续按 ID 进入原袋详情，沿用分页、收货和标签打印。 |
| FL-06 | P1 | 跨端操作术语不同。网页已有改名、停用守卫。 | 保留 Flutter 分区名「仓位速览」，页面操作统一使用「新建库位」「上级库位」「更改上级」。完整对齐时管理员菜单加入「改名」「停用」并走现有服务端守卫。停用有库存的库位或子树时显示服务端原因，原节点保留。 |

源码定位：[Flutter 速览页](../../clients/app/lib/features/warehouse/screens/location_overview_screen.dart#L23) · [库位 API](../../clients/app/lib/services/lab_api_client.dart#L233) · [库位模型](../../clients/app/lib/features/unified/models/detail_models.dart#L80) · [权限模型](../../clients/app/lib/features/unified/models/inventory.dart#L105) · [仓位路由](../../clients/app/lib/features/warehouse/warehouse_routes.dart#L19) · [网页参照](../../server/ubuntu22.04/odoo_addons/lab_team_web/static/src/js/pages/locations.js#L313) · [服务端树响应](../../server/ubuntu22.04/odoo_addons/lab_workflow/models/lab_workflow_api.py#L175) · [移动守卫和记账](../../server/ubuntu22.04/odoo_addons/lab_workflow/models/lab_p3_api.py#L278)

## EDA 界面审查与修改清单

**评级：有关键问题。** EDA 面板的核心任务是读取当前设计、查看实验室可用库存并处理缺料。应延续可以一扫看完的 BOM 表、逐行候选和明确的按袋预览。桌面宿主保留自己的窗口和入口，采用跨端的颜色角色、操作用词、布局和反馈规则。

| 编号 | 优先级 | 实际发现 | 修改要求 |
| --- | --- | --- | --- |
| EDA-01 | P0 | `一键出库` 的禁用条件未包含 `UNKNOWN`。`openBomOutbound()` 清空原 attempt，`runBom()` 和切换范围会重置整个出库状态。新出库可申请新请求号。 | 将未决出库与扫描结果分开。未知结果时给出持续可见的状态、原样重试和核对入口。首次动作、切换范围、刷新、重开面板都不能绕过锁。按服务端身份与连接范围隔离待确认记录，保留重放所需的冻结字段，凭据不写入待确认记录。只允许在服务端明确确认结果或通过请求流水核实后解除锁。成功、需要重新确认、确定失败各走既有状态。依据 `feedback.md › Best practices` 的“把反馈放在它描述的内容附近”。 |
| EDA-02 | P0 | 主按钮白字覆盖三段蓝色渐变。暗色测得 2.86:1、2.44:1、1.83:1，浅色测得 2.86:1、3.65:1、5.62:1。 | 改用跨端的角色色。深色建议沿用 Flutter 的 `#C9FF3F` 填充配 `#0A0D06` 字，**16.64:1**。浅色建议沿用 Flutter 的 `#3D7A00` 填充配 `#FFFFFF` 字，**5.27:1**。主要操作、链接、选中态和成功态分别定义令牌，确认换肤后新旧状态仍易辨认。依据 `accessibility.md › Vision` 的小字号对比度建议和 `color.md › Best practices` 的颜色一致性。 |
| EDA-03 | P1 | 相同目的地用了「连接设置」「连接/账户」「连接与账户」。未连接提示仍要求「登录 Odoo」，网络错误还提旧网桥。头部又重复放设置和诊断。 | 统一入口叫「连接设置」，密钥输入叫「EDA 密钥」，主按钮叫「保存并连接」。常用区保留「器件库」「原理图库存」，收拢重复入口但保留诊断可达。连接、失效、吊销、网络故障各有贴近操作的提示。依据 `toolbars.md › Best practices` 的“选择必要的项目，避免拥挤”。 |
| EDA-04 | P1 | 既有 1100×800 截图显示「需求」「可用」「缺口」「未知」逐字断行。列宽 `2.5rem` 又要扣除左右 16 px。 | 保证这三列表头及状态单行，建议每列至少 56 CSS px，数字右对齐。位号在逗号处分行，61 个以上仍可完整查看。窄面板允许表格容器内部横滑，表格上方的范围、刷新、对比、出库仍可用。候选子行紧跟对应主行，展示 SN、可用量、完整库位和袋码。依据 `layout.md › Visual hierarchy` 和 `lists-and-tables.md › Content` 的可扫读及避免裁切要求。 |
| EDA-05 | P1 | 确认弹窗支持 Esc，但当前初始焦点在确认出库，代码没有设置标题关联、限制 Tab 范围或恢复焦点。整页 `render()` 会重建候选控件。 | 对话框关联标题，初始焦点落在第一输入或取消，Tab 与 Shift+Tab 保持在弹窗内，取消后回到原控件。为切换页签、搜索、展开候选、勾选替代和对话框提供明确焦点。重渲染后恢复同一条目的焦点。依据 `focus-and-selection.md › Best practices` 的“避免未经交互改变焦点”。 |
| EDA-06 | P1 | 已有深浅色分支。多个正文元素使用 11–12 px，玻璃背景和密集信息增加小窗口阅读负担。 | 采用网页和 Flutter 共用的中性内容面板。功能导航和弹窗可保留较轻的半透明层。基本正文 13 CSS px 起，辅助文字可用 12 CSS px 且满足对比度。桌面常用控件至少 28×28 CSS px，触控设备常用按钮至少 44×44 CSS px。深浅色、系统缩放和高对比度下保持同一操作可达。依据 `typography.md › Ensuring legibility`、`layout.md › Adaptability` 和 `dark-mode.md › Dark Mode colors`。 |

源码定位：[面板头部](../../plugins/jlc-eda/src/iframe/app.html#L13) · [连接提示](../../plugins/jlc-eda/src/iframe/app.js#L337) · [确认弹窗](../../plugins/jlc-eda/src/iframe/app.js#L279) · [候选与状态](../../plugins/jlc-eda/src/iframe/app.js#L845) · [新预览重置](../../plugins/jlc-eda/src/iframe/app.js#L1281) · [切换范围重置](../../plugins/jlc-eda/src/iframe/app.js#L1479) · [重扫重置](../../plugins/jlc-eda/src/iframe/app.js#L1626) · [颜色令牌](../../plugins/jlc-eda/src/iframe/app.css#L5) · [主按钮渐变](../../plugins/jlc-eda/src/iframe/app.css#L987) · [Flutter 令牌](../../clients/app/lib/ui/glass/glass_tokens.dart#L80) · [网页令牌](../../server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css#L14)

### 跨端统一的业务用语

| 用户看到的对象或状态 | 应表示的事实 |
| --- | --- |
| 库位名称、库码、库位路径 | 分别为名称、`K…` 稳定编码及完整层级。名称或父级改变后，标签与实物仍通过库码定位同一条记录。 |
| 实验室 SN、立创 C 编号、袋码 | 分别为本地器件档案、设计关联和库存袋。候选显示 SN，原 BOM 保留 C 编号和位号。 |
| 可用、缺料、未知、资料未收录 | 可用是服务端可领数量。缺料有已知差额。未知没有可靠读取结果。资料未收录时仍可按规格查实验室候选。 |
| 可选替代、已选替代、依据较弱 | 候选与选中态由用户操作区分。规格依据不足时给出文字提示。 |
| 待确认、已完成、需重新确认、失败 | 未知结果保留原请求。成功以服务端领用记录为准。库存变化时重新预览，明确失败后再开启新操作。 |

## 验收矩阵

在隔离 Odoo 建同一套测试数据，包含 `WH/库存/M区` 和 `WH/库存/R区`，真实父级 ID、一个 `view` 祖先、60 个 M 和 18 个 R 库位。另建深层节点、重复名称但不同路径、一个停用库位、正可用量和 0 的袋。用管理员和普通库存用户分别登录。真实 EDA 主流程使用隔离服务和测试工程，完成功能写入只发生在隔离库。网页与客户端之间互验路径时优先比记录 ID、库码、父级和统计，不比较展示行数。

### Flutter

| 验收 ID | 操作 | 通过标准 |
| --- | --- | --- |
| FL-T01 | 打开「仓位速览」，展开 `WH → 库存`，分别进入 M 区与 R 区。折叠、再展开、刷新。 | 两区并列，60/18 个子节点对应测试记录。根、叶和目录状态准确，刷新保留展开。验证按数字排序，视图节点没有标签、出入库入口。 |
| FL-T02 | 折叠 M 区，用 `M(10,6)` 和它的库码分别搜索。用区名、完整路径和不存在的词再查，随后清空。 | 命中显示完整祖先和唯一目标，区名能找到对应分支。同名不同 ID 不互相替换。查无结果明确提示，清空恢复之前的展开状态。 |
| FL-T03 | 从树点击内部库位，打开袋详情，加载第二页，返回。给同一库位预览标签。 | 仍使用原 ID 路由。袋分页无重复，详细数值与隔离 API 一致。详情中「含下级」和速览「本库位」有明确区分。标签内容仍用原库码。 |
| FL-T04 | 普通用户登录。切换为管理员，观察权限加载中，随后退出或进入离线。 | 普通用户、权限未确定和离线均不出现写操作，且实际请求数为 0。管理员上线后可见操作。服务端对普通用户的写请求仍拒绝。 |
| FL-T05 | 管理员在 M 区下建子库位，再移动到 R 区；另测移动至根、改名、停用空库位，以及停用有袋的父级。 | 网页和 Flutter 返回同一 `id` 与 `parent_id`。成功后目标分支展开，旧库位码、袋、quant 不变。含袋子树停用被拒绝。失效目标和跨公司目标由服务端拒绝，页面给出可理解提示。 |
| FL-T06 | 检查目标选择，再通过隔离接口提交自身、后代、当前父级及中途停用的父级。 | 页面排除自身、后代和当前父级。服务端拒绝自身、后代或已停用父级，重复设置当前父级不得改变路径或库存。已停用目标刷新后不可选。没有路径循环或孤立记录。 |
| FL-T07 | 人工制造移动已提交但响应丢失，重进页面点击重试。同时验证创建响应丢失、会话过期和双击提交。 | 一次移动只产生一次有效结果，重试使用同键同参。创建结果未知只进入核对流程，不自动创建重复记录。过期提示重新登录，切换账号不会带出别人的待确认操作。 |
| FL-T08 | Windows 和 Linux 窗口测试 900、1280 px 宽。Android 试 360、412 dp 和 200% 字体。分别用鼠标、Tab/Enter 或触摸浏览和编辑。 | 不溢出，不丢文字和关键操作，焦点可见。返回和分区导航保持状态。打印、扫码入库、收货等选择器仍只列内部库位。 |

### EDA

| 验收 ID | 操作 | 通过标准 |
| --- | --- | --- |
| EDA-T01 | 安装候选 `.eext`，在模拟宿主和真实嘉立创 EDA 中测试 1100×800 与紧凑窗口 640×480，深浅色各一次，另测 125%/150% 缩放。 | 读取入口、主要操作和提示可达，视图能滚到底。数量列名称和「未知」不拆字。表格窄时仅容器内部横滑。以实际样式和组合后的背景测常用按钮、警告、输入及页签，小字对比度至少 4.5:1。 |
| EDA-T02 | 用 `C5137636` 的 61 个位号重测。首个位号缺封装，其余含 `C0603_L1.6-W0.8`，参数值包含 `100 nF`。并放入普通缺料、仅无 C 编号和无匹配器件。 | 捕获实际请求形状为独立值 `100nF` 和封装 `0603`。候选跟随原 BOM 行，显示当前库存和 SN。无 C 编号器件仍在同一表中。零候选、加载失败、可用为 0 和未知分别显示。 |
| EDA-T03 | 键盘从标签进入 BOM，展开候选，勾选、换选和取消。打开按袋预览，用 Tab、Shift+Tab、Esc 操作。 | 焦点可见且不会随机跳转。状态更新后同一控件仍能操作。预览绑定刚选的 SN、库位、袋与数量。Esc 取消，无写入。 |
| EDA-T04 | 测未配置密钥、已连接、密钥吊销、网络失败和重新打开面板。 | 设置入口只有一个明确名称。状态与下一步准确，诊断无明文密钥、Cookie 或内部错误栈，操作指引不再提旧本地网桥。 |
| EDA-T05 | 模拟服务端已创建领用单但响应超时。再点重新读取、仅刷新、换读取范围、换页、关闭重开。 | 原请求仍可见，所有新出库入口都被阻断，库存读取仍可进行。重试请求号、用户、用途、袋和数量与原提交一致。后端只出现一张领用单及一组库存变动。无证据时不显示成功，也不产生新请求号。 |
| EDA-T06 | 管理员和普通操作员分别确认，测试取消、减库存导致需要重新确认、服务器明确拒绝、正常提交。 | 取消和预览无写入，更改后需重新核对。普通操作员本人领用，管理员代领仍分开记录操作者和领用人。成功页面、备注和领用凭证能核对选中的 SN 和实际发袋。 |
| EDA-T07 | 升级安装 4.1.4 到新候选，重新打开面板，检查标题、诊断和扩展管理器。用最终包跑全部测试。 | 三处版本相同，现有连接配置按原合同保留。最终 `.eext` 的内容和哈希对应当前冻结源，包测试和浏览器验收运行的是同一个文件。无额外本机桥接程序。 |

## 发布判定与留证

1. 每项标记 `PASS`、`FAIL` 或 `BLOCKED`。一条 `PASS` 须有平台、版本、数据集、命令或操作、结果、证据路径及包哈希。**所有必验项 100% 有证据并通过才标为发布验收通过**。结果未知或缺真机记为 `BLOCKED`。这个标准约束验收覆盖，无法保证未来没有缺陷。
2. Flutter 从同一冻结源码生成三端成品。Windows 和 Linux 保留完整 x64 bundle。Android 核对支持的 ARM64 目标和现有 APK 证书指纹。分别验证冷启动、覆盖安装、登录保持、仓位树和写权限。当前 Windows 构建工具和 Android SDK 可用，未发现已连接 Android 设备。Linux Native/WSLg 的实跑和 EDA 宿主实装均待验证。
3. EDA 更新版本和发行目录，预先保存旧版的已知失败证据。至少让 EDA-T02、EDA-T05 能在旧版本复现已知差异，在新包通过。用 `npm run test:all`、`npm run verify` 和实际 `.eext` 浏览器回放验证。隔离浏览器仅覆盖宿主模拟，真实宿主交付必须另外记一次。
4. 复用 Flutter 的 `warehouse_data_test.dart`、目标页面和路由 widget 测试、`odoo_call_route_test.dart`、`FakeLabApi`，补全树、权限和超时用例。后端复用 `test_13_location_tree_and_move_replay`、`test_01_location_tree_and_move_api`。执行 `flutter analyze`、`flutter test` 和 `python tools/repo_check.py`，按实际输出记录原有警告和新失败。 [Flutter 测试目录](../../clients/app/test/features/warehouse/) · [EDA 发布包回放](../../plugins/jlc-eda/scripts/verify-bom-equivalents.mjs) · [隔离 HTTP 测试](../../server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_p3_workflows_http.py#L389)
5. 为每个成品登记新版本、SHA-256、签名状态、构建工具链和可回滚版本。留存模拟、隔离 Odoo、真实宿主或真机三类证据。测试账号、密钥、Cookie 和真实库存导出不随证据分发。 [发布规范](../../docs/development/RELEASE.md)

设计参考采用其可访问性与信息组织通用原则。EDA 为桌面宿主中的 HTML 面板，Flutter Android 和桌面端按各自输入方式验收。 [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) · [Layout](https://developer.apple.com/design/human-interface-guidelines/layout) · [Color](https://developer.apple.com/design/human-interface-guidelines/color) · [Typography](https://developer.apple.com/design/human-interface-guidelines/typography) · [Lists and tables](https://developer.apple.com/design/human-interface-guidelines/lists-and-tables) · [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars) · [Feedback](https://developer.apple.com/design/human-interface-guidelines/feedback) · [Focus and selection](https://developer.apple.com/design/human-interface-guidelines/focus-and-selection) · [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)

## 实施记录（2026-11-23）

用户确认「按照审查开始修改」。上表的修改项已实现，验收用例补了可重复执行的自动化；真机与真实 EDA 宿主仍是待验收项，未据此宣称发布通过。

| 编号 | 状态 | 证据 |
| --- | --- | --- |
| FL-01 | 已实现 | `LabApiClient.locationsTree`（`with_tree`）、`LabStockLocation.parentId/hierarchyKnown/isView`、`inventoryLocationTreeProvider`。测试：`locationsTree asks for the tree…`、`an older host without parent_id…` |
| FL-02 | 已实现 | `location_overview_screen.dart` 建树、自然排序、折叠、搜索保留祖先、刷新保持展开。测试：`shows the zones…`、`expanding a zone…`、`search reveals a deep match…` |
| FL-03 | 已实现 | 写入口由 `can_manage_locations` 且 `known` 控制；新建对话框含上级选择；结果未知提示核对并不自动重试。测试：`an operator never sees a write action`、`a manager sees create and move` |
| FL-04 | 已实现 | `LocationMoveController` 冻结键重试、`updateLocationParent` 显式 `parent_id: false`；对话框区分「原样重试 / 核对后放弃」。测试：`retry of the SAME move reuses…`、`a DIFFERENT target gets a new key`、`updateLocationParent sends…` |
| FL-05 | 已实现 | 统计只算 `data.locations`，视图目录不计；文案标明本库位/不含子库位。测试：`counting excludes view folders…` |
| FL-06 | 部分实现 | 术语统一为「新建库位 / 上级库位 / 更改上级」。改名/停用仍是 Web 端能力，Flutter 未加（未在本轮范围内新增）。 |
| EDA-01 | 已实现 | `state.bom.pending` + `lab_eda_pending_outbound` 持久化；重扫/切范围不清除；新出库被禁用；重试用保存的键。浏览器夹具断言未决横幅、禁用、重扫保留、同键重试。 |
| EDA-02 | 已实现 | `--primary/--primary-hover/--on-primary`；实测深色 16.64:1、浅色 5.27:1；浏览器夹具按计算样式断言 ≥4.5:1。 |
| EDA-03 | 已实现 | 页签与提示统一「连接设置」，删除头部重复按钮，移除桥接/配对码措辞。包测试断言新标签。 |
| EDA-04 | 已实现 | 数值列 4.5rem、表头不换行、表格最小宽 900px 由容器横滑；浏览器夹具断言「需求/可用/缺口」单行。 |
| EDA-05 | 已实现 | `confirmModal` 带 `aria-labelledby`、初始焦点、Tab 循环、Esc 关闭并还焦；浏览器夹具断言焦点不逃逸且 Esc 不写入。 |
| EDA-06 | 部分实现 | 信息性小字提到 12px；正文基线仍为 13px。桌面/触控最小控件尺寸未逐项加 CSS 断言，需在设计走查中确认。 |

已执行的验证：

- `clients/app`：`flutter analyze --no-pub` 0 error / 0 warning；`flutter test --no-pub` 526 通过、5 跳过；新增 `test/features/warehouse/location_tree_test.dart` 11 项。
- `plugins/jlc-eda`：`npm run test:all` = 144 单元 + 18 打包测试通过；`verify-bom-equivalents.mjs` 对实际 `.eext` 断言读取/候选/缺料/出库、未决锁、同键重试、焦点与主按钮对比度。
- 上述均在隔离模拟环境，未接触生产、真实 EDA 工程或实机。

仍待完成的实际设备验收：

1. 真实嘉立创 EDA 宿主安装 `4.2.0`，跑 EDA-T01…T07。
2. 三端原生包已构建。Windows 与 Linux 通过通道包首帧检查，Android 覆盖安装和三端完整升级回退仍待完成。
3. 生产 Odoo 上的客户端连接与真实库位树（读路径已在生产只读核对，客户端未连生产）。
