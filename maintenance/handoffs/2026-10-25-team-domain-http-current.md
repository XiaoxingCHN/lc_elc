# 当前交接：team域名HTTP已接通，DNS停用完成，HTTPS待确认

## 用户目标与已确认边界

内网/VPN使用team.l-creation.club，根欢迎页、/login、/lab使用自有前端，保留旧站/API。用户已保存阿里云team A192.168.31.105；明确允许服务器自身DNS改为路由器192.168.31.1，明确允许停用其旧DNS服务。新域名HTTP阶段由Codex按既定迁移范围决定先实施。

LE新生产账号和订阅协议仍未获答复，不能将DNS授权推定为协议同意。后续大量编码先查GitHub要求已写入WORKFLOW；此轮已查上游并采用原生能力。

## 当前权威源码、分支和版本

业务源仍为server/ubuntu22.04/odoo_addons/lab_team_web19.0.1.0.0；完整server来源175文件、tree 9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4未改。分支codex/two-stage-receipt-plan，已有远端起点14cf1ef；本批文档未提交/推送。

运行配置：新增/etc/nginx/sites-available/team-l-creation-club及enabled软链，HTTP输入SHA256 b86d8433eb120c8deb7c5ae3aef3ede8e980d4c34ac97581d2481dd3c77fdc66；固定X-Odoo-Database=LcHardwareHouse。Odoo management_host已设team.l-creation.club，root_aliases保持0，management_host_enabled未设即默认启用。无新模块或客户端包。

## 已完成工作与证据

- 服务器resolv.conf仅127.0.0.1→192.168.31.1，正常系统解析和LE端点TLS200；dnsmasq disabled、无进程、53无监听，配置/软件保留。IP/DHCP/路由/VPN/NM/Meta未改。
- 新vhost nginx-t/reload exit0；Odoo参数经ORM commit+signal生效。Odoo与Nginx master未重启，旧vhost与原入口/API保持正常，库存只读基线不变。
- Codex真实LAN域名三组独立CookieJar共15响应通过：根欢迎200、/login200、匿名/lab和详情303到自有登录、/team兼容200；自动选生产库，不再需要首次访问旧选择页。线上CSS/JS缓存hash正确。
- DNS与HTTP审计及备份完整hash分别见team-domain-dns-repair-20261025.md、team-domain-http-deploy-20261025.md；Codex独立证据见team-domain-codex-review-20261025.md。
- 浏览器自动化超时，生产视觉未测；真实用户完整登录/操作、VPN跨网未测。未做写入测试、未创建测试账号/伪造会话。
- 最终Python3.15 repo_check exit0、49通过0错误，git diff --check exit0；15份相关文档机密扫描0命中；server源175文件与冻结tree一致。未verify-payloads，保留既有离线载荷warning；未推送本轮文档。

## 剩余工作与下一步

1. 等待用户明确同意LE生产账号注册和当前协议 https://letsencrypt.org/documents/LE-SA-v1.8-July-06-2026.pdf 。没有同意前不得--agree-tos、注册或下订单。
2. 获同意后用现有Certbot1.21 manual DNS-01原生交互，显式LE生产server与team cert-name；若无运营邮箱，使用其受支持的无邮箱流程，不提取旧账号邮箱、不代填假邮箱。获取实际TXT交用户添加，公共解析检查后继续。私钥留服务器，不打印、不提交。
3. 证书成功后单独备份更新team vhost启用443，team80重定向HTTPS，保留旧vhost；不自签、不-k、不配置长期HSTS或未审查的续期任务。
4. manual续期未自动化，按实际notAfter提前处理；如需自动续期优先研究现成lego/alidns或现有成熟provider及受限凭据。
5. 当前resolv.conf手工指向路由器，不是NM/DHCP完全托管。网络事件后是否改写未测，勿未经同意再改NM/netplan或启动旧DNS。

## 依赖与私有材料

Nginx、Odoo、Certbot均现有；GitHub调研见team-domain-reuse-research-20261025.md。三个自写helper已拒绝，禁止执行。审核输入/请求/指标在local/build/team-domain-migration-20261025/，Git排除。当前HTTP已用原生命令上线，不要重复执行“目标须不存在”的首次部署步骤。

DSH同一task-codex-team-web-phase1-1a236b6b-505a-46ed-95be-a8df122ee26c、session-979373c3-4290-414f-af00-cd63e7d177bf；cursor3573，实际ali/deepseek-v4.1-flash-1017/high、idle/turn-completed，自动批准false。

## 生产与回滚

当前可用URL：http://team.l-creation.club/（仅HTTP，内网/VPN网络可达前提）。HTTPS尚未启用，不宣称全量迁移完成。

备份：/var/backups/lc-elc/dns-resolv-20261025T2055Z 和 /var/backups/lc-elc/team-http-20261025T2102Z，目录名按实际记录原样引用。回滚新站点需先校验链接/配置归属与hash，仅下线本次新链接并恢复management_host旧值/存在性，复核nginx配置再reload；不得删除已安装模块、恢复整个数据库或改旧vhost。DNS恢复也仅按已批准范围，未经新授权不恢复被用户明确停用的旧DNS服务。
