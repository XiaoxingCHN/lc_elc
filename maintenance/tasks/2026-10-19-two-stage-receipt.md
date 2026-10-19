# 任务：两阶段入库实现

- 目标/用户场景：按已确认计划实现制袋贴标与扫码上架两个循环；使用 apple-ui-designer 设计、apple-design 审查，保持三端共享 Flutter 源。
- 当前问题及复现方法：原客户端只能实际入库后打印袋码，无法先批量贴标再上架。
- 验收标准：制袋、打印不改变库存；扫码确认后只入库一次；补打沿用原码；取消、权限、公司隔离及旧业务回归正确；记录真实测试数量和限制。
- 允许修改目录/接口：clients/app、server/ubuntu22.04/odoo_addons/lab_workflow 及相关文档、registry、任务交接与审计。新增 pending/list、create、update、resolve、confirm；标签新增 pending 类型。
- 业务不变量/依赖：库存以 stock.move/stock.quant 为准；同立创编号合并展示；每袋独立码；离线只读公开缓存；操作人由服务端会话确定。
- 负责人/协作者及分工：Codex 单代理，无代理并行。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan；28dd8bf032404eee5d1196aff786fd96b2cf8b52；实施前 active-sources 指向归档快照，完成后新增候选源快照，旧 manifest 不改。
- 环境与凭据获取方式：Flutter 3.47.7 / Dart 3.13.5，Windows 本机组件测试；WSL 既有只读 Odoo 19 / Python 3.10 运行时，命名空间内新建 PostgreSQL 临时库；仅用测试夹具账号，无真实凭据。
- 实施步骤：沿用计划与源码核对；实现服务端状态和事务；实现两个客户端循环与标签；组件、隔离事务与 HTTP 并发测试；设计审查；记录并冻结候选源。
- 测试命令、实际结果与退出码：见 docs/development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md 和本任务交接。
- 未验证项及风险：原生三端安装包、相机/扫码枪及实体打印未验收；进程内并发夹具锁等待单列，不当作通过。
- 发布文件、hash和回滚点：仅候选源码，无发布包、部署、提交或推送；旧发布物和来源快照保留。
