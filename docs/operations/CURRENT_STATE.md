# 当前状态与已知限制

## 2026-10-28 P3 自有 Web 日常业务：候选已冻结 / 构建 / 登记（**未部署生产**）

- **版本（已定版）**：`lab_workflow 19.0.2.0.0`、`lab_team_web 19.0.1.1.0`、`server-ops 2026.10.28.1`
  （`maintenance/registry/components.json` 已同步）。`lab_catalog 19.0.2.0.5`、`lab_inventory 19.0.1.0.0`、
  `lab_theme 19.0.1.0.2`、`lab_site 19.0.1.0.0`、`client 1.1.3+6`、`eda 3.0.3` **均不变**。
- **生产仍是 P2**：`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5`、`lab_workflow 19.0.1.2.0`；
  本轮**没有部署、没有 `-u`、没有重启、没有改 DNS/公网、没有读写生产库**。
- **范围**：`lab_team_web` 新增 13 个业务页面（两阶段入库、扫码、袋与追溯、标签、领用/归还、
  流水、库位、类别映射、管理、档案、账号），`lab_workflow` 新增 8 个 JSON-RPC 窄接口 + 新模型
  `lab.location.mapping` + `POST /lab/labels/pdf` + `GET /lab/scan` 303 到 `/team/scan`，
  并修复安全审查 S1（跨账号归还）/S2（畸形入参）/S3（`adopt_stock` 部分提交）/S4/S5。
- **已通过（有证据、可复核）**：
  - 隔离 ORM 业务 **82/82，0 fail 0 error**（**role wrapper 之后真实重测**：`backend-orm-final.log` + `backend-orm-final-evidence/`，同轮 HTTP 6 并发亦过）
  - 真实 HttpCase **21/21**，`failed=0 errors=0 p3_class_ran=1`，RC=0（`httpcase-r8.log`）
  - API 断言 **54 pass / 0 fail / 1 blocked**（total **55**；1 blocked 为 Origin 断言，本轮未提供 Origin URL，**不得改判 PASS**）（`runs/run.KOJbZY/verify-summary.json`）
  - Nginx 配置契约 1.26.2 **34/34**、1.30.6 **34/34**（`real-nginx-r2-results.json`；源码层，**未部署**）
  - 进程内并发独立 adapter **6/6**，负向自检 `detected=true`，exit 0（`concurrency-standalone-r3.json`；`test_enable:false`、`registry_cursor_patched:false`）
  - linux runner **17**（`runner-linux-r2.log` OK）、core **17/17**、XML **6/6**、JS 语法 **15/15**、路由表 **79** 条 `--check`
- **浏览器主链（R8）**：**31 步 28 pass / 0 fail / 3 blocked**，`unreached=0`
  （`runs/browser-20261028T065311Z/browser-p3.json`、`browser-r8.log`）。3 blocked 是
  `p3-cross-user-denied`、`p3-receipt-same-key-conflict`、`p3-unknown-outcome-retry` 的
  **DOM 场景未执行**；这三项由 API 断言 / HttpCase / core 独立覆盖，**不得写成 DOM 通过**。
  同轮真实 UI+服务端事实通过：两种 canonical key（`lcsc:`→裸 `C…`、`lab:` 走 `catalogDetail` 保具体档案）、
  建袋不增 quant、上架 +2、重复确认 quant 不变、领用 −2、部分归还 +1，role/materials/locations/mappings 管理页可用。
- **有效性前提（写报告不得省略）**：原 `--test-enable` 进程内并发套件因 **Registry 锁 blocked**
  （Probe 直接证实 `Registry._lock` 由主线程持有），wrapper 整体 **exit 1**，
  **不得称该命令全绿、也不得称"原进程套件通过"**；6 条并发断言由独立 process adapter 复用执行并全过。
- **测试口径**：`test_04` 的 quantity 为**精确匹配实际成功请求**（并发成功方可能是 10 或 11），
  **不得硬编码 10**；两管理员并发互撤后保留 1 名 manager，另一侧 `FORBIDDEN` 属合法权限撤销。
