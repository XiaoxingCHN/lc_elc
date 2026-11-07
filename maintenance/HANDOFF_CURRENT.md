# 当前维护交接：2026-11-06 器件库按需抓取已部署生产（2026-11-06T14:29–14:31Z）

最新：[按需抓取交接](handoffs/2026-11-06-catalog-on-demand-fetch.md)｜[任务](tasks/2026-11-06-catalog-on-demand-fetch.md)。`lab_catalog 19.0.2.0.10` **已部署**（同批 `-u` 还覆盖 `lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2`；`lab_team_web 19.0.1.2.1` 未参与），`-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback。备份 `/var/backups/lc-elc/20261106T142949Z-before-upgrade/`（`db.dump` 118,970,696 B / `40863d50…3ba0d66`；`filestore.tar.gz` 12,819,190 B / `5b9e5d42…a3f5fc0`；旧三模块源码在同目录）。升级脚本仍把 `/web/login` 的 303 判为失败（既有缺陷，不是故障）：独立复核带 DB 头 200、`odoo.service` active/enabled。`ir.cron`「器件库：处理在线补抓队列」（id 25，每 1 分钟）自 2026-11-06T14:31:16Z 起每约 62 秒运行，至 2026-11-07T13:11Z 共 1356 次、0 失败、队列为空；Odoo 日志同期 0 条 ERROR/CRITICAL/Traceback。客户端源码仍 `1.2.0+7`，`flutter test` **326 passed / 5 skipped / 0 failed**、纯 Python 15/15。DB 行已核对（2026-11-07T13:17Z）：四模块 `installed`，`lab_catalog_fetch_request` 表与 7 个索引含部分唯一索引 `lab_catalog_fetch_active_uniq`（`state IN (queued,resolving,fetching)`），`lab_catalog.ir_cron_lab_catalog_fetch` → `res_id=25` 与运行中的 job 25 一致；行数统计待 `verify_deploy2.sh`。**未做真实网络端到端（三个目标料号）、未构建客户端包、未冻结 source manifest。**

## 此前维护交接：2026-11-06 Flutter Liquid Glass 三端候选构建（未发布/未部署）

[三端候选构建交接](handoffs/2026-11-06-client-glass-candidates.md)｜[构建任务](tasks/2026-11-06-client-glass-candidates.md)。客户端 `1.2.0+7` 冻结源保持 177 文件一致。Windows 与 Linux 完整候选包已生成，主会话重算 SHA256 与归档完整性一致；Android 因 16 项 Gradle/Maven 运行时依赖无法离线解析而 blocked，**没有 APK**。三端 Flutter 测试均 319 passed / 5 skipped / 0 failed。Windows 原构建脚本两次失败后由隔离生成目录的私有 CMake 适配完成，不记为原脚本全链通过。真实 GUI、业务、OS 安全存储、扫码、实体打印和性能未验证。候选包只在 Git 排除的 `F:/lc_elc/local/build/`；未发布、部署、提交或推送。

## 此前维护交接：2026-11-06 Flutter Liquid Glass 源码候选（未发布/未部署）

最新：[Flutter Liquid Glass 交接](handoffs/2026-11-06-client-liquid-glass.md)｜[基础层任务](tasks/2026-11-06-client-glass-foundation.md)｜[业务屏任务](tasks/2026-11-06-client-glass-screens.md)｜[客户端冻结源](registry/source-client-liquid-glass-20261106.json)。客户端 `1.2.0+7` 采用深色玻璃 + 荧光绿，保留业务结构、路由、参数搜索、待入库筛选与登录/更新生命周期。真实模糊仅用于 chrome 与浮层，内容卡片无模糊；A4 白底黑字。Flutter 测试 **319 passed / 5 skipped / 0 failed**，分析 **0 error / 0 warning / 118 info（exit 1）**；已查看登录、目录、详情、两阶段入库和 A4 共 6 张离屏 PNG。新客户端源清单 177 文件、tree `a19e0ddf…da1d0e4e`，已激活。**未构建/发布安装包，未部署生产，未提交/推送；真机、读屏、实体打印未验证。** `repo_check` 的客户端冻结已通过，但全仓仍有另一项服务端源码晚于 active r2 的冻结差异，详见交接。

## 此前维护交接：2026-11-03 P3 Web 生产部署完成（r3 已在生产生效；公网回归通过）

**模型政策（2026-11-02 用户指令，长期有效）**：禁用来自 Codex 的所有模型，后续只允许使用 DeepSeek 模型；不得唤醒 root/Codex 桥、不得派发 GPT/codex 系子代理，接手代理按此执行。

最新（2026-11-04）：[参数关键词搜索交接](handoffs/2026-11-04-receipt-parameter-search.md)｜[任务](tasks/2026-11-04-receipt-parameter-search.md)｜[冻结源 r2](registry/source-server-param-search-20261104-r2.json)。实现分支 `feat/receipt-param-search`（基线 `main` `c808065`），版本 `lab_inventory 19.0.1.1.0` / `lab_catalog 19.0.2.0.6` / `lab_workflow 19.0.2.0.1` / `lab_team_web 19.0.1.2.1`。已实现参数归一化（含 `10Ω=10R`、`4R7`、`R1`、`4k7`、`1k5`、`100nF=0.1uF`）、本地/目录参数检索、分词 AND、待入库 query/state/total、Web 筛选与“查看全部结果”。本机可执行的纯逻辑/JS 测试 8/8、21/21、19/19 通过，`py_compile`/`generate_routes --check`/`git diff --check` 通过；**ORM/HttpCase、真实浏览器、Flutter 未验证**；`repo_check` 仅剩既有 `frozen-source:client`（`clients/app/t.obj`）错误。**2026-11-04T12:59–13:09Z 已部署到生产**：四模块升级 exit 0、服务 active、参数回填 695,217/695,217 并 ready；备份与旧源码见 `/opt/odoo/backups/20261104T125944Z-before-upgrade/`。未提交/推送；未导入；未做真实业务写。

最新（2026-11-03）：[生产部署交接](handoffs/2026-11-03-p3-production-deploy.md)｜[任务](tasks/2026-11-03-p3-production-deploy.md)｜[冻结源 r3](registry/source-server-web-ui-20261102-r3.json)｜[候选包登记 r3](registry/artifact-server-web-ui-20261102-r3.json)。
**r3 已于 2026-11-03 00:16–00:36Z 部署到生产** `192.168.31.105`（DB `LcHardwareHouse`）：`lab_team_web 19.0.1.1.0 → 19.0.1.2.0`（`-u lab_team_web`，`UPGRADE_EXIT=0`、错误行 0），
`lab_site` 仅权限归一（内容=冻结）、`lab_theme` 仅由 `deploy-theme.sh` 换冻结版，`lab_workflow 19.0.2.0.0` / `lab_catalog 19.0.2.0.5` / `lab_inventory 19.0.1.0.0` 未变；
一致备份 `/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`（`db.dump` 110,944,415 B / `40c76d0679d2a7915ba5857d5009c291c18f17fdf239803a484246228993ba19`、
`filestore.tar.gz` 12,819,190 B / `305b841f50f0b3417b120a3ff0b52e61800d533f3a2337418f3114a2d85abfda`（611 条目）、`store_fname` 139/140/缺失 0、`service_was_active=false`），
源码回滚快照 `/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`；菜单 before 234 行 → `removed 0 / added 1 / changed 12 / match 1`（新增 `lab_team_web.menu_legacy_label_wizard`，id 382，12 条仅 action 变）；
网关切到 release `/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z`（include sha `34289f2612c9adb460c787c6765f72525bd1db5359eff515164cbb1ab42508ef`，回滚点 `bb3164e5…`，allowlist pages 24 / apis 5 / legacy 13）；
`50-verify` **PASS 129 项 / 0 失败**、`90-close` **completed**（`DEPLOY_COMPLETED_UTC=20261103T003543Z`、`DEPLOY_FACTS_PROVEN=43`、服务 active、HTTP login 200）；
公网回归通过（`/ 200`、`/login 200`、`/team/scan 303`、`/team/lab/receipts 303`、旧 action 303、`/web/login 404`、写方法 403、`POST /lab/api/catalog/search 415`、`workflow_core.js` sha 一致）；
最终部署包 **93,486 B** / `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / 27 条目 / FROZEN 18 / shipped 15 / `bundle-meta` freeze `f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`（91,307 B / `8215a795…`、91,586 B / `e453db43…`、92,857 B / `085945a2…` 为部署前中间包，非最终）；
证据归档 `local/web-ui-implementation/evidence/production/p3-deploy-evidence-20261103.tar.gz`（21,344 B / `53433008c3bb6ae48da899105e64d2fd6e814b24a47d5b2617a3fe9cdc8069b5` / 20 条目）；DPAPI blob 已删除（`BLOB_DELETED`）；
**未做**：commit/push（分支 `codex/receipt-search-feedback` 仍在工作区）、客户端包（`1.1.3+6` 不变）、真实业务写、DNS/Docker/其他服务、回滚演练、CI。

