# team 域名迁移 HTTP 阶段：Codex核验

## 范围与决定

用户要求开始迁移，选择内网/VPN，并自行保存阿里云team A记录；服务器域名与首页路径按既定范围由DSH执行、Codex审查。用户后续明确批准服务器resolv.conf改用路由器192.168.31.1，并允许停用服务器自己的DNS。

Codex决定先完成沿用现有内网HTTP的域名入口，HTTPS等待独立的LE生产账号与协议答复。这个HTTP分阶段决定由Codex作出，不能写成用户已单独确认HTTP或逐文件批准配置。自动批准一直关闭。

## 复用与候选审查

用户要求大量编码前先查GitHub。已核对Certbot、lego、acme.sh上游、许可证及相关功能，详见复用研究；本次直接使用Nginx和Odoo原生能力，不新写认证/选库/ACME/DNS客户端。

旧三个自写helper存在备份、符号链接判断和参数回滚问题，均拒绝并未执行；实际使用系统原生命令与Odoo官方shell。Nginx候选修正了location代理头不继承的问题，每个代理location均包含Host/forwarded/固定DB头，websocket使用HTTP1.1。采用的HTTP配置2392B，SHA256 b86d8433eb120c8deb7c5ae3aef3ede8e980d4c34ac97581d2481dd3c77fdc66；TLS注释骨架未用于生产。

## 已核验的执行证据

- DSH因当前模型连接失败的两次尝试没有执行服务器操作；用户换模型后恢复ali/deepseek-v4.1-flash-1017/high。DNS与HTTP两个执行回合均收到真实turn-completed。
- DNS备份目录 /var/backups/lc-elc/dns-resolv-20261025T2055Z，原文件副本hash匹配。仅nameserver 127.0.0.1改为192.168.31.1，新文件SHA256 46607e45205411140c910740991c74e9a8d208c199e45ec327f8ed7ffa5e2002。普通文件644原属主/inode保持。正常系统解析与LE端点HTTPS200、TLS校验通过；旧dnsmasq disabled且无进程，旧failed状态未做美化重置。未改Meta/NetworkManager/路由/DHCP/IP，也未恢复旧解析服务。
- Nginx独立新增team站点，实际文件hash与审查输入一致；nginx-t和reload exit0。旧odoo vhost副本hash仍3d64e8fe98fdedd3125e632f987a901dd5ce9becef0a4887f3e54364d3ed30fd；备份目录 /var/backups/lc-elc/team-http-20261025T2102Z。以上目录名原样引用，不据此推导操作时区。
- 仅新增参数management_host=team.l-creation.club，使用官方shell的set_param、commit、registry.signal_changes；root_aliases仍0、management_host_enabled仍未设置。Odoo主PID124857、Nginx master1092均未重启。旧Host的根站点、登录及API对照正常，更新清单hash不变。库存读数与前一基线一致，没有库存写入。

## Codex客户端独立检查

直接使用本机正常DNS与真实URL http://team.l-creation.club/，没有人工Host头、X-Odoo-Database或--resolve。三组独立CookieJar，每组五个路径，共15次响应符合预期：

- / 为自有欢迎200/3876B；/login为自有表单200/3902B，data-db为生产库。
- 匿名/lab为303到/login?next=%2Flab；详情lab:1的next冒号编码保留。
- /team兼容路径200/3921B；没有旧数据库选择页或旧Odoo登录跳转。
- 线上CSS 36406B、JS34613B均200；内容缓存键分别7e9eee9d31f5、faa1bc0b6393，与实际字节SHA1前12位一致。
- 控制台曾把中文按错误编码显示为替换符；独立读取保存的UTF8指标确认页面标题为正确中文，实际字符串无U+FFFD，并非生产页面乱码。

浏览器自动化创建/绑定超时，未取得生产视觉截图，不算视觉PASS。真实用户完整登录、库存操作、VPN跨网、实际网站编辑器仍未验证。

## 收尾检查

Python3.15执行tools/repo_check.py，exit0、49项通过、0错误（2926个候选文件），未verify-payloads，保留production-py312-rebuild警告。git diff --check exit0；15份本批相关文档机密扫描0命中。重新计算server源仍175文件，tree与已冻结清单一致。未新增或重复运行业务单测；没有业务源码改动，不把静态关键词检查冒称业务测试。当前文档未提交/推送GitHub。

## 剩余工作

LE生产账号及当前订阅协议仍未得到用户同意：没有注册账号、接受协议、创建订单、生成实际TXT挑战或签发证书，443未启用。manual续期没有自动化。NetworkManager未来网络事件是否改写当前resolv.conf未测，不声称服务器DNS已完全跟随DHCP。

后续获明确同意后复用原生Certbot manual交互，由用户添加真实TXT，验证后才继续签发与TLS配置；不绕过旧cert.pem读取的安全网拒绝，不忽略TLS验证，不自行加DNS API凭据或计划任务。
