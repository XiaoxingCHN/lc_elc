# 维护交接：管理子域名HTTPS已可用，离开内网后的状态

## 用户目标与已确认边界

用户自行完成Let’s Encrypt生产账号注册、协议确认及DNS验证，已获得team.l-creation.club证书；继续既定内网/VPN域名迁移，DSH负责配置实施、Codex独立验收。用户随后离开内网，当前不继续服务器操作。

## 当前权威源码、分支和版本

codex/two-stage-receipt-plan，起始14cf1ef；lab_team_web19.0.1.0.0。完整server源175文件与source-server-team-web-phase1-20261025.json匹配，tree9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4。未改应用源或历史manifest。

## 已完成工作与实际证据

- DSH按任务启用443并将team的80入口改为308跳转，保留精确认证请求清头及4处固定数据库头。候选、原配置与差异在local/build/team-https-enable-20261025，未提交Git。
- Codex在离开内网前独立验证12项全部通过，验证脚本exit0：系统默认信任链/域名验证成功，TLS1.3；HTTPS欢迎/登录/兼容入口200，匿名仓库与详情303；3条HTTP到HTTPS跳转保持路径查询；CSS/JS200；旧Host选库后Android更新清单200/1826B及原哈希不变。证据local/build/team-https-enable-20261025/root-verify.json。
- TLS握手取得公开证书指纹8707d3cf705f8bc9aeb1f20a4cf61e45eaf22fbfeab72e1d723b49a3f9f2526a，SAN包含team.l-creation.club，到期时间2027-01-23 21:22:47（Asia/Shanghai）。未读取私钥。
- 证书文件路径的直接读取曾被DSH安全检查拒绝，未换工具读取文件；采用正常验证TLS连接检查服务端公开证书，未跳过信任检查。
- 用户在HTTPS启用前已确认原登录无反应恢复；该确认不能充当HTTPS真实账号全流程验收。
- 本轮本机Python3.15运行tools/repo_check.py：49检查通过、0错误、exit0；保留既有production-py312-rebuild载荷警告，未verify-payloads。git diff --check退出0，仅换行规范提示。

## 剩余工作与阻塞

- DSH桥接在用户离开内网后连接被拒，未取得最终turn-completed或生产备份目录/哈希/操作退出码的完整审计。当前只能确认上述真实服务结果与本地候选；桥接恢复后须读取同一task/session尾部和既有备份定位，不能重新盲目上线。
- 等回到内网或连接VPN后由用户验证HTTPS实际登录、刷新保持登录与退出；浏览器视觉、手机、VPN跨网未追加实测。
- 手动DNS证书不自动续期。下一项应先调研成熟阿里云DNS客户端与最小授权方案，再配置自动验证/续期/成功后reload及失败提示；尚无DNS API凭据，不创建密钥、不注册定时任务、不声称自动续期完成。
- 本批域名文档尚未提交/推送。维护全局文档和检查可以在本地完成，服务器操作等待重新具备内网连接。

## 依赖和产物

现有Nginx/Certbot/Odoo，无新增模块；证书与私钥仅留服务器原位置。不会把用户邮箱、TXT挑战值、私钥或会话写入Git。DSH继续使用task-codex-team-web-phase1-1a236b6b-505a-46ed-95be-a8df122ee26c与session-979373c3-4290-414f-af00-cd63e7d177bf，最后已见实际模型ali/deepseek-v4.1-flash-1017/high。

## 生产状态和回滚

当前已观察到https://team.l-creation.club可用及HTTP308；旧入口更新清单保持基线。修改前team vhost SHA256 e3674661515dbbd5852ae825b3c96bafeb36036956ce7b8519d2857c8561d1e6。新备份绝对路径尚待DSH最终审计确认，不能编造；必要时核验既有项目备份后仅恢复team vhost并nginx-t/reload，不恢复数据库、不改其他网络或vhost。
