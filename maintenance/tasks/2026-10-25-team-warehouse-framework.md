# 任务：先确认框架，再委派DSH实施

- 用户目标：统一自有仓库Web前端，后端继续由Odoo承担主要业务，并使用指定DeepSeek Harness会话实施。
- 最新授权：用户已确认框架并要求开始；DSH负责代码与测试，可开子代理，Codex负责方案、决策和验收。第一批为独立入口、登录、仓库搜索和详情，隔离验证后提交审查，不自行上线。
- 本轮授权补充：仅修正根项目与既有app子项目的桥接授权，保留人工审批；已配置并核对成功。允许必要的本机桥接兼容修复，不扩大至其他工程或生产/DNS。
- 草案：docs/architecture/TEAM_WAREHOUSE_FRAMEWORK_DRAFT.md。
- 验收：页面职责、拟议路径、两个入库循环、领用归还、模块分工、第一批范围及业务不变量明确；用户确认后再执行委派。
- 桥接：授权已修正；0.2.0本地兼容补丁通过11项回归。用户完整结束旧进程并重开后，真实采用指定会话成功，返回preset为ptc；第一批append已接受并实际开始执行。任务ID和增量游标保存在Git排除的local/build/dsh-unified-web-phase1-20261025/context.json；实际配置为ali / deepseek-v4.1-flash-1017 / high。此前两个错误空白绑定均关闭，未向其append。
- 结果：第一批候选由DSH完成，Codex核心隔离浏览器验收通过；65项逻辑测试通过、1项跳过，11项Odoo HTTP测试通过。175文件候选源已冻结，生产未部署。最终限制和交接见maintenance/handoffs/2026-10-25-team-web-phase1.md及maintenance/audit/team-web-phase1-codex-review.md。
