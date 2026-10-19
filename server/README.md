# Odoo服务端唯一维护入口

当前源码和部署工具在[ubuntu22.04](ubuntu22.04/)；三个自定义模块在odoo_addons。保持内部布局，升级脚本会按自身目录导入lc_odoo_conf.py，安装器会寻找tools/crawler/odoo_addons。不要只移动一个脚本。

- lab_inventory 19.0.1.0.0：依赖stock/product/mrp，属于必要业务底层。
- lab_catalog 19.0.2.0.3：资料与统一网页仓库。
- lab_workflow 19.0.1.0.2：库存工作流、追溯标签和角色显示。

当前成品修复包在releases/2026-10-18，与源102文件hash逐项一致。旧Ubuntu整包在local/archive/packages，仅是20261015历史，不能拿旧包覆盖当前模块。

[开发](../docs/development/SERVER.md)、[升级/备份/恢复](../docs/operations/SERVER.md)、[生产快照状态](../docs/operations/CURRENT_STATE.md)。生产采集定时定义另见services/lcsc；服务源码仍在ubuntu22.04/crawler，只有一份可编辑权威源。

本次归档不重新上线。新装cp310离线闭包与现有生产cp312不是同一环境，不能混装条码wheel。
