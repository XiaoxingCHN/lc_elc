# 维护交接：2026-11-09 网页端「采购入库」按需抓取入口

## 用户目标与已确认边界

用户在手机浏览器打开 `team.l-creation.club` 的「采购入库」，输入 `tlv77` 时只看到"没有匹配的器件"，没有客户端那样的"到立创商城抓取"入口（2026-11-08 23:02 截图）。目标：同一位置可一键查候选/抓取，抓到后沿用既有解析与建袋流程。用户随后明确要求"部署到生产"。

边界：只补器件资料（`lab.catalog.item/param`），不写产品/`stock.quant`/`stock.move`，不自动选档案、不自动建袋；关键词仍不可直接抓详情；不改客户端契约与既有路由。

## 当前权威源码、分支和版本

- 分支 `feat/receipt-param-search`，worktree `read-tomc-memory-56e7a2`。
- `lab_catalog 19.0.2.0.17`（`server/ubuntu22.04/odoo_addons/lab_catalog/__manifest__.py`）
- `lab_team_web 19.0.1.2.7`（`.../lab_team_web/__manifest__.py`，`controllers/common.py` 的 `lc_version` 同步）
- `maintenance/registry/components.json` 已同步；`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2` 未改。
- active server 清单：`maintenance/registry/source-server-web-fetch-entry-20261109-r9.json`（274 文件、tree `4144e419199a8545d34a94051a0ccd9923b55ef8692e17084e323b65d9b8c9b6`）。`…-r6.json`、`…-r7.json`、`…-r8.json`、`…-20261108.json` 与 `…-r2.json` 等更早清单保留不改写。

改动集中在：
- `lab_team_web/static/src/js/pages/receipts.js`：保存 `fetch_suggestion`（只对当前输入有效）、空态 `emptyAction` 按钮、`startFetch()` → `catalogFetch`（`sync:true`，30 秒超时）、`pollFetch()`（仅 `queued/resolving/fetching`，1.5 秒 × 40）、`finishFetch()`（`done` 收敛为 `lcsc:Cxxxx`；`candidates`/`not_found`/`failed` 分别呈现）、候选面板、输入变化即作废旧建议。
- `lab_team_web/controllers/common.py`：登记 `catalogFetch` / `catalogFetchStatus`；修正 `lc_version`。
- `lab_team_web/static/src/css/team.css`：候选面板与空态按钮样式（原按钮样式只在 `[data-kind="error"]` 生效）。
- `lab_catalog/tools/lcsc_remote.py`：`MIN_KEYWORD_LEN` 6 → 5（仍要求含字母），`controllers/catalog_api.py` 文案同步。
- `server/ubuntu22.04/upgrade_modules.sh`：新增 `--modules`（默认 `lab_inventory,lab_catalog,lab_workflow`），原来无法把 `lab_team_web` 随批部署。

## 已完成工作与实际证据

纯逻辑/契约测试（本机，未联网）：

- `python -I .../lab_catalog/tests/test_lcsc_remote.py` → 24 tests OK，exit 0（门槛用例改为 `TLV9` 拒绝、`TLV90` 放行）。
- `python -I .../lab_catalog/tests/test_lcsc_openapi.py` → 23 tests OK，exit 0。
- `python -I .../lab_team_web/tests/test_p3_web_contract.py` → 28 tests OK；`test_p3_ui_consistency.py` → 15 tests OK；`test_entry_contract.py` → 11 tests OK（修正 `lc_version` 前有 2 条失败）。
- `node .../lab_team_web/tests/test_combobox.mjs` → 23/23 passed（新增 2 条 `emptyAction` 用例）；`test_workflow_core.mjs` → 19/19 passed；`node --check .../pages/receipts.js` → exit 0。
- `python -I tools/repo_check.py` → exit 0；`python -I tools/generate_routes.py --check` → exit 0（94 条路由，无新增）；`git diff --check` → 0。

生产部署（用户本轮授权"部署到生产"）：

