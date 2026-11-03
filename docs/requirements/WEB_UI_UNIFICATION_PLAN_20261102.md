# 网页视觉与交互统一方案（含旧操作台迁移）

日期：2026-11-02。状态：提案，未实施、未部署、未完成视觉验收。本轮只改方案文档。

## 目标与本轮边界

把网页端整理成一套完整、一致、能顺手完成日常工作的界面，**范围是整个自有 Web 与全部日常业务入口**，包括仍在用 Odoo 原生模板的旧扫码/入库操作台；不是只给来料页补一个搜索下拉，也不是给旧 Bootstrap 页面换一层配色。

延续现有官网品牌：深色背景、浅色正文、荧光绿强调。保持现有 Odoo 账号与库存业务层，沿用自有网页入口；Odoo 原生后台仅作为管理员维护入口保留，不删除 stock/product/mrp 等底层应用，不修改其业务规则。

本方案不授权生产变更，不修改客户端，不冻结版本、不改 registry，不提交、不推送。

## 当前证据与尚未完成事项

- 自有 UI 已有共享外壳与变量：`lab_team_web/views/pages.xml:5`（布局模板）、`views/team_templates.xml`（业务页外壳与公共状态区）、`static/src/css/team.css:14`（色彩与按钮变量）、`static/src/js/workflow_core.js:653`（六状态标记）。应在此基础上收敛，不另起风格。
- 自有页面已覆盖 18 个路由（见下表），但交互约定不一致：来料页 `static/src/js/pages/receipts.js:558` 的 `resolveItem` 只处理 `lcsc:`、`lab:` 和裸码扫描，没有输入过程中的关键词候选；`receipts.js:585` 的 `requestResolve` 异步回调直接写入选中值，没有请求序号保护，旧响应可覆盖新输入；`views/workflow_receipt.xml:121` 把 `product_template_id` 直接显示给使用者。
- 表单/状态/表格各自实现：`static/src/css/workflow_inventory.css:59` 只为本域设置 `color-scheme: dark`；`team.css:2013` 的 `.lc-table-wrap` 用 `overflow-x:auto` + `min-width:560px` 让窄屏横向滚动；`receipts.js:1308` 的 `wireTabs` 只切换 `aria-selected`，无方向键与焦点管理；`views/workflow_inventory.xml:416` 角色勾选提交即时生效，与其他表单的“保存”语义不同。
- **旧操作台仍是真实源码路径**：`lab_workflow/views/lab_scan_views.xml` 的 `lab_scan_console` 模板用 `web.html_container` + Bootstrap（`container mt-3`、`card`、`form-control`、`btn btn-primary`），内有内联 `<script>`（`lab_scan_views.xml:206-233`）向 `/lab/scan/resolve` 发请求，与自有页“仅 `script-src 'self'`、无内联脚本”的纪律不一致。
- `GET /lab/scan` 是否已跳新页取决于运行态：`lab_workflow/controllers/lab_web.py:46-58` 先算跳转目标，命中才 `redirect(target, code=303)`，否则回退渲染旧模板；目标由 `ir.config_parameter`（`p3_rules.SCAN_REDIRECT_PARAM`，默认 `/team/scan`）和 `_route_available()`（`lab_web.py:88-94`，用 `ir.http._match` 判定）共同决定。**因此“源码里有新页”不能等同于“线上已迁移”**；当前线上参数值与模块升级状态本方案未验证。
- `maintenance/audit/style-unification-20261024.md` 顶部已注明“100%”为原实施者自述，视觉兼容性未验证；不能当作全站风格验收。
- P3 历史测试说明业务功能覆盖，不代表全站视觉、弹层、窄屏或实际部署版本已通过。本提案基于源码与文档检查，**没有**实时线上视觉审查，也没有登录生产补结论。
- 现有截图 `local/build/p3-web-20261028/runs/browser-20261028T065311Z/shot-p3-*.png` 的中文字形渲染为方框，只能证明“页面能打开”，不能作为中文排版或视觉验收证据。
- **交互独立评审补充（`local/legacy-web-team/ux-audit.md`，作为证据看待；以下条目均已按源码复核，非评审原文照抄）**：
  - 触发路径：`static/src/js/pages/receipts.js:1326-1332` 只有点击按钮才解析；全页仅 `:1392-1396` 对 `[data-lc-scan]` 绑定 Enter，料号输入框没有 input/keydown 监听，且该输入框位于 `data-lc-form="pending-create"` 表单之外（`views/workflow_receipt.xml:105-133`），挂载时无 autofocus。旧台反而有 `lab_workflow/views/lab_scan_views.xml:227-230` 的 `input.focus()` + Enter→`labResolve()`。
  - 候选可辨识性：`receipts.js:664-675` 对 `lab_template_ids` 置 `sn=null`，选项文本 `:494-499` 只含 sn/name/mpn 与 `#product_template_id` —— 两个同名同型号档案会得到仅差数据库 id 的同文选项。
  - 选中值不同步：`renderMaterialSelect` 只在渲染时写 `select.value`（`:520-530`），全文件没有 `material-select` 的 change 监听；提交读表单值（`:729`），`templateId=0` 时静默省略（`:755`），服务端按 item_key 取默认档案 —— 会出现“屏幕上是 A、提交的是 B”。
  - 请求不可取消：`static/src/js/workflow_core.js:449-467` 每请求建 AbortController 但只用于超时，`rpc()`（`:536`）不返回句柄，页面层无法取消在途请求；`receipts.js:585` 的回调直接写 `state.selected`。
  - 页签：`wireTabs`（`receipts.js:1308-1321`）只切 class/aria-selected/URL，无 tabpanel/aria-controls/方向键；刷新按 URL 恢复页签（`:1419-1435`）但 `state.selected` 为空。
  - 窄屏导航：`team.css:1419-1439` 在 ≤760px 让 `.lc-nav` 换行后 `flex-wrap:nowrap; overflow-x:auto`，与第一节“收进抽屉”相反；原组件清单缺“导航/抽屉”一行。（**实施前证据**：2026-11-02 本轮已按 1024px 断点改为固定侧栏 + 抽屉，原 ≤760px 横向滚动规则已从 `team.css` 删除；此行保留仅为记录评审依据。）
  - 权限前提：候选只能走 `lab_catalog/controllers/catalog_api.py:54` 的 `/lab/api/catalog/search`（`auth='user'`），模型入口 `models/lab_catalog_item.py:724` 先执行 `_check_catalog_read_access()`。正常配置下 `lab_workflow.group_lab_user` 的 `implied_ids` 已含 `lab_catalog.group_lab_catalog_user`（`lab_workflow/security/lab_workflow_imply.xml:19-20`，且 `group_lab_operator` 隐含 `group_lab_user`，`lab_workflow_groups.xml:33`），所以“有库存角色但无目录读取”属异常配置而非常态；仍必须按 `lab_team_web/controllers/common.py:66-70,246` 的 `has_catalog_access()` 实测，且不得为界面放宽目录权限。
  - 旧台诊断：旧台把 resolve 返回整体 `JSON.stringify` 进 `<pre id="lab_scan_result">`（`lab_scan_views.xml:207-220`）；新页对 bag/location（`receipts.js:589-593`）与未识别码（`:619-622`）只给一句话，没有可复述的诊断号。
