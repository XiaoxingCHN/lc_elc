# Netlify HTTPS回源部署（2026-10-27）

## 当前结果与待办

专用HTTPS回源网关与IPv4 bore隧道已部署，正常SNI、证书信任和路由/缓存检查通过。已生成Netlify更新包，**等待用户更新现有rad-taffy-56e1ce项目**；Netlify端HTTPS业务回源与真实账号尚未验收，不能据此宣布最终上线。

现有Netlify HTTP诊断测试已由用户截图及Lead web_fetch/Windows IPv4无代理独立复核：200、完整标记、no-store、Netlify fwd=miss。该证据只证明此前7882固定文本代理，不证明新HTTPS业务代理。

## DNS、证书与运行配置

- 新域名origin-team.l-creation.club通过固定IPv4阿里公共DoH确认A为159.223.110.159；此前递归NXDOMAIN缓存已过期。普通dig被fake-IP影响，不作为权威DNS证据。
- DNS-01公开TXT已由CA验证；独立Certbot证书lc-elc-netlify-origin于2026-10-27 21:14:10 +08签发，exit0。没有替换team原证书，没有读取私钥/账号凭据。请求wrapper PID242276已结束；状态目录/var/lib/lc-elc-netlify-origin/20261027-a1保留证据，不在Git保存TXT值。
- 新链路：Netlify（待更新）→ https://origin-team.l-creation.club:16444 → bore0.5.3 → 127.0.0.1:18445 TLS白名单网关 → Odoo8069。
- 新增/etc/nginx/conf.d/lc-bore-netlify.conf，include /var/lib/lc-elc-bore/releases/netlify-20261027-a1/gateway.conf；新unit lc-bore-netlify.service enabled/active，仅IPv4，普通用户运行，自动重连。旧lc-bore-public.service和原LAN vhost保持，不重启Odoo；Nginx仅reload。18445仅回环，合成验证18446已关闭。
- 回源Host严格限定origin-team（含允许端口）；上游管理Host/XFH固定team.l-creation.club。POST Origin只允许team和用户当前Netlify项目的精确HTTPS域名，不接受任意netlify.app、HTTP或null。转发头仍覆盖/清除，不信任来源伪造。
- 所有响应private/no-store，CDN-Cache-Control与Netlify-CDN-Cache-Control均no-store，隐藏ETag/Last-Modified；上游canonical绝对跳转改相对路径；Cookie适配Nginx1.18。
- 21:34查询team现有A已为159.223.110.159，不再声称它仍指向LAN。用户当前无需再改DNS；Netlify项目更新并验收后再添加team自定义域名和替换CNAME。

## 本轮验证

| 层次 | 结果 | 实际范围 |
|---|---|---|
| 新renderer | 9/0，exit0 | 回源/公开Host分离、精确Origin、无缓存、独立zone、固定无业务诊断路径、输入拒绝 |
| 原renderer/契约 | 8/0 + 21/0，exit0 | 未破坏原公网白名单行为 |
| 生产本机TLS网关 | 79/0，exit0 | 新证书、页面、敏感路径/方法/Host/Origin、缓存与原LAN hash/健康 |
| 合成upstream Nginx1.18 | 15/0，exit0 | Cookie安全属性、冷认证DB头、canonical Host、真实禁缓存/去验证器、清伪造头、共享限速429 |
| 公网正常SNI第一轮 | 21/1，exit1 | 一次POST/lab在TLS建连前重置；不是该路径返回错误业务码，原记录保留 |
| 公网正常SNI第二轮 | 22/0，exit0 | 固定标记、页面、匿名跳转、Origin允许/拒绝、敏感路径、缓存与完整域名/证书校验 |
| 自动重连 | 通过，exit0 | 精确PID归属校验后TERM，新PID在15秒有界检查内重新注册16444，随后正常SNI固定标记再次成功 |

没有使用-k或禁用SNI。web_fetch环境对新高位HTTPS地址曾fetch failed，不能据此推断Netlify回源也会失败；现有代理curl与Node实际正常SNI通过。Netlify真实回源仍须上传后复核。没有真实账号密码，因此不算真实登录通过。

证据在local/build/netlify-https-origin-20261027：deployment.json、cookie-probe-summary.json、public-normal-sni-run1.json、public-normal-sni-results.json、reconnect-result.json；远端release/verification目录保留。首次unit部署任务脚本错误引用了不存在的模板文件，发生在写unit前；修正引用后成功，未覆盖旧服务。

## 来源与交付物

运维2026.10.27.3；[新冻结源](../registry/source-server-netlify-https-origin-20261027.json)211文件，treeSHA256 fcdad4728edf4f7eee4333f01063ce179fda3eff78a8ffa98d384ebd712a1d54，manifestSHA256 53d615d42ec2381d71561db39fa3dc9f43ba01067ef526cb74338e17ad0a0ca6。实际网关候选5个文件与bore二进制均已哈希校验，不声称全部211个源文件已部署。

新增render-netlify-gateway.py、其9项测试、netlify三份模板、build-netlify-site.py。打包脚本核对自身及模板均匹配冻结源，拒绝覆盖既有产物。

交付local/build/netlify-https-origin-20261027/netlify-odoo-https-20261027-v1.zip，741字节，SHA256 ad030b953b4266d24356e095727cab6179b0cb8a36a4f6de9599cabd662327eb。ZIP含index.html/_redirects/_headers，200强制rewrite从专用HTTPS回源取得真正页面；index仅占位。元数据同名JSON记录来源、原始文件hash和netlify_deployed:false（构建时事实，不改写成已部署）。

## 用户操作与后续验收

用户在已有rad-taffy-56e1ce项目Deploys拖拽解压目录，等Published后返回URL/结果；应出现管理站点页面。Lead先核对Netlify HTTPS标记、页面、敏感路径、POST Origin、缓存，再用户现有账号验证登录/刷新/退出/目录，不发送密码或Cookie。通过后将team加入该项目自定义域名，按Netlify指引将team原A替换为项目CNAME；根站点/项目不动。

公共bore隐藏真实访客IP，认证采用共享限速（6次/分钟burst5），并发会共享额度；Netlify26秒代理时限、大文件下载、证书DNS续期自动化、国内多运营商稳定性仍需后续处理。既有备份恢复集问题不算本轮解决。

## 回滚

先停用lc-bore-netlify.service；核对/etc/nginx/conf.d/lc-bore-netlify.conf属于本轮include后移出，仅nginx -t成功后reload。保留release/证书/日志，不删旧网关或恢复旧upstream。Netlify尚未更新；更新后的回滚可从Deploys重新发布上一个已记录部署。证书TXT不再是签发阻塞，后续可由用户清理；origin-team A必须保留用于HTTPS回源。
