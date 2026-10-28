# 维护交接：team 子域名迁移准备，等待两项确认

## 最新授权补充

用户随后明确同意：服务器resolv.conf仅从127.0.0.1改用已测可用的路由器192.168.31.1（先备份、失败恢复、不改IP/DHCP/路由/VPN/NM、不重启网络）；另明确允许停用服务器自己的DNS。已向DSH派发执行，目标仅dnsmasq.service disable --now、保留配置/软件，不停其他网络服务。实际完成状态以新的DNS修复审计为准。LE生产账号/协议仍未得到同意，原固定公网DNS与NM配置变更方案不执行。以下段落保留前序准备时点，不代表最新两项仍均待批准。

## 用户目标与已确认边界

使用team.l-creation.club作为内网/VPN管理站点，根欢迎页、/login、/lab为自有页面；原站点及客户端接口保留。用户已在阿里云保存team A记录。DSH主要写实现，Codex决策验收。用户新要求“大量编码前先查GitHub成熟方案”，已加入WORKFLOW并完成本批调研。

本轮允许项目域名配置准备与切换；全局DNS/网络原本不在范围。已提出额外两项确认。用户对DNS项澄清：已停用旧解析服务、路由器改为自动获取DNS；因此旧的固定223.5.5.5/1.1.1.1提议暂停，不算已批准，正在只读核对服务器当前网络管理器/DHCP提供的DNS，再给出回归现有网络自动DNS的具体方案。不得恢复旧DNS/内网CA。LE生产账号及协议仍未收到同意。不能把经过时间或本交接当作同意。

## 当前权威源码、分支和版本

分支codex/two-stage-receipt-plan，已推送起点14cf1ef。lab_team_web19.0.1.0.0已生产安装；server来源仍175文件，tree 9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4。本轮未改业务源码或active source，未提交/推送本批文档。

## 已完成工作与实际证据

- 公共1.1.1.1及本机系统DNS已解析team域名到192.168.31.105；新Host当前80返回404，尚未切换配置。
- 旧Nginx项目vhost：sites-enabled/odoo软链到sites-available/odoo，hash 3d64e8fe98fdedd3125e632f987a901dd5ce9becef0a4887f3e54364d3ed30fd；仅80监听，443空闲。Odoo proxy_mode=True，无db_name/dbfilter。根别名保持0，management_host未设置；源码已支持新managementHost自动允许根业务路径。
- Certbot1.21.0存在，manual模块import通过；无需安装阿里云插件即可手动DNS-01。没有Let's Encrypt生产账号，staging有1个叶子账号目录；未读账号JSON/邮箱/密钥。
- 系统resolv.conf是root:root644普通文件，仅nameserver127.0.0.1；dnsmasq自2026-10-22失败，53无人监听。显式上游223.5.5.5/1.1.1.1查询有应答；经已有Meta fake-IP及真实IP连接LE均HTTP200、TLS校验成功。属于系统DNS失效，不能说服务器无公网出口。未更改代理/路由或重启DNS服务。
- DSH旧证书cert.pem读取被安全网拒绝，未重试/未绕过；不要求Codex换工具读取同一受阻文件。旧证书SAN不明，不复用它承诺新域名HTTPS；旧续期指向当前未运行的内网ACME9000。
- DSH模型曾变为zhr-hpx/gpt-6.1-sol并连续两轮TRANSPORT失败，未执行工具。用户回复换模型后恢复ali/deepseek-v4.1-flash-1017/high，后续只读准备已实际turn-completed，自动批准保持false。
- Codex通过已授权SSH独立只读核对vhost、监听及proxy_mode；已退出该会话。未导出凭据、真实配置或任何私钥。
- 本轮Python3.15 repo_check exit0，49通过，保留离线载荷warning，未verify-payloads；git diff --check exit0；4份相关文档机密扫描0命中。候选语法检查与关键词检查仅为静态证据，未冒称生产nginx-t通过。

## 剩余工作与阻塞

1. 按最新DNS澄清完成服务器接口/NM/DHCP/文件属性只读检查，向用户确认精确的自动DNS方案；旧固定上游方案不执行。LE新账号/协议仍待明确答复；未同意部分不动。
2. 最小候选在local/build/team-domain-migration-20261025/，以EXECUTION_PLAN.md及Nginx候选为审查材料。三个自写apply/rollback/parameter helper已拒绝，禁止执行；优先系统原生命令和Odoo官方shell。
3. 如DNS修复获准：先重核resolv.conf形态/特殊属性/哈希并备份；采用经实测与明确批准的网络现有DNS接管方案，保留IP/网关/路由/连接方式。getent与正常TLS请求验证，失败恢复。不自行解除immutable保护、改NM profile/netplan或重启连接。
4. 如证书获准：原生Certbot manual DNS-01，明确--server为LE生产端点；新账号接受用户确认过的协议，不提取旧账号邮箱。无用户运营邮箱则使用支持的无邮箱流程并记录无邮件提醒。保持原生交互进程取得实际TXT，交用户添加，公共解析验证后再继续；不自写ACME/DNS客户端，不关闭TLS验证。
5. 本项目Nginx独立vhost固定X-Odoo-Database=LcHardwareHouse，转发Host及forwarded头；每个定义proxy_set_header的location都要完整必要头，websocket用HTTP1.1。目标已存在/旧配置hash变化即停。保留旧vhost及入口。
6. 用Odoo官方shell的env设置management_host、commit、registry.signal_changes；保存参数旧值与存在性，回滚按快照恢复，root_aliases和management_host_enabled不改。上线后验证多worker、新域名fresh会话、旧入口、库存基线。
7. 本轮不注册续期任务；manual认证无hook不能自动续期。按实际notAfter提前续期，后续优先评估lego/alidns等成熟provider与受限凭据。

## 依赖和产物

研究见maintenance/audit/team-domain-reuse-research-20261025.md；只读事实见team-domain-preflight-20261025.md。现有Nginx/Odoo/Certbot已足够完成基本集成，无新安装包、无新源快照。GitHub只读调研已确认Certbot/lego/acme.sh功能及许可证，未运行外部安装脚本。

DSH沿用task-codex-team-web-phase1-1a236b6b-505a-46ed-95be-a8df122ee26c，session-979373c3-4290-414f-af00-cd63e7d177bf，已处理cursor3268。私有请求与上下文均在local/build目录，Git排除。

## 生产状态和回滚

截至本交接，未修改生产配置、参数、源文件或业务数据，未reload/重启、未注册CA账号/订单、未生成TXT挑战或新证书。原部署及上一轮备份保持。不能宣称新域名已迁移或HTTPS已可用；下一轮从上述明确授权与事实继续。
