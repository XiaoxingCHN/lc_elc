# 任务：网页视觉与交互统一方案（全站 + 旧操作台迁移）

协作偏好（用户本轮明确）：大部分工作由 DeepSeek 子代理完成，Codex 主审，必要时视觉审查；可选 Qoder DeepSeek、WorkBuddy DeepSeek、CodeArts DeepSeek。本轮实际执行为前两种，未调用 CodeArts。

- 目标/用户场景：用户反馈录入来料的编号及关键词搜索缺乏候选与即时反馈；此前"全站风格统一"尚未完成，且旧 Odoo 扫码/入库操作台等日常页面仍可能是旧样式。需要一份覆盖自有 UI 与旧操作台迁移的方案，供 Codex 审查。两份独立只读审查（交互 `local/legacy-web-team/ux-audit.md`、旧入口 `local/legacy-web-team/entry-audit.md`）与本轮 Codex 初审意见均已按源码复核后合并。
- 当前问题及复现方法：`lab_team_web/static/src/js/pages/receipts.js:558` 只解析完整料号，无关键词候选；`receipts.js:585` 无请求序号保护；`lab_workflow/views/lab_scan_views.xml` 仍是 Bootstrap + 内联脚本的旧控制台，`GET /lab/scan` 仅在 `lab_web.py:49-52` 条件满足时 303 到新页，否则回退旧模板；旧报告 `maintenance/audit/style-unification-20261024.md` 的 100% 为自述，不能作为视觉验收。
- 验收标准：方案覆盖 18 个自有路由 + 旧操作台迁移矩阵（入口/当前实现/目标页/业务能力/未证实状态）、桌面与窄屏布局、完整来料操作台样板、全站组件与反馈约定、分期顺序、逐入口验收清单；明确"能力等价再切换、旧 GET 白名单映射保留业务上下文、旧 POST 不重定向重放、管理员原生维护保留、不换色冒充完成"；本轮不编码。
- 允许修改目录/接口：仅 `docs/requirements/WEB_UI_UNIFICATION_PLAN_20261102.md`、`maintenance/tasks/2026-11-02-web-ui-unification-plan.md`、`maintenance/handoffs/2026-11-02-web-ui-unification-plan.md`；无接口变更。
- 业务不变量/依赖：实验室库存以 `stock.quant`/`stock.move` 为权威；两阶段入库（制袋不加库存、上架确认才入库）；领用人须系统账号、归还关联原领料；权限、CSRF、`request_key` 幂等、行锁与未知结果保护不变；`bore` 白名单不扩大。生产、客户端、版本与 registry 不改。
- 负责人/协作者及分工：DSH（本会话）负责只读盘点与方案修订；Codex 负责范围、共用规范、设计与最终验收决策，必要时做真实界面视觉审查。
- 分支/起始commit/源码manifest：`codex/receipt-search-feedback`；起始 `b3bcbf244e44939c6d481e3f97f11579cdf9ee99`；既有 `maintenance/registry/source-server-p3-web-20261028.json` 不改。
- 环境与凭据获取方式：本机源码只读；不连生产、不读取真实凭据、不登录线上补结论。
- 实施步骤：停止此前下发的实现轮次；只读盘点自有页面与旧菜单/表单/向导/跳转；修订方案文档（含迁移矩阵、布局、组件、分期、逐入口验收）；运行 `python tools/repo_check.py` 与 `git diff --check` 记录实际结果；写交接供 Codex 审查。
- 测试命令、实际结果与退出码：`python tools/repo_check.py` → `PASS` / 52 项 / `errors: []` / **exit 0**（`production-py312-rebuild` 警告不变）；`git diff --check` **exit 0**；三份文档行尾空白自查 `TRAILING_TOTAL=0`。本轮仅文档，业务测试不适用；未做视觉验收。详见交接。
- 未验证项及风险：未实时渲染任何页面；生产状态只到 2026-10-28 登记时点（`lab_workflow 19.0.1.2.0`、`lab_team_web 19.0.1.0.5`），当前版本与 `scan_redirect` 参数值未核实；旧菜单在生产菜单树中的实际可见性、矩阵 xmlid 升级后存在性、目标路由是否注册均未核实；旧控制台三卡能力对齐只做源码级；旧模板隐藏/下线、菜单改指需要单独授权。
- 发布文件、hash和回滚点：无发布，无构建产物；旧源码快照与产物不变；回滚 = 还原上述三份文档（均未提交）。
