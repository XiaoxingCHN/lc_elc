# 当前状态与已知限制

归档基线：2026-10-19。当前说明优先于local/archive中的旧README。计数是相应证据的时点快照，不是永久业务要求。

2026-10-19 已完成[两阶段入库实现与验收](../development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md)：客户端 **1.1.0+3** 三端原生候选包已重建，尚未发布；Android签名匹配，Windows进程冒烟及Linux动态依赖检查通过，三端界面、安全存储和实体扫码打印仍待验收，见[原生交接](../../maintenance/handoffs/2026-10-19-native-candidates.md)。**lab_workflow 19.0.1.1.0 已上线**，服务active、HTTP200，权限与单QR标签PDF检查通过。升级前后bag1、quant2、move1、operation1、catalog695217、location16及数量/预留总量0一致，pending0、trace1，历史袋码无缺漏；未写入生产测试库存。详见[上线交接](../../maintenance/handoffs/2026-10-19-server-deploy.md)及[审计](../../maintenance/audit/server-deploy-20261019.json)。

本轮完整回滚备份 `/var/backups/lc-elc/20261019T073840Z-before-upgrade` 与部署目录 `/opt/odoo/deployments/two-stage-20261019-a1/old-source.tar.gz` 配对；数据库和154个附件的实物/hash已核验，未离机备份或完整恢复演练。首次升级因工具把旧模块保留在addons根而失败，移出后重试成功；工具已修复并通过108项故障测试，最终服务端源清单为 `source-server-two-stage-receipt-opsfix-20261019.json`，104个业务文件与原候选一致，额外3个运维修复文件已同步。active-sources 指向最终源；所有历史manifest和发布包来源保持不变。

## 归档发布版本和权威源

以下版本与逐文件核对事实均为归档时点，不代表当前候选源仍与旧安装包字节一致。

| 组件 | 当前版本 | 维护源/成品 |
|---|---|---|
| Flutter Windows/Android/Linux | 1.0.1+2 | clients/app / clients/<platform>/releases/1.0.1 |
| lab_inventory | 19.0.1.0.0 | server/ubuntu22.04/odoo_addons/lab_inventory |
| lab_catalog | 19.0.2.0.3 | 同级lab_catalog |
| lab_workflow | 19.0.1.0.2 | 同级lab_workflow；20261018精简与权限修复包 |
| EDA专业版插件 | 3.0.3 | plugins/jlc-eda；Node桥接同目录bridge |
| 中文采集/资料导入编排 | 20261019服务器只读快照 | services/lcsc/systemd-production；采集源码server/ubuntu22.04/crawler |

具体来源及SHA在maintenance/registry。当前客户端66个Dart/pubspec业务文件已与原构建冻结和三端构建副本核对；Odoo102文件在初始导入时与最新修复ZIP相同；随后新副本仅规范化客户端两行空白和网页XML末尾多余空行，原始文件另存且变换hash/patch已登记（import-transformations.json），业务逻辑不变。干净Git克隆测试另发现Flutter模板忽略了Gradle启动文件，现已显式跟踪jar/gradlew；生成registrar与IDE状态转存历史，当前完整源指针按修正后的新manifest登记。完整源树本次另建立baseline manifest，UTF8文本指纹按LF归一化，另保留导入原字节hash，兼容Windows/Linux Git换行。

## 已知生产事实（来自20261018验收，归档仅只读复核必要元数据）

- Odoo192.168.31.105:8069，DB LcHardwareHouse；三个模块installed、服务active、HTTP200。
- 器件695217、参数4110477、分类2791；卸载40个无关模块、保留52个业务模块及依赖。
- 网站6页内容hash、保留模块账号权限一致。系统记录6账号含模板/非活动，普通列表3个。
- 当前没有实验室库存/bag/领料数据；POS自带默认产品随卸载移除，未删除真实库存。
- 权限26项事务回滚测试、7组件测试、9浏览器项通过，条码PNG/PDF生成成功；物理打印机未测。
- 归档只读导出确认每日03:30开始/05:30结束（Asia/Shanghai），OnSuccess触发Odoo资料导入；未在本轮重新跑采集/导入。
- 生产备份在服务器/opt/odoo/backups/module-cleanup-production-20261018T153740Z，未下载完整生产数据库到本地。

## 本轮归档实际验证

- 所选来源到目标逐文件复制核对SHA256；完整记录local/manifests/migration-files.json（已完成；旧progress仅为故障续传记录，最终以迁移摘要和完成报告为准）。
- EDA在新路径105/105单测、13/13包测试、build与verify均exit0，重建eext/bundle与旧发布物hash相同；没有冒称真实EDA宿主再导入验收。
- 服务端纯逻辑26项运行、1跳过，exit0；不是Odoo ORM生产重测。
- 现有运维故障夹具100项检查在新路径/WSL root通过，不访问真实PostgreSQL或systemd；初次非root前置失败已记录。
- 新维护工具8项通过：源码冻结/换行、机密扫描、离线导入覆盖/越界保护、构建dry plan。
- 最终安卓APK公开证书8b4c…ff43，已与原Windows离线密钥匹配；WSL默认key640b…a5ff不是最终发布身份。公证书明文登记、私钥Git排除。
- 原WSL工具已只读导出4.4GB（JDK/SDK/Flutter/cache及Linux适配），路径/成员/hash见registry/wsl-toolchain.json。没有搬迁或修改原WSL SDK。

最终源码/Git边界检查通过；空目录克隆的源码检查、8项维护测试、路由一致性与构建dry-run四项均通过。具体结果见maintenance/audit及归档完成报告，不能仅以本段静态说明当成功证据。

## 仍需知道的边界

1. 三端当前包是导入的既有1.0.1成品，不是从本次未来Git commit全量重编译的新包。Android按用户约定未模拟器测试；Linux1.0.1未重新完整做SecretService/CUPS/实体打印。原客户端测试233通过、5跳过，保留其来源。
2. 新通用build_client入口本次检查dry-run与工具测试，不保证便携VS或旧WSL私有adapter解包后无需调整即可编译。标准VS与Linux开发依赖有明确获取步骤。
3. 旧Ubuntu离线整包是20261015快照，不含今天最新全部修复，保留为历史。全新cp310闭包与生产cp312 ABI不同；已导出生产70个公开包版本锁，但完整cp312 wheelhouse还需同ABI准备机生成和隔离验收。
4. 新npm缓存联网准备曾180秒超时，不能标为npm ci --offline已通过；当前node_modules和lock已保存，新路径EDA构建已通过。按依赖指南可联网重新填缓存。
5. 原有部分器件图片资源404仍存在，未借归档修复；没有全量手册离线镜像。
6. GitHub远端尚未创建/推送；CI流程已准备但未云端运行。离线大文件仍在本机，离开本机前需导出可信载荷及单独私钥备份。
7. 历史原始聊天/补丁/候选源码保留在旧目录或local归档，不自动进入Git，不应盲执行。旧计划/计数不代表当前状态。
