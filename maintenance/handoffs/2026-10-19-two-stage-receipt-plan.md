# 维护交接：2026-10-19 两阶段入库计划书

## 用户目标与已确认边界

形成两个循环的计划：先批量建档、制袋码、打印贴标，再逐袋扫码推荐库位并确认实际入库。标签采用单追溯二维码、袋码文字、型号／名称、关键参数、封装和有则显示的立创编号；SN、品牌可选，初始数量和库位默认关闭。本轮仅编写计划。

## 当前权威源码、分支和版本

分支 codex/two-stage-receipt-plan，起始 commit 28dd8bf032404eee5d1196aff786fd96b2cf8b52。客户端 1.0.1+2，Odoo 与 EDA 版本不变。权威源码及 active-sources.json 未修改。

## 已完成工作与实际证据

- 计划书：docs/development/TWO_STAGE_RECEIPT_PLAN.md。
- 按任务模板记录：maintenance/tasks/2026-10-19-two-stage-receipt-plan.md。
- 更新 CHANGELOG 和 CURRENT_STATE，明确计划尚未实现。
- 环境：本机 PowerShell，Codex 配套 Python 运行时。
- `python tools/repo_check.py --output maintenance/audit/two-stage-receipt-plan-repo-check.json`：退出码 0，49 项检查通过；有 1 项既有 cp312 重建载荷未完成警告。未核验大文件载荷。
- `git diff --check`：退出码 0；提示 CHANGELOG 的 CRLF 将规范为 LF，无空白错误。
- 上述为文档与仓库检查，业务测试执行数为 0；历史测试不作为本次业务验收。

## 剩余工作与阻塞

按计划实施前确定分类参数映射、库位推荐分类依据、标签尺寸与测试设备，再实现服务端待入库记录及客户端两个循环。新功能、ORM 权限与事务、三端原生构建、实体扫码打印均未执行，标记 skipped（本轮文档范围）。当前无文档交付阻塞。

## 依赖和产物

无新依赖、发布包或签名使用，无需新 source manifest。仓库检查详见本任务 audit JSON；已知 production-py312-rebuild 缺口继续有效。

## 生产状态和回滚

未访问或修改生产，未部署、重启、导入或变动库存。文档变更可通过 Git 差异审阅和撤回，不涉及数据库回滚。未提交或推送。
