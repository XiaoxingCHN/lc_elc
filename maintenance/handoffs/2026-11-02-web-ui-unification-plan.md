# 维护交接：网页视觉与交互统一方案（含旧操作台迁移）

## 最终主审补记（2026-11-02）

三路任务均已完成。主写与交互审查实际为 `magpie/qoder-cn/dfmodel`，入口审查为 `magpie/workbuddy-ai/deepseek-v4.1-flash`，均 high。用户另允许 CodeArts DeepSeek，本轮未调用。Codex 已审阅合并结果、抽核绑定/角色继承/旧解析与提交语义，并纠正“目标未就绪先隐藏旧入口”的方案：能力对齐前保留既有合法可用入口，不能中断日常工作；同时修正根菜单 xmlid 表述。

结论：可作为网页设计与后续实施的方案依据。并非源码实现或视觉/生产验收通过。主方案实际约 380 行，主写者报告中“203 行”是计数误述；以文件为准。用户当前要求仅方案，后续先做关键页与展开下拉的设计审查。

## 用户目标与已确认边界

编号/关键词搜索及候选反馈需覆盖所有端；用户随后明确先出网页方案，要求把尚未完成的"全站风格统一"纳入，并特别指出**当前入库操作台可能仍是 Odoo 老样式，全部日常页面都要统一**。本轮只出方案：不实现业务、不改客户端、不部署、不连生产、不读真实凭据、不改版本/registry、不提交不推送。

## 当前权威源码、分支和版本

分支 `codex/receipt-search-feedback`，起始 `b3bcbf244e44939c6d481e3f97f11579cdf9ee99`。本轮未修改任何源码、模块版本、`active-sources.json`、`maintenance/registry` 既有登记或产物。P3 源码登记 `maintenance/registry/source-server-p3-web-20261028.json` 保持不变，未改写历史快照。是否已在生产生效不在本交接结论内。

## 已完成工作与实际证据

只读盘点 + 三份文档修订（均在允许写域内，全部为未跟踪新文件/修改）：

1. `docs/requirements/WEB_UI_UNIFICATION_PLAN_20261102.md`：在原方案上补齐 **旧 Odoo 日常页面迁移矩阵**（20 行入口 → 当前实现（文件:行）→ 目标页 → 必须保留的能力 → 迁移状态/未证实项），新增旧链接兼容规则、EDA/客户端入口、迁移完成判定，并把布局（桌面 1440 / 窄屏 375）、完整来料操作台样板、10 个共用组件、9 态反馈、5 期实施顺序、18+ 条逐入口验收清单写全。
2. `maintenance/tasks/2026-11-02-web-ui-unification-plan.md`：更新目标、写域、验收标准、不变量、未验证项。
3. 本交接。

关键盘点证据（只读，可复核）：

- 旧控制台：`lab_workflow/views/lab_scan_views.xml` 为 `web.html_container` + Bootstrap 模板（`:9` `container mt-3`、`:32` `#lab_scan_input`、`:46-97` 来料建袋表单、`:100-142` 领用、`:145-191` 归还、`:193-203` 三处 `/odoo/action-*` 链接、`:206-233` 内联脚本、`:238-242` `action_lab_scan_console` = `ir.actions.act_url` url `/lab/scan`）。
- 迁移条件：`lab_workflow/controllers/lab_web.py:46-58` 仅在 `_scan_redirect_target()` 有值且 `_route_available()`（`:88-94`，`ir.http._match`）通过时 303，否则渲染旧模板；参数为 `p3_rules.SCAN_REDIRECT_PARAM`，默认 `/team/scan`。**源码存在新页 ≠ 线上已迁移。**
- 旧菜单/动作：`lab_workflow/views/menu.xml`（扫码操作台/领用记录/库存袋与追溯码/库存作业流水/配置）；`lab_issue_views.xml:105`、`:115` 归还向导、`lab_bag_views.xml:122`、`lab_operation_views.xml:125`、`lab_location_views.xml:59`、`lab_label_views.xml:52`、`lab_request_log_views.xml:80`、`lab_user_access_views.xml:3`。
- 器件库侧：`lab_catalog/views/lab_catalog_menu.xml:8-12` 为 `ir.actions.client` tag `lab_catalog.unified` 的 OWL 统一器件库；`:28-53` 四个 manager/绑定子菜单；`lab_inventory/views/menu.xml:5-11` 四个日常菜单（元器件档案/库位管理/类别→库位映射/库存流水）。
- EDA：`plugins/jlc-eda/src/main/panel.js:68-76` 固定 7 个 `ODOO_ACTIONS`，`:78-85` 拼 `/odoo/action-<xmlid>`——插件只会打开旧动作，必须靠 GET 白名单映射落到新页。
- 客户端：`clients/app/lib` 不内嵌网页（仅 `features/unified/services/pdf_output.dart:159` `launchUrl(Uri.file(...))`），业务走 `/lab/api/`，会话走 `/web/session/*`；入口适配登记为后续任务，本轮不改。
- 自有 UI 路由 18 个（`lab_team_web/controllers/workflow_pages.py:194-273`、`pages.py:130-236`），页面脚本 13 个、CSS 4 个、视图 6 个。

