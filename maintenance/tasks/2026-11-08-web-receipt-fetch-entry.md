# 任务：网页端采购入库接入按需抓取入口

- Status: ready-for-human
- Category: enhancement

- 目标/用户场景：用户在手机浏览器打开 `team.l-creation.club` 的「采购入库」，在料号输入框键入 `tlv77`，本地库没有结果时只看到"没有匹配的器件"，无法像客户端那样到立创商城抓取。目标：网页端同一位置也能一键抓取/查候选，抓到后可直接沿用既有解析与建袋流程。
- 当前问题及复现方法：2026-11-08 23:02 用户截图（采购入库，输入 `tlv77`，空态无按钮）。根因：`lab_team_web/static/src/js/pages/receipts.js` 只把 `catalogSearch` 的 `items` 交给下拉组件，丢弃了服务端 `fetch_suggestion`；`controllers/common.py` 的 `WORKFLOW_ENDPOINTS` 也没有登记 `catalogFetch` / `catalogFetchStatus`。另外 `MIN_KEYWORD_LEN=6` 让 5 字符的 `tlv77` 连候选建议都不会出现。
- 验收标准：零结果时只在服务端确认可抓的情况下出现按钮；点击才发请求；同步未完成时轮询状态并如实显示；`done` 后输入收敛为 `lcsc:Cxxxx` 并可继续建袋；关键词只列候选，选定 C 码后才抓详情；不写库存、不自动建袋；输入改变后旧按钮/候选立即作废。
- 允许修改目录/接口：`server/ubuntu22.04/odoo_addons/lab_team_web/`（`controllers/common.py`、`static/src/js/pages/receipts.js`、`static/src/css/team.css`、`tests/`）、`server/ubuntu22.04/odoo_addons/lab_catalog/`（`tools/lcsc_remote.py` 门槛、`controllers/catalog_api.py` 文案、`tests/`）、`maintenance/` 与文档、登记表。**不改**客户端契约与既有路由。
- 业务不变量/依赖：库存只认 `stock.quant`/`stock.move`；抓取只补器件资料（`lab.catalog.item/param`），不得写产品/quant/move；不自动选档案、不自动建袋；关键词仍不可直接抓详情。
- 负责人/协作者及分工：主代理实现与测试；用户提供截图与真实使用场景；部署需用户本轮授权。
- 分支/起始commit/源码manifest：`feat/receipt-param-search`（worktree `read-tomc-memory-56e7a2`）；起始清单 `source-server-lcsc-openapi-20261108.json`，本轮依次冻结 `source-server-web-fetch-entry-20261108.json`、`…-r2.json`，最终激活 `source-server-web-fetch-entry-20261109-r2.json`（274 文件，tree `6946414f…3cb4c2`，清单 sha256 `fb459a5f…3469f9`）（公网网关修复后重新冻结）。
- 环境与凭据获取方式（只写位置，绝不写值）：无新增凭据；抓取沿用服务器 `/etc/lc-elc/openapi.env`（`root:odoo 0640`）。
- 实施步骤：
  1. `receipts.js`：保存 `fetch_suggestion`（只对应当前输入）；空态 `emptyAction` 渲染按钮；`startFetch()` 调 `catalogFetch`（`sync: true`，30 秒超时）；`pollFetch()` 只对 `queued/resolving/fetching` 轮询 `catalogFetchStatus`（1.5 秒 × 40）；`finishFetch()` 处理 `done`/`candidates`/`not_found`/`failed`；候选面板渲染在表单内，点选后只抓该 C 码。
  2. `common.py`：登记 `catalogFetch`、`catalogFetchStatus`；`lc_version` 修正为 `19.0.1.2.2`（原 `19.0.1.1.0` 与 manifest 不一致）。
  3. `team.css`：新增候选面板样式，并让空态按钮也有样式（原来只在 `[data-kind="error"]` 下生效）。
  4. `lcsc_remote.MIN_KEYWORD_LEN` 6 → 5，文案同步；关键词仍要求含字母。
  5. 版本：`lab_catalog 19.0.2.0.14`、`lab_team_web 19.0.1.2.2`，`components.json` 同步；重新冻结并激活服务端清单。