- **冻结 / 构建 / 登记（本轮完成）**：源快照
  [source-server-p3-web-20261028.json](../../maintenance/registry/source-server-p3-web-20261028.json)
  **250 文件**，treeSHA `fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43`，
  manifestSHA `0bfc1e3f581d90109c3e8942ff85cd9880a22ceac950d3c6fd93c0e90389c164`；
  `active-sources.server` 已指向该快照，**旧 manifest 与旧产物未覆盖**。
  候选包 `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`
  （13,186,981 B，SHA256 `9070800b65b8fa3c751b5d4ac0dc5d94910a97e27128adbd0ff4370c4549e564`，
  250 文件逐条 raw+normalized 校验、251 归档条目重读一致；构建环境 Windows 11 + Python 3.15 stdlib zip；
  **纯源码、无 runtime/数据库/凭据**；源码 ZIP **签名 N/A**）；登记
  [artifact-server-p3-web-20261028.json](../../maintenance/registry/artifact-server-p3-web-20261028.json)；
  构建摘要在同目录 `build-summary*.json`。
- **仓库检查**：`repo-final-r1.json` **52 项 PASS，exit 0**，唯一 warning 为 `production-py312-rebuild`；
  旧 active 源 hash 漂移已随冻结消除，已无 credential-scan 失败。
- **公网未开放**：`bore/nginx/bore-public-allowlist.conf.template` 已逐端点列出 P3 页面与写接口
  （源码，**未部署**）；`validation-plan.md` §9 的 G1–G9 未逐项宣称通过。精确门槛在 Nginx 层
  （源码已过 1.26.2 与 1.30.6 各 34/34）；Netlify 侧是 `/*` → `httpsOrigin/:splat 200!` 通配透传、
  `_headers` 亦为 `/*` 全局、无 functions，**不需要为 P3 逐路径增补**；公网联调与部署仍未做。
  合成测试库/证据已保留，Lead 自建项目 PG 已按租约精确停止，**无活跃测试服务**。
- **仍未关闭（不因本轮分项通过而消失）**：手机流量不挂 VPN 的正式域名实测、实体摄像头/扫码枪与
  实体纸张打印、真机安装升级；生产 **Python 3.12 与隔离 runtime 3.10.12 不等价**，生产 cp312
  wheelhouse 缺失、"完整离线恢复"未闭合；**一致 filestore 备份**未取得（P2 备份首份
  `filestore.tar.gz` 仅 59 字节空归档，139 个附件在独立 supplement 且与 `db.dump` 非同一时刻，
  `odoo_restore.py` 只解 `filestore.tar.gz`）。
- 详见 [交接](../../maintenance/handoffs/2026-10-28-p3-web-workflows.md) 与 [任务](../../maintenance/tasks/2026-10-28-p3-web-workflows.md)；
  发布预检计划与全部证据在本机 `local/build/p3-web-20261028/`（Git 排除，克隆后不存在）。

以下为此前时点记录，按各自日期理解。

2026-10-27正式team域名CNAME与可信HTTPS已确认，实际Netlify Edge22项通过；现有代理路径工作，本机系统解析仍到LAN，区域Netlify IPv4直连有超时，官方默认负载均衡75.2.60.5直连固定标记两次通过。**尚待用户手机流量无VPN在正式域名打开/登录确认**，不能承诺全网稳定；未因诊断改DNS/代理。见[正式验收](../../maintenance/audit/netlify-formal-domain-acceptance-20261027.md)。以下为此前时点。

2026-10-27用户已确认Netlify真实登录成功、功能正常；自动前端22/0。当前待team绑定/CNAME：用户进入的是可选Netlify DNS向导，继续阿里云外部DNS，只将team A改为CNAME rad-taffy-56e1ce.netlify.app，保留origin-team A及根站点。正式域名证书/会话仍未验收。旧7882诊断服务精确停止并保留日志。见[验收](../../maintenance/audit/netlify-frontend-acceptance-20261027.md)。以下为此前时点。