- **全局暗色主题已存在**：`lab_theme/__manifest__.py:25-34` 把 `lab_theme/static/src/css/global_dark_theme.css` prepend 进 backend/frontend —— 旧 Odoo 页面本身就是暗色，**不能凭“看起来是暗色”判断已迁移**，必须按模板/动作 id 判定。
- **根级别名是配置结果，不是路由缺失**：`lab_team_web/tools/paths.py:23` 的 `ROOT_ALIASES = ('/login', '/logout', '/lab', '/scan', '/account')` 覆盖 13 个业务页的第二条路由；`root_aliases=0` 或 management Host 不匹配时按不存在处理（`common.py:340-360`、`pages.py:140,163,180`），因此“根别名 404”要先查配置与 Host，再判断是否迁移问题。
- **日常第一屏仍指向 OWL 客户端动作**：`lab_catalog/views/lab_catalog_menu.xml:14-26` 重定义了 `lab_inventory.menu_lab_root`（action = 统一器件库 OWL、groups = `group_lab_catalog_user`、sequence 60），并把「仓库」挂在下面（sequence 1）。
- **菜单/动作都还指向旧 action**：`lab_workflow/views/menu.xml:5-38`、`lab_catalog_menu.xml`、`lab_inventory/views/menu.xml` 中没有任何一条 act_url 指向新页 —— 这正是“服务器旧 GET 映射”不能代替“菜单已迁移”的原因（机制见 2.6）。

## 一、统一页面结构（自有 UI）

桌面：固定业务侧栏 + 顶部账号区；内容区固定为“页面标题与说明 → 筛选/主操作 → 内容 → 分页/结果”。窄屏：同层级导航收进抽屉，保持当前位置，不把全部菜单横向堆叠；主操作按钮在首屏可达，不依赖横向滚动。**实施前现状与此相反**：`team.css:1419-1439` 在 ≤760px 让 `.lc-nav` 占满一行并横向滚动，属于要改的现状，不是既有实现。（本轮已实现：≥1024px 固定侧栏、≤1023px 抽屉；原 ≤760px 横向滚动规则已删除。）

| 导航组 | 页面（路由） | 重点 |
| --- | --- | --- |
| 器件与库存 | `/team/lab` 器件库、`/team/lab/items/<item_key>` 详情、`/team/lab/bags`、`/team/lab/bags/<bag_id>`、`/team/lab/locations` | 共用器件信息卡；数量来源与单位清楚；库位/袋在详情展开 |
| 日常操作 | `/team/lab/receipts` 来料入库、`/team/scan` 扫码上架、`/team/lab/issues/new` 领用、`/team/lab/issues` 归还与记录 | 共用选择器与表单；步骤清楚；提交前可核对，完成后知道下一步 |
| 记录与标签 | `/team/lab/history` 流水、`/team/lab/labels` 标签中心 | 共用筛选、状态标记、分页；打印与库存确认区分清楚 |
| 管理 | `/team/lab/materials` 器件档案、`/team/lab/location-mappings` 类别→库位映射、`/team/lab/settings` 成员权限、`/team/account` 账号 | 共用编辑与确认；危险操作可辨识；按权限展示 |
| 入口 | `/team` 欢迎、`/team/login` 登录、`/team/logout` | 同一品牌、表单与反馈规范 |

普通成员日常业务必须落在上述自有页面；不因为某页暂时缺能力就把使用者导入原生后台。

路由口径：本表 18 个页面入口 = `controllers/workflow_pages.py:194-273` 的 13 个业务页 + `controllers/pages.py:130-236` 的 5 个入口页；每个入口同时注册 `/team/...` 与根级别名两条规则，合计 36 条 route 规则。**不要把“13 个业务页”与“全站路由总数”混为一个数字**；根别名是否可用取决于 `root_aliases` 与 management Host 配置（见“当前证据”）。

## 二、旧 Odoo 日常页面迁移矩阵

### 2.1 判定原则

1. **日常业务入口迁移**：普通成员每天用的扫码、入库、领用、归还、袋与追溯、库位、标签、流水，一律以自有 UI 为目标页，且必须保住全部既有能力（解析、制袋、打印、上架确认、部分归还、未知结果保护）。
2. **管理员维护入口保留**：器件档案批量维护、分类树、导入批次、幂等请求日志、用户与权限的 Odoo 原生视图属于维护/诊断面，保留原生形态，不迁进日常路径，也不改其业务规则。
3. **不换色冒充**：旧模板即使沿用，也不做“套一层深色皮肤”。判定依据是日常路径是否还会打开旧模板，而不是 CSS 有没有变。
4. **能力等价再切换**：目标页缺一项既有能力时，不得把旧入口关掉；迁移完成 = 目标页能力覆盖 + 旧入口仅剩兼容跳转。
5. **安全规则不变**：权限门槛、CSRF、`request_key` 幂等、行锁、未知结果保护全部沿用现有模型方法与控制器，不因换页面而放宽；`/lab/api` 的权限边界与 `bore` 白名单不扩大。
6. **按业务频率与责任面判定，不按角色名判定**：即使某日常操作只有 manager 能做（如成员权限、器件档案维护），只要它是日常业务，就纳入统一 UI；只有真正低频且偏运维/审计的（分类树、导入批次、幂等请求日志、Odoo 用户与权限原生视图）才保留原生。不得因为“这个角色叫 manager”就把应统一的日常操作排除在外。
7. **权限结果显式**：无权限必须是 403 或引导登录，不能用“回退旧界面”掩盖授权失败（细则见 2.3）。
8. **迁移以菜单/动作改指为准**：服务器端旧 GET 兼容映射只解决“旧链接进来”，不代表日常入口已迁移；判定完成要看菜单项与 `ir.actions.*` 本身是否已指向自有业务页（机制见 2.6）。

### 2.2 逐入口矩阵

状态列含义：**目标页已有（源码）** = 自有页面已存在且源码层面覆盖主要能力；**需补充** = 目标页存在但源码层缺能力；**保留原生** = 维持 Odoo 维护入口；**未证实** = 线上是否已按此路径生效未经核实。

