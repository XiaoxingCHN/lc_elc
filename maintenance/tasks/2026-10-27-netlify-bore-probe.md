# 任务：Netlify→bore隔离回源验证

- 目标：为用户提供可直接拖拽部署的Netlify测试包，验证非标准端口回源及国内直连体验。
- 授权范围：本机准备文件、NAS普通用户目录固定文本诊断服务与临时bore，用户自行创建独立Netlify测试项目。
- 禁止：不修改现有Netlify根站点、不改DNS、不将生产Odoo作为首次Netlify测试目标、不降低生产TLS校验。
- 写入：local/build/netlify-bore-probe-20261027；本任务与审计交接。
- 验收：测试服务IPv4回环、固定无敏感文本、24小时到期清理；验证代理→bore响应；压缩包根目录含index.html、_redirects及所需静态资源。Netlify实际回源需用户上传后继续验证。
- 依赖：现有bore0.5.3、NAS Python3、用户Netlify账户，不读取其凭据。
- 已知边界：Netlify普通rewrite不能可靠假设自定义Host，正式方案需独立回源域名/匹配证书和网关Host/Origin适配；请求26秒限时。
