# 变更记录

## 2026.11.06 器件库按需抓取部署到生产（2026-11-06T14:29–14:31Z；cron 已运行）

- 部署：在 `192.168.31.105`（DB `LcHardwareHouse`）执行 `upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261106/modules`，`-u lab_inventory,lab_catalog,lab_workflow` **退出码 0、ERROR/CRITICAL/Traceback 行数 0**。生产 `/opt/odoo/custom-addons` 现为 `lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2`；`lab_team_web 19.0.1.2.1` 未参与，客户端仍 `1.2.0+7`（未构建/发布）。
- 备份：`/var/backups/lc-elc/20261106T142949Z-before-upgrade/`——`db.dump` 118,970,696 B / `40863d500fffc8f36013cd99da8625d3ed988799826f6633cc178f41d3ba0d66`；`filestore.tar.gz` 12,819,190 B / `5b9e5d42a03d339dcbab225ad3e1da09913b4b853dcded117fcb29614a3f5fc0`；`MANIFEST.json`、`odoo.log.tail`；旧三模块源码在 `module-source-before-upgrade/`。
- 健康检查：脚本把 `/web/login` 的 303 判为失败（既有缺陷，303 → `/web/database/selector`）；独立复核 `/web/login` 带 `X-Odoo-Database` 为 200、`odoo.service` active/enabled、14:31:36Z `Modules loaded`。
- 运行证据：`/var/log/odoo/odoo.log` 自升级后到 2026-11-07 13:11Z **0 条 ERROR/CRITICAL/Traceback**；`ir.cron`「器件库：处理在线补抓队列」（id 25，每 1 分钟）自 2026-11-06 14:31:16Z 起每约 62 秒运行，累计 1356 次启动、0 失败，每次 `fully done (#loop 1; done 0; remaining 0)`。
- DB 行核对（2026-11-07T13:17:07Z）：四模块 `installed`（`lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2` / `lab_team_web 19.0.1.2.1`）；`lab_catalog_fetch_request` 表存在，7 个索引含部分唯一索引 `lab_catalog_fetch_active_uniq`（谓词 `state IN ('queued','resolving','fetching')`）；`lab_catalog.ir_cron_lab_catalog_fetch` → `res_id=25`，与运行中的 job 25 一致。行数统计未跑（脚本在 Odoo 19 的 `ir_cron.model_id` 处中断），另以 `verify_deploy2.sh` 补查。
- 未做：真实网络端到端（三个目标料号）、Flutter widget 测试、客户端包构建、source manifest 冻结。

## 2026.11.06 器件库搜索未命中按需抓取（源码候选；【已部署】见上一条）