- 备份 `/var/backups/lc-elc/20261108T162707Z-before-upgrade`（归档 sha256 `35d17e9e…9ce4d`）。
- `upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261109/modules --modules lab_catalog,lab_team_web` → `-u` 退出码 0，0 条 ERROR/CRITICAL/Traceback。
- DB 复核：`lab_catalog|19.0.2.0.14|installed`、`lab_team_web|19.0.1.2.2|installed`；`lab_inventory`、`lab_workflow` 版本未变。
- `odoo.service` active；`/web/login`（带 `X-Odoo-Database: LcHardwareHouse`）200；部署后 10 分钟日志 0 条错误；服务端静态资源已含新增抓取代码。
- 部署脚本既有缺陷仍在：健康检查把 `/web/login` 的 303 判为失败，需独立复核带库头 200。
- 首轮部署失败于 `set: pipefail: 无效的选项名`：本机改脚本时写入了 CRLF，服务器 bash 解析失败；改回 LF 后成功，仓库副本已按 `.gitattributes` 保持 LF。

### 公网入口修复（同日 01:00 CST）

首次在手机上点击抓取返回 `INTERNAL_ERROR`。定位：`team.l-creation.club` 经 Netlify→bore→网关 `/etc/nginx/conf.d/lc-bore-netlify.conf`，其 allowlist 未登记 `catalog/fetch`、`catalog/fetch_status`，网关直接 404，请求没有到 Odoo（11-06 的两条 404 日志同因）。

- 新建 release `/var/lib/lc-elc-bore/releases/p3-web-20261109T010500Z`：从在用的 `p3-web-20261103T002651Z` 原样复制 `gateway.conf`/`bore-proxy-headers.conf`，只插入两条精确 `location`（规范化 diff = +2 行），include 路径同步改写。
- `nginx -t` 通过；`nginx -T` 中该 include 出现 2 次；`systemctl reload nginx` 后 active。公网 `POST /lab/api/catalog/fetch`、`/fetch_status` 均 200，Odoo 日志可见对应请求。
- 回滚点 `…/p3-web-20261109T010500Z/rollback/project-include.before`（原 include sha `34289f26…08ef`，新 `7e9566d6…2371`）；切回旧 release 或恢复该文件并 reload 即可。
- 仓库同步：`bore/nginx/bore-public-allowlist.conf.template`、`tests/test_p3_gateway_contract.py`（契约 34 OK / 13 skipped）；重新冻结 `source-server-web-fetch-entry-20261109-r2.json`（274 文件，tree `6946414f…3cb4c2`，清单 sha256 `fb459a5f…3469f9`）。
- 未改：直连公网网关 release `20261027-a2`（走 16443 直连时仍无这两个端点）、`lc-bore-public.conf`、DNS、Docker。

### 官方接口边界（生产实测）

- C 码抓取：官方 SMT `/smtOpenApi/smtComponent/selectComponentInfoByCodes`，`C17414` 已验证。
- 关键词候选：官方 `/lcsc/openapi/product/search/global` 对当前账号返回 `接口权限不足, 访问被拒绝`，因此 `tlv77`/`100nF` 仍走 LCSC 网页搜索接口（只读候选、不写库），选定 C 码后才进官方 SMT。

### 无感接续检索与器件详情入口（19.0.1.2.3，2026-11-09 13:58 CST 已部署）

用户追加要求：不要每次专门点"搜索立创商城"；关键词先查本地，真正选定候选后再快速拉资料；并要能看到抓到器件的完整详情。

