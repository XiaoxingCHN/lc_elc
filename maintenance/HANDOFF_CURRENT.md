# 当前维护交接：2026-10-19 两阶段入库候选

后续：本轮功能/生产交接已上传既有GitHub的 `codex/two-stage-receipt-plan` 分支（功能提交0716829）；[客户端自动更新方案](../docs/development/CLIENT_UPDATE_PLAN.md)已梳理，尚未实现、未发布更新包，见[本轮上传与方案交接](handoffs/2026-10-19-github-update-plan.md)。

最新交接见 [服务端已上线](handoffs/2026-10-19-server-deploy.md) 和 [原生候选包](handoffs/2026-10-19-native-candidates.md)。生产lab_workflow **19.0.1.1.0**、三模块installed、服务active/HTTP200，库存及袋记录数量未改变；完整备份、权限与标签检查已核验。部署工具保留旧模块位置缺陷已修复，最终服务端源指向opsfix清单，108项故障测试通过。客户端1.1.0+3三端候选包构建完成但未发布，Windows仅进程冒烟，三端界面、安全存储和实体扫码打印仍待验收。功能与隔离测试见 [两阶段入库实现](handoffs/2026-10-19-two-stage-receipt.md)。

以下保留归档交接背景，版本和完成事实指归档时点，不代替最新候选源记录。

## 工作根和规范

新工作根F:/lc_elc，原F:/lc_elc_workspace只作来源/历史，不再在旧源上改功能。先读README、AGENTS、CURRENT_STATE和ARCHIVE_REPORT。

## 版本

客户端1.0.1+2；Odoo inventory19.0.1.0.0/catalog19.0.2.0.3/workflow19.0.1.0.2；EDA3.0.3。当前源指针在maintenance/registry/active-sources.json，安装包与原始/维护源的关联在releases.json。

## 已完成

各当前组件/成品/离线载荷/历史明确分层，138000余条文件迁入记录逐项校验；原目录零删除。原WSL工具另导出4.4GB。Git未包含SDK、数据、安装包或私钥。最终纯Git空目录克隆四项检查通过。

## 下次从哪里开始

- 新功能/bug：任务模板→分支→对应唯一源→测试→新冻结--activate→发布，旧manifest/包不覆盖。
- 待处理的真实缺口：KNOWN_GAPS，尤其生产完整cp312 wheelhouse、离机备份、npm离线缓存验证和部分原生实机验收。
- 凭据不在仓库。Android匹配密钥在local/private/signing，公开证书registry/android-signing.json；不要使用证书不同的旧WSL默认key。
- 本次没有部署、重启服务、写生产库存或恢复采集；生产仅限定只读核对。GitHub私有远端/推送需由所有者给URL再执行。

## 证据

maintenance/audit保存新路径测试与克隆检查；evidence保存精选历史验收；完整复制/处置映射在local/manifests，原始构建/一次性脚本在local/archive。不可把已提交或历史通过直接称当前新包验收通过。
