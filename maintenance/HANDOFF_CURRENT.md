# 当前维护交接：2026-10-28 P3 自有 Web 源码候选已验证、冻结

最新：[P3 正式交接](handoffs/2026-10-28-p3-web-workflows.md)｜[任务](tasks/2026-10-28-p3-web-workflows.md)｜[冻结源](registry/source-server-p3-web-20261028.json)｜[候选包登记](registry/artifact-server-p3-web-20261028.json)。日常 Web 工作流候选完成；250 个源文件与纯源码 ZIP 已逐文件核验登记。当前源码 ORM 82、HttpCase 21、独立并发 6、浏览器主链 28 项通过；API 1 项与浏览器 3 个场景仍明确 blocked，原 test-enable 并发模式因 Registry 锁 blocked，不能伪称全模式通过。repo_check 52/0，生产 cp312 恢复载荷 warning 保留。生产仍 P2，未部署；用户已授权将本轮 Git 更新推送到既有 origin 的 P3 功能分支，提交以远端分支为准；手机无 VPN、摄像头/实体打印、生产 Python3.12 等价仍未实测。主代理自建测试 PG 已按租约停止，合成证据保留。

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