- `receipts.js`：本地零结果且服务端给出 `fetch_suggestion` 时，输入静默 **800ms** 后自动 `startFetch`——关键词只列候选，精确 C 码/完整 MPN 直接抓资料。`state.autoFetched` 保证同一关键词本页只自动打一次；`onQuery` 里 `cancelAutoFetch()`；`state.fetching`/建袋锁定时不触发；空态按钮保留为显式重试。候选点选后才 `catalogFetch(code)` 拉完整资料（原链路不变）。
- `receipts.js` + `views/workflow_receipt.xml`：已选物料卡片显示「查看器件详情（参数 / 文档 / 档案与流水）」，`target="_blank"` + `rel="noopener noreferrer"`，URL 为 `LC.urls.item + item_key`，冒号按 `itemHref`/`quote_item_key` 约定保留（`/lab/items/lcsc:C54110218`）；无 `item_key` 时隐藏。
- 版本/清单：`lab_team_web 19.0.1.2.3`；active 清单 `source-server-web-fetch-entry-20261109-r3.json`（274 文件，tree `106ef58b…e15b4819`，清单 sha256 `0ef9d7c7…c835067`）；`…-r2.json` 保留。
- 测试：`test_p3_ui_consistency.py` **19/19**（新增 4 条静态契约）、`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_combobox.mjs` 23/23、`test_workflow_core.mjs` 19/19、`node --check receipts.js` OK、`repo_check.py`/`generate_routes.py --check`/`git diff --check` 均 exit 0。
- 部署：备份 `/var/backups/lc-elc/20261109T055838Z-before-upgrade`（归档 sha256 `3a7cafb6…949b87`）→ `-u lab_team_web` 退出码 0、0 条 ERROR/CRITICAL/Traceback → 起服务；DB `lab_team_web|19.0.1.2.3|installed`；`odoo.service` active；`/web/login` 带库头 200；Odoo 返回的 `receipts.js` 含 `scheduleAutoFetch`/详情链接逻辑（85,468 B）；`ir_ui_view` 中该视图 arch 含 `material-detail-link`；重启后日志 0 条 ERROR/CRITICAL/Traceback。
- **过程事故（已恢复）**：第一次执行在"归属修正/校验"处中止——暂存 `ops/` 只带了 `upgrade_modules.sh`/`lc_odoo_conf.py`/`odoo_backup.py`，漏了同目录的 `lc_archive.py`/`lc_service.py`/`odoo_restore.py`。当时服务已停止、代码已替换但未执行 `-u`。补齐三个依赖后**原样重跑**同一脚本（新备份 `20261109T055838Z`）成功；数据未回滚，未做 `-u` 以外的写操作。
- **仍未验证**：自动接续的去抖/取消手感、`not_found`/失败态、限流与"锁被占用退回 cron"；自动关键词查询会增加立创接口调用量。

### 19.0.1.2.4：抓取中改词丢失自动接续（2026-11-09 14:21 CST 已部署）

- 现象（用户截图）：`STM32G434` 返回"立创未找到"后改输 `STM32G437`，只剩手动按钮。根因：上一笔抓取未结束时 800ms 计时器触发，`state.fetching` 为真即丢弃，抓取结束后也没有补排。
- 修正：`scheduleAutoFetch` 在抓取中记 `state.autoFetchPending`；`startFetch` 收尾 `resumeAutoFetch()` 按当时输入与建议补排（仍只自动一次、仍要求输入一致）；`finishFetch(result, query)` 先比对当前输入，慢返回的旧结果不覆盖已改输入、不弹旧候选。
- 部署：备份 `/var/backups/lc-elc/20261109T062109Z-before-upgrade`（归档 sha256 `898baf77…34aa9a`）→ `-u lab_team_web` 退出码 0、0 条 ERROR/CRITICAL/Traceback → 起服务；DB `lab_team_web|19.0.1.2.4|installed`；静态 `receipts.js` 86,734 B 含 `autoFetchPending`/`resumeAutoFetch`。测试 `test_p3_ui_consistency.py` 21/21。清单 `…-r4.json`（274 文件，tree `63c10f8c…a2b11fc`，sha256 `a940dc97…baf7fa`）。

### 19.0.2.0.15：抓取慢的根因是 IPv6 不可达（2026-11-09 17:21 CST 已部署）