- 版本：`lab_catalog 19.0.2.0.9 → 19.0.2.0.10`（`components.json` 已同步）；客户端源码变更但版本仍为 `1.2.0+7`。
- 服务端：新增 `lab_catalog/tools/lcsc_remote.py`（固定域名、无 Odoo 依赖）：精确 C 码直取详情，精确 MPN 走英文站公开搜索并**只在 `productModel` 完全相等时**采用，否则返回候选；中文名称/品牌/分类/参数/封装/CNY 价格全部取 `item.szlcsc.com` 中文详情页。新增 `lab.catalog.fetch.request` 状态机、部分唯一索引去重、`pg_try_advisory_lock` 串行的 cron worker（每分钟 2 条）、ACL/记录规则；`/lab/api/catalog/search` 在精确查询零结果时返回 `fetch_suggestion`，新增 `/lab/api/catalog/fetch` 与 `/fetch_status`（每用户 5 个进行中、每小时 20 次）。抓取只 upsert `lab.catalog.item/param` 与 `catalog_stock`，不创建产品、不写 quant/move；非电子一级分类在请求中文页前即跳过，未知分类转人工复核。
- 客户端：空结果页显示“立即从立创商城抓取”，轮询 1 秒、最多 60 次，`done` 后自动刷新；`candidates` 逐条列出封装让用户选择，不自动取第一条；失败显示服务端中文原因并可重试；换查询或销毁时取消轮询。
- 测试（本机真实执行）：新增 `catalog_fetch_test.dart` 7/7；`flutter test --no-pub` exit 0，**326 passed / 5 skipped / 0 failed**（基线 319/5）；`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 120 info**（新增 2 条与既有风格一致的 `prefer_initializing_formals`）；`test_lcsc_remote.py` 15/15。
- 仓库检查：`python tools/repo_check.py` exit 1，50 项通过，错误为本轮尚未冻结的 `frozen-source:client`（4 文件）与 `frozen-source:server`（13 文件）；16 条 payload 警告为既有缺口。`generate_routes.py` 已重新生成 `routes.json`（94 条），`--check` exit 0；`git diff --check` exit 0。
- **未做**：未在 Odoo/PostgreSQL 测试库运行 ORM 用例、未做真实网络端到端、未做 Flutter widget 测试；未升级模块、未注册定时任务、未建表、未部署生产、未冻结 source manifest、未提交/推送、未构建安装包。任务单见 `maintenance/tasks/2026-11-06-catalog-on-demand-fetch.md`。该时点状态已被上一条部署取代：模块已升级、表与 cron 已生效、改动已提交 `e563da0`；仅 source manifest 仍未冻结。

## 2026.11.06 Flutter Liquid Glass 源码候选（未构建/未发布）

- 客户端 `1.1.3+6 → 1.2.0+7`：默认深色玻璃 + 荧光绿，保留路由、业务文案、协议、登录记忆、参数搜索、待入库服务端筛选和库存语义。零新增 pub 依赖。
- 新增 `lib/ui/glass/` 设计系统与 `lab_ui.dart` 兼容层；只有 `GlassSurface` 创建 `BackdropFilter`，真实模糊仅用于 chrome/抽屉/搜索建议/浮层，滚动卡片与内容面板无模糊。高对比度、减少动效、44×44 目标与 prominent accent/onAccent 配对已实现。
- 登录、目录、详情、收/领/还、离线、标签和两阶段入库接入视觉层；`StatusBanner` 提供图标+文字状态；A4 预览固定白底黑字。保留 `UpdateHost` 与既有业务慢响应保护，不机械替换全部 Material 按钮。
- 验证：`flutter analyze --no-pub lib test` exit 1，0 error / 0 warning / 118 info；`flutter test --no-pub --reporter compact` exit 0，**319 passed / 5 skipped / 0 failed**。已查看 6 张深色离屏截图；真机、性能、读屏、实体打印未验证。
- 冻结 `maintenance/registry/source-client-liquid-glass-20261106.json`（177 文件，tree `a19e0ddf2f7cdba420ae7605763c40926c3745d3ab5de60387c8aab7da1d0e4e`）并激活；未构建/发布安装包，未部署生产、未推送。`generate_routes.py --check` 与 `git diff --check` exit 0；`repo_check` 仅剩另一项服务端源码晚于 active r2 的 `frozen-source:server` 差异，不记作全仓 PASS。

## 2026.11.04 入库关键词搜索扩展到参数值（生产已部署 2026-11-04T12:59–13:09Z；真实浏览器验收待做）

- 版本（`components.json` 已同步）：`lab_inventory 19.0.1.0.0 → 19.0.1.1.0`、`lab_catalog 19.0.2.0.5 → 19.0.2.0.6`、`lab_workflow 19.0.2.0.0 → 19.0.2.0.1`、`lab_team_web 19.0.1.2.0 → 19.0.1.2.1`；client/eda/theme/site 不变。
- 共享归一化：新增 `lab_inventory/tools/param_search.py`（无 Odoo 依赖），按现有标签逻辑选取关键参数（电阻 `阻值/精度/功率`、电容 `容值/容量/电容量/耐压/额定电压/介质/材质`、其他前 3 个），生成归一化检索文本。覆盖大小写、SI 前缀、`Ω/ohm`、`100nF = 0.1uF`、`±1%`、`1kV = 1000V`，以及低阻 R 记法 `10Ω = 10R`、`4.7Ω = 4R7`、`0.1Ω = R1`、`4.7kΩ = 4k7`、`1.5kΩ = 1k5`；原始写法与 NFKC 写法同时保留（如 `±2℃` / `±2°C`）。
- `lab_inventory`：`product.template` 新增存储字段 `lab_search_specs`（由 `lab_specifications` 计算）与 trigram GIN；迁移 `19.0.1.1.0/post-backfill_lab_search_specs.py` 分批回填。
- `lab_catalog`：`lab.catalog.item.search_params` + trigram GIN；参数 create/write/unlink 增量重算；导入器在既有 COPY/upsert 中写入；新增独立可重入回填脚本 `tools/backfill_search_params.py`（批大小、起始 ID、dry-run），完整回填后写 `lab_catalog.param_index_state=ready`。检索改为空白分词、每词 AND，身份字段或参数文本命中即可；facets 与 search 共用同一条件；`/lab/api/catalog/search` 响应新增 `param_index_ready`（只增不改），前端在未就绪时提示"参数索引未就绪"。排序仍为本地有货优先、再按编号。
- `lab_workflow` + `lab_team_web`：`pending/list` 新增可选 `query`、`state`（`pending/done/cancelled/all`）并返回过滤后的 `total`；不传 `state` 保持旧行为，Web 默认只看待入库。来料页新增关键词输入、状态筛选与"共 N 条"；combobox 有结果时显示"查看全部结果"链接到 `/team/lab?q=`，空结果/失败时隐藏，原有防抖、8 条、2 在途、8s 超时与 IME 行为不变。
- 测试（本机真实执行）：纯归一化 `test_param_search.py` **8/8**；`test_combobox.mjs` **21/21**（新增 view-all 用例）；`test_workflow_core.mjs` **19/19**；改动 Python `py_compile` OK；`git diff --check` 0。新增 Odoo ORM 用例 `test_catalog_param_search_orm.py` 与待入库 query/state/total/owner 用例，但本工作区**没有可用的 Odoo/PostgreSQL 测试实例，未执行**（不得记作通过）；真实浏览器、Flutter 未验证；生产目录数据已回填但未做人工搜索验收。
- 冻结：新建 `maintenance/registry/source-server-param-search-20261104-r2.json`（file_count **264**、tree_sha256 `503e278221851fa129351bae12e95b6da5a8eeb5192d4e8ab2e5907c270ab378`、清单 sha256 `485c93c2ca3d1543bf8bb8838acb538f24c0a6f23ae4b68418cd4c8f3410b86a`）并 `--activate`；r1 与旧 r3 清单未改写。r2 修正参数全部移除时空文本被 ORM 写成 NULL、导致就绪扫描误判的问题（改用单空格哨兵）。`maintenance/registry/routes.json` 已重新生成（**92** 项，包含合并后既有但此前未登记的 13 条 legacy 入口；本任务未新增路由）。
- `python tools/repo_check.py` exit 1：51 项通过，唯一错误为既有 `frozen-source:client`（`clients/app/t.obj` 缺失，与本轮无关）；`frozen-source:server` 已随新快照消除；16 条 payload 警告为既有离线载荷缺口。`generate_routes.py --check` exit 0，`git diff --check` 0。
- 生产部署（**2026-11-04T12:59–13:09Z**，`192.168.31.105` / `LcHardwareHouse`）：四模块 `-u lab_inventory,lab_catalog,lab_workflow,lab_team_web` 退出码 0、0 条 ERROR/CRITICAL/Traceback；服务 active；四模块版本 installed；参数回填 **695,217/695,217**、`lab_catalog.param_index_state=ready`。一致备份 `/opt/odoo/backups/20261104T125944Z-before-upgrade/`（`db.dump` 110,948,317 B / `2c8bd939…810794`；`filestore.tar.gz` 12,819,190 B / `c180ca54…c929f`），旧四模块源码在同目录 `module-source-before-upgrade/`。`/web/login` 303 → `/web/database/selector`（带 cookie 最终 200），标准升级脚本把它误判为失败；本次用四模块副本 + `finish_remote.sh` 收尾。**未做**：commit/push、真实浏览器验收、Flutter、目录导入、真实业务写；未执行回滚。

## 2026.11.03 P3 Web 生产部署（r3 → 生产 LcHardwareHouse；公网回归通过；`DEPLOY_STATE=completed`）

- 部署：**2026-11-03 00:16–00:36Z** 在 `192.168.31.105`（DB `LcHardwareHouse`，Odoo19 / Python 3.12.15 / base 19.0.1.3 / 55 模块 / nginx 1.18.0）执行 r3。`LC_DEPLOY_MODULES=lab_site,lab_team_web,lab_theme`（`lab_site` 仅权限归一、内容=冻结；`lab_theme` 仅由 `deploy-theme.sh` 换冻结版），`-u` 只跑 `lab_team_web`：**19.0.1.1.0 → 19.0.1.2.0**，`UPGRADE_EXIT=0`、错误行 **0**；`lab_workflow 19.0.2.0.0` / `lab_catalog 19.0.2.0.5` / `lab_inventory 19.0.1.0.0` 未变。
- 一致备份（停服态）`/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`：`db.dump` **110,944,415 B** / `40c76d0679d2a7915ba5857d5009c291c18f17fdf239803a484246228993ba19`；`filestore.tar.gz` **12,819,190 B** / `305b841f50f0b3417b120a3ff0b52e61800d533f3a2337418f3114a2d85abfda`（**611 条目**）；`MANIFEST.json`、`odoo.log.tail`；`store_fname` distinct **139** / tar 成员 **140** / 缺失 **0**；`service_was_active=false`。源码回滚快照 `/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`。
- 菜单：before **234 行**（lab_* 21 行，sha `3eb392d032ae1c0ed7a78456cd837c89aa1dc9f7ffc3f167c2e211b24a5e7c2a`）→ `removed=0 / added=1 / changed=12 / match=1`；新增 `lab_team_web.menu_legacy_label_wizard`（id 382、parent `lab_workflow.menu_lab_config`、action `lab_workflow.action_lab_label_open`），12 条仅 action 变；tree stable sha `bafa905fc5f5fdb65fe3ea72af42647e78300b685d5323b9764db26e9ec64b8c`。
- 网关：release `/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z`，`/etc/nginx/conf.d/lc-bore-netlify.conf` 现 include 该 release 的 `gateway.conf`，include sha **`34289f2612c9adb460c787c6765f72525bd1db5359eff515164cbb1ab42508ef`**（切换前 `bb3164e5630cc70cb24e9a1f95bdf8b5e40492ddee721c5ec5d01de2f2d8c4e9`，回滚点同目录 `rollback/project-include.before`）；allowlist pages **24** / apis **5** / legacy **13**；未动 `lc-bore-public.conf`、DNS、Docker、其他服务。
- 验收：`50-verify.py` = **PASS，129 项检查 / 0 失败**（`/var/tmp/lc-deploy/verify-20261103T003528Z.json` + `verify-facts-…env`）；三模块逐文件与冻结清单逐字节相等（`lab_site 19` / `lab_team_web 58` / `lab_theme 6` 文件）；13 条 legacy action GET/HEAD 全过、POST 全拒；`/web/login`、`/database`、`/jsonrpc`、ORM 404；`workflow_core.js` sha `6942f733fddaf4b3183a0251ad5d2ac99913d4c339921ca48dc59b7346cc0936`。
- 收口：`90-close.sh` 写 **`DEPLOY_STATE=completed`**、`DEPLOY_COMPLETED_UTC=20261103T003543Z`、`DEPLOY_FACTS_PROVEN=43`；run env `/var/tmp/lc-deploy/run-20261103T001600Z.env` sha `20f5b3fe34c2ed6c1c3f35a6141368a729a4e3baf4532ccdafe5dfb7905ec008`，close log `/var/tmp/lc-deploy/close-20261103T003543Z.log`；close 后服务 active、HTTP `/web/login` 200。
- 公网回归（`team.l-creation.club`，Netlify→bore→网关）：`/ 200`、`/login 200`、`/team/login 200`、`/team/lab/receipts 303`、`/team/scan 303`、`/lab/bags 303`、`/odoo/action-lab_workflow.action_lab_scan_console 303`、`/odoo/action-lab_inventory.action_lab_mapping 303`、`/web/login 404`、`GET /lab/api/inventory/bags 403`、`POST /team/lab/receipts 403`、`POST /lab/api/catalog/search 415`、`workflow_core.js` sha 一致、`pages/receipts.js 200`、`workflow_receipt.css 200`。
- 产物：**最终实际部署包** `deploy-bundle-web-ui-20261102-r3.tar.gz` = **93,486 B** / `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / **27 条目** / FROZEN **18** / shipped **15** / `bundle-meta` freeze `f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`；部署前中间包 91,307 B / `8215a795…`、91,586 B / `e453db43…`、92,857 B / `085945a2…` **均非最终**。源码候选 ZIP 13,251,571 B / `3800e2a2…` / 259 条目；r3 冻结清单未改写（258 文件、tree `95baea91…`、清单 sha `2192a354…`）。
- 部署期修复的脚本缺陷（真实、已修）：`05-bootstrap.sh`（tar 选项顺序 / mawk 转义斜杠正则 / `members.txt` 误判顶层，`f2d46931a5ddf15d430f63c469f78476345a22aa20be367526301e70b6755fde`）、`00-preflight.sh`（网关 include 闸门改声明式，`c48bbfddb5070f35e7724761b7a865ed3e0ab7a32d2abb1385b88577bd8ef99a`）、`lib.sh`（`http_login_code` 多路径 + `X-Odoo-Database`，`d5da44ed05aa46fab3e90bf53fe2215bbc490c1bbff315b63445db261817ba98`）、`40-gateway.py`（reload 优雅切换竞态加有界 settle，`487283ee6ee844a0ca81af66f57cda70fcc1a74579bb506be2096125cb231e7b`）、`50-verify.py`（`ir_ui_menu.action` Char vs res_id int、origin 探针补 DB 头、公网 5xx 有界重试，`14d4c1e084691486c5b231028848a553b948f269aae802c5238ee55a64997f0d`）；`FROZEN-20261102.sha256` 已同步，`check-scripts` `SYNTAX_ERRORS=0`、`USED_BUT_MISSING none`。
- 证据与凭据：`local/web-ui-implementation/evidence/production/p3-deploy-evidence-20261103.tar.gz`（**21,344 B** / `53433008c3bb6ae48da899105e64d2fd6e814b24a47d5b2617a3fe9cdc8069b5` / 20 条目）；`local/private/web-ui-20261102.dpapi` 已删除（`BLOB_DELETED`），本机不再存生产口令。
- 未做：未 commit/push（分支 `codex/receipt-search-feedback` 仍在工作区）；未建/发布客户端包（客户端 `1.1.3+6` 不变）；未做真实业务写；未动 DNS/Docker/其他服务；未执行回滚；未读 CI。