部署前时点（2026-11-02）：[本轮交接](handoffs/2026-11-02-web-ui-unification-implementation.md)｜[任务](tasks/2026-11-02-web-ui-unification-implementation.md)｜[冻结源 r3](registry/source-server-web-ui-20261102-r3.json)｜[候选包登记 r3](registry/artifact-server-web-ui-20261102-r3.json)。`lab_team_web 19.0.1.2.0` / `server-ops 2026.11.02.1` 已定版（`lab_workflow 19.0.2.0.0` 未改，磁盘 `__manifest__.py` 与 `components.json`、生产 DB 记录一致）；r3 在 r2 冻结点之后又修两处深色视觉缺陷，只改 `server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css`——`team.css:38-41`（`body.lc-body` 令牌块内）新增 `color-scheme: dark`（原生滚动条 / select / input 按深色 UA 渲染），`team.css:2181` 的 `.lc-combobox-pop` 由 `max-width: min(540px, calc(100vw - 28px))` 改为 `min(780px, calc(100vw - 28px))`（1440 时弹层与 770px 输入框同左同宽，窄屏仍受视口约束，注释补句 `team.css:2166`），并补齐了 r2 时 3 项 blocked；隔离实例在 r3 源码上 `-u` 后 **52 tests、FAIL: / ERROR: 计数 0**（RUN=`upgrade-keepdb-20261102T134429Z`、`ODOO_EXIT=0`），DB 实测 `lab_team_web=19.0.1.2.0`（installed）；r3 源清单 **258 文件**、treeSHA `95baea916fbe4c8504e9a3bc2ce1c18235cf53689373d323b32d914d1e1fe8de`（清单 sha256 `2192a3545ebbe2ea3293072d1cc971a8deab1e524a4e39c20503d760888a7224`，已 `--activate`，旧 10-28、r1、r2 清单均未改写）；r3 源码候选 ZIP（**13,251,571 B**、sha256 `3800e2a210a1c0fdad562112b4682ed02d83ae466f678443bfafb1923a02d4f7`、259 条目）与 r3 部署包（**91,307 B**、sha256 `8215a7958fe227452f19f3458a149509169cfd3cf26fadfbd6ecad82b6e8f02d`、27 条目 / `FROZEN-20261102.sha256` 18 条 / `bundle-meta` freeze_sha256 `93b07b02…` / `params.env` 已指向 r3）已构建并登记；真实浏览器证据（r3 源码重跑）：下拉截图 **53/53 all pass / 0 fail**（1440 视口 input=pop=770px、gap 0，375 视口 input=pop=277px 且 `document.scrollWidth=375`，5 个用例 `colorScheme` 实测均为 `dark`），全站真实套件 **55 项 55 pass / 0 fail / 0 blocked**（exitCode 0；静态袋 41、`real-receipt-multi-create-lock`、`real-receipt-legacy-precondition` 三项已补证）；另有工具侧证据缺陷（非产品缺陷）：静态袋页与动态袋详情共用测试 id `real-bag-detail-<1440|375>` 导致截图互相覆盖，已用 `--only=pages` 复跑（35 项 32 pass / 0 fail / 3 条主动跳过标记）留下静态袋 41 截图，本轮未改工具源码；**r2（tree `aad3eacd…` / ZIP 13,251,445 B / bundle 91,273 B）与 r1（tree `634d1893…` / ZIP 13,251,270 B / bundle 91,154 B）已被 r3 取代，保留为历史，不得部署**；r3 收尾 `python tools/repo_check.py` = **PASS / 52 项 / 0 errors / 1 既有 warning（`production-py312-rebuild`）**，证据 `local/web-ui-implementation/evidence/repo-check-20261102-r3.json`；`git diff --check` 0。客户端侧：Flutter 收据/待打印入库页内联搜索建议已完成并冻结——`maintenance/registry/source-client-receipt-search-feedback-20261102.json`（`file_count=169`、tree_sha256 `ee5adebdaa0c3e81dfa616b8dc55243d6419790422b93b010f9126f3aaa70072`、清单 sha256 `d703e507cd04bbe6bad648a3bf263b79d6626bf34ae77bba45cae88d6d37952f`），`active-sources.client` 已指向它，旧 `source-client-android-install-fix-final-20261019.json` 未改写（历史）；验证为 `flutter test` exit 0、295 passed / 5 skipped（5 skip 为既有需真实 Odoo 账号的 live 用例），新测试文件 20/20，`flutter analyze` exit 1 但 0 error / 0 warning / 119 既有 info，无 emulator/真机运行（receipt 页无专门提交锁 widget 测试），客户端版本仍 `1.1.3+6`、未构建/发布 APK。截至该时点：未提交、未推送、未部署（2026-11-03 已完成生产部署，见顶部与 `maintenance/handoffs/2026-11-03-p3-production-deploy.md`）。生产只读探测（历史，2026-10-28 轮）：DB `team_web 19.0.1.1.0` / `workflow 19.0.2.0.0`、mapping 表存在、旧静态资源与 10-28 冻结一致、quant 2 行、附件 423 / filestore 139 文件；部署仍被网络阻塞：2026-11-02 本轮 `192.168.31.105` ping 100% 丢失、TCP 22/8069 不可连、本机同网段 `192.168.31.213` ARP 无表项，尚未开始第 0 步；主机恢复在线后按 `local/web-ui-implementation/deploy-plan.md` 继续，`local/build/web-ui-20261102/script-sha-map.json` 存有 14 个 remote 脚本 sha（与 FROZEN 一致）。 【2026-11-03 更新】该候选随后于 2026-11-03T003543Z 部署完成（DEPLOY_STATE=completed、DEPLOY_FACTS_PROVEN=43、公网回归通过）；上文 91,307 B / 8215a795… 与「未部署」是部署前时点状态；最终实际部署包为 93,486 B / 34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a、bundle-meta freeze_sha256 f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b；详见上方 2026-11-03 段。

