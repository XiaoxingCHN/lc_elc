# 最新上线状态

2026-10-25：**lab_team_web 19.0.1.0.0 已完成候选验收，生产发布正在执行**。独立欢迎、登录、仓库检索和详情使用自有布局；本轮仅安装新模块，保留原 API 与旧站。当前结果以[发布任务](../maintenance/tasks/2026-10-25-team-web-publish.md)和后续生产审计为准，尚不代表域名已切换。

2026-10-24：lab_portal 方案已废弃、源码已移除，最近生产审计为 uninstalled；[门户交接](../maintenance/handoffs/2026-10-24-portal-deploy.md)仅保留历史安装证据。

2026-10-24：**lab_catalog19.0.2.0.4 暗色主题已上线**。仅更新主题与资产配置，服务active、认证后台/主题CSS200、库存计数和更新通道不变；视觉及手机验收尚未完成。备份与验证见[主题交接](../maintenance/handoffs/2026-10-24-dark-theme-deploy.md)。

lab_workflow19.0.1.2.0更新接口已按本轮明确授权上线，服务active，Android manifest200（1.1.3+6 stable）、Windows/Linux204；备份、权限和库存不变证据见[交接](../maintenance/handoffs/2026-10-19-update-endpoint-deploy.md)。以下此前候选/部署说明为各自时点。

# Odoo服务端唯一维护入口

当前源码和部署工具在[ubuntu22.04](ubuntu22.04/)；三个自定义模块在odoo_addons。保持内部布局，升级脚本会按自身目录导入lc_odoo_conf.py，安装器会寻找tools/crawler/odoo_addons。不要只移动一个脚本。

- lab_inventory 19.0.1.0.0：依赖stock/product/mrp，属于必要业务底层。
- lab_catalog 19.0.2.0.3：资料与统一网页仓库。
- lab_workflow 19.0.1.1.0：库存工作流、两阶段入库、追溯标签和角色显示；2026-10-19已上线，实际版本、备份和验收见[本轮交接](../maintenance/handoffs/2026-10-19-server-deploy.md)。
- 当前维护源为19.0.1.2.0候选，新增客户端更新只读分发接口，尚未部署，见[更新器实现](../docs/development/CLIENT_UPDATE_IMPLEMENTATION.md)。分发根取Odoo真实data_dir，不与库存附件混放。

归档成品修复包在releases/2026-10-18，导入时与源102文件hash逐项一致；后续候选源码已变更，不能再把该旧包当作新源码构建物。旧Ubuntu整包在local/archive/packages，仅是20261015历史，不能拿旧包覆盖当前模块。

[开发](../docs/development/SERVER.md)、[升级/备份/恢复](../docs/operations/SERVER.md)、[生产快照状态](../docs/operations/CURRENT_STATE.md)。生产采集定时定义另见services/lcsc；服务源码仍在ubuntu22.04/crawler，只有一份可编辑权威源。

初始归档未重新上线，后续两阶段入库已按本轮授权独立部署。新装cp310离线闭包与现有生产cp312不是同一环境，不能混装条码wheel。升级前必须核实实际data_dir；旧模块保留目录必须在addons扫描范围之外，见[运维说明](../docs/operations/SERVER.md)。
