# 验收证据

> 归档证据索引。旧测试结果按对应时间与版本阅读，现行验收见[当前状态](../docs/operations/CURRENT_STATE.md)。

2026-10-18/保存精选原始JSON（当前UI/权限/条码/源冻结），对应历史修复真实结果；maintenance/audit保存本次归档新路径检查摘要。二者不能混为同一次验收。

完整构建日志、一次性脚本和历史截图保存在 `local/archive/evidence` 或[退役补档所登记的位置](../maintenance/handoffs/2026-11-14-workspace-retirement.md)。不把SSH包装器、聊天、会话状态和真实凭据提交Git。引用日志时仅输出必要计数、退出码、路径与hash。

2026-10-19 归档时记录 EDA 105 项单测、13 项打包测试与构建/verify均通过；重建eext/bundle与已发布3.0.3字节hash相同。服务端纯逻辑26项、1跳过；不代表本轮重新部署或生产业务写入。
