# 任务：战队仓库 Web 入口 第一批（独立入口/登录/检索/详情）

- 授权与分工：用户已确认框架；Codex 负责方案、关键决策与验收，DSH 负责实现与测试，允许子代理。
- 草案与契约：docs/architecture/TEAM_WAREHOUSE_FRAMEWORK_DRAFT.md、
  docs/architecture/TEAM_WAREHOUSE_API_CONTRACT.md。
- 允许改动：新增 server/ubuntu22.04/odoo_addons/lab_team_web/**、
  对应 tests/审计/交接/CHANGELOG；**不改** lab_theme、lab_site 与既有三模块业务代码。
- 不做：生产安装/升级/重启/卸载、DNS/代理/HTTPS、GitHub 推送。

## 通过条件

1. 欢迎页/登录/仓库检索/器件详情构成可运行纵向流程（服务端渲染 + 渐进增强）。
2. 匿名访问进本站登录并带完整 next；登录后回到同一深链接（含 `lcsc:C123` 冒号）。
3. 权限由服务端判定：无目录角色 403，非法 itemKey 400，不存在 404。
4. 不破坏旧官网、网站编辑器、原生后台与原生登录；`root_aliases=0` 时根别名真实 404。
5. 深色+荧光绿设计，窄屏可用，文字可读；未实现能力显示"暂未开放"而非假成功。
6. L1 纯测试与 L2 Odoo 隔离测试可复现；浏览器视觉由 Codex 验收。

## 结果

- 见 maintenance/audit/team-web-phase1-report.md 与 handoff。
