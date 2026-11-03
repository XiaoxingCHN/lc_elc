# 维护交接：2026-10-27 Netlify HTTPS回源网关已部署

## 用户目标与边界

标准HTTPS网址不显示端口，国内不挂代理访问；用户已手动部署rad-taffy-56e1ce测试项目并添加origin-team A/TXT。现阶段先更新该项目验证，不提前改team自定义域名。

## 当前来源与版本

运维2026.10.27.3；[冻结源](../registry/source-server-netlify-https-origin-20261027.json)211文件，tree fcdad4728edf4f7eee4333f01063ce179fda3eff78a8ffa98d384ebd712a1d54。业务模块版本未改。

## 实际工作与证据

[审计](../audit/netlify-https-origin-20261027.md)记载全部命令范围、结果、产物SHA及失败轮次。新Certbot证书21:14签发，TLS网关回环18445、bore IPv4 159.223.110.159:16444、unit lc-bore-netlify.service enabled/active；原LAN/旧网关保留。renderer9/0+原8/0+契约21/0，真实本机79/0，合成Cookie/头/缓存15/0；公网第一轮21/1（TLS reset）、第二轮正常SNI22/0；自动重连及后续标记通过。

## 当前需要用户操作

下载local/build/netlify-https-origin-20261027/netlify-odoo-https-20261027-v1.zip，解压后在已有rad-taffy-56e1ce项目Deploys上传。尚未部署，不能说Netlify端业务HTTPS/真实账号通过。team当前A实际上已为159.223.110.159；先不再改DNS，前端验证后才在Netlify绑定team并改项目CNAME。

## 产物与依赖

ZIP741字节，SHA ad030b953b4266d24356e095727cab6179b0cb8a36a4f6de9599cabd662327eb；同名JSON记录冻结源与原始模板hash。所有证据位于同local目录。远端/var/lib/lc-elc-bore/releases/netlify-20261027-a1与verification/netlify-20261027-a1-cookie；证书请求状态/var/lib/lc-elc-netlify-origin/20261027-a1。原诊断7882仍服务旧测试部署，等新版本成功后按state PID归属清理，24小时也会自动停止。

## 后续与回滚

用户更新后独立复核Netlify正常HTTPS回源、缓存、Origin与Cookie，真实账号在用户浏览器验证。公共bore真实来源IP不可见、共享限速与26秒时限、DNS证书续期未自动化均保留。回滚只停新unit、核对并移出新conf再nginx -t/reload，保留所有证据；不覆盖原vhost或旧upstream。