## 2026.11.02 战队管理站点统一 UI r3（两处深色视觉修复 + 53/53 下拉证据 + 55/55 真实套件全绿；新增 artifact 登记 r3；未提交/未推送；**部署见 2026.11.03 条目**）

- 源码变更（r3 相对 r2，**共 2 处，只改 `server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css`**）：① `team.css:38-41`（`body.lc-body` 令牌块内，`--lc-ease` 之后、`display:flex` 之前）新增 `color-scheme: dark`，令原生滚动条 / select / input 按深色 UA 渲染；② `team.css:2181` 的 `.lc-combobox-pop` 由 `max-width: min(540px, calc(100vw - 28px))` 改为 `min(780px, calc(100vw - 28px))`，桌面 1440 时候选弹层与 770px 输入框同左同宽，窄屏仍受视口约束（注释补句 `team.css:2166`）。其余 CSS 属性、JS、XML、Python 均未改；manifest 差异仅此一个文件，258 个源文件不变。
- 遗留 B / C 已修复（原记于 r2 artifact 的 limitations，此处给实测值）：B「深色主题缺 `color-scheme`、原生控件按浅色渲染」→ 5 个下拉用例 `colorScheme` 实测均为 `dark`（修复前 `normal`）；C「1440 下拉偏窄」→ 1440 视口 `input=770px`、`pop=770px`（gap 0，修复前 540px），375 视口 `input=pop=277px` 且 `document.scrollWidth=375` 无横向溢出。
- 升级验证（隔离 WSL Odoo19 实例，r3 源码，真实退出码，**不是生产**）：`upgrade-only-test.sh` → RUN=`upgrade-keepdb-20261102T134429Z`、`ODOO_EXIT=0`，`lab_team_web` **52 tests**、FAIL: / ERROR: 计数 **0**，日志 `local/web-ui-implementation/evidence/upgrade-keepdb-20261102T134429Z.log`；DB 实测 `lab_team_web=19.0.1.2.0`（installed）。
- 真实浏览器（r3 源码重跑）：下拉截图 `capture-receipt-dropdown.mjs` = **53/53 pass / 0 fail**（`local/web-ui-implementation/out/receipt-dropdown-20261102/evidence.json`：total 53 / pass 53 / fail 0 / failedIds `[]`；补充截图 `width-fix-1440.png` 118,206 B / 1440×900、`width-fix-375.png` 67,712 B / 375×812、度量 `width-fix-measure.json`；headless Chrome 156.0.8078.74）；全站真实套件 `run-real-ui.mjs` = **55 项 55 pass / 0 fail / 0 blocked**（exitCode 0、writeGate 全 true，report `local/web-ui-implementation/out/run-real-2026-11-02T13-38-39-691Z/report.json`），r2 时 3 项 blocked 全部补齐：静态袋详情 1440/375（`/team/lab/bags/41`，lab.bag id=41、trace `TRC00000045`、company=1；httpStatus 200 / errCount 0 / horizontalOverflow false / smallTargetCount 0）、`real-receipt-multi-create-lock`（archiveId=13、C990000001、tracking=none、无批次库存 12.00，createPosts=1、payloadMatch true、trace `TRC00000046`）、`real-receipt-legacy-precondition`（`PRECONDITION_FAILED`、`legacy_untracked_stock`、库存 12→12 未变、hasBag false、提示可见）。
- 套件证据缺陷（工具问题，非产品缺陷；未改工具源码）：给了 `WEBUI_BAG_ID` 后静态袋页与动态袋详情共用测试 id 前缀 `real-bag-detail-<1440|375>`，同一 id 两次、截图按 id 命名互相覆盖（`13-38-39Z` 里 `real-bag-detail-1440.png` 实际是动态袋 42）；已用 `--only=pages` 复跑（`local/web-ui-implementation/out/run-real-2026-11-02T13-40-31-993Z/report.json` = 35 项 32 pass / 0 fail / 3 blocked 全为 `--only` 主动跳过标记，exitCode 3）留下静态袋 41 截图 `…/13-40-31-993Z/shots/real-bag-detail-1440.png`（172,807 B，1440×2258）；建议静态页 id 改为 `real-page-bag-detail-<vw>`。同库并发跑套件会互相污染合成数据，只能串行。
- 冻结与产物（本机打包，r3；部署结果见 2026.11.03 条目）：新源清单 `maintenance/registry/source-server-web-ui-20261102-r3.json`（file_count=258，tree_sha256=`95baea916fbe4c8504e9a3bc2ce1c18235cf53689373d323b32d914d1e1fe8de`，sha256=`2192a3545ebbe2ea3293072d1cc971a8deab1e524a4e39c20503d760888a7224`，已 `--activate`；旧 10-28、r1、r2 清单均未改写）；r3 源候选 `local/build/web-ui-20261102/candidates/server-web-ui-20261102-r3-source.zip`（bytes=13251571，sha256=`3800e2a210a1c0fdad562112b4682ed02d83ae466f678443bfafb1923a02d4f7`，entries=259 = 258 源文件 + `MANIFEST.json`，构建报告 `local/build/web-ui-20261102/candidates/build-summary-20261102-r3.json`）；r3 部署 bundle `local/build/web-ui-20261102/candidates/deploy-bundle-web-ui-20261102-r3.tar.gz`（bytes=91307，sha256=`8215a7958fe227452f19f3458a149509169cfd3cf26fadfbd6ecad82b6e8f02d`，entries=27，`FROZEN-20261102.sha256` 18 条 = 15 随包脚本 + 3 本地脚本（无空行），`bundle-meta.json` 的 `freeze_sha256`=`93b07b020fb76d0ce48075495737a1e08b34df081370ab966eddacfb40b416b8`、`shipped_script_count=15`，`params.env` 已指向 r3 的 zip/manifest 与两个 sha；**2026-11-03 更新**：部署期修复脚本缺陷后重打，最终实际部署包 bytes=**93,486** / sha256=`34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / entries=27 / `FROZEN` 18 / `bundle-meta` freeze=`f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`，本条前面列的 91307 为部署前中间包）；新登记 `maintenance/registry/artifact-server-web-ui-20261102-r3.json`（version=`lab_workflow19.0.2.0.0+lab_team_web19.0.1.2.0+server-ops2026.11.02.1`，`kind=source-only-local-candidate`，`production_deployed=false`，`supersedes` 指向 r2 登记）。**r2（tree `aad3eacd…`、ZIP 13,251,445 B、bundle 91,273 B）与 r1 已被 r3 取代，保留为历史，不得部署。**
- 其他实测（r3 收尾）：`python tools/repo_check.py` = **PASS / 52 checks / 0 errors / 1 既有 warning（`production-py312-rebuild`）**，证据 `local/web-ui-implementation/evidence/repo-check-20261102-r3.json`、exit 0；`git diff --check` = 0。沿用（未重跑、与 r3 无关）：`test_combobox.mjs` 20/20、`test_workflow_core.mjs` 19/19、bore 契约 `Ran 19 tests ... OK (skipped=7)`；Flutter 客户端 295 passed / 5 skipped、`flutter analyze` 0 error / 0 warning / 119 info、客户端清单 169 文件 tree `ee5adebd…` / sha `d703e507…`、版本仍 `1.1.3+6`（未构建/发布 APK）。
- 生产部署（2026-11-03 更新）：**已于 2026-11-03T003543Z 部署完成**（`DEPLOY_STATE=completed`、`DEPLOY_FACTS_PROVEN=43`、公网回归通过；artifact 登记 `production_deployed` 已改为 `true` 并新增 `production_deployment` 块），本条目 2026-11-02 时点写的「主机不可达 / 未部署」已失效。仍成立：隔离环境 WSL Python 3.10.12 + Odoo19 与生产 Python 3.12.15 不等价，生产 cp312 离线闭包仍缺（repo_check 的 `production-py312-rebuild` 警告）。

## 2026.11.02 战队管理站点统一 UI 收尾（r2 版本冻结 + 源候选 + 部署包；未提交/未推送/未部署；**r2 历史，已被 r3 取代**）

- 版本（`components.json` 已同步）：`lab_team_web 19.0.1.1.0 → 19.0.1.2.0`、`server-ops 2026.10.28.1 → 2026.11.02.1`；其余组件（`lab_workflow`/`lab_catalog`/`lab_inventory`/`lab_theme`/`lab_site`/client/eda）本轮不改，见 `maintenance/registry/components.json`。
- 源码变更（`lab_team_web`，分支 `codex/receipt-search-feedback`）：整站 1024px 断点（≥1024 固定侧栏 / ≤1023 抽屉）；`LC.combobox`（250ms 去抖、IME 组字不检索、请求序号 + 在途 ≤2 + 8s 显式超时与「重试检索」、方向键/Enter/Esc/Tab 与 aria 语义）；来料页关键词候选与多档案明确选择；建袋结果未知期锁定 `material-select`；旧入口 13 条 `/odoo/action-<xmlid>` 兼容路由（非 GET/HEAD 返回 405）与 `views/legacy_entry_menu.xml` 菜单可逆改指（卸载还原）；issues 页行内按钮统一 44px（`workflow_issue.css`/`workflow_inventory.css`）。
- Flutter 客户端（并行的客户端轮，已完成并冻结；版本仍 `1.1.3+6`）：收据/待打印入库页内联收据搜索建议——新增 `clients/app/lib/features/unified/widgets/catalog_suggest_search.dart`（818 行，格式化后：OverlayPortal + CompositedTransformFollower 浮层、防抖 `Duration(milliseconds: 250)`、每键 `_seq` 递增作废旧请求、IME 组合期（`_controller.value.composing.isValid`）不查询、loading/empty/error+retry、Up/Down/Enter/Escape/Tab、48dp 行高、TapRegion 外点关闭、不裁切）与测试 `clients/app/test/features/unified/catalog_suggest_search_test.dart`（739 行、20 个用例）；改 `clients/app/lib/features/unified/screens/receipt_screen.dart`（+66/-4）、`.../screens/pending_receipt_screen.dart`（+129/-16）、`.../providers/inventory_providers.dart`（+20/-1）、`.../test/features/unified/item_picker_test.dart`（1 行文案）。验证（`clients/app`，`--no-pub`、无 `pub get`）：`flutter test --no-pub --reporter compact` exit 0、`+295 ~5`（295 passed / 5 skipped，5 个 skip 为既有需真实 Odoo 账号的 live 用例），单跑新测试文件 20/20；`flutter analyze --no-pub` exit 1 但 0 error / 0 warning / 119 info（全为改动前既有 info，新文件 0 新增，证据 `local/web-ui-implementation/evidence/flutter-analyze-20261102.txt`）；两个新文件 `dart format --output=none --set-exit-if-changed` 无改动。客户端源码已冻结 `maintenance/registry/source-client-receipt-search-feedback-20261102.json`（file_count=169、tree_sha256=`ee5adebdaa0c3e81dfa616b8dc55243d6419790422b93b010f9126f3aaa70072`、清单 sha256=`d703e507cd04bbe6bad648a3bf263b79d6626bf34ae77bba45cae88d6d37952f`，已 `--activate`，旧 `source-client-android-install-fix-final-20261019.json` 未改写）；**未升版、未构建/发布 APK**；无 emulator/真机运行，receipt 页无专门提交锁 widget 测试（pending 页有）。
- 升级验证（隔离 WSL Odoo19 实例，在 r2 源码上重跑，真实退出码，**不是生产**）：`upgrade-only-test.sh`（`-u lab_team_web --test-enable --test-tags=/lab_team_web --stop-after-init`）→ RUN=`upgrade-keepdb-20261102T125331Z`、`ODOO_EXIT=0`，模块用例 `52 tests`、`0 failed, 0 error`，日志 `local/web-ui-implementation/evidence/upgrade-keepdb-20261102T125331Z.log`；升级后 DB 实测 `ir_module_module.latest_version('lab_team_web')=19.0.1.2.0`（state=installed）。
- 其他实测（同轮，真实退出码）：`test_combobox.mjs` 20/20、`test_workflow_core.mjs` 19/19、bore `test_legacy_action_gateway_contract.py` `Ran 19 tests ... OK (skipped=7)`（7 skip 为环境相关）、`python tools/repo_check.py` = PASS / 52 checks / 0 errors / 1 既有 warning（`production-py312-rebuild`，冻结时点；上一版记的「文档更新时点重跑为 51 checks / 1 error `frozen-source:client`」真实原因是并行客户端改动当时尚未冻结，不是回归——冻结客户端源码后按 `python tools/repo_check.py --output local/web-ui-implementation/evidence/repo-check-20261102-r2-flutter.json` 重跑 = PASS / 52 项 / 0 errors / 1 既有 warning）、`git diff --check` = 0。
- 冻结与产物（本机，未部署，r2）：新源清单 `maintenance/registry/source-server-web-ui-20261102-r2.json`（file_count=258，tree_sha256=`aad3eacd53b112943d2204b6cb9ba7e1f4feb1cee445dea3608b2a0fe254f765`，sha256=`9b29e0d2f4441ed61c2de4c0df48584dc8a56379737da9666b6004593592fd4d`，已 `--activate`；旧 `source-server-p3-web-20261028.json` 与 r1 `source-server-web-ui-20261102.json` 均未改写）；r2 源候选 `local/build/web-ui-20261102/candidates/server-web-ui-20261102-r2-source.zip`（bytes=13251445，sha256=`cb868d7645b48836666810c84d2571a2e353f69bf5269e028f1f84a147f9de62`，entries=259 = 258 源文件 + `MANIFEST.json`，构建报告 `local/build/web-ui-20261102/candidates/build-summary-20261102-r2.json`）；r2 部署 bundle `local/build/web-ui-20261102/candidates/deploy-bundle-web-ui-20261102-r2.tar.gz`（bytes=91273，sha256=`848082612140a6aa8710c4dc9505690fc6aaa9ca78e7fd80c6139ef138811f34`，entries=27，`FROZEN-20261102.sha256` 19 条 = 15 随包脚本 + 3 本地脚本 + 1 空行，`bundle-meta.json` 的 `freeze_sha256`=`93b07b020fb76d0ce48075495737a1e08b34df081370ab966eddacfb40b416b8`，`params.env` 已指向 r2 的 zip/manifest 与两个 sha）；artifact 登记 `maintenance/registry/artifact-server-web-ui-20261102-r2.json`（version=`lab_team_web19.0.1.2.0+server-ops2026.11.02.1`，`production_deployed=false`）。**r2 只比 r1 多一条 CSS 修复：`server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css:2198` 的 `body.lc-body .lc-panel:has(.lc-combobox-pop:not([hidden])) { overflow: visible; }`，修 375px 下拉向上展开被裁切；r1（tree `634d1893…` / sha `fe34ed95…`、ZIP 13251270 B、bundle 91154 B）已被 r2 取代，不得部署，仅作历史保留。**
- 文档：`local/web-ui-implementation/deploy-plan.md` 新增**第 8.5 步**（50-verify 之后执行 `remote/90-close.sh` 写 `DEPLOY_STATE`，含 incomplete 的唯一例外与不可逆性）与 `§1.1` 候选实测参数表；`docs/operations/CURRENT_STATE.md` 追加同日收尾段落；交接见 `maintenance/templates/HANDOFF.md` 与 `local/web-ui-implementation/handoff.md`。
- 真实浏览器证据（r2 源码上重跑）：`capture-receipt-dropdown.mjs` 48 断言 all pass / 0 fail（5 用例 keyword1440 / keyword375 / multi1440 / multi375 / bare-code1440，证据 `local/web-ui-implementation/out/receipt-dropdown-20261102/evidence.json`）；`run-real-ui.mjs` 54 项 51 pass / 0 fail / 3 blocked（report `local/web-ui-implementation/out/run-real-2026-11-02T12-50-26-676Z/report.json`，3 blocked 为 `real-page-bag-detail-deferred` 缺 `WEBUI_BAG_ID`〔已由动态袋用例覆盖〕、`real-receipt-multi-create-lock` 与 `real-receipt-legacy-precondition` 缺 `WEBUI_LEGACY_ARCHIVE_ID`，不猜）；r1 时期两轮存量证据（`run-real-2026-11-02T10-22-34-590Z` 55 项 54 pass/1 fail=两枚 36px 按钮；修 44px 后 `run-real-2026-11-02T11-08-17-482Z` 34 项 30 pass/0 fail/4 blocked）仅作历史。部署仍阻塞：生产主机 `192.168.31.105` 不可达（ping 100% 丢失、TCP 22/8069 不可连、同网段无 ARP 表项），本轮未接触生产、未 SSH、未部署；不构成"生产已验证"或"全平台通过"结论。

## 2026.10.28 P3 自有 Web 日常业务（源码候选：功能验证完成，未发布/未部署）

- 版本（`components.json` 已同步）：`lab_workflow 19.0.1.2.0 → 19.0.2.0.0`、`lab_team_web 19.0.1.0.5 → 19.0.1.1.0`、`server-ops 2026.10.27.3 → 2026.10.28.1`；`lab_catalog`/`lab_inventory`/`lab_theme`/`lab_site`/`client 1.1.3+6`/`eda 3.0.3` 不变。
- `lab_team_web`：13 个业务页面（`/team/lab/receipts`、`/team/scan`、`/team/lab/bags[/<id>]`、`/team/lab/labels`、`/team/lab/issues[/new]`、`/team/lab/history`、`/team/lab/locations`、`/team/lab/location-mappings`、`/team/lab/settings`、`/team/lab/materials`、`/team/account`）+ 公共外壳与 `window.LC` 运行时；写操作走 JSON-RPC + 前端 `request_key`，唯一表单 POST 为 PDF。
- `lab_workflow`：8 个 JSON-RPC 窄接口（袋列表/袋详情/库位改停用/类别映射三件/成员与角色）、新模型 `lab.location.mapping`、`POST /lab/labels/pdf`、`GET /lab/scan` 303 至 `/team/scan`；修复安全审查 S1 跨账号归还、S2 畸形入参、S3 `adopt_stock` 部分提交、S4 按 id 读取复核公司、S5 停用库位。
- 运维：公网 allowlist 模板逐端点新增 P3 页面与 POST（源码，**未部署**；`adopt_stock`/`legacy_stock`/通用 ORM 明确不放行）；新增 `verify-p3-write.sh`、`browser_flow_p3.py`、`test_p3_runner.py`、`test_p3_gateway_contract.py`。
- 验证（分项如实记，**不构成"P3 全部验证通过"**）：
  - **已通过**：隔离 ORM 业务 **82/82，0 fail 0 error**（**role wrapper 之后真实重测**：`backend-orm-final.log` + `backend-orm-final-evidence/`，同轮 HTTP 6 并发亦过）；真实 HttpCase **21/21**（`httpcase-r8.log`：total=21 failed=0 errors=0 `p3_class_ran=1`，RC=0）；API 断言 **54 pass / 0 fail / 1 blocked**（total 55，1 blocked 为 Origin 断言——本轮未提供 Origin URL，**不能改判 PASS**）；Nginx 配置契约 1.26.2 **34/34**、1.30.6 **34/34**；独立 process adapter 并发 **6/6**（`concurrency-standalone-r3.json`，负向自检 `detected=true`）；linux runner **17**；core **17/17**；XML **6/6**；JS 语法 **15/15**；路由表 **79** 条。
  - 真实浏览器主链 **31 步 28 pass / 0 fail / 3 blocked**（`runs/browser-20261028T065311Z/browser-p3.json`、`browser-r8.log`）：3 blocked 为 `p3-cross-user-denied`、`p3-receipt-same-key-conflict`、`p3-unknown-outcome-retry` 的 **DOM 场景未执行**，由 API 断言 / HttpCase / core 独立覆盖，**不得写成 DOM 通过**。真实 UI+服务端事实成立：两种 canonical key、建袋不增 quant、上架 +2、重复确认 quant 不变、领用 −2、部分归还 +1，role/materials/locations/mappings 管理页可用。
  - 有效性前提（不得省略）：原 `--test-enable` 进程内并发套件因 **Registry 锁 blocked**（Probe 直接证实 `Registry._lock` 由主线程持有），wrapper 整体 **exit 1**，**不得称该命令全绿、也不得称"原进程套件通过"**；6 条并发断言由独立 process adapter 复用执行并全过。
  - 历史失败（ORM R3/R4、HTTP R2、HttpCase 9 error、浏览器缺 `websockets`）为修复前记录，保留在 `local/build/p3-web-20261028/` 供追溯。
- 候选内产品修复：`receipts.js` 把 `lcsc:<C码>` 正确转成裸 `C…` 交付 `resolve`，`lab:<id>` 走既有 `catalogDetail` 适配以保住具体本地档案；`LABB:`/`LABL:`/SN/立创原厂码路径不变。
- 测试 trace 读取口径：只从**本轮新增的唯一 DOM 行 td** 读 `raw` trace；仅扫码时才补 `LABB:` 前缀，**不得要求表格文本里出现 QR 前缀**。
- 冻结 / 构建 / 登记（**已完成**）：
  - 源快照 `maintenance/registry/source-server-p3-web-20261028.json`：**250 源文件**，treeSHA `fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43`，manifestSHA `0bfc1e3f581d90109c3e8942ff85cd9880a22ceac950d3c6fd93c0e90389c164`；`active-sources.server` 已指向该快照，旧 manifest 与旧产物未覆盖。
  - 候选包 `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`：**13,186,981 B**，SHA256 `9070800b65b8fa3c751b5d4ac0dc5d94910a97e27128adbd0ff4370c4549e564`；250 个文件逐条 raw+normalized 校验 + **251 个归档条目重读**全部一致；构建环境 Windows 11 + Python 3.15 stdlib zip；**纯源码，无 runtime/数据库/凭据**；源码 ZIP **签名 N/A**。
  - artifact 登记 `maintenance/registry/artifact-server-p3-web-20261028.json`；构建摘要 `local/build/p3-web-20261028/build-summary*.json`。
  - 仓库检查 `repo-final-r1.json`：**52 项检查 PASS，exit 0**，唯一 warning 为 `production-py312-rebuild`。
- 测试口径修正：`test_04` 的 quantity 为**精确匹配实际成功请求**（可能是 10 或 11），**不得硬编码 10**；两管理员并发互撤后保留 1 名 manager，另一侧 `FORBIDDEN` 属合法权限撤销。
- 未关闭（不因本轮完成而消失）：手机流量不挂 VPN 实测、实体摄像头/扫码枪、实体纸张打印、真机；生产 Python 3.12 **不等价**隔离 3.10.12，完整离线恢复（cp312 wheelhouse + 一致 filestore 备份，P2 旧备份附件不完整且非一致快照）未闭合；**未做生产部署与公网开放**。
- [交接](maintenance/handoffs/2026-10-28-p3-web-workflows.md)｜[任务](maintenance/tasks/2026-10-28-p3-web-workflows.md)｜证据与候选包在 `local/build/p3-web-20261028/`（Git 排除）。

## 2026.10.27 正式team域名HTTPS验收

- 用户完成标准CNAME，实际Netlify Edge正常SNI/证书与22项检查通过；旧LAN200已通过remote_ip识别并排除。
- 区域节点直连超时、官方默认负载均衡单点可直连，记录线路差异；未改DNS或代理，待手机流量无VPN正式域名验收，不作全网稳定性承诺。[记录](maintenance/audit/netlify-formal-domain-acceptance-20261027.md)。

## 2026.10.27 用户侧登录通过，正式域名待绑定

- 用户确认Netlify真实账号登录和功能正常；自动端到端22/0。精确停止已完成使命的7882固定文本诊断服务，保留日志。
- 正式team域名使用阿里云外部DNS+CNAME接入，无需切Netlify DNS委派；仍待正式TLS/会话验收。[记录](maintenance/audit/netlify-frontend-acceptance-20261027.md)。

## 2026.10.27 Netlify实际前端验收

- 用户已更新现有测试项目；实际HTTPS前端22/0，静态资产内容一致、敏感路由与Origin拒绝、动态响应不缓存。
- 真实账号会话仍待用户登录/刷新/退出确认，然后进行team域名绑定与CNAME切换；不覆盖此前冻结源/产物。
- [验收证据](maintenance/audit/netlify-frontend-acceptance-20261027.md)。

## 2026.10.27 Netlify HTTPS回源网关与部署包

- 专用origin-team证书签发；新增IPv4 bore16444/回环TLS18445，明确回源Host与公开Origin、canonical管理Host，禁止共享缓存/验证器，保留白名单与原LAN vhost。
- 新renderer9/0、原8/0+契约21/0、真实本机79/0、合成15/0、最新正常SNI公网22/0，自动重连通过；原21/1 TLS重置记录保留。
- 运维2026.10.27.3，新[冻结源](maintenance/registry/source-server-netlify-https-origin-20261027.json)211文件；Netlify ZIP记录来源和SHA，等待用户更新已有项目，尚未宣称前台/真实账号最终通过。
- [审计](maintenance/audit/netlify-https-origin-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-netlify-https-origin.md)。

## 2026.10.27 Netlify实际回源通过与HTTPS准备

- 用户站点rad-taffy-56e1ce.netlify.app回源成功；Lead独立web_fetch/本机IPv4无代理均确认200与完整标记，响应no-store、fwd=miss。
- 为专用origin-team回源名启动独立DNS-01证书请求，等待用户添加A/TXT；保留现有team证书与DNS。正式业务回源/登录尚未验收。
- [审计与DNS待办](maintenance/audit/netlify-https-origin-20261027.md)。

## 2026.10.27 Netlify最小回源测试准备

- 提供无需构建、可拖拽部署的独立测试包，Netlify200 rewrite请求固定文本IPv4 bore探针；校验归档与脚本语法并实际取得中继标记。
- 尚未部署Netlify，等待用户上传并返回站点URL；暂不改DNS，不改原官网，不连接生产Odoo。诊断服务24小时到期。
- [审计与后续条件](maintenance/audit/netlify-bore-probe-20261027.md)。

## 2026.10.27 IPv4 bore独立网关部署

- 新增经过校验的独立白名单网关renderer与systemd模板，运维2026.10.27.2；生产仅新增回环18443网关与159.223.110.159:16443隧道，保留内网vhost。
- Nginx1.18 Cookie兼容、精确Origin/Host端口、敏感路径默认拒绝、共享认证POST限速；生产本机49/0、合成12/0、无SNI严格TLS公网19/0、自动重连通过。
- 正常浏览器SNI仍需DNS切换后验收，真实账号未测；Qoder委派未返回产物，未算独立验收。
- [审计](maintenance/audit/bore-public-ipv4-deploy-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-bore-public-ipv4-deploy.md)｜[冻结源](maintenance/registry/source-server-bore-public-ipv4-20261027.json)。

## 2026.10.27 bore IPv4/代理诊断纠正

- 真实公网合成服务经现有HTTP代理CONNECT/正向转发成功，域名与IPv4均HTTP200+精确响应；独立curl复核exit0。仅本机直连该中继超时，不能推出境外全部封锁。
- 撤销此前“HTTP代理不转TCP、bore必须放弃”的错误判断；本轮未改VPN/DNS/生产配置，测试隧道已清理。生产公网白名单入口仍未部署。
- [审计](maintenance/audit/bore-ipv4-proxy-recheck-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-bore-ipv4-proxy-recheck.md)。

## 2026.10.27 P2 模块生产上线

- `lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5` 已在生产 LcHardwareHouse 上线；服务 active、TLS 登录 200，库存与其它模块未变。
- 修复备份工具默认 `data_dir` 与生产实际不符导致**附件漏备**的缺陷：现同时解析配置、当前用户与 `odoo` 服务用户 home，库内有附件但归档为空时直接失败；已补备 139 个真实附件并新增 3 项回归测试。
- 通用 `upgrade_modules.sh` 硬编码三模块且不含 `lab_team_web`，本次改用专用最小发布流程，避免误升级或漏升级。
- 未改 DNS/Nginx/公网入口；`team.l-creation.club` 仍指向内网 `192.168.31.105`。公网需真实节点+标准443+隧道登记。
- 新快照 [source-server-production-p2-20261027.json](maintenance/registry/source-server-production-p2-20261027.json)（202 文件）；`repo_check` PASS 52/0。
- [审计](maintenance/audit/production-p2-deploy-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-production-p2-deploy.md)。

## 2026.10.27 P2 隔离验收证据加固

- P2 127/0/0/0，exit 0；浏览器28/0，P1 116/0，hook7/0；lab_team_web19.0.1.0.5、lab_catalog19.0.2.0.5候选未部署。
- 修复authority丢端口、原生退出语义、资产代理安全地址回退和隧道就绪检查；严格CSP/SSRF/TLS边界不变。
- 下载清单独立Ed25519验签、中文截图复核、同轮计数和源码稳定性通过。旧77/0完整验收口径撤销，旧快照和失败轮次保留。
- bore167项（WSL165通过2缺Node跳过，Windows补测2/0）；lab_team_web87项（86通过1 HttpCase跳过）；lab_catalog23/0。
- 新快照：[source-server-p2-evidence-hardened-20261027.json](maintenance/registry/source-server-p2-evidence-hardened-20261027.json)。生产仅内网只读，无部署/重启/DB查询，公网与真机未验收。
- [审计](maintenance/audit/bore-p2-evidence-hardening-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-p2-evidence-hardening.md)。

## 2026.10.26 P2 最终

- lab_team_web 19.0.1.0.4：白名单重建 JSON-RPC 错误脱敏（全限定名兼容、业务消息过滤、未知错误通用+trace_id、端点 gating、uninstall_hook/restore）；退出/登录相对跳转；JS 退出 fetch+CSRF。
- 入口：CSP/XFO/Referrer same-origin、POST Origin 精确同源、@COOKIE_FLAGS@（P2 运行时 Nginx 1.30.6 proxy_cookie_flags，1.26.2 仅探测）。
- 验证：P2 77/0 BLOCKED=2 SKIP=0；P1 94/0；契约 12/0；模块单测 OK；headless Chrome 真实流程（登录/检索/详情/刷新/退出，console/CSP 无错误）通过；合成 update release 匿名 manifest 200 与下载/字节/sha256/角色/遍历断言通过。
- 冻结：source-server-bore-p2-final3-20261026.json（194 文件，tree 3ba4ac57…），repo_check 51/0。

## 2026.10.26 P2 隔离闭环修复

- lab_team_web 19.0.1.0.3：白名单重建式 JSON-RPC 错误脱敏（全限定名兼容、业务消息过滤、未知错误通用化 + trace_id）；幂等安装/可还原/uninstall_hook；端点级 gating。
- 入口模板：CSP/XFO/Referrer、POST Origin 精确同源、@COOKIE_FLAGS@；P2 运行时 Nginx 1.30.6 proxy_cookie_flags（1.26.2 仅探测，不冻结）。
- 结果：P2 61/0 BLOCKED=3 SKIP=1；P1 回归 94/0；契约 12/0；脱敏单测 8/0。asset 公开源与更新包 blocked。

## 2026.10.26 P2 真实 Odoo 只读验证

- 新增 `server/ubuntu22.04/bore/scripts/verify-real-odoo.sh`（环境变量驱动，无凭据），在隔离 Odoo 19 上经最终 P1 模板验证登录/会话/角色/资源/更新清单/拒绝路径/限速，**PASS=46 FAIL=0**。
- 入口模板补 CSP/nosniff/X-Frame-Options/Referrer-Policy；契约测试增至 10 项。
- 记录待决策缺口：会话 Cookie 仅 HttpOnly、JSON-RPC 错误含 traceback、生产未应用新头、web.base.url 仍 http。

## 2026.10.26 bore 公网入口 P1 本地隔离实现

- 新增 `server/ubuntu22.04/bore`：默认拒绝的入口 Nginx 模板（精确路径/方法白名单）、代理头覆盖、限流钩子、边缘 stream 模板、本地验证脚本与契约测试。
- 本地实测：真实 Nginx 1.18.0 + bore 0.5.3 + 合成上游，完整链路（边缘 Nginx stream → bore → TLS+PROXY 入口 → 上游）**94 断言通过、0 失败**；契约测试 9 项通过；失败路径测试 10 项通过（端口占用/WORK 复用）；运行时完整性 10 项通过（篡改归档拒绝且不解包）。
- 上游研究：bore（MIT）官方无 PROXY protocol，边缘必须由成熟 Nginx stream 生成；浏览器/客户端旧调用迁移、真实 Odoo 会话与公网节点仍未验证。
- 仅本地/隔离；未部署、未开公网、未改生产。

## 2026.10.26 bore公网入口与自有UI整合方案

- 基于当前源码形成仅Odoo登录的公网入口、HTTPS/可信来源IP/精确路由白名单和完整自有UI迁移方案；记录免费中转与标准443约束，复用成熟能力。
- 盘点旧WebClient/网站/扫码页面及客户端调用，先补入库/领用归还/标签等业务，再收敛普通用户入口；原生维护仅管理员内网可达，网站卸载另审依赖。仅文档，不表示已实施或获准清库/卸载。

## 2026.10.25 管理子域名HTTPS接入

- 用户自行完成LE生产签发，team Nginx启用443与80到HTTPS的308跳转，保留认证补修和旧vhost。正常TLS与页面/保护/资产/旧更新清单12项独立检查通过。
- manual证书到期2027-01-23，续期未自动化；HTTPS真实账号流程未测。离开内网后DSH桥接不可用，最终备份/操作审计待恢复取得，不计全部收尾完成。

## 2026.10.25 新域名冷登录会话补修

- 仅在team域名原生认证代理清除选库请求头，修复Odoo19首次认证后无法持久保存会话；其他路由仍自动选库。备份后校验并reload Nginx，业务源码、旧vhost和库存未改。
- 隔离4组场景13条断言通过；生产匿名入口、错误账号及旧更新清单复核通过。用户随后确认“可以了”，原登录无反应已恢复；刷新保留登录及退出未追加实测，HTTPS尚未启用。

## 2026.10.25 内网管理域名HTTP接入

- team.l-creation.club新增独立Nginx vhost并固定生产数据库；现有lab_team_web启用该management_host，根欢迎页、/login、/lab可直接访问，无需旧数据库选择页，旧站/API兼容保留。
- 按追加授权把服务器自身DNS从失效localhost改为路由器192.168.31.1，停用旧dnsmasq并取消自启；保留配置与回滚备份，IP/路由/其他网络服务未改。
- 客户端真实域名三组15项HTTP响应符合预期，CSS/JS内容缓存键一致；业务源码/库存基线未改。HTTPS未启用，LE账号/协议待用户答复；真实账号全流程、VPN与视觉未重测，manual续期未自动化。

## 2026.10.25 独立仓库 Web 第一批

- 新增 lab_team_web 19.0.1.0.0：自有欢迎、登录、检索和详情页面，Odoo 继续提供认证、权限和真实库存；保留旧后台与 API。
- 修正安全回跳、异常白屏和登录表单提交；手机采用紧凑信息行，CSS/JS 使用内容 hash 更新缓存。
- 候选验证：65 项逻辑通过、1 项跳过；11 项隔离 HTTP 通过；桌面/375px核心浏览器流程通过。175 文件来源冻结，生产发布另记审计；后续入库领用、DNS 和真机不计已完成。
- 本轮完整备份后仅新增 lab_team_web 并上线，服务active，新18文件匹配、旧133文件及库存基线不变，原页面/更新通道正常。多库首次会话需经原登录选库，管理Host/根别名未启用；生产真实账号全流程未重测。

## 2026.10.24 门户安装

- lab_portal19.0.1.0.0：独立战队首页、原生管理系统登录入口；修正原稿XML、资源路径和登录循环。
- 隔离安装及错误登录流程验证后完整备份上线，生产首页/13资源/认证跳转通过，原库存与更新通道不变。浏览器控制被URL安全检查中止，视觉验收未完成。后台主题可读性问题仍未修复。

## 2026.10.24 Odoo暗色主题上线

- lab_catalog19.0.2.0.4：暗色与荧光绿主题；修正改稿类名不匹配，保留器件卡片/工作流/手机布局；仅屏幕应用主题。
- 生产完整备份后升级，108文件匹配、服务active、真实认证后台与CSS200，库存/更新通道不变。视觉、手机与打印验收仍待完成。

## 2026.10.19 Android更新发布与安装入口修复

- Android1.1.3+6已发布stable seq2，实际旧版验签/版本判断、LAN清单200、认证完整包/hash、403与匿名303通过；实机安装仍待验证，旧安装入口失败需手动覆盖一次。

- 按用户明确请求发布Android1.1.2+5 stable（清单200、旧版验签/递增判断、认证完整包/hash及拒绝访问均验证），实际手机安装仍失败，未把发布当作实体验收。
- 1.1.3+6修复合法私有缓存路径别名被错误拒绝，仍校验真实目录包含、大小/hash及APK身份；显示权限/校验/安装器/取消等具体原生原因。真实JVM路径9项、Flutter275通过5跳过，分析0错误0警告。

## 2026.10.19 器件选择修复

- 按本轮明确授权上线lab_workflow19.0.1.2.0更新接口，三端manifest204，库存/袋计数不变；完整备份和权限验证完成，未发布stable包。

- 客户端1.1.2+5：修复采购入库选择器无限高度白屏；弹层内显示立创资料清单、服务端搜索及自定义新建入口，打开不自动弹键盘。校验提示去除Bad state技术前缀。
- 更新面板展示当前目标服务器，区分接口404、未发布204和连接/清单错误；新增实际打开弹层及本地HTTP回归。测试和三端候选见本轮修复交接。

## 2026.10.19 客户端更新器候选

- 客户端1.1.1+4：启动/前台恢复检查、重试、签名/版本/平台校验、同源登录下载和更新面板；非计费网络后台下载，确认后Android系统安装或桌面独立助手切换完整包，保留旧版。增加过期会话、请求保护及Windows短暂文件锁处理。
- lab_workflow19.0.1.2.0候选：匿名最小发布清单、需lab角色的完整包下载；签名发布工具和配套来源/依赖登记。三端候选已构建，尚未部署新服务端、发布stable或完成两版原生升级验收。

## 2026.10.19 服务端上线与部署修复

- lab_workflow 19.0.1.1.0已上线，三模块installed，服务active/HTTP200；前后库存和袋记录数量一致，权限与单QR标签检查通过。
- 修复升级工具将旧模块目录留在addons根导致Odoo19扫描失败的问题；旧源码改存配套备份、升级前校验扫描边界，108项运维故障测试通过。首次失败与重试、完整备份定位均保留在上线交接。

## 2026.10.19 原生候选包

- 基于冻结源重建 Windows、Android、Linux 1.1.0+3；完整桌面bundle及APK记录SHA256，Android与既有证书匹配，Linux依赖和执行权限通过。构建默认指向本地验收服务，未发布替换旧包；原生启动与实体扫码打印待测。
- 构建工具增加独立Gradle缓存选项，维护测试8项通过。用户另授权服务端子代理上线，其生产结果见独立上线交接和审计。

## 2026.10.19 两阶段入库开发候选

- 客户端源码 1.1.0+3、lab_workflow 源码 19.0.1.1.0：新增先建档制袋打印、再扫码选择库位确认实际入库两个循环；支持手工建档、独立袋码、补打、取消、打印选择恢复和安全重试。
- 默认袋标签调整为稳定身份和关键参数；同料号已有库存库位优先。新服务校验当前账号／公司和操作权限，实际入库沿用库存事务并防止重复提交。
- 按 Apple 风格简化分组、字段及动作，增加文字缩放、明暗主题、超时和隔离事务／HTTP 并发验收；进程内并发夹具限制单列。未构建发布新安装包，未部署生产。

## 2026.10.19 两阶段入库计划

- 新增两阶段入库与袋标签计划书：先建档制码打印，再扫码确认实际入库；明确标签字段、接口边界和验收标准。功能尚未实现，未变更组件版本或生产环境。

## 2026.10.19 维护归档基线

- 统一当前Flutter、Odoo、EDA、采集同步的权威源码与发布入口；旧版本独立保留。
- 新增组件/成品/源码/大文件来源登记、AGENTS协作规范、任务交接模板与维护检查。
- 保留离线依赖、历史数据及原WSL实际工具；Git排除大文件与私有签名。
- 原工作区未删除；生产仅做限定源码/服务与公开依赖元数据只读导出，没有部署、重启或业务写入。
- 当前功能版本不因归档改号；已知测试限制见CURRENT_STATE。
