# 交接：2026-10-19 更新器候选

用户要求实现已确认方案。主代理独立开发；未新上线、发布stable或推送代码。GitHub原功能/方案分支仍停在8df35b5。

client1.1.1+4、lab_workflow候选19.0.1.2.0；生产19.0.1.1.0不变。当前完整清单source-client-updater-releasecheck-20261019.json和source-server-updater-20261019.json已激活；早期prebuild/final快照保留，不更改旧成品来源。实现和接入见[实现说明](../../docs/development/CLIENT_UPDATE_IMPLEMENTATION.md)，包/hash/环境/命令及日志指纹见[审计](../audit/client-updater-20261019.json)。

启动/恢复检查、签名清单、同源会话下载、费用策略、取消和校验、更新面板、Android系统安装、桌面独立助手、准备握手和失败回退已实现。桌面目标机无需Python/Dart。私钥不分发，只保留公钥登记。

Flutter全量264通过5跳过（含22项更新器测试）；维护10通过1跳过；Odoo54通过1跳过，HTTP并发6通过；分析无error/warning。三端从冻结源构建，Android证书匹配，Linux动态依赖无缺失。实际面板已渲染，200%文字、明暗及窄屏通过。

故障日志单列保留：登录fixture未隔离自动探测导致挂起Timer，已修正fixture并暂停卸载后的重试；隔离/dev缺随机设备导致HTTP原生组件abort，补标准设备绑定后通过；Windows打包工具显式UTF8修复。未把这些失败或跳过算PASS。

下一步是两个真实原生版本的完整升级/回退、Android权限/取消和数据保留、真实计费网络、实体扫码打印及断电验证，然后按发布流程单独授权部署服务端和stable清单。第一版不做差分、断点续传或强制安装。旧版需先人工安装完整更新器包。本轮包默认本地验收服务，尚无stable清单。

产物在local/build/updater-20261019，交付取审计标记validated的包，不按mtime选择。依赖/签名key-id见client-update-dependencies-20261019.json；私钥在Git排除位置，不复制服务器或记录聊天。桌面未做OS签名，Android仍为既有debug证书。

生产没有新改动；此前回滚继续按server-deploy交接的首份DB/filestore/旧源码配对。客户端保留旧完整目录和事务状态，断电中断须验证绝对路径、标记及版本后人工恢复，不自动删除。