2026-10-27 Netlify实际前台验收：用户已更新rad-taffy-56e1ce项目并见登录页；Lead对实际站点22/0（IPv4 HTTPS、无显式HTTP代理）：页面、JS/CSS权威源码hash、敏感路径/Origin拦截、private/no-store与无缓存命中均通过。**真实账号登录/刷新保持/退出未确认，team自定义域名仍待切换**；本轮无生产写入或DNS变更。见[验收](../../maintenance/audit/netlify-frontend-acceptance-20261027.md)。

2026-10-27 HTTPS回源已部署：origin-team证书签发，IPv4 bore16444→回环TLS网关18445，lc-bore-netlify.service已启用并通过自动重连。真实本机79/0、合成15/0、最新公网正常SNI22/0；首次公网21/1因单次TLS重置，失败证据保留。新Netlify ZIP待用户更新现有rad-taffy-56e1ce项目，**Netlify端HTTPS业务代理/真实账号尚未验收**。team A当前159.223.110.159，最终前端通过后改CNAME。运维2026.10.27.3；[审计](../../maintenance/audit/netlify-https-origin-20261027.md)｜[交接](../../maintenance/handoffs/2026-10-27-netlify-https-origin.md)。下方为此前时点。

2026-10-27 Netlify回源实测通过：用户站点rad-taffy-56e1ce.netlify.app经Netlify到bore7882取得完整诊断标记，Lead独立web_fetch与Windows IPv4不使用代理均200，响应no-store、fwd=miss。已启动独立origin-team.l-creation.club的DNS-01证书申请，等待用户新增回源A和TXT，team暂不切换。现有证书/业务网关未改；正式HTTPS回源和真实登录尚未通过，详见[本轮审计](../../maintenance/audit/netlify-https-origin-20261027.md)。

2026-10-27 Netlify评估：用户希望隐藏端口并能在国内直连。已准备独立拖拽测试包和无生产数据的IPv4 bore诊断服务，等待用户上传新Netlify项目后复核实际回源。现有根站点单次本机IPv4直连200约0.92秒，不能视为全国稳定性证明。**暂缓此前team DNS直接切到bore的步骤**；Netlify正式域名/回源证书/登录会话尚未实现。详见[测试审计](../../maintenance/audit/netlify-bore-probe-20261027.md)。

2026-10-27公网网关部署：独立IPv4回环TLS网关18443已加载，lc-bore-public.service enabled/active，公共中继159.223.110.159:16443，自动重连端口保持验证通过。真实本机网关49/0、合成Cookie/头/限速12/0、无SNI但严格校验TLS链与域名的公网19/0；正常浏览器SNI尚超时，真实账号未测。**当前等待用户将阿里云team A记录改为159.223.110.159，之后继续正常SNI与浏览器验收**；URL须含:16443。运维版本2026.10.27.2，新[源快照](../../maintenance/registry/source-server-bore-public-ipv4-20261027.json)；[审计](../../maintenance/audit/bore-public-ipv4-deploy-20261027.md)。内网业务vhost未改写，DNS/VPN/库存未改。下方为此前时点。

2026-10-27 晚间网络复核：**bore 公网经现有 VPN/HTTP 代理可用**。NAS 到真实 IPv4 中继建链，Windows 通过 7897 的 CONNECT/正向代理，使用域名/IPv4 四种组合均获得 HTTP200 与精确合成内容（2.1～2.3秒）；本机直连两种组合超时。撤销“境外全部封锁、代理不支持TCP、必须放弃bore”的结论。合成隧道已停止，生产TLS登录200，未改VPN/DNS/路由或生产入口。**正式Odoo公网白名单入口尚未部署**。详见[复核审计](../../maintenance/audit/bore-ipv4-proxy-recheck-20261027.md)。

2026-10-27 P2 模块已上生产：`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5` 在 LcHardwareHouse 生效，odoo/nginx active、TLS 登录 200，库存 2 行与其它模块未变。本轮同时修复备份工具默认 data_dir 造成的附件漏备（已补备 139 文件、加回归测试）。新快照[source-server-production-p2-20261027.json](../../maintenance/registry/source-server-production-p2-20261027.json)；[审计](../../maintenance/audit/production-p2-deploy-20261027.md)。**公网仍未开通**：team.l-creation.club 仍解析到内网 192.168.31.105，无 AAAA，需真实公网节点+标准443+隧道登记；DNS/Nginx 本轮未改。