| 入口（菜单/动作 xmlid） | 当前实现（证据） | 目标页 | 必须保留的业务能力 | 迁移状态/未证实项 |
| --- | --- | --- | --- | --- |
| `lab_workflow.menu_lab_scan` 扫码操作台 → `action_lab_scan_console`（`ir.actions.act_url`，url `/lab/scan`，`lab_scan_views.xml:238-242`） | `lab_scan_views.xml`：解析卡片（:32-40）、来料建袋（:46-97）、领用（:100-142）、归还（:145-191）、跳转链接（:193-203）、内联脚本（:206-233）；控制器 `lab_web.py:46` 条件 303，`:121` resolve、`:142` submit | `/team/lab/receipts` + `/team/scan` | 扫码解析、建袋、打印标签、上架确认、领用、归还、未决请求保护 | 目标页已有（源码）；旧控制台“一页三卡”合并语义需在目标页逐项对照；**未证实**线上 303 是否生效 |
| `lab_workflow.menu_lab_issue_line` 领用记录 → `action_lab_issue_line`（`lab_issue_views.xml:105`，list,form） | Odoo 列表/表单；`lab_return_wizard_views.xml:5` 归还向导 | `/team/lab/issues`、`/team/lab/issues/new` | 领用登记（领用人须系统账号）、按原领料部分归还、状态与项目字段 | 目标页已有（源码）；需补充：领用/归还的完整键盘与错误状态 |
| `action_lab_return_wizard` 扫码/表单归还（`lab_issue_views.xml:115-125`：`res_model` = `lab.issue.line`，`view_mode` **list,form**，domain `outstanding_quantity > 0`；归还表单视图 `lab_return_wizard_views.xml:5`） | Odoo 列表选行 → 表单内「登记归还」 | `/team/lab/issues` 归还表单 | 关联原领料、数量上限=未归还数、默认回原库位/原袋 | 需补充：向导内校验提示迁移为页内错误；类型已按源码核对为 list,form（不是纯 form） |
| `lab_workflow.menu_lab_bag` 库存袋与追溯码 → `action_lab_bag`（`lab_bag_views.xml:122`） | Odoo list,form | `/team/lab/bags`、`/team/lab/bags/<bag_id>` | 一袋一码、追溯链、袋状态与库位 | 目标页已有（源码）；需补充：追溯链在窄屏可读、单袋详情字段对齐 |
| `lab_workflow.menu_lab_operation_list` 库存作业流水 → `action_lab_operation`（`lab_operation_views.xml:125`） | Odoo list,form | `/team/lab/history` | 流水筛选、分页、状态与关联单据 | 目标页已有（源码）；需补充：窄co'de'a屏列表不以横向滚动为主 |
| `lab_workflow.menu_lab_location` 库位与库码 → `action_lab_location`（`lab_location_views.xml:59`） | Odoo list,form | `/team/lab/locations` | 库位树、库码、库位上下架可用性 | 目标页已有（源码） |
| `lab_workflow.menu_lab_labels` 批量标签（A4）→ `action_lab_label_open`（`lab_label_views.xml:52`，form wizard） | Odoo 向导 + `/lab/labels/plan`、`/lab/labels/download`（`lab_web.py:210,245`，operator 门槛、尺寸/批量边界、`no-store`） | `/team/lab/labels` | 批量选择、A4 排版、PDF 下载、仅 operator | 目标页已有（源码）；需补充：打印前预览、失败原因可见 |
| `menu_lab_request_log` 请求记账（幂等）→ `action_lab_request_log`（`lab_request_log_views.xml:80`） | Odoo list,form | 无（不迁入日常 UI） | 幂等键、载荷指纹、未知结果排查 | **保留原生**（manager 诊断入口）；不暴露给普通成员 |
| `lab_catalog.action_lab_unified_catalog_client` 统一器件库 / `menu_lab_unified_catalog` 仓库（`lab_catalog_menu.xml:8-26`，OWL client tag `lab_catalog.unified`） | Odoo 内 OWL 页面（单列表+分类树+筛选+图片卡片+详情） | `/team/lab`、`/team/lab/items/<item_key>` | 组合筛选、分类浏览、详情、库存与档案状态 | 目标页已有（源码）；需补充：与 OWL 页的筛选项逐项对照，避免能力回退 |
| `view_lab_catalog_item_action` 资料库索引（`lab_catalog_views.xml:99-102`，`view_mode` **tree,form**，manager） | Odoo 列表/表单 | `/team/lab/materials` 为日常维护页 | 档案增改、上下架标记、字段校验 | 目标页已有（源码，日常面）；批量运维仍用原生列表 |
| `view_lab_catalog_category_action` 商城分类（`lab_catalog_views.xml:127-130`，`view_mode` **tree**，manager） | Odoo 列表 | 无 | 分类树维护 | **保留原生**（低频管理） |
| `view_lab_catalog_binding_action` C 编号绑定（`lab_catalog_views.xml:147-150`，`view_mode` 为 **tree**） | Odoo 绑定列表（只列表浏览） | `/team/lab/materials` 页内绑定表单（`workflow_inventory.xml:518` 的 `data-lc-form="material-bind"`；`static/src/js/pages/materials.js:132` 行内“绑定”按钮、`:343` `catalogWrite()`、`:360` `catalogBind`、`:672` 提交处理） | 立创号与本地档案绑定、唯一约束去重、结果未知时可显式重试同一内容 | 目标页**源码已有**（此前误记为“待接入”，此处更正）；待验：与原生 tree 的等价性（列表浏览/批量、唯一约束冲突文案） |
| `view_lab_catalog_import_run_action` 导入批次（`lab_catalog_views.xml:201-204`，`view_mode` **tree,form**，manager） | Odoo 列表/表单 | 无 | 导入批次与结果审计 | **保留原生** |
| `lab_inventory.menu_lab_product` 元器件档案 → `action_lab_product`（`lab_inventory/views/menu.xml:5`） | Odoo list,form | `/team/lab/materials` | 档案字段、图片、库存来源 | 目标页已有（源码）；与资料库索引去重需在验收时确认同一份数据 |
| `lab_inventory.menu_lab_location` 库位管理 → `action_lab_location`（`menu.xml:7`） | Odoo list,form | `/team/lab/locations` | 同上库位能力 | 目标页已有（源码），注意 xmlid 与 lab_workflow 库位动作同名不同源，验收需分别确认 |
| `lab_inventory.menu_lab_mapping` 类别→库位映射 → `action_lab_mapping`（`menu.xml:9`） | Odoo list,form | `/team/lab/location-mappings` | 类别与库位映射规则 | 目标页已有（源码） |
| `lab_inventory.menu_lab_move` 库存流水 → `action_lab_move`（`menu.xml:11`） | Odoo list,form | `/team/lab/history` | 流水查询与导出 | 目标页已有（源码）；需补充：筛选条件与导出能力对照 |
| 历史库存分袋适配 `lab_workflow/controllers/lab_inventory_api.py:184` `legacy_stock`、`:196` `adopt_stock` | **只有 JSON-RPC，全仓无 UI 入口**（在 `controllers/`、`views/`、`static/` 中均无调用方） | 无 | 历史库存一次性分袋、对账报告 | **保留在维护面，不新增日常 UI**；理由：这是一次性迁移/排障动作，由管理员按脚本调用；若业务要求日常化，须另行立项，不在本轮扩业务实现 |
| `lab_workflow.menu_lab_location` 库位与库码（`menu.xml:30`，父级 `menu_lab_config`） | Odoo `stock.location` list,form | `/team/lab/locations` | 库位树、库码、上下架可用性 | 目标页已有（源码）；**菜单仍指向原生 action**，须按 2.6 改指。**不能因为它在「配置」组下就整组排除** |
| `lab_workflow.menu_lab_labels` 批量标签（`menu.xml:34`） | Odoo form 向导 → base64 下载 | `/team/lab/labels` | 批量选择、A4 排版、PDF、仅 operator | 目标页已有（源码）；向导的字段勾选/预览等价性待逐项对照；菜单仍指向原生向导，须按 2.6 改指 |
| `lab_workflow.menu_lab_request_log` 请求记账（幂等，`menu.xml:38`） | Odoo list,form | 无 | 幂等键、载荷指纹、未知结果排查 | **保留原生**（低频诊断面）；理由：只有排障时才需要看原始载荷与请求号，迁进日常 UI 反而扩大敏感信息面 |
| `lab_user_access_views.xml:3` 继承 `res.users` 表单 | Odoo 表单 | `/team/lab/settings` | 角色授予、末位管理员保护、跨公司影响提示 | 目标页已有（源码）；Odoo 用户/权限原生视图保留 |
| Odoo 原生 stock/product/mrp 等应用菜单 | Odoo 原生 | 无 | 底层库存、产品、制造维护 | **保留不动**；不删除、不迁移、不套色 |

视图类型已逐个按源码核对：`action_lab_issue_line`、`action_lab_return_wizard`、`action_lab_bag`、`action_lab_operation`、`action_lab_location`、`action_lab_request_log` 为 `list,form`；`action_lab_label_open` 为 `form`（wizard）；`lab_catalog` 的 item 为 `tree,form`，category 与 binding 为 `tree`，import run 为 `tree,form`；`lab_inventory` 的 product/location/mapping/move 为 `list,form`。源码里 `tree` 与 `list` 两种写法混用（新版以 list 为标准），不影响动作语义，但迁移验收必须按实际视图类型核对能力，不能一律假设“列表+表单”。

