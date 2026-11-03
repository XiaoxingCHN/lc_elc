# 维护交接：2026-10-27 IPv4 bore 受保护公网入口

## 用户目标与边界

用户要求继续完成bore，只走IPv4，在确实需要操作时通知。最新澄清认可先配置服务器，阿里云DNS最后切换；固定端口用于地址稳定，若要省略端口需公网443。

## 权威源码与版本

server运维2026.10.27.2，[冻结源](../registry/source-server-bore-public-ipv4-20261027.json)205文件，tree a6296a2920e1b73de23da8087a051433983400566f6359df1bb3b8477decabf5。Odoo模块版本未改。

## 已完成与实际证据

详见[部署审计](../audit/bore-public-ipv4-deploy-20261027.md)。独立Nginx网关回环18443已加载，systemd lc-bore-public.service enabled/active，真实IPv4中继159.223.110.159，公网16443。新renderer8/0、原契约21/0、真实生产本机49/0、隔离Cookie/头/限速12/0、无SNI但严格验证TLS链和域名的公网19/0；自动重连端口保持通过；repo_check52/0。Qoder委派未完成，不算独立验收。

## 下一步必须继续

通知用户将阿里云team A记录从192.168.31.105改为159.223.110.159，TTL默认即可，不添加AAAA，不动根域名。访问 https://team.l-creation.club:16443/ 。拿到用户“已改”后恢复同一任务，先测正常SNI（当前握手超时，尚不保证仅DNS切换就解决），再真实浏览器/账号流程。验证脚本 local/build/bore-public-gateway-20261027/lead-public-verify.mjs --normal-sni 。本机HTTP代理127.0.0.1:7897；不要再次把直连超时推断成bore不可用。

## 依赖/产物

远端release /var/lib/lc-elc-bore/releases/20261027-a2，root所有bore /usr/local/lib/lc-elc/bore/bore，独立conf /etc/nginx/conf.d/lc-bore-public.conf。本机JSON证据同上local目录；没有保存真实凭据、cookie值或聊天到Git/TOMC。

## 生产状态/回滚

未改业务vhost、DNS、VPN、账号或库存，Odoo未重启。仅新增回环网关与独立隧道unit、Nginx reload。回滚先停用独立bore unit，核对本轮include后移出lc-bore-public.conf并nginx -t/reload；保留证据，不恢复旧odoo vhost以免重复upstream。公共中继隐藏来源IP、共享认证限速与端口非永久所有是明确限制。此前备份恢复集完整性问题不属于本轮已解决项，继续按原未验收状态处理。