2026-10-26 P2 隔离闭环：真实 Odoo 19 经最终 P1 模板验证登录/Cookie/刷新/退出/角色/Origin/错误响应/限速/更新清单，**P2 77/0 BLOCKED=2 SKIP=0**；P1 回归 94/0；契约 12/0。修复：gated JSON-RPC 错误白名单脱敏（lab_team_web 19.0.1.0.4）、Nginx 1.30.6 proxy_cookie_flags、CSP/Origin、相对跳转、headless Chrome 真实流程。生产未应用；asset 公开源 blocked。

2026-10-26 P2 真实 Odoo 只读验证：隔离 Odoo 19 经最终 P1 入口模板完成冷登录/Cookie/刷新/会话接口/目录/详情/静态/asset/退出失效、错误认证与非法 DB、next 边界、四角色边界、安全响应头、跨来源、匿名更新清单、敏感路径默认拒绝、两来源限速，**PASS=46 FAIL=0**；生产仅只读核对。发现待决策：Odoo 会话 Cookie 仅 HttpOnly（缺 Secure/SameSite）、原生 JSON-RPC 错误含 traceback、生产入口缺 CSP（模板已补待应用）、web.base.url 仍 http。未做公网/真实密码/P3。见[审计](../../maintenance/audit/bore-p2-real-odoo-readonly-20261026.md)。

2026-10-26 bore P1 本地隔离入口：在 server/ubuntu22.04/bore 新增默认拒绝的入口 Nginx 模板（按真实控制器/JS 端点）、代理头覆盖、登录端点限速钩子、边缘 stream 模板与本地验证脚本；用真实 Nginx 1.18.0 + bore 0.5.3 + 合成上游验证「公开边缘 Nginx(stream，不接受客户端 PROXY) → bore 隧道 → TLS+PROXY 入口 → 上游」完整链路：94 项断言通过、9 项契约测试通过；失败路径 10 项断言通过（端口占用/WORK 复用不影响已有服务、无子进程残留）；运行时完整性 10 项通过（篡改归档拒绝且不解包）。PROXY 来源 IP、伪造 XFF/Forwarded 与伪造 PROXY 拒绝、默认拒绝、路径绕过、限速与断链失败关闭均本地实测；真实公网节点/标准 443/真实 Odoo 会话/自动续期/生产部署仍未验证，不构成公网开放授权。见[审计](../../maintenance/audit/bore-p1-local-isolated-entry-20261026.md)。

2026-10-26 方案状态：用户明确要求bore公网访问只使用Odoo登录，不新增身份门禁，并希望整合旧页面为自有UI。已完成[完整方案](../requirements/PUBLIC_ACCESS_AND_UNIFIED_UI_PLAN.md)：本地38个路由装饰器/44个路径模式，识别EDA旧后台链接、Flutter通用ORM兼容调用、自有Web写业务尚未接入，以及bore来源IP与Odoo冷却的配合风险。方案待确认，未派发DSH、未连生产、未部署bore/切DNS/卸载或清库；不代表公网安全验收通过。

2026-10-25 HTTPS更新：team.l-creation.club已启用受信任TLS及HTTP308跳转，Codex离开内网前独立12项通过（信任/SAN/HTTPS页面/保护/跳转/资产/旧更新清单）。证书有效期至2027-01-23 21:22:47（Asia/Shanghai），手动DNS续期未自动化。用户自行完成LE注册/协议/签发；HTTPS真实账号、刷新和退出未测。用户离开内网后本机DSH桥接拒绝连接，最终备份定位与操作退出码未取得，后续恢复同一任务核验，不重复部署。见[最新交接](../../maintenance/handoffs/2026-10-25-team-https-current.md)。以下为此前阶段记录。