关键决策（含理由）：

- **迁移判定看日常路径是否还打开旧模板，不看 CSS 有没有变**；旧 Bootstrap 换深色皮不算完成。
- **能力等价再切换**：目标页缺一项既有能力就不关旧入口；扫码/制袋/打印/上架确认/部分归还/未知结果保护逐项对照。
- **旧 GET 只做静态白名单映射**：保留 `bag_id`/`issue_line_id`/`item_key`/筛选等上下文并按类型校验，未知参数丢弃；先鉴权再验证目标路由存在才 303；未注册/无权回退原动作，不送 404，不开开放重定向。
- **旧 POST 绝不重定向重放**：`/lab/scan/submit`、`/lab/scan/resolve` 带 `request_key`，保持原行为；下线需单独授权，本轮不评估下线动作。
- **管理员原生维护保留**：分类树、导入批次、幂等请求日志、Odoo 用户/权限、stock/product/mrp 底层不动、不删、不套色。
- **组件优先小适配而非引入框架**：现有 CSP 仅 `script-src 'self'`、无内联脚本/CDN，引用 GOV.UK accessible-autocomplete（MIT）与 trevoreyre/autocomplete（MIT v3.0.3）仅作调研，本方案未引入依赖。

## 检查命令、实际结果与退出码

- `python tools/repo_check.py`：**exit 0**，`{"result":"PASS","passed_checks":52,"errors":[],"warnings":[{"check":"known-payload-not-built","id":"production-py312-rebuild"}]}`，`git_candidate_files` 3060，`production_access:false`，`payload_verification:false`。
- `git diff --check`：**exit 0**（无输出）。注意：三份文档当前均为未跟踪文件（`??`），`git diff --check` 不覆盖未跟踪内容；因此另对三份文件按行尾空白/制表符规则自查，结果见下条实际命令。
- 未跟踪文件行尾空白/制表符自查（`Select-String -Pattern "[ \t]+$"`）：三份文档命中 0 处（`TRAILING_TOTAL=0`）。
- 两份独立审查并入后再跑（本轮最终）：`python tools/repo_check.py` → `PASS` / `passed_checks: 52` / `errors: []` / **exit 0**（`production-py312-rebuild` 警告不变）；`git diff --check` **exit 0**；三份文档按 `[ \t]+$` 自查 `TRAILING_TOTAL=0`；方案文档 203 行（`Get-Content` 计数）。`git status` 确认为三个未跟踪文件（`??`），未提交。
- 未运行业务测试、模块构建、载荷校验、浏览器渲染或视觉比图：本轮仅方案，不适用；不因此声称任何视觉或线上结论。

## 剩余工作与阻塞

- 未做真实渲染与视觉验收：无设计稿、无可用中文截图（既有 `local/build/p3-web-20261028/runs/browser-20261028T065311Z/shot-p3-*.png` 中文为方框）。视觉审查需真实界面或设计稿，不能用源码推断通过。
- **未证实项（不得当成事实）**：生产 `lab_workflow.scan_redirect` 参数现值；`lab_team_web` 是否已在生产安装/升级；旧菜单在生产菜单树的实际可见性；矩阵中每个 xmlid 在 `-u` 升级后的存在性；生产各目标路由是否注册。
- **生产版本只到最后登记时点**：2026-10-28 文档记录为 `lab_workflow 19.0.1.2.0`、`lab_team_web 19.0.1.0.5`；本轮未访问生产，**不能据此断言今天仍是该版本**，也不能据此断言“线上没有 303”。
- 旧控制台"一页三卡"（解析/来料/领用/归还）与目标页的逐项能力对照只做了源码级，未做等价性验证。
- 旧模板隐藏/下线、菜单调整、任何生产动作均需单独授权。
- 两份只读独立审查（交互 `local/legacy-web-team/ux-audit.md`、旧入口 `local/legacy-web-team/entry-audit.md`）已完成并与 Codex 初审意见一并合并（见下节）；下一步是 Codex 终审 → 设计稿 → 实施。