以下为此前 2026-10-28 P3 候选（结论同上轮；P3 生产部署未执行）：

[P3 正式交接](handoffs/2026-10-28-p3-web-workflows.md)｜[任务](tasks/2026-10-28-p3-web-workflows.md)｜[冻结源](registry/source-server-p3-web-20261028.json)｜[候选包登记](registry/artifact-server-p3-web-20261028.json)。日常 Web 工作流候选完成；250 个源文件与纯源码 ZIP 已逐文件核验登记；ORM 82、HttpCase 21、独立并发 6、浏览器主链 28 项通过；API 1 项与浏览器 3 个场景仍明确 blocked。日常 Web 工作流候选完成；250 个源文件与纯源码 ZIP 已逐文件核验登记。当前源码 ORM 82、HttpCase 21、独立并发 6、浏览器主链 28 项通过；API 1 项与浏览器 3 个场景仍明确 blocked，原 test-enable 并发模式因 Registry 锁 blocked，不能伪称全模式通过。repo_check 52/0，生产 cp312 恢复载荷 warning 保留。生产仍 P2，未部署；用户已授权将本轮 Git 更新推送到既有 origin 的 P3 功能分支，提交以远端分支为准；手机无 VPN、摄像头/实体打印、生产 Python3.12 等价仍未实测。主代理自建测试 PG 已按租约停止，合成证据保留。

