# 归档验收与交接

日期：2026-10-19。新维护根：F:/lc_elc。用户确认：当前可用版+独立历史，中文文档/英文目录，Git准备私有GitHub，大文件本地保留并记录获取方法。

## 已完成

- 当前共享Flutter源、三端完整成品、Odoo模块与运维脚本、EDA与Node桥接、中文采集与同步编排均有唯一维护入口。
- 已登记原目录 178157 个文件条目；其中 138285 个来源条目有明确迁入映射。所有原文件删除数为0。
- 未迁入当前维护源的构建缓存、浏览器/代理会话、一次性诊断与未发布候选仍保留原目录；逐个原因在local/manifests/original-disposition.json。不是把所有旧目录平铺复制进Git。
- 核心迁入文件逐项核对来源与目标SHA256；SQLite重复副本经过全量hash判断后在新目录引用同一历史快照，原数据库没有删除。
- 补充实际WSL工具归档4436412077字节；Node runtime/字体/许可证等所需文件保留。匹配Android密钥已不透明复制到local/private/signing，公开证书8b4c…ff43，不入Git。
- 数据、SDK、安装包、签名/会话材料均被Git排除；29组大文件/外部依赖/私有材料有来源、具体路径和获取恢复命令。
- 归档格式变换和Android Gradle跟踪修复都有原始副本、前后hash与理由；不改变业务逻辑。GeneratedPluginRegistrant和IDE状态归历史，.g.dart模型仍是源码。

## 本轮真实验证

- EDA新路径105单测+13包测试、构建/verify成功；重建eext与bundle和现有3.0.3发布物完全同hash。
- 服务端纯逻辑26项运行，25通过、1跳过；没有假称Odoo ORM/生产流程本轮重测。
- 运维故障夹具100/100通过；WSL root仅为临时归属检查，PostgreSQL/systemd均stub。第一次非root的前置失败保留在日志。
- 新维护工具8项通过（包括越界/覆盖保护、凭据输出边界、源冻结、当前指针切换不覆盖历史）。
- 正式Shell脚本19个bash -n通过；没有执行部署脚本。
- 关键载荷/成品/数据库完整性检查60项通过，无错误；警告明确指向尚未构建的完整生产cp312 wheelhouse。
- 初次空目录Git克隆揭示Flutter模板忽略Gradle启动文件的问题，已记录并修正；修正后重新克隆到另一个空目录，源码检查、8项维护测试、路由一致性、构建dry-run四项均exit0；Gradle脚本Git模式为100755。结果见maintenance/audit/git-clone-check.json，初次失败也保留原因。

## 后续维护入口

从README和AGENTS开始，组件与当前源指针见maintenance/registry/components.json、active-sources.json。任务/交接模板在maintenance/templates；构建、测试、发布、服务器升级/备份/回滚、GitHub恢复分别有文档与实际工具。

历史安装包不覆盖；新任务生成新manifest并--activate更新当前代码指针，旧安装包的来源关联保持不变。源manifest保留原字节hash和文本LF规范化hash，Windows/Linux Git换行不同不会误报逻辑变动。

## 仍然明确保留的限制

- 未重新编译三端并做所有实机验收。Android无模拟器测试、Linux1.0.1未重做完整SecretService/CUPS/实体打印；旧版报告不冒充新版测试。
- 新通用构建工具验证dry-run/逻辑，便携VS/WSL旧adapter可能需要按解包根适配；已有完整工具/真实配方可追溯。
- 本地SQLite是662768器件历史资料，不是服务器最新695217的数据库。生产完整备份仍在服务器，未因归档下载到本机。
- 生产70个Python3.12公开包版本已锁定；完整cp312 wheelhouse尚需准备/隔离验收。新装cp310闭包不能混用。
- 新npm缓存准备网络超时，不能称npm ci --offline已验收；现成node_modules保留并在新路径实际构建通过。
- 部分原有图片404仍未修复；GitHub远端没有创建/推送，CI仅准备。

这些限制和下一步在KNOWN_GAPS.md列出，不能因归档完成就被改成业务全部通过。

## 凭据和原目录

没有在Git保存实际密码、cookie、token或签名私钥。原F:/lc_elc_workspace及旧C兼容目录保持可追溯；以后应将工作目录切换到F:/lc_elc，避免误改旧副本。生产只做限定源码/配置和公开包元数据只读导出，没有重启、部署、业务写入或启动爬虫。
