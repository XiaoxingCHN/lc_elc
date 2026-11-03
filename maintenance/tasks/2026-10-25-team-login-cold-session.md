# 任务：新管理域名首次登录无反应

- 目标：修复team.l-creation.club首次登录后会话不持久或界面无反馈；保留正常选库、自有路径、旧站与接口。
- 用户问题：报告“登录没有反应”，并补问HTTPS及官网Netlify托管。当前HTTP域名已接通，HTTPS/LE协议仍未同意，不得在此任务注册CA账号或改Netlify项目。
- 已查证：新域名登录页/JS200，正确JS MIME，无CSP阻止；使用随机不存在的用户名测试原生认证，正常返回AccessDenied。GitHub Odoo19 http.py在header选库且session.db未设时置session.can_save=False(stateless)。当前Nginx把X-Odoo-Database加入所有请求，包括原生authnone认证端点，存在冷登录成功但不能保存cookie的问题。
- 允许修改：本项目team Nginx vhost的认证端点转发；必要最小前端反馈修复须另据复现；局部隔离回归测试、文档。保留DNS修复、旧dnsmasq停用、旧vhost、global dbfilter、所有业务数据与模块源。只项目Nginx校验通过后reload，备份失败或新假设不成立即停并报告。
- 分工：DSH负责确认生产同版本源、隔离复现/修复/配置操作；Codex审查方案与结果。先查GitHub成熟方案已执行，本次优先Odoo原生认证，不新写会话或认证系统，不新增插件。
- 候选最小方案：仅精确location=/web/session/authenticate不发送X-Odoo-Database（覆盖为空，保留Host与forwarded头），认证参数db由原生端点选库并保存cookie；其余页面保留现有header，对已有同库session正常沿用。须由安装源码和隔离的真实账号冷CookieJar往返验证后决定，不能只测匿名200。
- 来源：分支codex/two-stage-receipt-plan/14cf1ef；server冻结175文件不变；当前team vhost输入SHA256 b86d8433eb120c8deb7c5ae3aef3ede8e980d4c34ac97581d2481dd3c77fdc66。
- 测试：隔离合法账号冷登录、cookie持久、后续受保护页和退出；错误账号显示；生产仅随机不存在用户名及未授权页/旧接口只读，绝不向用户索取密码、不创建生产测试用户或伪造session。
- 待交付：证据、最小差异、备份/哈希、Nginx验证/重载退出码、已测与未测、交接；有源变动按流程新冻结，旧manifest/产物不改写。
- 当前结果：冷会话补修已上线，隔离4组场景13断言通过；生产匿名/错误账号与旧更新清单复核通过，175文件冻结不变。repo_check49项通过/0错误，exit0。用户随后确认“可以了”，原登录无反应恢复；刷新保持会话及退出未追加实测；详见maintenance/handoffs/2026-10-25-team-login-cold-session.md。
