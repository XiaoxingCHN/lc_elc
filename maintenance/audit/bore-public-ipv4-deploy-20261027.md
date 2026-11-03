# IPv4 bore 公网白名单网关部署（2026-10-27）

## 交付状态

服务器端已部署并运行，DNS尚未切换；普通浏览器的正常SNI与真实账号全流程尚未验收。不能把无SNI诊断的通过写成浏览器公网最终通过。

当前链路：team.l-creation.club:16443 → 公共中继IPv4 159.223.110.159:16443 → systemd bore0.5.3 → 127.0.0.1:18443 独立TLS白名单网关 → 127.0.0.1:8069 Odoo。bore只转发该独立网关，不转发原始8069或现有无白名单443。

## 生产改动与来源

- 新增 /etc/nginx/conf.d/lc-bore-public.conf，include /var/lib/lc-elc-bore/releases/20261027-a2/gateway.conf。只新增IPv4回环18443，不改写现有team vhost；部署前后其SHA256一致。
- 新增 /etc/systemd/system/lc-bore-public.service，普通用户运行，enabled/active，自动重启、只允许AF_INET与AF_UNIX。程序置于root所有的 /usr/local/lib/lc-elc/bore/bore。
- 复用既有Nginx配置中的证书引用；未读取证书或私钥内容，没有修改证书。
- Nginx1.18使用proxy_cookie_path兼容Secure/SameSite=Lax，保留Odoo HttpOnly；不使用该版本不支持的proxy_cookie_flags。
- 未升级模块、未改账号/库存、未改VPN/路由/DNS；Odoo未重启，Nginx仅reload。
- 运维源码版本2026.10.27.2；[冻结源](../registry/source-server-bore-public-ipv4-20261027.json) 205文件，treeSHA256 a6296a2920e1b73de23da8087a051433983400566f6359df1bb3b8477decabf5，manifestSHA256 ac4477cd9ff122c24e2cfd91fdc01cc930b7fa92673dece8bb81d2a2fda8f08f。实际部署候选只有renderer/allowlist/headers/unit四个冻结文件及已登记bore二进制，不能据此声称全部205个文件均已部署。
- bore二进制SHA256 0be5c2533066bf36cad773657cafb564441d072d6cf0824357a0f22c4dac04dd。

## 验证证据（本轮）

| 层次 | 结果 | 范围 |
|---|---|---|
| renderer边界测试 | 8/0，exit0 | 输入注入、回环监听、Host端口、Origin配对、旧版Cookie兼容 |
| 原网关契约回归 | 21/0，exit0 | 默认拒绝、公开authority、转发头等 |
| 生产本机真实TLS网关 | 49/0，exit0 | 页面、静态、匿名保护、敏感路径/编码绕过/方法/Host/Origin；内网配置hash与登录健康 |
| 独立合成upstream+Nginx1.18 | 12/0，exit0 | 实际Cookie Secure/HttpOnly/SameSite、冷认证清DB头、保留外部端口、清除伪造转发头、共享认证限速429 |
| 公网经当前HTTP代理 | 19/0，exit0 | 无SNI诊断模式；TLS链与team域名均严格校验，不使用-k，不使用真实账号 |
| 自动重连 | 通过，exit0 | 精确确认bore MainPID后发送TERM，systemd自动拉起新PID且再次申请16443；15秒有界检查成功，随后TLS1.3+登录200 |
| 仓库检查 | 52/0，exit0 | 既有production-py312-rebuild离线载荷未闭环警告仍保留；未运行载荷全量验证 |

证据目录 local/build/bore-public-gateway-20261027：deployment.json、cookie-probe-summary.json、public-no-sni-results.json、reconnect-result.json，以及各任务脚本。远端对应release/verification目录；本轮未删除失败候选或测试日志。

## 失败与纠正（不隐藏）

- a1独立nginx -t因长Origin map精确键超过默认hash桶失败；未加载生产。a2改用严格锚定正则，避免修改全局hash参数。a1保留不覆盖。
- 首次activate检查遇到reload尚未完成绑定，新增配置已自动撤回；加入有界监听就绪检查后再试。
- 冷登录GET没有session Cookie是现有固定DB头的stateless行为，不能用“GET必须设置cookie”作为正确验收条件。真实成功认证的Cookie/保持会话仍待现有账号复验。兼容指令的实际行为通过独立合成upstream验证，不能冒充真实账号登录通过。
- 普通SNI为team域名时，当前代理链路TLS握手超时；同一中继地址、相同证书校验和HTTP Host，不发送SNI则可完整获得TLS1.3与200。说明故障受SNI差异影响，但尚不能唯一定位为某个代理/DNS规则。DNS仍指向LAN，需要切换后重新测正常SNI。没有把禁用SNI部署给浏览器，也没有降低TLS校验。
- Qoder CN角色委派首次返回continuable句柄，但未取得产物；随后短审查调用超时且没有可观察job。首个句柄已停止，没有closing message。未把它记成完成的独立审查，全部测试由Lead实际执行。Desktop桥接端口也不可用，未重启或改造Harness。

## 仍需用户操作

阿里云DNS，l-creation.club域名下：将主机记录team的现有A记录192.168.31.105替换为159.223.110.159，TTL可保持默认/600。不要新增第二条不同IP的同名A来混用，不添加AAAA，不修改根站点记录。最终本阶段访问URL为 https://team.l-creation.club:16443/ 。

DNS只负责IPv4地址，不负责端口转换。公共bore不提供本项目可控443；固定16443是稳定访问地址的选择，不是协议必须。端口不归项目永久所有，公共中继IP变更或端口被占用仍需维护。

切换后：先以正常SNI复跑public verifier，复核证书/登录页/敏感路径；再由用户现有Odoo账号实际验证登录、刷新、退出、目录与详情。不能使用SSH密码猜测Odoo密码。

## 已知限制与回滚

公共bore隐藏真实访客IP，网关不信任客户端XFF/Forwarded，认证POST采用全入口共享限速6次/分钟、burst5；并发登录会共享额度，Odoo的IP冷却也可能共享，尚不等同于受控边缘生成PROXY的完整架构。证书自动续期仍是既有待办。

本轮回滚只需先disable --now lc-bore-public.service，再确认 /etc/nginx/conf.d/lc-bore-public.conf 是本轮include文件后移出该文件，nginx -t成功后reload。无需恢复或重复添加旧odoo upstream，不使用此前lc.rm退役记录里会产生重复upstream的回滚方法。保留release与日志作证据。当前nginx/odoo/bore均active，LAN受信任TLS登录200，18443仅回环监听；合成验证18444已关闭。