以下为此前公网入口交接：

最新：[正式域名验收](audit/netlify-formal-domain-acceptance-20261027.md)。team CNAME已正确；实际Netlify公网端点正常SNI、证书与22项检查全部通过（经现有代理显式连接52.74.6.109，逐项要求Netlify Edge）。本机系统解析仍到NAS192.168.31.105，最初LAN200已排除。当前区域IP直连超时，官方默认75.2.60.5两次curl可信TLS/标记通过，表现有线路差异；未擅自改用户CNAME/代理/系统DNS。下一步请用户手机流量不挂VPN访问正式team并登录；默认netlify.app下用户此前已确认真实登录功能正常，不能冒充正式域名手机已测。来源与ZIP沿用2026.10.27.3；7882已停并保留证据，旧受保护16443入口暂保留。

以下为此前CNAME等待时点：

最新：[前端验收](audit/netlify-frontend-acceptance-20261027.md)。用户已确认真实账号登录成功、功能正常；Lead实际前端22/0。用户当前截图是可选Netlify DNS委派向导，需返回域名管理走外部阿里云CNAME，无需设置四条NS。正确记录team CNAME→rad-taffy-56e1ce.netlify.app，保留origin-team A。原别名已独立HEAD200确认有效。旧HTTP诊断7882已按精确PID/脚本路径停止、日志保留。待CNAME/Netlify自定义域名完成后验收正式team TLS和会话；来源/ZIP沿用2026.10.27.3，不覆盖。