- 现象：`STM32F427IIH6`（立创 C503072）输入后仍只有手动按钮；查 `lab_catalog_fetch_request` id 13 为 `queued`/"抓取时间预算已用完"——自动抓取确实发出，但 15 秒内只走完搜索。
- 根因：`wmsc.lcsc.com`（CloudFront）的 AAAA 在本机不可达，`urllib` 按 `getaddrinfo` 顺序逐条尝试 IPv6，单次 `search_products` **120.6 秒**（同刻 curl 0.7 秒），同步预算立即耗尽、cron 也被拖住（当时同一行在 cron 里卡 5 分钟以上）。
- 修复：`lcsc_remote` 改用 `_IPv4HTTPSConnection`（只解析 IPv4，SNI 仍按域名）；读取响应分块并在块间核对预算，慢速吐数据也会在预算处中止。生产同代码实测：搜索 0.55s、详情 0.48s、中文页 0.36s（合计约 1.4s）。
- 部署：备份 `/var/backups/lc-elc/20261109T092100Z-before-upgrade`（归档 sha256 `6bc3cf32…c701c`）→ `-u lab_catalog` 退出码 0、0 条 ERROR/CRITICAL/Traceback → 起服务；DB `lab_catalog|19.0.2.0.15|installed`；`/web/login` 带库头 200。清单 `…-r5.json`（274 文件，tree `18007fa1…14b48`，sha256 `460ff5ae…f5e4`）。
- 部署后验证：原先排队的请求 12/13 在 09:23:35–09:23:50 由 cron 处理完（row 12 `not_found` 1 秒、row 13 `done` 14 秒）；`lab_catalog_item` 已收录 `C503072`（STM32F427IIH6，ST，UFBGA-176，13 条参数，`fetched_at 2026-11-09 09:23:49Z`）。此前每 120 秒被杀掉的 cron worker 超时不再出现。
- 用户看到的"找不到该对象（可能已删除或不属于当前公司）。"是随后手动「解析料号」对关键词的正常 NOT_FOUND 文案，不是抓取接口报错；抓取失败/排队有自己的中文提示。

### 19.0.2.0.17 / 19.0.1.2.7：中文页风控下的详情链路修复（2026-11-09 22:28 CST 已部署）

