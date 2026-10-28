# 维护交接：2026-10-25 新管理域名登录补修

## 用户目标与已确认边界

用户报告新域名登录“按钮和页面完全没有变化”。修复限本项目team域名代理；DSH实施、Codex审查。公网官网继续Netlify托管，不迁移项目、不修改DNS/网络；HTTPS仍待此前LE生产账号/协议问题答复，未启用。

## 当前权威源码、分支和版本

- 分支codex/two-stage-receipt-plan，起始HEAD 14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71。
- lab_team_web19.0.1.0.0；应用源码未变。冻结source-server-team-web-phase1-20261025.json共175文件，Codex本轮重新计算tree SHA256为9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4，与冻结一致。未改历史manifest。
- 代理配置变更发生在生产项目vhost；候选与原始HTTP配置存local/build/team-login-cold-session-20261025、local/build/team-domain-migration-20261025，均为Git排除材料。

## 已完成工作与实际证据

- 已查GitHub官方Odoo19 http.py与原生session.authenticate：冷会话用X-Odoo-Database选库会置can_save=False；请求虽认证成功却不写会话Cookie。生产安装代码一致。
- DSH隔离库合成账号复现：带头认证成功但后续SessionExpired；去头认证保存Cookie、后续带头读取受保护/team/lab成功、CSRF退出成功。4组场景共13条断言，exit0，非生产真实账号验收。
- 仅新增精确location=/web/session/authenticate，完整保留转发头，X-Odoo-Database设空；其余4个location继续固定库。候选/生产SHA256 e3674661515dbbd5852ae825b3c96bafeb36036956ce7b8519d2857c8561d1e6。
- DSH安装、nginx -t、systemctl reload nginx成功，组合执行exit0。nginx主进程1092和Odoo124857未重启；443未监听。具体记录见maintenance/audit/team-login-cold-session-20261025.md。
- Codex独立HTTP检查：根欢迎200、登录200、匿名仓库303、兼容/team200；随机不存在账号认证200+AccessDenied。旧lc.rm.com与新域名在明确选库后Android清单均200/1826B，SHA256152d47ae1145b8c81200409a5af4e47b952e1ec1dcbe8d10c4105959a945cb65保持基线。旧Host未选库探测失败，不能混作选库后的回归失败。
- Codex确认生产表单、错误节点、defer脚本完整；JS34613B，SHA2561951e05a7fdfc8dd41d784baf063b1901987082fd481be2e3c5c34ed38407d93，node --check退出0。静态检查不能证明真实浏览器事件已绑定。

## 剩余工作与阻塞

- 2026-10-25用户回复“可以了”，原登录无反应按用户复验闭环；不需要继续索取Console信息。
- 浏览器IAB快照超时；Edge窗口最小化，当前控制入口无法取得可操作状态。Codex未独立操作生产真实账号。登录恢复来自用户确认；刷新保留登录和退出仍未追加实测。
- 本机无既有DOM测试依赖，DOM模拟skipped；未为此安装新工具或按猜测改前端。
- HTTPS、VPN跨网与移动端未测；未创建生产测试账号、未伪造会话、未写测试库存。

## 依赖和产物

仅使用现有Nginx/Odoo原生认证，无新增插件；DSH沿用原session和task，ali/deepseek-v4.1-flash-1017/high。私有认证材料不入文档或Git。

本轮使用本机Python3.15执行`python tools/repo_check.py --output local/build/team-login-cold-session-20261025/repo-check.json`：49项检查通过，0错误，exit0；既有production-py312-rebuild载荷警告保留，未运行--verify-payloads。`git diff --check`退出0（仅换行规范提示）；7份本轮相关文档简单机密模式扫描0命中，此扫描不代替完整人工边界审查。未新增应用代码，未重复无关客户端测试。

## 生产状态和回滚

备份目录/var/backups/lc-elc/team-login-fix-20261025T2142Z（0700）；该名称是原样目录名，不据Z推断时区。team-vhost.before.conf与修改前文件SHA256均为b86d8433eb120c8deb7c5ae3aef3ede8e980d4c34ac97581d2481dd3c77fdc66。

必要时仅恢复该文件至/etc/nginx/sites-available/team-l-creation-club，校验nginx -t后reload并复核；不恢复整库、不改旧odoo vhost或DNS。当前仓库文档尚未提交/推送，本轮没有声称已推送。