以下为此前等待真实账号确认时点：

最新：[实际Netlify前端验收](audit/netlify-frontend-acceptance-20261027.md)。用户已更新rad-taffy-56e1ce并看到登录页；Lead实际前台IPv4 HTTPS22/0，页面、静态资产hash、默认拒绝、Origin与private/no-store均通过。尚未用真实账号，下一步用户登录→刷新保持→退出后/lab回登录；确认后再绑定team自定义域名/改CNAME。来源与ZIP沿用2026.10.27.3冻结源，不改旧产物。

以下为此前部署包等待上传时点：

最新：[Netlify HTTPS交接](handoffs/2026-10-27-netlify-https-origin.md)｜[审计](audit/netlify-https-origin-20261027.md)。origin-team证书21:14签发，IPv4 bore16444→回环TLS18445已部署；79项真实本机、15项合成、最新公网正常SNI22项均通过，自动重连通过。新包local/build/netlify-https-origin-20261027/netlify-odoo-https-20261027-v1.zip待上传现有rad-taffy-56e1ce项目Deploys，Netlify端业务与真实账号尚未验收。team当前A已为159.223.110.159，前端通过后再绑定自定义域名/改CNAME；暂不让用户重复改DNS。运维2026.10.27.3，新源source-server-netlify-https-origin-20261027.json（211文件）。

以下为此前证书等待时点：

最新：[HTTPS回源准备](audit/netlify-https-origin-20261027.md)。用户站点rad-taffy-56e1ce.netlify.app已部署，固定文本回源通过；Lead web_fetch及本机IPv4无代理独立复核200/完整标记/no-store。新域名origin-team.l-creation.club使用独立证书名lc-elc-netlify-origin，Certbot DNS-01已启动，等待用户添加origin-team A和_acme-challenge.origin-team TXT。挑战有效等待窗口至2026-10-27 21:33:40 +08，root状态目录/var/lib/lc-elc-netlify-origin/20261027-a1。TXT值以当次challenge-public.json为准，不存Git。先不改team解析。正常HTTPS业务回源、Host/Origin/缓存适配及真实账号尚未完成。

以下为此前测试包准备时点：

最新：[Netlify回源测试审计](audit/netlify-bore-probe-20261027.md)。已准备local/build/netlify-bore-probe-20261027/netlify-bore-test-20261027.zip，用户只需解压并拖入新的Netlify项目，返回netlify.app URL。诊断bore159.223.110.159:7882只返回固定文本，至2026-10-28 20:44自动停止；Node语法、ZIP完整性、实际中继响应已验证。**Netlify本身尚未部署验收；暂不修改阿里云DNS**。正式方案需独立回源域名/证书及Host/Origin/会话缓存适配，不能直接宣称当前16443回源可用。

以下为此前bore服务器部署时点：

最新：[网关部署交接](handoffs/2026-10-27-bore-public-ipv4-deploy.md)｜[审计](audit/bore-public-ipv4-deploy-20261027.md)。IPv4中继159.223.110.159:16443、回环白名单TLS网关18443与systemd自动重连已部署验证；内网vhost不变。当前等用户将阿里云team A改为159.223.110.159，再继续普通浏览器正常SNI/真实账号验收。无SNI严格校验证书诊断19/0不等于浏览器验收通过。运维2026.10.27.2，新source-server-bore-public-ipv4-20261027.json。

以下为此前网络复核时点：

最新：[网络复核交接](handoffs/2026-10-27-bore-ipv4-proxy-recheck.md)｜[审计](audit/bore-ipv4-proxy-recheck-20261027.md)。bore经现有VPN/HTTP代理可访问：真实IPv4中继+合成服务，4种代理路径HTTP200与完整内容，2种本机直连超时；不再宣称bore不可用或境外全部封锁。测试隧道已停止，未改生产配置；正式Odoo公网白名单入口仍待部署。

以下为此前P2上线时点：

