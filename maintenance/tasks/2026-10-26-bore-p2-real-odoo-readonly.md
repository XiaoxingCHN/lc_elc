# 任务：P2 只读自有 UI 与真实 Odoo 会话/权限验证

- 目标/用户场景：在 P1 隔离入口之上验证**真实 Odoo** 的登录/会话/角色/资源/更新清单与公开入口拒绝边界，为后续有限只读公网试运行提供证据；不新增登录系统。
- 当前问题及复现方法：P1 仅用合成上游验证代理链路；真实 Odoo 的冷会话 Cookie 保存、刷新、退出、角色边界、Cookie 标志与安全响应头、Origin/跨来源、限速与 Odoo 冷却关系尚未用真实实例验证。
- 验收标准：
  1) 真实 Odoo 19 隔离实例（私有库/合成账号/独立端口与 data_dir）经**最终 P1 模板**（边缘 Nginx stream → 入口 TLS+PROXY → Odoo）完成：冷登录成功、Cookie 保存、刷新保持、session 接口一致、目录/详情/静态/asset 可读、退出立即失效；
  2) 错误认证与非法 DB 返回完整响应且不泄露堆栈/路径；
  3) next 跳转边界、无角色/目录角色/操作员/管理员访问边界；
  4) Cookie Secure/HttpOnly/SameSite、CSP/nosniff/防嵌入、Origin 跨来源行为；
  5) 匿名更新清单兼容；公开入口对敏感路径/通用 ORM/原生后台默认拒绝；
  6) 两合成来源登录限速与真实 Odoo 冷却互不混淆。
- 允许修改目录/接口：server/ubuntu22.04/bore（入口模板/测试脚本）、lab_team_web 窄修（如发现缺陷且向后兼容）、local/build/bore-p2-20261026 证据、maintenance 任务/审计/交接、必要时 CHANGELOG/CURRENT_STATE。
- 业务不变量/依赖：库存权威 stock.quant/stock.move；不改认证系统；不改生产；不复制生产库/配置/账号；合成测试数据仅限隔离库。
- 负责人/协作者及分工：DSH 实施+隔离证据；Codex 最终审查（独占 bore-p1-codex-review-20261026.md）；用户验收。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan，HEAD 14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71；P1 review2 快照 186 文件（source-server-bore-p1-local-review2-20261026.json）。本轮不重做/不改写 P1 历史快照。
- 环境与凭据获取方式（只写位置，绝不写值）：生产仅通过既有受控 SSH 只读；隔离环境为既有 WSL 私有 PostgreSQL + venv + Odoo 19 + 合成库；测试账号为合成账号。
- 实施步骤：
  1) 生产只读核对（服务/证书/HTTP 跳转/匿名与保护/静态/更新清单/参数白名单/模块元数据）；
  2) 启动私有隔离环境，准备合成用户（无角色/目录/操作员/管理员）与最小目录数据；
  3) 用 P1 模板渲染入口（真实 Odoo 上游），补必要安全响应头后跑 P2 断言矩阵；
  4) 记录证据、修复缺陷（若为模板/窄 API）、repo_check/git diff、必要时新 snapshot。
- 结果：P2 77/0 BLOCKED=2 SKIP=0（exit 0）；P1 94/0；契约 12/0；模块单测 OK；证据 local/build/bore-p2-20261026/。
- 冻结：source-server-bore-p2-final3-20261026.json（194 files, tree 33bbc70…，lab_team_web 19.0.1.0.4）。

- 未验证项及风险：真实公网节点/443、真实用户密码流程、移动端/VPN、P3 写业务、自动续期均不在本轮。
- 发布文件、hash和回滚点：待执行后补记；源变更则新建 server 快照 --activate，旧 manifest 不改写。