- 测试命令、实际结果与退出码：
  - `python -I .../lab_catalog/tests/test_lcsc_remote.py` → **24 tests OK**，exit 0（门槛用例改为 `TLV9` 拒绝、`TLV90` 放行）。
  - `python -I .../lab_catalog/tests/test_lcsc_openapi.py` → **23 tests OK**，exit 0。
  - `python -I .../lab_team_web/tests/test_p3_web_contract.py` → **28 tests OK**；`test_p3_ui_consistency.py` → **15 tests OK**；`test_entry_contract.py` → **11 tests OK**（修正 `lc_version` 后由 2 条失败转全过）。
  - `node .../lab_team_web/tests/test_combobox.mjs` → **23/23 passed**（新增 2 条 emptyAction 用例）；`node .../test_workflow_core.mjs` → **19/19 passed**；`node --check .../pages/receipts.js` → exit 0。
  - `python -I tools/repo_check.py` → exit 0；`python -I tools/generate_routes.py --check` → exit 0（94 条，无新增路由）；`git diff --check` → 0。
- 未验证项及风险：
  - **浏览器手测**：2026-11-09 01:0x CST 用户在手机端重试 `tlv77` 已正常（按钮→候选链路可用）；`not_found` 与失败提示、限流（每用户 5 个进行中 / 每小时 20 次）仍未实测。
  - 首次实测暴露：公网网关 allowlist 未登记 `catalog/fetch`、`catalog/fetch_status`，请求在 Netlify→bore 网关 404（返回 `INTERNAL_ERROR`）。已新增网关 release `p3-web-20261109T010500Z` 并 reload，公网两端点 200 且到达 Odoo；仓库模板与契约测试同步补齐。旧的直连公网网关 release `20261027-a2` 未改。
  - 官方接口边界：C 码抓取走官方 SMT 通道；官方关键词搜索接口对当前账号返回"接口权限不足"，关键词候选仍走 LCSC 网页搜索（只读），选定 C 码后才走官方 SMT。
  - ~~未部署~~ 已于 2026-11-09 00:27 CST 部署：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261109/modules --modules lab_catalog,lab_team_web`，`-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_catalog|19.0.2.0.14|installed`、`lab_team_web|19.0.1.2.2|installed`；服务 active、`/web/login` 带库头 200、10 分钟日志 0 错误、静态资源含新代码。部署脚本原本只认三个业务模块，本轮为它加了 `--modules`；首轮曾因脚本 CRLF 化报 `set: pipefail: 无效的选项名`，改回 LF 后成功。
  - 同步抓取会占用一个 Odoo worker 最多约 15 秒；锁被占用时退回 cron，前端最多等 60 秒后如实告知。
  - 关键词门槛下调到 5 字符后，`100nF` 这类参数词也会发起一次候选检索（只读、不写库），需要观察立创接口的调用量与命中质量。
- 发布文件、hash和回滚点：部署备份 `/var/backups/lc-elc/20261108T162707Z-before-upgrade`（归档 sha256 `35d17e9e…9ce4d`）。回滚点：备份内旧两模块源码 + `-u lab_catalog,lab_team_web`；需要数据回滚时用同目录 `db.dump`/`filestore.tar.gz`；源码清单指回 `source-server-lcsc-openapi-20261108.json`。
- 交接：[2026-11-09 网页端采购入库按需抓取入口](../handoffs/2026-11-09-web-receipt-fetch-entry.md)。

## 第二轮（2026-11-09 下午）：无感接续 + 器件详情入口（19.0.1.2.3）

- **用户追加要求**："加上而且我需要无感搜多不要每次都需要我专门点一下搜索立创商城"；"关键词检索你可以先检索本地再检索立创真正选择后你快速把信息拉下来"；以及抓到器件后手机端看不到完整详情。
- **实现**：
  - `receipts.js`：本地零结果 + `fetch_suggestion` → 输入静默 800ms 后自动 `startFetch`（关键词列候选、精确码直接抓资料）；同一关键词本页只自动一次（`state.autoFetched`）；输入改变 `cancelAutoFetch()`；抓取中/建袋锁定不触发；原空态按钮保留为失败后的显式重试。
  - `receipts.js` + `workflow_receipt.xml`：已选物料卡片新增「查看器件详情（参数 / 文档 / 档案与流水）」，新标签页 + `rel="noopener noreferrer"`；冒号保留（`/lab/items/lcsc:C54110218`），无 `item_key` 时隐藏。
- **版本/清单**：`lab_team_web 19.0.1.2.3`（manifest、`lc_version`、`components.json`、`test_entry_contract.py` 同步）；active 清单 `source-server-web-fetch-entry-20261109-r3.json`（274 文件，tree `106ef58b…e15b4819`，清单 sha256 `0ef9d7c7…c835067`）。
- **测试**：`test_p3_ui_consistency.py` **19/19**（新增 `ReceiptSeamlessFetchTest` 4 条）；`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_combobox.mjs` 23/23、`test_workflow_core.mjs` 19/19、`node --check receipts.js` OK、`repo_check.py`/`generate_routes.py --check`/`git diff --check` 均 exit 0。
- **部署**：2026-11-09 13:58 CST，`upgrade_modules.sh --code-dir ~/lc-deploy-teamweb-20261109T135736Z/mods --modules lab_team_web`；备份 `/var/backups/lc-elc/20261109T055838Z-before-upgrade`（归档 sha256 `3a7cafb6…949b87`）；`-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_team_web|19.0.1.2.3|installed`；服务 active、`/web/login` 带库头 200、静态 `receipts.js` 与视图 arch 均为新内容、日志 0 错误。第一次执行在停服换码后因暂存 `ops/` 缺少 `lc_archive`/`lc_service`/`odoo_restore` 而中止，补齐依赖后原样重跑成功（数据未回滚）。
- **仍未验证**：手机端自动接续的真实手感、`not_found`/失败态、限流（5 个进行中 / 每小时 20 次）与"锁被占用退回 cron"；自动关键词查询会提高立创调用量。

## 第三轮（2026-11-09 14:21 CST）：抓取中改词丢失自动接续（19.0.1.2.4）

- **用户反馈**：截图输入 `STM32G434` 未找到后改成 `STM32G437`，页面仍要求自己点「立即从立创商城抓取」。根因：上一笔抓取未结束时计时器触发，`state.fetching` 为真即丢弃计时器，结束后没有补排。
- **修正**：`scheduleAutoFetch` 在抓取中记 `state.autoFetchPending`；`startFetch` 收尾调用 `resumeAutoFetch()` 按当时输入与建议补排（仍只自动一次、仍要求输入一致）；`finishFetch(result, query)` 先比对当前输入，慢返回的旧结果不再覆盖已改输入或弹旧候选。
- **版本/部署**：`lab_team_web 19.0.1.2.4`；备份 `/var/backups/lc-elc/20261109T062109Z-before-upgrade`（归档 sha256 `898baf77…34aa9a`），`-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_team_web|19.0.1.2.4|installed`；静态 `receipts.js` 86,734 B 含新逻辑；日志 0 错误。
- **测试**：`test_p3_ui_consistency.py` **21/21**（新增：抓取中改词要补排、旧结果不得覆盖输入）；`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、Node 23/23 与 19/19；`repo_check`/`generate_routes --check`/`git diff --check` 均 exit 0。
- **清单**：active `source-server-web-fetch-entry-20261109-r4.json`（274 文件，tree `63c10f8c…a2b11fc`，清单 sha256 `a940dc97…baf7fa`）。

