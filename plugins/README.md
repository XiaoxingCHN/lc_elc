# 嘉立创 EDA 专业版插件

当前本机候选是 `4.2.0`，成品在 `jlc-eda/releases/4.2.0/`。在扩展管理器导入 `lab-inventory-odoo_v4.2.0.eext`，从「连接设置」填写服务器和库存管理员发放的 EDA 密钥。

4.x 使用 Odoo 的 `lab_eda` 模块直接鉴权。插件没有本机安装服务或 Node 运行时要求。旧 3.x 的桥接资料用于历史维护。EDA 负责器件查询、原理图或 PCB 的 BOM 库存对比、手动选替代料和按袋领用。Web 与 Flutter 继续负责日常库存管理。

[插件安装说明](jlc-eda/README.md) · [成品索引](../releases/README.md) · [构建与验收交接](../maintenance/handoffs/2026-11-23-client-eda-alignment.md)。