> 待核查：上述 xmlid 是否都出现在 `-u` 升级后的菜单树、以及目标页路由在生产是否全部注册，本方案未连生产核实。

### 2.3 旧链接兼容与跳转规则

- **GET 白名单映射**：只把矩阵中“迁移”类入口的 GET 链接（`/odoo/action-<xmlid>`、`/lab/scan`）静态映射到目标页，映射表写在代码常量里，不做开放式参数拼接。
- **保留业务上下文**：允许携带 `bag_id`、`issue_line_id`、`item_key`、筛选条件等既有上下文，按白名单字段名逐个取值并校验类型；未知参数丢弃，不原样透传。
- **先鉴权后跳转**：跳转前完成现有 `require_lab_access()`/operator 校验，再确认目标路由已注册（复用 `lab_web.py:88-94` 的 `ir.http._match` 判定），命中才 303。
- **权限失败显式，不用旧界面兜底**：无权限一律 403，或 302 到 `/team/login` 要求登录，并说明缺哪个角色；**不允许**因为“新页打不开”就把未授权用户送回旧界面。只有目标页所属模块未安装/未升级、目标路由确实未注册这类**部署原因**，才允许回退到仍然独立鉴权的内网兼容页，并在页面与文档标注“迁移未完成”；公网入口不得因此扩大白名单，也不得让兼容页绕过 `bore` 既有边界。
- **按真实语义区分旧端点（已按源码核对）**：
  - `GET /lab/scan`（`lab_web.py:46`）：入口读请求，可 303 到目标页。
  - `POST /lab/scan/resolve`（`:121`，`csrf=True`）：**解析/读**，只调用 `lab_resolve_code()` 返回解析结果，不写库；此前与写入口混称，此处更正。
  - `POST /lab/scan/submit`（`:142`，`csrf=True`）：**唯一的 `request_key` 写入口**（receipt/issue/return，`:153` `payload.setdefault('request_key', ...)`）。
  - `POST /lab/labels/plan`（`:210`，operator）：排版试算，只算每页张数/总页数，不改库存；`POST /lab/labels/download`（`:245`，operator）：生成并下载 PDF，不改库存。
  - 以上 POST 一律不得用 307/308 或前端自动重发搬到新页；保持现有 CSRF、权限、幂等与未知结果行为，下线需单独授权。
- **新页对应端点**（各旧端点 docstring 已标 deprecated）：解析 → `/lab/api/inventory/resolve_code`；来料/领用/归还 → `/lab/api/inventory/{receipt,issue,return}`；标签试算 → `/lab/api/labels/plan`；PDF → `POST /lab/labels/pdf`。
- **幂等与未知结果不变**：跳转只影响“去哪里填表”，不影响 `request_key`、载荷指纹、行锁与未知结果提示；未知结果仍按原载荷原键重试。
- **映射不等于迁移**：2.3 只解决“旧链接/旧书签/旧插件进来”；判断日常入口是否迁移，必须看 2.6 的菜单/动作改指结果。只做服务器映射而菜单仍指旧 action 时，日常点击仍会进 Odoo 原生页，迁移未完成。
- **根级别名与 404**：`/scan`、`/lab/receipts` 等别名在 `root_aliases=0` 或 management Host 不匹配时按不存在处理（`common.py:340-360`、`pages.py:140,163,180`）；排障先查配置与 Host，不把它当迁移缺陷，兼容层也不得假设根别名一定存在。
- **旧模板降级而非美工**：迁移完成后旧模板仅作为管理员/兼容回退可达（菜单隐藏或仅 manager 可见），不进入日常路径；隐藏菜单需要单独确认，不在本轮执行。

### 2.4 EDA 与客户端入口

- `plugins/jlc-eda/src/main/panel.js:68-76` 的 `ODOO_ACTIONS` 固定映射 7 个入口（bag_list、issue_list、label_open、location_list、operation_list、scan_console、request_log），`odooActionUrl()`（`:78-85`）拼成 `/odoo/action-<xmlid>` 并新窗口打开。**首选方案是后续插件版本把动作表直接改为新业务 URL**（`/team/lab/bags`、`/team/lab/issues`、`/team/lab/labels`、`/team/lab/locations`、`/team/lab/history`、`/team/lab/receipts`），由插件自身完成入口迁移；服务器端 2.3 的精确旧 GET 映射只是**旧版本插件与旧书签的兼容层**，不是唯一或长期方案，且白名单仅限矩阵中已迁移的固定 xmlid，不接受任意 URL。
- `request_log` 与 `label_open` 属管理/打印面：前者保留原生诊断页，后者映射到 `/team/lab/labels`，但需 operator 权限，无权时给出说明而不是空白页。
- Flutter 客户端（`clients/app/lib`）不内嵌网页：仅 `features/unified/services/pdf_output.dart:159` 用 `launchUrl(Uri.file(...))` 打开本地 PDF；业务请求走 `/lab/api/`，会话走 `/web/session/*`（`config/odoo_config.dart:42,45,48`）。客户端入口适配属于后续独立任务，本轮只登记，不修改。
- 站内快捷入口：`lab_scan_views.xml:194,197,200` 三处 `/odoo/action-*` 链接随旧模板一起降级；新页侧边栏导航（`pages.xml:5` 布局）是唯一日常入口。

### 2.5 迁移完成的判定

1. 矩阵中“迁移”行全部目标页可用，能力逐项对照通过（见第七节验收清单）。
2. 日常导航与 EDA 打开的入口都不再落到旧模板；旧模板仅管理员兼容可达。
3. 旧 GET 映射有单测覆盖（白名单、上下文保留、无权/未注册回退、无开放重定向）。
4. 旧 POST 行为与幂等、未知结果保护有回归测试，未被跳转逻辑影响。
5. 若某能力不能对齐，保留旧入口并在文档写明差距；不以“已换色”结项。
6. EDA 入口以插件自身改为新业务 URL 为主路径；服务器兼容层只保留矩阵内固定 xmlid 白名单，确认无旧版本调用后再单独评估移除。
7. 无权限场景抽查：必须得到 403 或登录引导，不能出现“越权也照样打开旧页面”或“静默回退”。


### 2.6 菜单与动作改指的落地机制（迁移的执行面）

2.3 的服务器映射只覆盖“旧链接进来”。日常迁移真正要改的是**菜单项与动作本身**，否则用户从侧栏点进去仍然是 Odoo 原生页/OWL 客户端动作。逐行选定以下三种方式之一后再实施：

| 方式 | 适用 | 具体实现 | 可逆性 |
| --- | --- | --- | --- |
| A 同 xmlid 覆盖 `action` | 目标页能力已对齐的日常入口 | 在自有模块的 menu xml 里重定义同名 `menuitem`，`action` 指向**新增**的 `ir.actions.act_url`（`url='/team/...'`、`target='self'`）；旧 `ir.actions.act_window` 记录保留，供 2.3 兼容层与管理员回退引用 | 改回原 action 引用即可 |
| B 仅调菜单可见性 | 动作仍要给管理员直接用 | menuitem 加/改 `groups`，日常角色看不到；管理员仍从原生视图进入 | 改 groups |
| C 保留原生并写明理由 | 低频维护/诊断面 | 不动 | — |

约束：

