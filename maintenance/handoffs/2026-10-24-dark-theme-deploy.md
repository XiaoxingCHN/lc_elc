# 维护交接：2026-10-24 暗色主题上线

## 用户目标与边界

用户明确要求读取风格统一内容并上线。仅部署器件库主题与资产 manifest，升级 lab_catalog、必要重启；未修改库存逻辑、DNS、采集、客户端或其他服务。

## 当前权威源码、分支和版本

权威源 server/ubuntu22.04/odoo_addons/lab_catalog，lab_catalog **19.0.2.0.4** 已上线；lab_inventory19.0.1.0.0、lab_workflow19.0.1.2.0保持 installed。现分支 codex/two-stage-receipt-plan，工作树未提交。最终冻结清单 source-server-dark-theme-final-20261024.json，132 文件，tree SHA256 f265ae1e5548023d93a4bd8e22f454a5d2533adb7190f4e59189608967226cb6。

## 已完成与证据

详见 maintenance/audit/dark-theme-deploy-20261024.json。修正外部改稿使用错误类名导致卡片/工作流/响应式布局丢失的问题；保留实际 XML 结构，按暗色、荧光绿风格重设样式。主题 screen media 隔离；打印效果仍未实测。原重启脚本不能备份生产旧代码、不能更新资产 manifest，已改成只读载荷检查，未执行原脚本。

首次候选在生产同 ABI libsass 编译时因 CSS min() 失败，尚未触及生产；修正 width/max-width 后新建不可变 final 快照，旧快照和原稿保留。最终 SCSS 编译17113字节；108个生产模块源文件匹配。仅 -u lab_catalog，exit0、服务active、升级及168行运行日志 ERROR/CRITICAL/Traceback均0。

真实临时认证会话请求后台200，获取两份真实 CSS 资产200，包含主题选择器/配色且无编译错误；临时会话已删除，认证值未输出。数据库验证事务只读回滚，不写测试库存。bag1/quant2/move1/operation1/catalog695217/location16/pending1/trace2，quantity/reserved均0，前后一致。Android清单200、Windows/Linux204，stable指针hash不变。维护工具11项测试通过exit0；仓库检查另见本轮repo-check审计。

## 剩余与限制

浏览器初始化超时，未完成可视化、手机布局或真实悬停验收，不将HTTP成功视作视觉通过。原报告“100%完成”“完全一致”“对比度≥7:1”未获验证。物理打印、完整恢复演练、离机备份、完整离线载荷核验均未执行。无关未跟踪 Python/、clients/app/t.obj 保留未动。没有执行GitHub推送。

## 依赖和产物

现有Odoo19/Python3.12/libsass，无新增依赖。部署包 local/build/dark-theme-20261024/server-dark-theme-19.0.2.0.4-final.tar.gz，11538137字节，SHA256 c76c2f8d7e5b5ca31c2940d80749aa66d819c8e84d0377312f92aa0a7d0329d9。原始改稿与安全操作配方保留在同目录。配置/凭据未入Git。

## 生产与回滚

本轮配套备份 `/var/backups/lc-elc/20261024T115739Z-before-dark-theme`，数据库/filestore hash与134个附件逐个核验、pg_restore --list exit0。旧模块在该备份的 module-source-before-upgrade/lab_catalog，位于 addons 扫描范围之外。阶段目录 `/opt/odoo/deployments/dark-theme-20261024-a2` 保留升级日志、受控配置及完整审计。

如出现视觉问题，优先发布新样式修复。必须回滚时先保存当前源/数据，核验绝对路径包含关系，停服务，从备份恢复旧模块、按资产注册需要升级目标模块并重启验证。不要盲用 HEAD~1 或直接清空整个 filestore。完整数据库恢复需要新的明确授权，且会回退备份后的业务写入；不是样式问题的默认处理方式。

## 最终仓库检查补充

未过滤的 tools/repo_check.py exit1：49项通过，30项语法错误均来自用户新增但未跟踪的 Python/pythoncore-3.15-64/Lib，项目检查器Python3.12不支持其新语法。原始FAIL保存在 dark-theme-repo-check-20261024.json；不算整仓PASS。临时仅对本次检查排除该无关本机载荷后49项通过exit0，见 dark-theme-scoped-repo-check-20261024.json；未改Git忽略配置、未移动或删除Python目录。已知production-py312-rebuild警告保留，未执行--verify-payloads。git diff --check exit0。开发机LAN登录/主题CSS/Android清单均200。