## 两份独立审查合并（本轮最终）

两份报告均按“证据”使用（原文未改动，位于 `local/legacy-web-team/`），逐条按源码复核后并入方案：

**交互审查（`ux-audit.md`）采纳**：触发与焦点缺失（`receipts.js:1326-1332`、`:1392-1396`；`workflow_receipt.xml:105-133`；旧台 `lab_scan_views.xml:227-230`）；候选同文（`receipts.js:664-675`、`:494-499`）；选择值不同步（`:520-530`、`:729`、`:755`）；请求不可取消（`workflow_core.js:449-467`、`:536`）；页签与刷新不一致（`receipts.js:1308-1321`、`:1419-1435`）；窄屏导航横向滚动（`team.css:1419-1439`）；旧台整段 JSON 诊断（`lab_scan_views.xml:207-220`）；检索成本（`lab_catalog_item.py:721-794`、`catalog_api.py:57`）。落点：方案“当前证据”、§3.1、§3.2、§3.3、§4.2、§4.3、§4.4、§六（新增 9 行验收）。

**入口审查（`entry-audit.md`）采纳**：1) “菜单/动作改指”机制缺失（该报告列为最大缺口）→ 新增方案 §2.6（A 同 xmlid 覆盖 action 指向新增 `ir.actions.act_url`；B 只调 `groups`；C 保留原生）＋12 行落点表＋5 条约束；2) 根级别名与 404 语义（`tools/paths.py:23`；`common.py:340-360`；`pages.py:140,163,180`）；3) 全局暗色注入使“看颜色判断迁移”失效（`lab_theme/__manifest__.py:25-34`）；4) `menu_lab_config` 不得整组排除 → 拆成库位/标签改指＋请求日志保留原生；5) `legacy_stock`/`adopt_stock` 有 API 无 UI（`lab_inventory_api.py:184,196`）→ 判定为维护面保留、不新增日常 UI 并写明理由；6) 根菜单 `groups` 被 `lab_catalog_menu.xml:14` 覆盖的可见性风险；7) 路由口径纠正为 18 个页面入口 / 36 条 route 规则。

**纠正/不采纳（详见方案文档“独立评审证据与采纳情况”）**：

- “只有库存角色则必然无目录读取权限”被组关系证伪：`lab_workflow_imply.xml:19-20` 让 `group_lab_user` 隐含 `group_lab_catalog_user`，`lab_workflow_groups.xml:33` 让 operator 隐含 user；改为“异常配置下必须降级并提示”，仍要求实测 `has_catalog_access()`。
- “线上没有 303、日常 100% 落旧台”：来自 2026-10-28 文档推断且本轮未访问生产 → 只能标为“最后登记时点版本（`lab_workflow 19.0.1.2.0`、`lab_team_web 19.0.1.0.5`）＋待核实”。
- “绑定无 UI”：被 `materials.js:132,343,360,672` 与 `workflow_inventory.xml:518` 证伪，矩阵保留“源码已有、等价性待验”。
- “13 个根级别名”→实为 5 个 `ROOT_ALIASES` 前缀覆盖 13 页；“13×2=26 条路由”只覆盖 `workflow_pages.py`，全站为 18 入口 36 条规则。
- 绝对化表述已缩到已检查范围（`server/ubuntu22.04/odoo_addons`、`plugins/jlc-eda/src/main`、`clients/app/lib`）：“全仓只有一个 `act_url`”“客户端完全无网页跳转”。
## 依赖和产物

未引入新依赖；无新成品、无源码冻结、无版本变更、无 registry 变更。三份文档均未提交，Git 工作区其他未跟踪材料（`Python/`、`clients/app/t.obj`、architecture/projectgraph 材料、`maintenance/tasks/2026-10-28-p3-production-deploy.md`）保持原样未触碰。