1. 改指一律用 `act_url` 指已注册的业务路由；不要用 `act_window` 指 http 路由，也不要新建“假模型”骗菜单。
2. 覆盖 menuitem 时保留既有 `groups` 与 `sequence` 语义。`lab_catalog/views/lab_catalog_menu.xml:14` 曾覆盖 `lab_inventory.menu_lab_root` 的 groups 为 `group_lab_catalog_user`；迁移不得再缩小可见性，并且要在实施时核对“只有 lab_inventory 组的账号能否看到根菜单”这一既存风险。
3. 每条改指必须对应 2.2 矩阵的同一行与第六节验收项，禁止“菜单改了但矩阵没记”。
4. 旧控制台的解析、入库、领用、归还能力改指前，必须逐项确认目标页已对齐（2.5 第 1 条）。未对齐时保留现有已授权的可用入口并标记迁移未完成；不能先隐藏仍必需的日常入口。仅重复、已替代或确属维护面的菜单才考虑 B。
5. 改指属于业务实现，需要单独授权；本轮只登记机制与目标，不实施。

逐菜单落点（xmlid 均按源码核对）：

| 菜单 xmlid | 当前 action | 目标 | 方式 | 前置条件 |
| --- | --- | --- | --- | --- |
| `lab_workflow.menu_lab_scan`（`menu.xml:11`） | `act_url /lab/scan` | `/team/scan` | A（能力未对齐前保留现有入口） | 旧台各业务能力逐项对照通过 |
| `lab_workflow.menu_lab_issue_line`（`:15`） | `act_window action_lab_issue_line` | `/team/lab/issues` | A | 归还向导语义已迁入页内 |
| `lab_workflow.menu_lab_bag`（`:19`） | `act_window action_lab_bag` | `/team/lab/bags` | A | 单袋详情/追溯链可读 |
| `lab_workflow.menu_lab_operation_list`（`:23`） | `act_window action_lab_operation` | `/team/lab/history` | A | 筛选与分页对齐 |
| `lab_workflow.menu_lab_location`（`:30`） | `act_window action_lab_location` | `/team/lab/locations` | A | 库位树/库码可用 |
| `lab_workflow.menu_lab_labels`（`:34`） | `act_window action_lab_label_open`（form 向导） | `/team/lab/labels` | A + B（向导留给管理员） | 字段勾选与预览等价性确认 |
| `lab_workflow.menu_lab_request_log`（`:38`） | `act_window action_lab_request_log` | 无 | C | 低频诊断面 |
| `lab_inventory.menu_lab_root`（被 lab_catalog 覆盖） / `lab_catalog.menu_lab_unified_catalog`（`lab_catalog_menu.xml:14,22`） | `ir.actions.client`（OWL 统一器件库） | `/team/lab` | A（另保留必要的管理员维护入口） | 器件库筛选/详情能力对照 |
| `lab_catalog.menu_lab_catalog_index`（`:28`） | `act_window view_lab_catalog_item_action`（tree,form） | `/team/lab/materials` | B | 批量运维仍在原生列表 |
| `lab_catalog.menu_lab_catalog_category`（`:35`） | `act_window`（tree） | 无 | C | 低频分类维护 |
| `lab_inventory.menu_lab_product` / `menu_lab_location` / `menu_lab_mapping` / `menu_lab_move`（`lab_inventory/views/menu.xml:5-11`） | 四个 `act_window`（list,form） | `/team/lab/materials`、`/locations`、`/location-mappings`、`/history` | A | 与 lab_workflow 同名动作分别核对来源，避免只改一处 |
| `lab_catalog` 绑定/导入批次菜单 | `act_window` | 绑定：`/team/lab/materials` 页内表单；导入：保留 | 绑定 A、导入 C | 绑定等价性确认（2.2 已注明源码已有） |

> 未登记的小部件/行内按钮入口（如原生表单里的“打印标签”“登记归还”）也要在同一轮按此表判定，不能只改菜单。
## 三、统一视觉与共用控件

- 色彩：沿用现有深色与荧光绿变量（`team.css:14` 起）；绿色用于主操作、选中与焦点；错误/警告/成功各有文字与状态色，不能只靠颜色区分。
- 字体：中文正文统一系统字体栈；料号、型号、追溯码用等宽字体；正文 16px 起，辅助文字不承担唯一重要信息。
- 尺寸：统一间距尺度、控件高度、边框与圆角；同一行的搜索框、普通输入、日期筛选、下拉触发器对齐；触控目标 ≥44px。
- 层级：一页一个明确主操作；次要操作用描边/文字；取消/删除不抢主操作；不把所有面板做成同样醒目的卡片。
- 表单：字段名、必填、单位、示例、错误位置统一；错误紧邻字段并保留已填内容；技术字段名改业务用语，诊断信息折叠。
- 下拉/候选：触发器、展开面板、候选行、选中态统一；限高可滚动；靠近视口底部时上翻；不被父容器或 `overflow` 裁切。
- 术语表（面向使用者）：`product_template_id`→“档案编号”，`item_key`→“器件编号”，`bag_id`→“袋编号”，`request_key`→折叠为“请求号（诊断）”；库存只把 Odoo 实验室数量标为库存，供应商数量标为“供应商在售”，两者不合并成同一个“库存”。

共用组件清单（先建规范再落地，避免每页重复实现）：

| 组件 | 作用 | 必须覆盖 |
| --- | --- | --- |
| 字段与校验 | 标签、必填、单位、示例、行内错误 | 错误定位、保留输入、禁用态 |
| 普通下拉 | 少量固定选项 | 键盘、暗色、窄屏 |
| 搜索型 combobox | 器件/库位/成员选择 | 防抖 250ms、最小输入、候选条数上限、请求序号/可取消、乱序丢弃、IME、autofocus、Enter/Esc、空/错/重试、显式选择、候选可辨识、双向绑定 |
| 状态区 | 加载/空/错误/结果未知/完成 | 文字+图标+颜色三通道，就近显示 |
| 提交锁 | 防重复提交 | 锁定范围、解锁条件、保持输入 |
| 列表与分页 | 流水、袋、领用记录 | 窄屏主次字段、展开详情、不靠横向滚动 |
| 表格/详情卡 | 器件、袋、库位 | 字段顺序一致、长文本换行 |
| 确认对话框 | 危险/不可逆操作 | 明确影响范围与取消 |
| 页签/步骤 | 来料两阶段 | `role=tabpanel`+`aria-controls`、roving tabindex、方向键/Home/End、焦点与状态说明、切换/刷新时的选择与在途请求契约 |
| 标签与徽标 | 档案状态、袋状态 | 不只靠颜色、可读文案 |
| 导航/抽屉 | 桌面侧栏、窄屏抽屉 | 触发按钮、焦点陷阱、Esc 关闭、关闭后焦点回触发按钮、`aria-current`、11 项导航不横向滚动（现状 `team.css:1419-1439`） |
| 诊断块（折叠） | 未识别码/失败排查 | 默认折叠、管理者可见、给可复述诊断号；**不把旧台整段 JSON 直接丢给日常用户** |


### 3.1 候选数据源、权限前提与请求预算

