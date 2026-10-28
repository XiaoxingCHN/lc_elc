# Netlify→bore最小回源测试包（2026-10-27）

## 后续独立复核

用户已部署 https://rad-taffy-56e1ce.netlify.app/ 并回传成功截图；Lead通过独立web_fetch及本机IPv4不使用代理取得200和完整固定标记，响应no-store、Netlify Edge fwd=miss。Netlify高位端口回源已在本例确认。下一步见[HTTPS回源准备](netlify-https-origin-20261027.md)。

## 准备包时状态

已准备可直接拖拽部署的测试包；尚未部署到Netlify，不能宣称Netlify高位端口回源或Odoo登录已经通过。当前等待用户创建独立Netlify测试项目并返回netlify.app地址。暂不修改team DNS，不迁移整个域名DNS，不修改既有Netlify官网项目。

## 实测与产物

- 现有根站点l-creation.club，本机IPv4不使用代理单次HTTP200/TLS校验0/0.920215秒；现有代理单次200/校验0/3.237268秒。只是一条网络的时点观测，不是国内多运营商稳定性结论。
- NAS普通用户目录 /home/hbut/bore/netlify-probe-20261027-a1，Python固定文本服务只监听127.0.0.1:46135；bore中继IPv4 159.223.110.159:7882。supervisor PID241349、初始bore PID241351，后续以state.json与完整命令校验归属，不模糊pkill。
- 固定诊断文本通过服务器直连真实中继IPv4、Windows现有代理HTTP正向请求、代理CONNECT请求分别成功取得。首次Windows正向请求12秒超时，后续相同URL成功；不把偶发超时解释成整个方案不可行。
- 服务2026-10-28 20:44:57 +08到期自动停止，保留日志与状态。只返回固定标记，不提供目录列表，不连接生产Odoo，不接受登录密码，不输出真实Cookie或业务数据。HTTP只用于这个无敏感内容的探针，正式回源仍要求HTTPS。
- local/build/netlify-bore-probe-20261027/netlify-bore-test-20261027.zip，3294字节，SHA256 d9740bc5ee17349336cfa41a13401637fdb3f477563f3c530e39a796fe6236f5。
- 归档根目录恰有index.html、probe.js、style.css、_redirects、_headers，zip完整性检查通过；node --check probe.js exit0。用户不需要Git、Node或构建命令。
- 前端只请求同源/_bore_probe，Netlify的200 rewrite再取诊断文本；只有HTTP成功且完整标记匹配才显示通过。请求20秒有界、no-store、不发送浏览器Cookie；当前尚无真实浏览器/Netlify部署实测。
- 源文件hash与包信息在同目录package.json；使用说明为同目录操作步骤.md。该包不是生产Odoo发布包。

## 用户操作

下载ZIP解压，将直接含index.html的目录拖入 https://app.netlify.com/drop 或 Add new project→Deploy manually；使用新项目，打开生成的HTTPS netlify.app地址，点击开始回源测试，回传站点URL与结果。用户可以在不挂代理的电脑、手机流量分别测试。

## 正式方案仍需准备

官方Netlify200 rewrite支持反向代理，26秒超时；官方支持答复说明普通rewrite不能任意覆盖Host，Host按回源主机名发送，不能直接靠headers={Host=...}假装解决。这要求正式阶段独立回源域名、匹配证书、网关Host/Origin适配与禁止缓存会话响应。需要Netlify真机部署后再确认高位端口回源、Cookie、POST、刷新、退出、下载限制。

参考：https://docs.netlify.com/manage/routing/redirects/rewrites-proxies/ ；https://answers.netlify.com/t/can-the-host-header-be-defined-on-a-redirect/19241/8 （支持答复，2024后续说明普通rewrite仍不支持Host覆盖）。

原生产IPv4白名单网关及lc-bore-public.service保持此前部署状态。本轮没有生产配置变更、重启或库存写入。