## 生产状态和回滚

未连接生产、未执行 SSH、未读写真实账号或库数据、未部署、未重启服务、未改 DNS/网关。仅文档增量，无生产回滚动作；如需撤回，直接删除/还原上述三份文档即可（均未提交）。

## Codex 初审修正（已并入方案，均按源码复核）

1. **器件绑定：方案原写“目标尚无绑定入口”是错的**。源码已有：`workflow_inventory.xml:518` 表单 `data-lc-form="material-bind"`；`static/src/js/pages/materials.js:132` 行内“绑定”按钮、`:343` `catalogWrite()`、`:360` `catalogBind`、`:672` 提交处理（文件头注释还说明 bind 无 `request_key`、靠 `(catalog_code, product_template_id)` 唯一约束去重）。已改为“源码已有、等价性待验”，待验点是原生 `tree` 的列表/批量能力与冲突文案。
2. **`/lab/scan/resolve` 不是写入口**：`lab_web.py:121` 为 `csrf=True` 的解析/读请求，只调 `lab_resolve_code()`；唯一 `request_key` 写入口是 `POST /lab/scan/submit`（`:142`，`:153` `payload.setdefault('request_key', ...)`）。标签端点真实语义：`/lab/labels/plan`（`:210`，operator，只算版式不改库存）、`/lab/labels/download`（`:245`，operator，生成 PDF 不改库存）。已改为四条端点分开表述，并统一保留“POST 不自动重放”。
3. **权限不得用旧界面兜底**：已改为无权限必须 403 或引导登录；只有“模块未安装/升级导致目标路由未注册”这类部署原因才可回退到仍独立鉴权的内网兼容页，并标注迁移未完成；公网白名单不扩大。
4. **EDA 主路径改为插件自身切新 URL**：服务器端旧 GET 映射降级为旧版本插件/旧书签的固定白名单兼容层，不再是唯一方案。
5. **视图类型逐个核对并更正**：`action_lab_return_wizard`（`lab_issue_views.xml:115-125`，res_model `lab.issue.line`）`view_mode` 实为 **list,form**（domain `outstanding_quantity > 0`；归还表单在 `lab_return_wizard_views.xml:5`）；`action_lab_label_open` 为 `form`；`lab_catalog` item 为 `tree,form`、category/binding 为 `tree`、import run 为 `tree,form`；其余 lab_workflow/lab_inventory 动作为 `list,form`。**注**：审查意见称“归还向导为 form 不是 list,form”，与源码 `lab_issue_views.xml:118` 的 `<field name="view_mode">list,form</field>` 不符，已按源码记录，请复核该条。
6. **管理范围按日常/低频区分，不按角色名**：日常操作即使仅 manager 可用（成员权限、器件档案维护）也要进统一 UI；保留原生的仅限低频运维/审计面（分类树、导入批次、幂等日志、Odoo 用户权限）。

## Codex 审查点（精简）

1. 迁移矩阵是否有遗漏的日常入口（尤其旧"待入库"路径、标签打印、追溯详情、详情页快捷入口）；保留原生的判定是否合理。
2. 旧 GET 映射规则是否会引入开放重定向或越权；上下文白名单字段是否够用；无权/未注册回退策略是否可接受。
3. 旧 POST 不下线、不重放的边界是否写清；与幂等/未知结果保护的关系是否明确。
4. 来料操作台样板与 9 态反馈、组件清单是否足够支撑直接出设计稿；术语表是否覆盖所有用户可见技术字段。
5. 分期顺序与逐入口验收清单能否逐条执行、证据是否可采集；"完成"判定是否还留有换色蒙混的空间。
6. 新增 §2.6 的菜单改指机制是否够落地：落点表是否漏掉日常入口（原生表单里的行内按钮、wizard 按钮、详情快捷入口），A/B/C 判定与“保留原生”的理由是否成立。
7. §3.1 的请求预算与权限降级（目录组被剔除时只保留编号/扫码解析）是否可接受；`rpc()` 不返回句柄时先用页面级 `seq` 的方案是否够用。
8. 根别名/management Host 的 404 语义与兼容层关系是否写清，会不会被误当成迁移缺陷。