- 两条数据源分工：**编号/扫码**走解析接口（新页 `/lab/api/inventory/resolve_code`，旧 `/lab/scan/resolve` 兼容），只解析一个代码、不产生候选列表；**关键词候选**走 `POST /lab/api/catalog/search`（`lab_catalog/controllers/catalog_api.py:54`，`auth='user'`）。
- 权限前提按实际组关系核对（不靠函数名猜）：模型入口 `models/lab_catalog_item.py:724` 先执行 `_check_catalog_read_access()`；正常配置下 `lab_workflow.group_lab_user` 已隐含 `lab_catalog.group_lab_catalog_user`（`lab_workflow/security/lab_workflow_imply.xml:19-20`），`group_lab_operator` 又隐含 `group_lab_user`（`lab_workflow_groups.xml:33`），所以操作员本来就该有候选权限。**异常配置**（目录组被剔除/自建账号）下 `has_catalog_access()` 为假时，界面降级为“仅编号/扫码解析”并在输入框旁常驻说明，不静默 403，也**不为界面放宽目录权限**。
- 公开缓存不能当候选源：`lab_catalog/controllers/asset_cache.py` 是图片资产缓存（`lab_catalog_asset_cache`），不是器件检索缓存；“匿名可搜”属新的安全评审，本轮不评估、不实施。
- 请求预算：最小输入 2 字符（`C` 前缀/纯数字可按前缀即查）；`limit≤10`（接口允许 1–200，见 `catalog_api.py:57`，界面不用大页）；不带 `category`/`brands` 过滤；读超时 8s，超时按“失败/结果未知”提示，不显示空结果。
- 过期与取消：页面维护 `seq`，每次输入自增并使旧请求失效；在途 ≤2；晚到响应一律丢弃。`workflow_core.js:536` 的 `rpc()` 当前不返回句柄（`:449-467` 的 AbortController 只用于超时），因此 P1 先用页面级 `seq` + 丢弃策略，之后单独评估给 core 增加可取消句柄，**不得改动 `rpc()` 既有的错误/未知结果语义**。
- 检索成本要正视：`models/lab_catalog_item.py:721-794` 的 `search_unified` 每次调用会 `CREATE TEMP TABLE _lc_lab` + `COPY` + `UNION ALL` + 二次计数；这就是“必须防抖、限条数、不逐键全量”的原因。若 P1 实测 P95 明显变慢，再评估窄查询或短 TTL 缓存，且缓存命中不得跨权限返回数据。

### 3.2 选择值与多档案契约

- **唯一事实来源是控件值**：combobox/下拉的当前值就是将要提交的档案；`state.selected` 只做展示派生。控件 change 必须同步卡片，或置空并显示“未选定”。
- 现状缺陷（要修，不是设计取舍）：`receipts.js:520-530` 只在渲染时写 `select.value`，全文件没有 `material-select` 的 change 监听；提交读表单值（`:729`），`templateId=0` 时静默省略（`:755`），服务端按 item_key 取默认档案 —— 屏幕显示 A、实际提交 B。P1 必须同时补“change 绑定”和“提交前一致性校验”。
- 自动选档只允许“唯一且无歧义”的候选，并在卡片上明示“已自动选择”；用户一改动，以控件值为准。
- 多档案：候选行至少含一项可区分事实（SN/库位/在库数量/建档时间，取现有接口字段），**禁止只用数据库 id 区分**；`lab_template_ids` 当前把 `sn` 固定为 `null`（`:664-675`），两个同名档案会得到同文选项，属现状缺陷。
- 供应商数量不得顶替本地库存：同一 C 号合并展示时，“实验室库存”与“供应商在售”分列，延续术语表口径。

### 3.3 页签、在途请求与刷新契约

- 语义补齐：面板加 `role="tabpanel"` + `aria-controls` + roving tabindex + 左右方向键/Home/End；切换只改视觉与 URL，不改业务状态。
- 在途请求：解析回调必须校验 `seq` 与“是否仍在当前步骤”，非当前步骤的回调不得写 DOM、不得复活旧选择（现状 `receipts.js:585-609` 会直接写 `state.selected`）。
- 切换/刷新二选一并写死：**推荐“保留已选并回填”**（输入框文本、已选卡片、控件值一起恢复）；若选择清空，必须显式提示“已清除上次选择”。现状是刷新只恢复页签、`state.selected` 为空（`:1419-1435`），属要修的隐式不一致。
- URL 只同步页签这类非敏感 UI 状态；不得把未提交的搜索词/候选写进历史，避免回退时出现半成品状态。
## 四、来料录入操作台样板

### 4.1 页面布局（桌面 / 窄屏同构）

顶部“来料入库”+ 一句说明；下方两个步骤页签：“① 录入来料与制袋 / ② 扫码上架”，默认落在第一步并直接聚焦搜索框，不要求先懂统一料号前缀。

第一步分三块（桌面：左右两栏，左侧录入、右侧待入库队列；窄屏：按下列顺序纵向排列）：

1. 搜索与选择器件（含候选面板、已选卡片）。
2. 制袋参数：每袋数量、袋数、备注、制袋按钮；重复料号可连续追加。
3. 待入库队列：本次生成的袋与标签队列，含“打印标签”“进入第二步”入口，显示“制袋与打印不增加库存；确认上架后入库”。

第二步：袋事实（器件、数量、袋编号）、库位选择、确认上架；每袋一行，可批量确认，失败行就地显示原因并可重试。

### 4.2 搜索与候选

输入框名称“搜索器件”，示例“立创编号、型号、名称或关键词”；编号与关键词同一入口，输入即查询，不依赖点击“解析”。完整扫码解析保留为辅助入口（粘贴/扫码枪整串仍可用）。

触发与焦点（当前源码没有，属要补的实现，不是既有行为）：

- 页面挂载后焦点落在搜索框；`Tab` 顺序为搜索框 → 候选 → 数量/袋数 → 制袋按钮。
- Enter = 立即解析当前输入，**不提交建袋表单**：料号输入框在 `data-lc-form="pending-create"` 之外（`workflow_receipt.xml:105-133`），而现在全页只给 `[data-lc-scan]` 绑了 Enter（`receipts.js:1392-1396`），所以“回车即解析/不误提交”要显式绑定并写测试。
- 扫码枪整串 + 回车走同一路径；输入法组词（`compositionstart/end`）期间不查、不抢焦点，组词结束再查。
- Escape 收起候选并保留已输入内容；失焦不自动选中；候选面板打开时方向键只在候选内移动。
- 查询预算按 3.1：最小 2 字符、候选 ≤10 条、8s 超时、`seq` 过期即丢弃；等待态在框下就近显示，不把旧候选当成新结果。

```text
搜索器件  [ 输入立创编号、型号或关键词                      ]
          ┌──────────────────────────────────────────────┐
          │ C123456  ·  示例型号                   本地已有 │
          │ 器件名称 / 规格 · 封装                          │
          │ 实验室库存：12 件                               │
          ├──────────────────────────────────────────────┤
          │ C654321  ·  示例型号                     资料库 │
          │ 器件名称 / 规格 · 封装                          │
          │ 尚无本地档案                                    │
          └──────────────────────────────────────────────┘
```

- 编号精确匹配靠前，关键词匹配名称/型号等服务端已支持字段；同一立创号合并为一行，已有实验室库存优先展示，但**具体档案必须显式选择**。
- 候选显示料号、名称、型号、封装、档案状态；只把 Odoo 实验室库存标为库存。
- 选中后在输入框下方显示稳定已选卡片，再填数量；选中本身不建档、不制袋、不改库存。
- 同一编号存在多个本地档案时列出全部并要求选择，绝不默认取第一个。
- 修改搜索内容立即解除旧选择（避免“屏幕上是 B、提交的是 A”）；清空/失焦/切换步骤/页面跳转都不得复活旧候选。
- 无匹配显示空态与“手动建档”入口；查询失败显示错误与重试，不能把失败说成没有该器件。
- 输入后立即显示等待反馈，约 250ms 防抖发送；中文输入法组词期间不抢焦点、不打断；每个新输入使旧请求与旧选择立即失效，晚到的响应不得写入。
- 鼠标、触控、方向键、Enter 可选；Escape 收起；Tab 正常离开；候选不会因一次失焦被误选。查询框使用搜索型 combobox 语义（`role="combobox"`、`aria-expanded`、`aria-activedescendant`、`role="listbox"`/`"option"`）。

