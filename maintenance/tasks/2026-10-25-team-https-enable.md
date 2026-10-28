# 任务：管理子域名启用HTTPS

- 目标/用户场景：继续域名迁移，将已恢复登录的team入口启用受信任HTTPS。
- 当前问题及复现方法：此前443无监听；用户现已自行完成Let’s Encrypt DNS验证并报告签发成功，证书路径为/etc/letsencrypt/live/team.l-creation.club/fullchain.pem，配套privkey.pem，有效期至2027-01-23。协议已由用户自行确认，不再重复申请或代签协议。
- 验收标准：正常TLS信任/SAN/有效期；HTTPS欢迎和登录200、匿名仓库保护；HTTP同Host路径及查询串转HTTPS；保留认证请求头补修、旧vhost/API与服务；不以匿名检查冒充真实账号全流程。
- 允许修改目录/接口：仅现有team项目Nginx vhost及私有候选/备份、维护文档。生产授权沿用当前明确的项目域名迁移；先备份、校验、reload，验证失败恢复。无网络/防火墙/路由器或其他业务变更。
- 业务不变量/依赖：Odoo数据和源码不动；固定库与认证精确location保留；不读取或输出私钥内容，不改证书文件，不运行新签发。
- 负责人/协作者及分工：DSH实施及原始审计，Codex制定方案/决策/独立验收及全局文档；沿用原DSH session/task。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan，14cf1ef；source-server-team-web-phase1-20261025.json，175文件，9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4。
- 环境与凭据获取方式：现有lc-nas受控连接；只引用证书和私钥路径，不收集/提交认证材料。当前team vhost预期SHA256 e3674661515dbbd5852ae825b3c96bafeb36036956ce7b8519d2857c8561d1e6。
- 实施步骤：核查新证书公开元数据和当前配置；唯一目录备份；添加443 TLS保留80进行检查；成功后单独80块仅team固定域名跳转HTTPS并复验；nginx-t失败或TLS失败恢复原配置。
- 测试命令、实际结果与退出码：待实施后补记正常TLS HTTP检查、nginx-t/reload、旧站/API基线及repo_check。
- 未验证项及风险：manual证书不自动续期，此轮不新增DNS密钥/定时任务；VPN/移动端和真实账号HTTPS全流程待复验。
- 发布文件、hash和回滚点：待审计记录；应用源不变不重写旧manifest，未授权本轮Git推送。

- 当前结果：离开内网前HTTPS与308均真实可用，独立12项检查通过/0失败，exit0；用户离开后DSH桥接不可用，最终生产备份/命令审计待恢复。当前交接maintenance/handoffs/2026-10-25-team-https-current.md。
