# 全仓文档与版本状态同步

## 审查范围

扫描 Git 已跟踪及未忽略的 240 份文档，包括 227 份 Markdown、10 份文本和 3 份 HTML。当前入口、组件说明和归档记录均纳入检查。忽略目录中的安装包与原始本机证据按发行登记查找。运行时 HTML、许可证、构建清单及历史日志保留其原始用途。

- 首页、组件安装说明、运维状态、成品索引和已知缺口统一按现行版本表阅读。[当前状态](../../docs/operations/CURRENT_STATE.md) · [成品索引](../../releases/README.md)
- EDA 维护与需求说明使用 4.x 密钥直连，旧 Node 网桥说明归入对应的历史段落。Web 模块 README 区分现行库位树与旧 P2/P3 验收。[插件入口](../../plugins/README.md) · [历史索引](../HISTORY.md)
- 旧 audit 与 handoff 中 13 个 Git 排除的证据引用保留原路径，以本机证据标注。当前工作树不含这些文件，无法验证其内容。

## 校对依据

| 对象 | 复核结果 |
| --- | --- |
| 服务器应用内更新 | Windows、Android、Linux 公网清单 HTTP 200，Ed25519 验签正确，版本 `1.4.0+26`、序号 26。详见[正式发布记录](2026-11-23-client-stable-release.md)。 |
| 本机成品 | 三端手动安装文件与 EDA 两份发行物的大小和 SHA-256 与对应发行登记一致。桌面手动安装和应用内通道包的归档布局与哈希分别记录。 |
| Web 与 EDA 服务端 | 正式登录页 200，匿名库位页转登录，EDA 引导接口缺密钥时返回 `MISSING_TOKEN`。库位树模块版本取[生产部署证据](2026-11-22-warehouse-location-tree.md)。 |
| GitHub | 仓库为公开可见，Releases 无条目。该入口独立于服务器 stable。 |
| 设备与宿主 | 用户设备完整覆盖升级、真实 EDA 宿主、生产账号完整交互均沿用原待验状态。 |

## 来源与历史

此次只刷新文档和对应登记。当前工作区的文档快照为 [客户端](../registry/source-client-docs-20261123.json)、[EDA](../registry/source-eda-docs-20261123.json) 和[服务端](../registry/source-server-docs-20261123.json)。对比旧活动清单，分别只更改 1、3、2 份 Markdown。原安装包和生产发布继续引用各自冻结的构建清单、提交和哈希。
