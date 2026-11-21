# 工程目录权威说明（PROJECT_LAYOUT）

本文件是 `F:\lc_elc` 仓库的目录结构说明：每个顶层目录的用途、唯一源码入口、是否入 Git、本机实测体积与首读文档。它只描述现状，**不移动、不重命名任何已跟踪路径**。

> 背景：旧工作区 `F:\lc_elc_workspace` 已于 2026-11-14 审核补档后删除，现在唯一工作根是 `F:\lc_elc`。退役记录见 `local/manifests/workspace-retirement-20261114.md`。

## 1. 顶层目录

| 目录 | 用途 | 唯一源码入口 | 入 Git | 本机实测体积 | 首读文档 |
|---|---|---|---|---|---|
| `clients/` | 三端共享 Flutter 源码 + 各端说明与编译成品 | `clients/app/` | 源码入 Git；`clients/*/releases/` 不入 | 714M | [clients/README.md](../../clients/README.md) |
| `server/` | Odoo 19 模块、Ubuntu 部署/备份/恢复、采集器、bore 网关 | `server/ubuntu22.04/odoo_addons/` | 是 | 71M | [server/README.md](../../server/README.md) |
| `plugins/` | 嘉立创 EDA 专业版插件与 Node 本机桥接 | `plugins/jlc-eda/src/`、`plugins/jlc-eda/bridge/server.mjs` | 源码/说明入 Git；`node_modules/`、`dist/`、`bridge/runtime/`、`releases/` 不入 | 369M | [plugins/README.md](../../plugins/README.md)、[MAINTENANCE.md](../../plugins/jlc-eda/MAINTENANCE.md) |
| `services/` | 采集/同步服务编排与生产 systemd unit 快照 | `services/lcsc/` | 是 | 21K | [services/lcsc/README.md](../../services/lcsc/README.md) |
| `dependencies/` | 离线工具链与依赖载荷；恢复/获取脚本 | `dependencies/README.md` + `restore_client_tools.ps1` / `tools/fetch_payload.py` | 脚本与说明入 Git；`sdk/`、各类缓存、载荷不入 | 22.1G（23,676,281,799 B） | [dependencies/README.md](../../dependencies/README.md) |
| `data/` | 本机历史数据快照（SQLite 等） | `data/README.md`（数据本体不入 Git） | 仅 `README.md` 入 Git | 3.4G | [data/README.md](../../data/README.md) |
| `docs/` | 当前架构、需求、开发、运维、决策 | `docs/README.md` | 是 | 1.4M | [docs/README.md](../README.md) |
| `maintenance/` | 组件/依赖/源码/成品登记、任务、交接、审计、检查与模板 | `maintenance/registry/components.json` | 是 | 3.0M | [components.json](../../maintenance/registry/components.json)、[templates/](../../maintenance/templates/) |
| `tools/` | 检查、构建、发布、冻结、依赖获取工具 | `tools/*.py` | 是 | 145K | [repo_check.py](../../tools/repo_check.py)、[WORKFLOW.md](../development/WORKFLOW.md) |
| `releases/` | 发布入口索引；实际成品在各组件 `releases/` 下 | `releases/README.md` | 是 | 4.0K | [releases/README.md](../../releases/README.md) |
| `evidence/` | 精选可公开的验收证据摘要 | `evidence/README.md` | 是 | 23K | [evidence/README.md](../../evidence/README.md) |
| `archive/` | 历史资料索引；实物在 `local/archive/` | `archive/README.md` | 仅 `README.md` 入 Git | 4.0K | [archive/README.md](../../archive/README.md) |
| `local/` | 本机缓存、迁移/退役记录、历史原物、私有签名、构建输出 | `local/README.md` | 不入 Git | 32.0G（34,409,281,819 B，含 `local/archive`） | `local/README.md`（Git 排除，本机文件） |
| `Python/` | 本机捆绑 Python 运行时 | 无（运行时，不参与源码） | 不入 Git | 184M | — |

体积为 2026-11-15 02:12–02:15（+08:00）本机实测；`clients`/`server`/`plugins`/`services`/`data`/`docs`/`maintenance`/`tools`/`releases`/`evidence`/`archive`/`Python` 用 `du -sh`，`dependencies`/`local` 用 `dir /s /-c` 的字节合计（文件数分别为 184,663 与 118,744），未四舍五入到整 GB 的两项在括号内给出字节数。

## 2. 二层地图

### `clients/`

- `app/`：**唯一** Flutter 源码。`lib/`、`test/`、`pubspec.yaml`、`pubspec.lock`；`android/`、`linux/`、`windows/` 是 Flutter 平台工程（不是各端成品目录）。
- `windows/`、`android/`、`linux/`：各端 `README.md` + `releases/`（成品，Git 排除）。
- 版本与必需文件以 `maintenance/registry/components.json` 的 `client` 为准。

### `server/ubuntu22.04/`

- `odoo_addons/`：6 个 Odoo 模块 `lab_catalog`、`lab_inventory`、`lab_workflow`、`lab_site`、`lab_team_web`、`lab_theme`（当前版本见 `components.json` 的 `odoo`）。
- `crawler/`：立创采集与快照（`snapshot_catalog.py`、`lcsc_catalog_archive.py` 等）。
- `bore/`：公网入口网关（`nginx/`、`netlify/`、`systemd/`、`tests/`、`scripts/`）。
- `systemd/`：`odoo.service.example`、`lcsc-crawler.service`。
- `tools/`：条码/视图检查（`check_barcode_rendering.py`、`check_views.py`、`configure_workspace_ui.py` 等）。
- 部署/备份/恢复脚本直接位于 `server/ubuntu22.04/` 根：`odoo_backup.py`、`odoo_restore.py`、`upgrade_modules.sh`、`install_offline.sh`、`install_crawler.sh`、`verify_checkpoint.py`、`lc_archive.py`、`lc_odoo_conf.py`、`lc_service.py`。没有单独的 `ops/` 子目录。