### 4.3 状态统一（全站通用）

| 状态 | 使用者应看到 |
| --- | --- |
| 未输入 | 输入提示与可用搜索方式 |
| 等待/查询中 | 就近“正在搜索…”；候选不可当作当前结果误选 |
| 有结果 | 可选候选、当前高亮、结果数量与更多结果入口 |
| 无结果 | “没有找到匹配器件”+ 修改关键词/手动建档 |
| 网络或权限失败 | 具体说明 + 重试或重新登录，不造空成功 |
| 权限不足（目录读取不全） | 说明缺哪个角色，并给出仍可用的“编号/扫码解析”路径（见 3.1）；不静默 403、不放宽权限 |
| 未识别/不支持类型 | 保留原输入、列出可识别前缀（`lcsc:C…`、`lab:…`、`LABB:`、`LABL:`、SN、裸 C）、给出可复述诊断号；原始返回只在折叠的“诊断详情”里给管理者看 |
| 已选中 | 已选器件与档案清楚，可重新选择 |
| 提交中 | 防重复操作，保持输入内容 |
| 结果未知 | “上次操作可能已完成，请先核对”；保留原请求重试，不允许换器件绕开 |
| 已完成 | 说明生成了什么、数量与下一步，不只弹“成功” |


### 4.4 第二步、页签与锁定（契约摘要）

- 第二步只展示袋事实（器件、数量、袋编号）、库位选择与确认上架；不改数量、不重建袋，失败行就地给原因并可重试。
- 页签切换、刷新、在途解析按 3.3：**保留已选并回填**为默认选择；在途回调必须校验 `seq` 与当前步骤；刷新不得出现“页签在第二步但已选为空”的静默不一致。
- 提交中（制袋/确认/打印）按现有 `applyLockState` 锁住相关控件、保持输入；锁定期内搜索与选档只读，不写档案、不写袋、不改库存；解锁后以服务端返回为准刷新队列。
- 制袋与打印不增加库存，只有第二步确认上架入库；这句话必须在界面上常驻，而不是只写在文档里。
## 五、实施顺序与审查点

1. **P0 规范与骨架（不部署）**：确定术语表、组件 API、状态映射；出设计稿——来料页桌面 1440 与窄屏 375、器件库列表、典型列表页，必须含下拉展开、已选、多档案选择、未识别码、空/错/未知结果、375 导航抽屉；同时给出 2.3 旧入口映射表与 2.6 菜单改指表草案。
2. **P1 来料操作台完整落地**：搜索框触发契约（autofocus、Enter 解析不误提交、IME、Esc）、候选数据源与请求预算（3.1）、选择值双向绑定与多档案可辨识（3.2）、页签与刷新契约（3.3）、制袋、待入库队列、打印、第二步上架；用真实隔离接口与合成数据验证；与旧控制台能力逐项对照表一并提交。
3. **P2 旧操作台迁移**：扫码上架、领用/归还、袋与追溯、库位先进；**先按 2.6 改菜单/动作指向**，再实现 2.3 的 GET 白名单映射与回退（映射只负责旧链接），旧 POST 保持不动；EDA 七入口逐个在隔离环境点开确认落点。
4. **P3 其余自有页收敛**：器件库/详情、流水、标签、映射、成员权限、账号、登录；**窄屏导航改抽屉**（组件见第三节，现状 `team.css:1419-1439` 横向滚动）；复用 P1 已验收组件，不重复造控件。
5. **P4 管理与验收**：管理入口收敛为原生维护面（分类/导入/幂等日志/用户权限）；逐入口走第七节清单；旧模板下线单独评估并另行授权。
6. 每阶段结束提交“实际执行了什么、哪些没执行”，不允许用源码推断视觉通过。

DSH 负责盘点、设计稿、实施与测试；Codex 负责范围、共用规范、设计与最终验收决策。当前只做方案梳理，实现任务保持停止。

## 六、逐入口验收清单

每条都要“真实请求 + 真实渲染”的证据（截图/日志/接口返回）；无法执行标 blocked，不记 pass。

| 入口 | 验收动作 | 通过条件 |
| --- | --- | --- |
| `/team/lab/receipts` | 输入裸 C 号、`lcsc:C…`、`lab:<id>`、中文关键词；含 IME 组词 | 四类输入都出真实候选并带入正确档案；组词期间不抢焦点 |
| 同上 | 页面加载后的焦点、Tab 顺序、Enter、Esc、扫码枪整串+回车 | 焦点在搜索框；Enter 只解析、不提交建袋；Esc 收起候选且保留输入；整串+回车走同一路径 |
| 同上 | 连续 5 次击键 | 只渲染 1 次最终结果；在途请求 ≤2；晚到响应不写入；候选 ≤10 条 |
| 同上 | 两种角色：正常 lab 角色、目录组被剔除的账号 | 前者出关键词候选；后者降级为编号/扫码解析并常驻说明，无静默 403、未放宽权限 |
| 同上 | 快速连续输入制造乱序、清空、失焦、切页签 | 晚到响应不写入、旧候选不复现、选中值随即失效 |
| 同上 | 同一 C 号存在多个本地档案（含两个同名同型号档案） | 选项至少含一项可区分事实，不能只差数据库 id；必须显式选择，默认不自动提交 |
| 同上 | 自动选档后把下拉改回占位/改选另一个 | 卡片与控件一致；建袋按新值或被拦，不出现“屏幕 A、提交 B” |
| 同上 | 断网/超时/无权限 | 显示错误与重试，不显示空结果，不伪造成功 |
| 同上 | 输入→切页签→返回；解析在途时切页签；刷新 | 已选按契约保留并回填（或显式提示已清空）；在途回调不写非当前步骤；刷新不出现空选择静默不一致 |
| 同上 | 制袋→打印→第二步上架 | 袋数、标签、库存变化符合既有规则；制袋本身不加库存 |
| 同上 | 提交中重复点击、未知结果后重试 | 不重复记账；未知结果保留原请求 |
| `/team/scan` | 扫码枪整串、手输、未知码 | 与旧控制台解析结果一致；未知码有明确提示 |
| 来料候选区 | `LABX:`、空串、错误前缀 | 保留输入、列可识别前缀、给可复述诊断号；原始返回只在折叠诊断里给管理者 |
| `/team/lab/issues`、`/issues/new` | 领用（须系统账号）、部分归还 | 关联原领料；数量与状态正确；余额不串 |
| `/team/lab/bags`、`/bags/<id>` | 一袋一码、追溯链展开 | 追溯链路完整，窄屏不需要横向滚动读关键字段 |
| `/team/lab/locations` | 库位树、库码、上下架可用性 | 与原生库位视图数据一致 |
| `/team/lab/labels` | 批量 A4、超限、非 operator | 超限有边界提示；非 operator 得到说明而非空白 |
| `/team/lab/history` | 筛选、分页、关联单据 | 与原生流水行数/字段一致 |
| `/team/lab/materials` | 档案增改、绑定 C 号 | 校验清晰；绑定冲突可辨识 |
| `/team/lab/settings` | 角色授予、撤销末位管理员 | 拦阻并说明影响公司范围 |
| `/team`、`/team/login` | 登录、失败、会话过期 | 同一品牌与反馈；失败不泄露账号存在性 |
| 旧 GET 映射 | 逐条打开矩阵中的 `/odoo/action-*` 与 `/lab/scan` | 303 到目标页；无权/未注册回退合理；无开放重定向 |
| 菜单改指（2.6） | 升级后逐个菜单项：`ir.ui.menu` 的 action、普通角色可见性、点开落点 | 日常入口打开自有页；管理员维护面仍可达；无权限得到 403/登录说明 |
| 根级别名 | `root_aliases` 开/关、management Host 匹配/不匹配 | 关闭时按 404 处理，不报 500；开启时别名与 `/team/...` 指向同一页 |
| 历史库存分袋 `adopt_stock` | 日常 UI 是否出现入口 | 文档写明“仅脚本/维护面”；不因迁移新增业务 UI，也不把它当缺陷 |
| 旧 POST | `/lab/scan/submit`、`/lab/scan/resolve` 重复提交 | 幂等与未知结果保护与迁移前一致，未被重定向重放 |
| EDA 七入口 | `panel.js` 七个动作逐个打开 | scan/label/bag/issue/location/operation 落新页，request_log 落原生诊断页 |
| 全站视觉 | 1440 与 375 两档，含暗色、下拉展开、错误、长文本 | 无裁切、无遮挡、无横向溢出；触控目标 ≥44px |
| 窄屏导航 | 375px 打开 11 项导航、开合抽屉、Esc、滚动后再开 | 不横向滚动；焦点陷阱正确；关闭后焦点回触发按钮；`aria-current` 正确 |