2026-10-25 登录补修：team域名Nginx仅在原生认证端点清除X-Odoo-Database，避免Odoo19冷会话进入stateless模式、认证成功却不能保存Cookie；配置校验和reload成功，Odoo未重启。隔离4组场景13条断言通过；生产匿名入口、随机不存在账号失败响应、旧更新清单哈希复核通过。用户随后回复“可以了”，确认原登录无反应已恢复，按用户复验记录；Codex未独立操作真实账号，刷新保留登录、退出和跨端流程未追加实测。HTTPS仍未启用。见[本次交接](../../maintenance/handoffs/2026-10-25-team-login-cold-session.md)。

2026-10-25 域名迁移准备：用户已在阿里云添加 `team.l-creation.club → 192.168.31.105`，内网/VPN访问。按本轮追加授权，服务器resolv.conf仅改用路由器192.168.31.1，旧dnsmasq已disabled且无进程，备份和正常系统解析/TLS验证通过，IP/默认路由及Odoo/Nginx保持正常。此为手工指定路由器DNS，未实现NetworkManager/DHCP自动DNS管理。新域名HTTP入口已接通：`http://team.l-creation.club/`，Nginx固定生产库，management_host仅命中新域名；根欢迎页、/login、匿名/lab保护已从客户端真实域名独立复核。旧vhost和root_aliases=0保留，Odoo与Nginx主进程均未重启。LE生产账号/协议尚未获同意，HTTPS和自动续期未启用，VPN跨网/真实账号全流程/生产视觉未测。见[DNS审计](../../maintenance/audit/team-domain-dns-repair-20261025.md)。

2026-10-25：**lab_team_web 19.0.1.0.0 已安装生产**。新增独立欢迎、登录、仓库检索和详情；18 个新模块文件与冻结源一致，旧五模块133文件、库存计数与合计保持不变，服务 active。欢迎/登录/匿名保护、静态资源和原入口已做生产HTTP检查；真实账号完整流程、生产大目录和真机未重测。65项逻辑通过+1跳过、11项隔离HTTP通过属于同源候选证据。见[生产审计](../../maintenance/audit/team-web-production-20261025.md)与[发布核验](../../maintenance/audit/team-web-publish-codex-review.md)。

旧IP/lc.rm.com多库入口仍需原登录选库方式，/team兼容路径保留；新管理Host已启用且fresh会话可直接使用根路径。root_aliases=0继续保证旧Host的/login与/lab行为不变；入库/领用新页面尚未接入。


2026-10-24：lab_portal 已废弃并从源码移除（生产 uninstalled），**不再是当前能力**；最新方案为 lab_team_web 候选。

2026-10-24：**lab_catalog19.0.2.0.4 暗色主题已上线**。仅更新主题与资产配置，服务active、认证后台/主题CSS200、库存计数和更新通道不变；视觉及手机验收尚未完成。备份与验证见[主题交接](../../maintenance/handoffs/2026-10-24-dark-theme-deploy.md)。

**最新Android stable为1.1.3+6（release_sequence2）**，已从冻结166文件构建并核验包签名/内容/来源，LAN清单200及认证完整包/hash通过，Windows/Linux仍204。修正私有缓存合法别名误拒，显示具体安装错误；275 Flutter通过5跳过、9项真实JVM路径检查通过。用户旧安装入口已失败，本次需手动覆盖修复APK一次，不先卸载；手机是否完全解决仍待实测。旧build5及渠道指针备份保留，服务不重启、库存不写入，见[最终安装修复交接](../../maintenance/handoffs/2026-10-19-android-install-fix.md)。

以下为此前发布/诊断时点：

最新：Android1.1.2+5已按用户明确要求发布到stable，旧1.1.1+4验签/版本判断、LAN清单200和真实认证完整下载/哈希/403/匿名303检查通过。用户手机反馈未知来源已允许但旧安装入口仍失败；当前开发修复1.1.3+6，原生路径9项、Flutter275通过5跳过、分析无错误警告。手机唯一根因尚无原生日志，不把路径测试当作实体安装通过。后续见[安装修复交接](../../maintenance/handoffs/2026-10-19-android-install-fix.md)和[build5发布交接](../../maintenance/handoffs/2026-10-19-android-stable.md)。

以下为此前交接时点：

