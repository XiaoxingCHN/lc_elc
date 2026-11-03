# 任务：Netlify正式HTTPS回源准备

- 已有证据：用户站点rad-taffy-56e1ce.netlify.app回源固定文本成功；Lead通过web_fetch与本机IPv4无代理独立取得200、完整标记、Cache-Control:no-store。
- 目标：新增origin-team.l-creation.club专用回源域名及证书，保留team的现有DNS直到正式链路通过。
- 授权范围：已授权继续公网部署；不改既有Netlify根项目、不读私钥/账号凭据、不猜测Odoo密码。
- 用户操作：阿里云新增origin-team A与ACME DNS TXT；记录值由实际证书挑战生成，不使用示例值。
- 允许修改：local/build/netlify-https-origin-20261027、任务/审计/交接；NAS独立证书申请工作目录与新证书名，不覆盖既有team证书。
- 下一步：证书完成后准备Netlify回源网关Host/Origin/缓存适配与新版部署包，验证后再切team CNAME。
- 未完成：正常浏览器HTTPS回源、真实账号、动态响应缓存与Cookie端到端。
- 实际结果：origin-team A生效、独立证书21:14签发；回环网关18445与lc-bore-netlify.service/公网16444已部署。
- 验证：新renderer9/0、原8/0+21/0、本机79/0、合成15/0、最新公网正常SNI22/0、自动重连通过；首轮21/1已保留；repo_check52/0（既有离线载荷警告）。
- 下一步：用户将新ZIP上传已有Netlify项目，Lead复核前端后再切team CNAME。当前team A实际159.223.110.159，不再称其为LAN。