## 七、完成的判断标准

- 矩阵每行都有明确结论：已迁移 / 保留原生（含理由）/ 能力差距（含清单），不存在“说不清”。
- 日常路径不再打开旧模板；旧模板只经管理员/兼容路径到达，且未通过换色声称完成。
- 每个选择器都检查关闭与展开状态；桌面与 375px 窄屏检查整页、滚动后内容、长文本与弹层。
- 来料编号与关键词都得到真实候选并带入正确档案；乱序、清空、IME、键盘、触控均验证。
- 权限、未决请求、防重复提交、库存权威规则与迁移前一致；不新增接口权限。
- 静态检查、组件测试、真实接口与浏览器流程分别记录；未执行项标明 blocked/skipped。
- 不以“代码已改”“exit 0”“旧报告 100%”代替全站体验验收。
- 菜单与动作是否已改指（2.6）逐条有结论；只做服务器映射、菜单仍指旧 action 的不算迁移。
- 候选的请求预算有实测数字（每次输入的渲染次数、在途请求数、候选条数上限、超时表现），不是只写“已加防抖”。
- 未识别码与权限降级都有可理解提示与受控诊断；旧台的整段原始 JSON 不得直接暴露给日常用户，也不再作为“功能等价”的证明。
- 暗色外观不构成迁移证据（`lab_theme` 全局注入旧台同样是暗色）；根级别名 404 要先看配置再判定缺陷。

## 检查记录（本轮）

- 只读盘点 + 三份文档修订（方案、任务、交接）；未改源码、模块版本、registry、客户端，未连生产、未提交、未推送。
- 合并两份独立只读审查与 Codex 初审意见，逐条按源码复核后写入本文件；报告原文未改动（`local/legacy-web-team/ux-audit.md`、`local/legacy-web-team/entry-audit.md`）。
- `python tools/repo_check.py`：退出码 0，`passed_checks` 52，`errors` 为空，保留既有 `production-py312-rebuild` 警告（未做离线闭环，属已知项）。
- `git diff --check`：退出码 0。三份文档均为未跟踪文件，git 不检查未跟踪内容，故另按行尾空白规则自查：三份文件命中 0 处（`TRAILING_TOTAL=0`）。
- 未运行业务测试、构建、载荷校验或浏览器渲染：本轮仅方案；不据此声称任何视觉或线上结论。


## 独立评审证据与采纳情况

两份独立评审均按“证据”使用，不当作指令；逐条源码复核后合并如下（完整原文见 `local/legacy-web-team/ux-audit.md`、`local/legacy-web-team/entry-audit.md`，本轮未改动它们）。

**已采纳（均有源码证据）**：触发路径与 autofocus/Enter（`receipts.js:1326-1332,1392-1396`；`workflow_receipt.xml:105-133`；旧台 `lab_scan_views.xml:227-230`）；候选同文不可辨识（`receipts.js:664-675,494-499`）；选择值与控件不同步（`:520-530,729,755`）；请求不可取消（`workflow_core.js:449-467,536`）；页签语义与刷新不一致（`receipts.js:1308-1321,1419-1435`）；窄屏导航横向滚动（`team.css:1419-1439`）；旧台诊断整段 JSON（`lab_scan_views.xml:207-220`）；检索成本（`lab_catalog_item.py:721-794`；`catalog_api.py:57`）；全局暗色注入（`lab_theme/__manifest__.py:25-34`）；菜单仍指旧 action（`lab_workflow/views/menu.xml`、`lab_catalog_menu.xml:14-26`、`lab_inventory/views/menu.xml`）；根别名由配置决定（`tools/paths.py:23`、`common.py:340-360`）。

**纠正/不采纳（过度断言或已被源码证伪）**：

1. “只有库存角色、无目录读取角色必然 403” —— 实际 `lab_workflow.group_lab_user` 的 `implied_ids` 已含 `lab_catalog.group_lab_catalog_user`（`lab_workflow_imply.xml:19-20`），常驻操作员本就有候选权限；改为“异常配置下必须降级并提示”，仍要求实测 `has_catalog_access()`，不为界面放宽权限。
2. “线上没有 303、日常 100% 落旧台” —— 该结论来自 2026-10-28 文档推断，本轮未访问生产；只能记为“最后登记时点的模块版本为 lab_workflow 19.0.1.2.0、lab_team_web 19.0.1.0.5，含 303 的 19.0.2.0.0/19.0.1.1.0 是否已在生产生效**待核实**”。
3. “绑定没有新页/无 UI” —— 已被 `static/src/js/pages/materials.js:132,343,360,672` 与 `workflow_inventory.xml:518` 证伪；矩阵保留“源码已有、等价性待验”。
4. “13 个根级别名” —— 实为 `ROOT_ALIASES` 5 个前缀（`/login`、`/logout`、`/lab`、`/scan`、`/account`）覆盖 13 个业务页的第二条路由。
5. “13 页×2=26 条路由” —— 只覆盖 `workflow_pages.py`；全站为 18 个页面入口、36 条 route 规则（另 5 个入口页在 `pages.py`）。
6. “全仓只有一个 act_url”“客户端完全无网页跳转” —— 绝对化表述已缩到已检查范围：`server/ubuntu22.04/odoo_addons`、`plugins/jlc-eda/src/main`、`clients/app/lib`。
7. EDA 与客户端入口属于后续独立任务：本轮只登记，不改插件、不改客户端。
## 来源与复用评估

现有共享基础：`lab_team_web/views/pages.xml`、`views/team_templates.xml`、`static/src/css/team.css`、`static/src/js/workflow_core.js`；页面域样式与脚本按现有布局继续维护。

方案调研参考 [GOV.UK accessible-autocomplete](https://github.com/alphagov/accessible-autocomplete)（MIT）与 [trevoreyre/autocomplete](https://github.com/trevoreyre/autocomplete)（MIT）。选择组件前须验证现有 CSP（仅 `script-src 'self'`、无内联脚本、无 CDN）、异步请求、真实选择值与未决锁兼容；优先在现有原生控件上做小适配，不为一个选择器引入新应用框架。本方案尚未选定或引入第三方依赖。
