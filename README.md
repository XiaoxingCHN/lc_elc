# LC_ELC 实验室库存系统

这个仓库是后续人工和AI共同维护的唯一入口，归档基线日期为 **2026-10-19**。当前业务版本：客户端 **1.0.1+2**，EDA插件 **3.0.3**；Odoo三个模块分别独立版本管理。

当前客户端 **1.1.0+3** 三端候选包已构建、尚未发布；生产 **lab_workflow 19.0.1.1.0** 已上线，新增[两阶段入库与袋标签](docs/development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md)。完整备份、生产验收和原生候选未验收项见[当前交接](maintenance/HANDOFF_CURRENT.md)。

> 当前源码在本仓库，历史副本在local/archive。原F:/lc_elc_workspace保留用于来源追溯，不再作为新开发入口。初始归档没有上线；后续服务端按用户独立授权升级，未启动或重启采集器。

## 从这里开始

| 你要做什么 | 入口 |
|---|---|
| 了解真实架构、业务边界 | [架构](docs/architecture/OVERVIEW.md)、[需求](docs/requirements/SCOPE.md) |
| 看当前版本、线上状态和已知限制 | [当前状态](docs/operations/CURRENT_STATE.md) |
| 修改Windows/安卓/Linux客户端 | [clients](clients/README.md)，权威源码[clients/app](clients/app/) |
| 修改Odoo网页/库存业务/API | [server](server/README.md)，权威源码[三个模块](server/ubuntu22.04/odoo_addons/) |
| 修改嘉立创EDA插件/本机桥接 | [plugins](plugins/README.md)、[插件维护](plugins/jlc-eda/MAINTENANCE.md) |
| 维护立创采集和每日同步 | [services/lcsc](services/lcsc/README.md) |
| 找依赖、下载URL和恢复命令 | [依赖获取](dependencies/README.md)、[文件获取登记](maintenance/registry/payloads.json) |
| 找现成安装包 | [发布索引](releases/README.md)，三端各自releases目录 |
| 发布、上线或回滚 | [发布流程](docs/development/RELEASE.md)、[服务器维护](docs/operations/SERVER.md) |
| 从GitHub克隆/准备首次推送 | [GitHub说明](docs/operations/GITHUB.md) |
| AI接手/人机协作 | [AGENTS.md](AGENTS.md)、[开发流程](docs/development/WORKFLOW.md)、[交接模板](maintenance/templates/HANDOFF.md) |

## 目录规范

```text
clients/            一份Flutter源码 + 各端说明和编译成品
server/             Odoo模块、Ubuntu部署/备份/恢复，保留其内部相对布局
plugins/            EDA插件和Node本机桥接
services/           采集/同步编排、生产service/timer快照
 dependencies/      离线工具链与依赖；脚本入Git，载荷不入Git
 data/              本地历史资料快照；不入Git
 docs/              当前架构、需求、开发、运维和决策
 maintenance/       组件/依赖/源码/成品登记、检查与交接模板
 tools/             可维护工具：检查、隔离构建、获取依赖、冻结和打包
 releases/          发布入口索引；具体成品放各组件releases下
 evidence/          精选可公开于私有项目的验收摘要，不把会话日志当代码
 archive/           历史资料索引
 local/             本机缓存、完整迁移记录、历史原物、私有签名、构建输出
```

英文目录、中文正文。`local/`、数据、成品和离线大文件均不提交Git；**只克隆Git不能立即拥有离线SDK和安装包**，按依赖登记下载或用离线载荷包恢复。项目源码中的字体、许可证、Gradle wrapper jar等必要小型运行资产保留。

归档结果与限制见[验收交接报告](docs/operations/ARCHIVE_REPORT.md)。

## 首次核对

在仓库根目录运行（Python3.10以上）：

```sh
python tools/repo_check.py
python -m unittest discover -s maintenance/checks -v
python tools/build_client.py --platform android --dry-run
```

完整离线载荷核验额外运行 `python tools/repo_check.py --verify-payloads`，会读取大文件。实际构建前按各平台README恢复工具链。默认不连生产、不启动爬虫、不改系统配置。

## 维护原则

一个组件一个权威源码入口；版本、成品hash和测试结果互相引用。新改动先分支和任务单，再验证/发布；原始发布包不可覆盖。现有生产环境与全新Ubuntu离线安装并非相同Python ABI，详见当前状态，不能混装。
