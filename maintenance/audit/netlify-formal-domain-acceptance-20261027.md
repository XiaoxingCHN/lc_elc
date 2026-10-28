# 正式team域名验收（2026-10-27）

## 已通过

用户完成CNAME后，NAS通过固定IPv4阿里公共DoH确认team.l-creation.club CNAME→rad-taffy-56e1ce.netlify.app，解析出的区域IPv4为52.74.6.109与13.215.239.219。未迁移NS，origin-team A保留。

正式域名正常SNI与完整证书验证通过；通过现有HTTP CONNECT代理显式连接Netlify公网52.74.6.109，HTTP Host/SNI均为team.l-creation.club。实际22项检查22通过0失败、exit0，每条必须Server=Netlify且Cache-Status标记Netlify Edge，排除内网误命中。

覆盖首页/登录页/HTTPS固定标记/匿名相对303/JS、敏感数据库与RPC/后台/websocket拒绝、允许的精确Origin与恶意Origin/null拒绝、方法限制、private/no-store与去验证器；无-k、无禁用SNI。此前用户已确认Netlify默认域名下真实账号登录成功和功能正常，不能冒充已在正式域名或关闭VPN手机上确认。

## 特别区分：LAN与公网

最初系统DNS下curl返回200、TLS0、约0.05秒，随后remote_ip证明实际对端192.168.31.105，**该次排除出Netlify正式公网验收**。Windows hosts中没有team命中项；不擅自改Windows/路由器DNS或代理规则，不断言具体是缓存还是分流配置。

当前本机直连两个区域Netlify IPv4有5/12秒TCP超时，旧默认netlify.app地址和根站点在本轮直连也出现超时；现有代理到Netlify实际HTTPS工作。不能因此泛化成国内全部不可用或必须VPN，也不能把代理通过算成无VPN通过。

对比Netlify官方文档的默认负载均衡75.2.60.5：直接IPv4、正式SNI、证书校验，两次curl获得200，第二次完整固定标记匹配、TLS0、TCP约0.064秒、TLS约0.430秒、总7.304秒；第一次约9.814秒。说明存在节点/线路差异，不是整个站点或bore一概不可达。该地址在官方文档中用于apex的后备A配置；本轮**没有将用户的标准子域CNAME改成该IP**，不能声称官方优先推荐子域这样配置。

一个仅用于备选线路的本地Node三请求探针在超时处理时发生未处理socket事件，exit1，未产生有效计数，**不算三项通过**；已修复诊断脚本重复销毁socket的事件处理、语法检查通过，未重复整组测试。后续独立curl完整标记实测不依赖该脚本。未修改生产代码。

## 证据与来源

local/build/netlify-https-origin-20261027/formal-domain-verify.mjs、formal-domain-results.json、formal-domain-output.json；备选线路formal-direct-default-lb.mjs仅为本机诊断，不能作为全通过报告。沿用运维2026.10.27.3、[211文件冻结源](../registry/source-server-netlify-https-origin-20261027.json)与原ZIP，不覆盖原产物或版本关联。

本轮未修改Nginx、Odoo、Netlify部署包、DNS或代理。原HTTP诊断7882此前已精确停止并留日志。lc-bore-netlify.service与回环18445继续承担HTTPS origin16444；原受保护lc-bore-public16443暂保留作切换期间旧入口，未声称已退休。

## 尚需用户验收

用手机流量（不经本机LAN、不挂VPN）打开 https://team.l-creation.club/ ，确认能打开并用已有账号登录。该域名Cookie与netlify.app不同，首次需重新登录。若通过，再完成正式域名刷新/退出确认和旧入口收尾；若不通，按用户网络具体现象处理，已有官方默认LB的单点直连证据可供比较，不要求用户盲目再次改DNS。

当前完成的是域名绑定、可信TLS与Netlify公网自动检查，不是国内多运营商稳定性保证。仍有bore隐藏来源IP/共享认证额度、Netlify26秒时限、证书DNS续期未自动化等既有运维限制。