### `plugins/jlc-eda/`

- `src/`：插件源码（`iframe/`、`main/`、`shared/`、`tests/`）。
- `bridge/`：本机 Node 桥接，入口 `server.mjs`，另有 `start-windows.cmd`、`start-linux.sh`；`bridge/runtime/` 为运行载荷，Git 排除。
- `assets/`、`locales/`、`scripts/`：资源、语言包、构建脚本。
- `releases/3.0.3/`：已发布成品，Git 排除；`dist/`、`node_modules/` 同样排除。

### `maintenance/`

- `registry/`：组件、依赖载荷、源码清单、成品、路由登记。**被引用的路径不得随意移动。**
- `tasks/`：任务单（模板 `templates/TASK.md`）。
- `handoffs/`：交接记录（模板 `templates/HANDOFF.md`）；`HANDOFF_CURRENT.md` 是当前入口。
- `audit/`：验收/审计记录；`checks/`：可执行检查脚本；`templates/`：任务与交接模板。
- `patches/`：当前为空目录（Git 不跟踪空目录）。

### `docs/`

- `architecture/`：架构总览、API 契约、路径调用说明（本文件也在这里）。
- `decisions/`：ADR；`development/`：开发/构建/发布流程；`operations/`：运维、当前状态、GitHub。
- `plans/`、`requirements/`：方案与需求；`history/` 当前为空目录（Git 不跟踪）。
- 入口：[docs/README.md](../README.md)。

### `tools/`

`repo_check.py`（仓库一致性检查）、`build_client.py`、`client_release.py`、`release.py`、`generate_routes.py`、`offline_bundle.py`、`fetch_payload.py`、`prepare_client_update.py`、`legacy_entry_rules.py`。

### `local/`

`archive/`（历史原物）、`build/`（隔离构建工作根）、`logs/`、`manifests/`（迁移/审核/冻结/退役逐文件记录）、`private/`（签名材料，绝不进 Git）、`receipt-feedback/`、`web-ui-implementation/`，加 `README.md` 说明分类规则。

2026-11 本轮整理事实：

- 根层散落文件与一次性目录已归档到 `local/archive/one-off-2026-11/`：本机实测 `scripts/` 14 个、`plans/` 10 个、`status/` 7 个、`status/tomc-20261103/` 3 个（共 34 个文件），外加整目录 `scripts/legacy-web-team/`（532 个文件）与 `status/tomc-20261103/`。
- `local/temp`、`local/tmp`、`local/local` 已删除。
- `local/` 根层现在只有 7 个分类目录 + `README.md`。
- 新增 Git 排除的 `local/README.md`，写明分类与保留规则。

## 3. 本机材料索引

| 材料 | 位置 | 说明 |
|---|---|---|
| 历史原物 | `local/archive/` | 旧发布、旧源码、旧数据、旧 EDA、迁移前修订、一次性产物 |
| 迁移/退役记录 | `local/manifests/` | 逐文件来源、哈希、审核与删除日志；与 CHANGELOG/交接互相引用 |
| SQLite 唯一副本 | `data/catalog/checkpoint-20261015/components.sqlite3` | 3,547,037,696 B / `ac536621…60823`；`local/archive/data/lcsc_cn_archive` 为既有归档原库 |
| 离线工具链 | `dependencies/` | Flutter/Android/Gradle/pub 缓存、SDK 与恢复脚本；逐项登记见 `maintenance/registry/payloads.json` |
| 各端成品 | `clients/*/releases/`、`plugins/jlc-eda/releases/`、`server/releases/` | Git 排除；版本与 hash 见 `maintenance/registry/releases.json` |

## 4. 不要动清单

- `maintenance/registry/*.json` 中登记过的路径（`source_root`、`required_files`、冻结清单的 `files`）：移动或改名会让登记与检查失效。
- `local/private/`：本机签名材料，整目录不搬迁、不外传、不进 Git。
- tag `archive-2026.10.19` 对应的源码路径：历史基线，不能重写。
- 需要移动任何已登记路径时，**先**更新 `maintenance/registry/` 与相关交接，再移动，最后跑 `python tools/repo_check.py`。

## 5. 已知问题（只记录，不处理）

- 根目录存在字面名为 `%SystemDrive%` 的目录骨架：`%SystemDrive%/ProgramData/Microsoft/Windows/Caches/*.db`，本机实测 7 个文件约 1 MB。疑似脚本未展开环境变量的误建物；Git 不跟踪，本轮不删除。
- `clients/app/t.obj` 与 `clients/app/build/`：本机构建产物，已被忽略。
- 根 `README.md` 顶部仍是 11 月初的状态长文，尚未改成目录入口（本文件与 `README.md` 的“目录规范”一节承担入口作用）。
- `Python/`：本机捆绑运行时，Git 排除，不应作为项目源码维护。
- `.idea/`：本机 IDE 配置，Git 排除。
- `docs/lc_elc.prg`：既有未跟踪文件，不在本文件描述范围。
- `docs/history/`、`maintenance/patches/`：当前为空目录，Git 不跟踪空目录。

---

本文件只做结构说明；权威版本、冻结清单与验收仍以 `maintenance/registry/` 和 `docs/operations/CURRENT_STATE.md` 为准。
