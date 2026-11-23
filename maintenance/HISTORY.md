# 历史文档索引

查当前运行版本、发布状态和待验证项，请从[当前状态](../docs/operations/CURRENT_STATE.md)、[成品索引](../releases/README.md)或[当前交接](HANDOFF_CURRENT.md)进入。历史文档中的「当前」「最新」「已通过」都以该文档所写的日期、环境和成品为准。

| 主题 | 历史证据 | 当前入口 |
| --- | --- | --- |
| 工作区和离线载荷 | [10 月 19 日归档验收](../docs/operations/ARCHIVE_REPORT.md)、[11 月 14 日旧工作区退役](handoffs/2026-11-14-workspace-retirement.md) | [工程目录](../docs/architecture/PROJECT_LAYOUT.md)、[依赖恢复](../dependencies/README.md) |
| 公网和自有 Web | [公网方案](../docs/requirements/PUBLIC_ACCESS_AND_UNIFIED_UI_PLAN.md)、[正式域名验收](audit/netlify-formal-domain-acceptance-20261027.md)、[P3 生产交接](handoffs/2026-11-03-p3-production-deploy.md) | [生产运维](../docs/operations/SERVER.md)、[11 月 22 日库位树](handoffs/2026-11-22-warehouse-location-tree.md) |
| 三端客户端 | [Android 1.1.3+6 安装修复](handoffs/2026-10-19-android-install-fix.md)、[1.3.2+10](handoffs/2026-11-10-client-1.3.2-selection-fix.md) | [三端 1.4.0+26 与 EDA 对齐](handoffs/2026-11-23-client-eda-alignment.md)、[stable 发布状态](handoffs/2026-11-23-client-stable-release.md) |
| EDA | 3.x 桥接维护说明属于旧架构。[4.1.4 替代料交接](handoffs/2026-11-22-eda-replacement-candidates.md)记录实际 `.eext` 的模拟验收。 | [4.x 插件入口](../plugins/README.md)、[跨端交互审查](audit/2026-11-23-client-eda-alignment.md) |
| 源码和成品分发 | 历史成品与旧快照保存在原路径。Git 忽略本机安装包、数据库、运行载荷和私有材料。 | [发布规范](../docs/development/RELEASE.md)、[GitHub Releases 与更新通道](../docs/operations/GITHUB.md) |

日常需要查证时，先找具体版本的构建和验收记录，再找测试数据、日志和来源清单。本机忽略的证据只在登记的受控目录或备份中。Git checkout 能提供源码与登记，完整成品需从对应发布入口或可信载荷恢复。
