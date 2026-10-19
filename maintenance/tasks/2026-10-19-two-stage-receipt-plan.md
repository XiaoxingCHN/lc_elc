# 任务：两阶段入库计划书

- 目标/用户场景：先批量建档生成袋码并打印贴标，再逐袋扫码选择库位确认入库；本轮交付计划书。
- 当前问题及复现方法：现有标签页只允许选择已入库袋，无法先制袋码再入库，详见计划书现状依据。
- 验收标准：明确两个循环、标签字段、库存提交边界、接口与权限范围、异常和验收场景，文档检查通过。
- 允许修改目录/接口：本轮仅 docs、maintenance 文档和 CHANGELOG；不修改业务接口或源码。
- 业务不变量/依赖：stock.quant/stock.move 为库存权威；单袋单追溯码；离线只读公开缓存；生产操作另行授权。
- 负责人/协作者及分工：Codex 单代理编写，无并行代理。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan；28dd8bf032404eee5d1196aff786fd96b2cf8b52；沿用 maintenance/registry/active-sources.json，不冻结业务新版本。
- 环境与凭据获取方式：本机 PowerShell 与可用 Python 运行时；无需凭据。
- 实施步骤：核对现状与模板 → 编写计划 → 仓库及差异检查 → 写交接。
- 测试命令、实际结果与退出码：见同任务交接和 maintenance/audit/two-stage-receipt-plan-repo-check.json。
- 未验证项及风险：全部新业务尚未实现；未执行组件、ORM、三端和实体扫码打印测试。
- 发布文件、hash和回滚点：计划位于 docs/development/TWO_STAGE_RECEIPT_PLAN.md；无新安装包、源码快照或部署。