最新：[本轮交接](handoffs/2026-10-27-production-p2-deploy.md)｜[审计](audit/production-p2-deploy-20261027.md)。`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5` 已在生产 LcHardwareHouse 上线，服务 active、TLS 登录 200；库存与其它模块不变。新快照[source-server-production-p2-20261027.json](registry/source-server-production-p2-20261027.json)（202 文件，repo_check 52/0）。本轮修复了备份工具默认 data_dir 导致附件漏备的真实缺陷（已补备 139 个附件并加回归测试）。**公网仍未开通**：team.l-creation.club 仍指向内网 192.168.31.105，需真实公网节点+标准443+隧道登记。

以下为此前交接时点：

最新：[安装修复](handoffs/2026-10-19-android-install-fix.md)。Android1.1.2+5已发布，HTTP下载/签名/权限通过；用户已开未知来源仍失败，1.1.3+6已构建并发布（seq2），清单200与认证完整包/hash通过，修复合法缓存别名误拒并显示具体原生失败环节。安装入口尚未实机验收。

以下为此前交接时点：

最新：[器件选择与更新状态修复](handoffs/2026-10-19-receipt-picker-fix.md)。客户端1.1.2+5，修复真实打开选择弹层时的无限高度白屏，加入自定义入口和明确更新状态；Flutter272通过5跳过。服务端更新接口 **19.0.1.2.0已上线**，三端manifest204、库存数量不变；完整备份及只读验证见[部署交接](handoffs/2026-10-19-update-endpoint-deploy.md)。未发布stable更新包。

以下为此前更新器开发时点：

最新：[客户端更新器候选](handoffs/2026-10-19-client-updater.md)。client1.1.1+4、server候选19.0.1.2.0；启动/恢复检查、验签下载与三端安装入口已实现并构建，真实安装与GUI回退待测。生产19.0.1.1.0未变，未发布stable清单，未推送本轮实现。当前源清单见active-sources。

历史上传：此前功能/生产交接已上传既有GitHub的 `codex/two-stage-receipt-plan` 分支（功能提交0716829）；[客户端自动更新方案](../docs/development/CLIENT_UPDATE_PLAN.md)已于方案阶段梳理；当前实现以顶部最新交接为准，见[本轮上传与方案交接](handoffs/2026-10-19-github-update-plan.md)。

最新交接见 [服务端已上线](handoffs/2026-10-19-server-deploy.md) 和 [原生候选包](handoffs/2026-10-19-native-candidates.md)。生产lab_workflow **19.0.1.1.0**、三模块installed、服务active/HTTP200，库存及袋记录数量未改变；完整备份、权限与标签检查已核验。部署工具保留旧模块位置缺陷已修复，最终服务端源指向opsfix清单，108项故障测试通过。客户端1.1.0+3三端候选包构建完成但未发布，Windows仅进程冒烟，三端界面、安全存储和实体扫码打印仍待验收。功能与隔离测试见 [两阶段入库实现](handoffs/2026-10-19-two-stage-receipt.md)。

以下保留归档交接背景，版本和完成事实指归档时点，不代替最新候选源记录。

## 工作根和规范

新工作根F:/lc_elc，原F:/lc_elc_workspace只作来源/历史，不再在旧源上改功能。先读README、AGENTS、CURRENT_STATE和ARCHIVE_REPORT。

## 版本

客户端1.0.1+2；Odoo inventory19.0.1.0.0/catalog19.0.2.0.3/workflow19.0.1.0.2；EDA3.0.3。当前源指针在maintenance/registry/active-sources.json，安装包与原始/维护源的关联在releases.json。

## 已完成

各当前组件/成品/离线载荷/历史明确分层，138000余条文件迁入记录逐项校验；原目录零删除。原WSL工具另导出4.4GB。Git未包含SDK、数据、安装包或私钥。最终纯Git空目录克隆四项检查通过。

## 下次从哪里开始

- 新功能/bug：任务模板→分支→对应唯一源→测试→新冻结--activate→发布，旧manifest/包不覆盖。
- 待处理的真实缺口：KNOWN_GAPS，尤其生产完整cp312 wheelhouse、离机备份、npm离线缓存验证和部分原生实机验收。
- 凭据不在仓库。Android匹配密钥在local/private/signing，公开证书registry/android-signing.json；不要使用证书不同的旧WSL默认key。
- 本次没有部署、重启服务、写生产库存或恢复采集；生产仅限定只读核对。GitHub私有远端/推送需由所有者给URL再执行。

## 证据

maintenance/audit保存新路径测试与克隆检查；evidence保存精选历史验收；完整复制/处置映射在local/manifests，原始构建/一次性脚本在local/archive。不可把已提交或历史通过直接称当前新包验收通过。
