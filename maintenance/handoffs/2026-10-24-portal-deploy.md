# 维护交接：2026-10-24 门户上线

## 用户目标与边界

用户要求推送提供的lab_portal更新到现有服务器。仅修正/安装门户，完整备份并必要重启；未改DNS、现有三个模块源码、库存逻辑、客户端或采集。

## 当前权威源码、分支和版本

server/ubuntu22.04/odoo_addons/lab_portal，**19.0.1.0.0 installed**。原lab_catalog19.0.2.0.4、lab_inventory19.0.1.0.0、lab_workflow19.0.1.2.0保持installed及源字节一致。分支codex/two-stage-receipt-plan，工作树未提交。最终源清单source-server-portal-final-20261024.json，154文件，tree SHA256 3e097d12bfee93577b3d8a7ba954f2260a2fbd91844f60b89d3eb340978820bd。初次source-server-portal-20261024.json是原稿中间快照，未部署，不改写。

## 已完成与实际证据

审计maintenance/audit/portal-deploy-20261024.json。原稿不是有效XML，继承定位不存在、图片路径不正确且登录按钮循环/CSS隐藏登录表单；已改为独立QWeb首页和website首页控制器，依赖已安装website。匿名访问/显示首页，管理系统链接/web/login?redirect=/odoo，登录表单保持原生；已登录根路径303到/odoo。门户CSS/JS只在独立首页引用，不污染后台/登录页。

隔离恢复副本中-i lab_portal成功，首页200、5个主体section、13个引用资源、原生登录表单/CSRF、错误凭据提示保持均通过。首次隔离测试因日志文件权限验证失败，补足权限后重试；未把失败算PASS。临时克隆库一度让生产匿名访问落入数据库选择器，已只清理本轮临时库lc_portal_verify_20261024，随后匿名首页/登录及认证路由全量复核通过。隔离HTTP进程已终止，私有测试文件留在受控阶段目录，不入Git。

生产完整备份后仅-i lab_portal，exit0、服务active；130个模块文件匹配，原108个文件未变。认证后台200、匿名首页200、13资源逐字节hash匹配，原生登录表单/CSRF存在；临时认证会话根路径303到/odoo、后台200且会话已删除。未执行真实账号密码登录。库存bag1/quant2/move1/operation1/catalog695217/location16/pending1/trace2及quantity/reserved0前后一致；更新Android200、Windows/Linux204，stable hash不变。升级日志及122行运行日志ERROR/CRITICAL/Traceback均0。维护工具11测试通过；repo-check见独立审计。

## 剩余与阻塞

Computer Use因无法可靠确认当前浏览器URL停止，IAB/Edge连接亦超时，未完成视觉/手机验收，不冒称显示完全一致。原后台白表浅字、紫色导航问题未修，用户此前截图已证明主题视觉验收不通过。完整恢复演练、离机备份未做。

## 依赖和成品

无新增系统依赖。server/releases/2026-10-24-portal/server-portal-19.0.1.0.0.tar.gz，12611497字节，SHA256 8e54e2e1e51c63ca792ab8888010f958ba4feaa0baea0b09f48228b1af2c77e7；同目录SOURCE_MANIFEST.json。原始门户改稿、配方存local/build/portal-20261024。来源登记artifact-server-portal-20261024.json。

## 生产与回滚

完整备份/var/backups/lc-elc/20261024T124820Z-before-portal，DB dump及filestore hash、141附件逐个核验，pg_restore --list exit0。旧三模块源码另存/opt/odoo/deployments/portal-20261024-a1/old-source.tar.gz，门户原先不存在。本轮阶段目录保留受控配置及验证日志，凭据不导出。

回滚优先发布控制器恢复原首页委托super().index，而非盲删已安装模块目录；后续需要新版本/新冻结及验收。卸载或整库恢复需要对应明确授权，整库恢复会回退备份后的业务数据。既有备份工具源指纹仍枚举三个原模块，后续完整源码备份必须另包含lab_portal或采用已冻结完整源包，不要误称该指纹已覆盖门户。

## 最终开发机检查

开发机LAN匿名首页、原生登录、Android清单均200。git diff --check exit0。完整repo_check exit1，49项通过，30个语法错误全部是未跟踪Python3.15标准库对Python3.12检查器不兼容；未修改该目录，不冒称完整PASS。仅临时排除/Python/本机载荷后49项通过exit0，已知production-py312-rebuild警告保留，未执行--verify-payloads。见portal-repo-check-20261024.json及portal-scoped-repo-check-20261024.json。