当前客户端开发候选 **1.1.2+5** 修复器件选择白屏、补齐弹层自定义入口、明确更新接口状态；测试/构建与未验收项见[修复交接](../../maintenance/handoffs/2026-10-19-receipt-picker-fix.md)。生产 **lab_workflow19.0.1.2.0已上线**，服务active、登录200，Android/Windows/Linux manifest均204。bag1/quant2/move1/operation1/catalog695217/location16/pending0/trace1及数量/预留总量0前后一致；完整备份核验和权限证据见[部署交接](../../maintenance/handoffs/2026-10-19-update-endpoint-deploy.md)。本轮未发布stable包。以下1.1.1+4段落为上一开发时点。

归档基线：2026-10-19。当前说明优先于local/archive中的旧README。计数是相应证据的时点快照，不是永久业务要求。

最新开发候选为客户端 **1.1.1+4**、lab_workflow **19.0.1.2.0**，实现启动/恢复检查、签名清单、同源后台下载、更新面板、Android系统安装与桌面独立更新助手；完整包和测试证据见[更新器交接](../../maintenance/handoffs/2026-10-19-client-updater.md)。当前active-sources指向更新器候选源；生产仍为下述19.0.1.1.0，未新部署或发布stable。真实设备安装、原生GUI升级/回退和物理打印未验收，不能用编译或目录夹具代替。

2026-10-19 已完成[两阶段入库实现与验收](../development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md)：客户端 **1.1.0+3** 三端原生候选包已重建，尚未发布；Android签名匹配，Windows进程冒烟及Linux动态依赖检查通过，三端界面、安全存储和实体扫码打印仍待验收，见[原生交接](../../maintenance/handoffs/2026-10-19-native-candidates.md)。**lab_workflow 19.0.1.1.0 已上线**，服务active、HTTP200，权限与单QR标签PDF检查通过。升级前后bag1、quant2、move1、operation1、catalog695217、location16及数量/预留总量0一致，pending0、trace1，历史袋码无缺漏；未写入生产测试库存。详见[上线交接](../../maintenance/handoffs/2026-10-19-server-deploy.md)及[审计](../../maintenance/audit/server-deploy-20261019.json)。

本轮完整回滚备份 `/var/backups/lc-elc/20261019T073840Z-before-upgrade` 与部署目录 `/opt/odoo/deployments/two-stage-20261019-a1/old-source.tar.gz` 配对；数据库和154个附件的实物/hash已核验，未离机备份或完整恢复演练。首次升级因工具把旧模块保留在addons根而失败，移出后重试成功；工具已修复并通过108项故障测试，最终服务端源清单为 `source-server-two-stage-receipt-opsfix-20261019.json`，104个业务文件与原候选一致，额外3个运维修复文件已同步。active-sources 指向最终源；所有历史manifest和发布包来源保持不变。

## 归档发布版本和权威源

以下版本与逐文件核对事实均为归档时点，不代表当前候选源仍与旧安装包字节一致。

| 组件 | 当前版本 | 维护源/成品 |
|---|---|---|
| Flutter Windows/Android/Linux | 1.0.1+2 | clients/app / clients/<platform>/releases/1.0.1 |
| lab_inventory | 19.0.1.0.0 | server/ubuntu22.04/odoo_addons/lab_inventory |
| lab_catalog | 19.0.2.0.3 | 同级lab_catalog |
| lab_workflow | 19.0.1.0.2 | 同级lab_workflow；20261018精简与权限修复包 |
| EDA专业版插件 | 3.0.3 | plugins/jlc-eda；Node桥接同目录bridge |
| 中文采集/资料导入编排 | 20261019服务器只读快照 | services/lcsc/systemd-production；采集源码server/ubuntu22.04/crawler |