- 现象（用户截图 + 原话）：`F407IGH6` 候选面板与"没有匹配的器件 / 立即从立创商城抓取"同屏；选定 `C503071` 后点「查看器件详情」只有本地档案、没有参数/文档（"我的器件详情呢"）；随后要求"修BUG要彻底不要每次都等我去说你的逻辑问题"。
- 定位：生产 `lab_catalog_fetch_request` id 16（`C503071`）连续 3 次 `failed`，原因是中文详情页 `item.szlcsc.com` 返回阿里云 WAF 的 JS 验证页（响应含 `aliyun_waf_aa` / `renderData`）。旧流程把中文页当唯一数据源，验证页一出整条失败，官方 SMT 通道已经给出的名称/型号/品牌/封装/库存/价格/**13 条参数**全部丢弃；占位档案"立创物料 C503071（待补全）"又因为没有 binding 行不会被回填，详情页自然只有空参数。
- 后端修复（`lab_catalog`）：
  - `lab_catalog_fetch._run()`：`verification_page` 且官方有数据 → `_parsed_from_official()` 入库（分类优先官方 `componentType` 名称匹配，匹配不到退回 `parentCatalogId`），请求 `done` 并如实注明"中文详情页被立创风控拦截"；无官方数据仍按可重试错误处理。**不求解验证、不伪造 cookie。**
  - `_upsert_item()` → `_enrich_stub_templates()`：资料入库后回填该 C 编号下的占位档案（只填空字段，人工值优先），并 bump inventory revision。
  - `lab_catalog_item._template_ids_by_codes()`：`_decorate()` / `_detail_catalog_item()` 由"只查绑定表"改为"绑定表 ∪ 档案自身归一化 C 码"，让网页入库建的无 binding 档案也能显示库存/袋/流水。
  - `_handle_remote_error()` 的验证页文案改为"触发了访问验证（风控，不是实验室系统故障）…"。
- 前端修复（`lab_team_web`）：`receipts.js` 的 `renderCandidates()`/`startFetch()` 收起下拉（候选与旧空态不再同屏）；新增 `normQuery()`（去空白 + NFKC + 大写）让比较与服务端一致，`STM32 G437` 这类输入也能自动接续；候选点击在建袋锁定时只提示、不改输入、不抓取；`done` 但无 `item_key`（或已锁定）时不拿旧输入解析。`views/pages.xml` 的详情页在 `local_only` 时说明"该编号还没有从立创抓取资料"，不再是看不出原因的空参数页。
- 生产验证：用部署后的代码抓 `C503071` → `request 18 done`（官方兜底文案）；`lab_catalog_item` 695220 = `STM32F407IGH6 / ST(意法半导体) / UFBGA-201 / 13 条参数 / 单片机(MCU/MPU/SOC)`；占位档案 #10 名称已回填、`lab_mpn=STM32F407IGH6`、`lab_package=UFBGA-201`；`detail('lcsc:C503071')` → 13 条参数、`lab_template_ids=[10]`、无 `local_only`。
- 部署：`19.0.1.2.5`（备份 `20261109T141243Z`，filestore `4ac71554…b60c`）、`19.0.2.0.16 + 19.0.1.2.6`（`20261109T142322Z`，`7dfc749b…2ba8`）、`19.0.1.2.7`（`20261109T142603Z`，`85cd4dea…13c9`）、`19.0.2.0.17`（`20261109T142847Z`，`da583eee…26a1`）。每次 `-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback；服务 active、`/web/login` 带库头 200、日志 0 错误；DB 现为 `lab_catalog|19.0.2.0.17`、`lab_team_web|19.0.1.2.7`。
- 测试：`test_catalog_fetch_inline.py` +3、`test_catalog_param_search_orm.py` +1、`test_p3_ui_consistency.py` **27/27**（+5）；`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_lcsc_remote.py` 25/25、`test_lcsc_openapi.py` 23/23、`test_combobox.mjs` 23/23、`test_workflow_core.mjs` 19/19、`node --check receipts.js` OK；`repo_check.py`/`generate_routes.py --check`/`git diff --check` 均 exit 0。新增的两条 Odoo ORM 用例需数据库，本机未跑，已用生产 `odoo shell` 只读/单条写入复核等价断言。
- 清单：`…-r6.json`、`…-r7.json`（tree `1f509b6d…54e6da`）、`…-r8.json`（tree `03811a23…7afcf56`）、`…-r9.json`（274 文件，tree `4144e419…c9b6`，active）。
- 工具修正：`tools/release.py` 的 `write_text` 在 Windows 上会写出 CRLF，导致每次 `snapshot --activate` 后 `active-sources.json` 触发行长警告；改为 `write_text_lf()`（`newline='\n'`），并把当前指针文件规范回 LF。已生成的 manifest 未改写。
- 仍未做：不破解立创验证码（中文分类细分与 PDF 文档等 WAF 解除；官方兜底已含参数）；官方兜底路径未做浏览器端到端手测；请求 17（`C8734`）未自动重跑；未提交/推送。

## 剩余工作与阻塞

- **浏览器手测**：2026-11-09 01:0x CST 用户在手机端重试 `tlv77` 已正常（网关补齐后按钮→候选链路可用）。`not_found`/失败提示的真实呈现仍未验证。
- 未实测限流（每用户 5 个进行中 / 每小时 20 次）与"锁被占用 → 退回 cron → 前端轮询到结果"的路径。
- 关键词门槛降到 5 字符后，`100nF` 这类参数词也会发起一次候选检索（只读），需观察调用量与命中质量。
- 未提交、未推送（用户未要求）。
- 与本次无关但仍未做：Windows `1.3.1+9` 候选包进 `clients/windows/releases/`。

## 依赖和产物

- 无新增凭据；抓取使用服务器 `/etc/lc-elc/openapi.env`（`root:odoo 0640`）+ systemd drop-in `EnvironmentFile=-/etc/lc-elc/openapi.env`。凭据值不在任何文档或仓库中。
- 服务端清单：`maintenance/registry/source-server-web-fetch-entry-20261109.json`（已激活）。
- 部署代码目录：服务器 `/home/hbut/lc-deploy-20261109/modules`（临时目录，可按需清理）。

## 生产状态和回滚

- 生产当前：`lab_catalog 19.0.2.0.17`、`lab_team_web 19.0.1.2.7`、`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2`，均 `installed`。
- 回滚：用备份目录里的旧两模块源码覆盖 `/opt/odoo/addons`（或等效代码目录）后 `-u lab_catalog,lab_team_web`；需要连数据一起回滚时用备份 `db.dump` + `filestore.tar.gz`（恢复前校验绝对路径包含关系）。源码层面把 `active-sources.server` 指回 `source-server-lcsc-openapi-20261108.json`。
- 本次部署未改数据模型字段，也没有新增写入路径；`lab.catalog.item/param` 只在用户主动抓取时被补写。