## 第四轮（2026-11-09 17:21 CST）：抓取慢的根因——IPv6 不可达（19.0.2.0.15）

- **用户反馈**：`STM32F427IIH6` 立创明明有（C503072），页面仍显示手动按钮，按「解析料号」还报"找不到该对象"。
- **定位**：生产 `lab_catalog_fetch_request` id 13 状态 `queued`、留言"抓取时间预算已用完"——自动抓取确实发了，但 15 秒预算内只走完搜索。生产机计时 `lcsc_remote.search_products` 单次 **120.6 秒**，同一时刻 `curl` 仅 0.7 秒；`getent ahosts wmsc.lcsc.com` 全是 CloudFront AAAA，本机 IPv6 到 CloudFront 不可达，urllib 按顺序逐条尝试（每条 15 秒）把预算和 cron 都拖死。"找不到该对象"是随后手动「解析料号」对关键词的正常 NOT_FOUND 呈现。
- **修复**：`tools/lcsc_remote.py` 新增 `_IPv4HTTPSConnection`（只解析 IPv4，证书仍按域名 SNI 校验）与 `_open_response` 测试接缝；读响应改为分块并在块间核对预算（慢速吐数据也会在预算处中止）。生产实测搜索 0.55s / 详情 0.48s / 中文页 0.36s。
- **版本/部署**：`lab_catalog 19.0.2.0.15`；备份 `/var/backups/lc-elc/20261109T092100Z-before-upgrade`（归档 sha256 `6bc3cf32…c701c`），`-u lab_catalog` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_catalog|19.0.2.0.15|installed`；服务 active、`/web/login` 带库头 200。
- **测试**：`test_lcsc_remote.py` **25/25**（新增 IPv4-only 断言，请求层改为替换 `_open_response`）、`test_lcsc_openapi.py` 23/23；`repo_check`/`generate_routes --check`/`git diff --check` 均 exit 0。
- **清单**：active `source-server-web-fetch-entry-20261109-r5.json`（274 文件，tree `18007fa1…14b48`，清单 sha256 `460ff5ae…f5e4`）。

## 第五轮（2026-11-09 22:28 CST）：中文页风控下的详情链路彻底修复（19.0.2.0.17 / 19.0.1.2.7）

- **用户反馈**：截图 `F407IGH6` 候选面板与"没有匹配的器件 / 立即从立创商城抓取"同时出现；选定 `C503071` 后点「查看器件详情」只有本地档案、没有参数；原话"我的器件详情呢""修BUG要彻底不要每次都等我去说你的的逻辑问题"。
- **定位**：`lab_catalog_fetch_request` id 16（`C503071`）3 次 `failed`——中文详情页 `item.szlcsc.com` 返回阿里云 WAF 验证页（`aliyun_waf_aa`/`renderData`）。旧流程把中文页当唯一数据源，验证页一出整条失败，官方 SMT 已给出的 13 条参数一起被丢掉；网页入库建的"立创物料 C503071（待补全）"档案没有 binding 行，也不会被回填。
- **修复**：
  - `lab_catalog_fetch`：中文页 `verification_page` 且官方有数据 → 官方事实入库（分类按官方 `componentType` 名称匹配，退回 `parentCatalogId`），请求 `done` 并注明；无官方数据仍可重试。新增 `_enrich_stub_templates()` 回填占位档案（只填空字段）。`_handle_remote_error` 文案改写。
  - `lab_catalog_item`：新增 `_template_ids_by_codes()`（绑定表 ∪ 档案自身 C 码），搜索/详情都能看到无 binding 档案的库存/袋/流水。
  - `receipts.js`：`renderCandidates`/`startFetch` 收起下拉；`normQuery` 与服务端同口径；候选点击在建袋锁定时只提示；`done` 无 item_key 不解析旧输入。
  - `pages.xml`：详情页 `local_only` 显示"资料还没有从立创抓取"说明。
- **生产验证**：`request 18 done`；`lab_catalog_item` 695220 = `STM32F407IGH6 / ST / UFBGA-201 / 13 参数 / 单片机(MCU/MPU/SOC)`；占位档案 #10 名称/型号/封装已回填；`detail('lcsc:C503071')` → 参数 13、`lab_template_ids=[10]`。
- **版本/部署**：`lab_catalog 19.0.2.0.17`、`lab_team_web 19.0.1.2.7`；四次部署备份 `20261109T141243Z / 142322Z / 142603Z / 142847Z`（filestore sha256 `4ac71554…`、`7dfc749b…`、`85cd4dea…`、`da583eee…`），每次 `-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback；服务 active、`/web/login` 带库头 200、日志 0 错误。
- **测试**：`test_catalog_fetch_inline.py` +3、`test_catalog_param_search_orm.py` +1、`test_p3_ui_consistency.py` **27/27**、`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_lcsc_remote.py` 25/25、`test_lcsc_openapi.py` 23/23、Node 23/23 与 19/19、`node --check` OK；`repo_check`/`generate_routes --check`/`git diff --check` 均 exit 0。两条新增 Odoo ORM 用例本机无数据库未跑，已用生产 `odoo shell` 复核等价断言。
- **清单**：`…-r6.json`、`…-r7.json`（tree `1f509b6d…54e6da`）、`…-r8.json`（tree `03811a23…7afcf56`）、`…-r9.json`（274 文件，tree `4144e419…c9b6`，active）。
- **未完成**：不破解立创验证码（中文分类细分/PDF 等 WAF 解除）；官方兜底未做浏览器手测；`C8734` 旧失败请求未重跑；未提交/推送。