具体来源及SHA在maintenance/registry。当前客户端66个Dart/pubspec业务文件已与原构建冻结和三端构建副本核对；Odoo102文件在初始导入时与最新修复ZIP相同；随后新副本仅规范化客户端两行空白和网页XML末尾多余空行，原始文件另存且变换hash/patch已登记（import-transformations.json），业务逻辑不变。干净Git克隆测试另发现Flutter模板忽略了Gradle启动文件，现已显式跟踪jar/gradlew；生成registrar与IDE状态转存历史，当前完整源指针按修正后的新manifest登记。完整源树本次另建立baseline manifest，UTF8文本指纹按LF归一化，另保留导入原字节hash，兼容Windows/Linux Git换行。

## 已知生产事实（来自20261018验收，归档仅只读复核必要元数据）

- Odoo192.168.31.105:8069，DB LcHardwareHouse；三个模块installed、服务active、HTTP200。
- 器件695217、参数4110477、分类2791；卸载40个无关模块、保留52个业务模块及依赖。
- 网站6页内容hash、保留模块账号权限一致。系统记录6账号含模板/非活动，普通列表3个。
- 当前没有实验室库存/bag/领料数据；POS自带默认产品随卸载移除，未删除真实库存。
- 权限26项事务回滚测试、7组件测试、9浏览器项通过，条码PNG/PDF生成成功；物理打印机未测。
- 归档只读导出确认每日03:30开始/05:30结束（Asia/Shanghai），OnSuccess触发Odoo资料导入；未在本轮重新跑采集/导入。
- 生产备份在服务器/opt/odoo/backups/module-cleanup-production-20261018T153740Z，未下载完整生产数据库到本地。

## 本轮归档实际验证

- 所选来源到目标逐文件复制核对SHA256；完整记录local/manifests/migration-files.json（已完成；旧progress仅为故障续传记录，最终以迁移摘要和完成报告为准）。
- EDA在新路径105/105单测、13/13包测试、build与verify均exit0，重建eext/bundle与旧发布物hash相同；没有冒称真实EDA宿主再导入验收。
- 服务端纯逻辑26项运行、1跳过，exit0；不是Odoo ORM生产重测。
- 现有运维故障夹具100项检查在新路径/WSL root通过，不访问真实PostgreSQL或systemd；初次非root前置失败已记录。
- 新维护工具8项通过：源码冻结/换行、机密扫描、离线导入覆盖/越界保护、构建dry plan。
- 最终安卓APK公开证书8b4c…ff43，已与原Windows离线密钥匹配；WSL默认key640b…a5ff不是最终发布身份。公证书明文登记、私钥Git排除。
- 原WSL工具已只读导出4.4GB（JDK/SDK/Flutter/cache及Linux适配），路径/成员/hash见registry/wsl-toolchain.json。没有搬迁或修改原WSL SDK。

最终源码/Git边界检查通过；空目录克隆的源码检查、8项维护测试、路由一致性与构建dry-run四项均通过。具体结果见maintenance/audit及归档完成报告，不能仅以本段静态说明当成功证据。

## 仍需知道的边界

1. 三端当前包是导入的既有1.0.1成品，不是从本次未来Git commit全量重编译的新包。Android按用户约定未模拟器测试；Linux1.0.1未重新完整做SecretService/CUPS/实体打印。原客户端测试233通过、5跳过，保留其来源。
2. 新通用build_client入口本次检查dry-run与工具测试，不保证便携VS或旧WSL私有adapter解包后无需调整即可编译。标准VS与Linux开发依赖有明确获取步骤。
3. 旧Ubuntu离线整包是20261015快照，不含今天最新全部修复，保留为历史。全新cp310闭包与生产cp312 ABI不同；已导出生产70个公开包版本锁，但完整cp312 wheelhouse还需同ABI准备机生成和隔离验收。
4. 新npm缓存联网准备曾180秒超时，不能标为npm ci --offline已通过；当前node_modules和lock已保存，新路径EDA构建已通过。按依赖指南可联网重新填缓存。
5. 原有部分器件图片资源404仍存在，未借归档修复；没有全量手册离线镜像。
6. GitHub远端尚未创建/推送；CI流程已准备但未云端运行。离线大文件仍在本机，离开本机前需导出可信载荷及单独私钥备份。
7. 历史原始聊天/补丁/候选源码保留在旧目录或local归档，不自动进入Git，不应盲执行。旧计划/计数不代表当前状态。
