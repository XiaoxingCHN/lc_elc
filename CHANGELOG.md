# 变更记录

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
