# 维护交接：2026-11-14 旧工作区 F:\lc_elc_workspace 审核与退役

## 用户目标与已确认边界

- 目标：逐条审核 2026-10-14 整包复制、2026-10-19 已合并的旧工作区 `F:\lc_elc_workspace`（原 178,156 文件 / 49,676,894,303 B），把未入 Git 的材料补档到 Git 排除的 `local/archive/**` 并留逐文件来源与 SHA256，然后删除原件回收空间。
- 边界（本轮实际遵守）：只改受版本控制的维护文档；本机只写 `local/archive/**`、`local/manifests/**`，只删除 `F:\lc_elc_workspace`。未改源码、未改冻结清单与 registry、未 commit / push、未接触生产。
- 明确未做：187 个缺失文件未逐个校验（路径全为 SDK 可重建缓存）；补档未做恢复演练；`output\` 接线图与 `.workbuddy` 会话状态未归档，已随删除消失；未替换旧工作区的 junction；未启动任何旧任务。
- 事实来源：本轮本机实测与 `local/manifests` 记录。本文件数字均为记录值，未四舍五入、未推算。

## 当前权威源码、分支和版本

- 分支 `codex/receipt-search-feedback`；合并基线 commit `3b3c3af`、tag `archive-2026.10.19`（`original_files_deleted: 0`）；本轮未 commit / push。
- 各组件版本不变：客户端 `1.1.3+6`、`lab_workflow 19.0.2.0.0`、`lab_team_web 19.0.1.2.0`、`lab_catalog 19.0.2.0.5`、`lab_inventory 19.0.1.0.0`、EDA `3.0.3`，见 `maintenance/registry/components.json`。
- 本机权威数据快照仍为 `data/catalog/checkpoint-20261015/components.sqlite3`（3,547,037,696 B / `ac536621032c6028b708847b4ee0d74669008c9dfd2dee480991dfa11ad60823`）。

## 已完成工作与实际证据

- 台账复核（`local/manifests/merge-recheck-20261114.json` / `.log`）：台账 138,295 条，138,294 条有目标、1 条无目标跳过；**138,107** 个目标仍在；缺失 **187** 个全为 `dependencies/sdk/windows/flutter/.pub-preload-cache/*.tar.gz`；抽查 **820** 个哈希，**51** 个因迁移后源码继续演进而不同，旧修订已补档。
- SQLite 全量比对：旧工作区 `lcscmigration/components.sqlite3` 与 `data/catalog/checkpoint-20261015/components.sqlite3` 全量 SHA256 一致（`ac536621032c6028b708847b4ee0d74669008c9dfd2dee480991dfa11ad60823`，各 3,547,037,696 B）；仅保留后者为本机权威副本。
- 补档（Git 排除，**2,870 文件 / 1,402,575,621 B**，逐文件见 `local/manifests/workspace-retirement-20261114.json`，说明 `workspace-retirement-20261114.md`）：`local/archive/workspace-candidates/` **570** 个未发布构建候选（965,324,105 B，含 560 MiB 服务端离线重建包与两个 Linux 客户端 tar.gz）；`local/archive/eda/workspace-intermediates/` **30** 个 EDA 3.x 只留原件的构建产物（186,794,874 B，仓库内无对应源码）；`local/archive/evidence/analysis-workspace-20261014/` **2,219** 个 WorkBuddy 记录（249,753,330 B）；`local/archive/source-import-before-format/` 新增 **51** 个不在 Git 的旧修订（703,312 B；该目录原有 4 个）。
- reparse point（扫描记录 `local/manifests/workspace-reparse-scan-20261114.txt`）：26 个目标全在工作区内部；外部 junction `lc_elc\build_work\e -> E:\lcb\build` 用 `rmdir` 单独删除，`E:` 未受影响（该目标本就不存在）。
- 删除：`robocopy <空目录> F:\lc_elc_workspace /MIR /XJ` 删除 **176,743 文件 / 46.243 GB**、**0 失败**，随后 `rmdir` 空根目录；F: 可用空间 **64.1 GB → 109 GB**；删除日志 `local/manifests/workspace-purge-20261114.log`。
- 仓库检查：`python tools/repo_check.py` **exit 0**（本机在删除后执行）。
- 文档同步（本轮）：`archive/README.md`、`data/README.md`、`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`、`maintenance/HANDOFF_CURRENT.md`、`README.md` 第 38 行，以及本 handoff 与对应 task。未 commit / push。

## 剩余工作与阻塞

- 无阻塞。可选后续：对 `local/archive/workspace-candidates/` 的补档做一次抽样恢复演练（本轮未做）。
- 删除与补档的完整性判断以 `workspace-retirement-20261114.json` 的逐文件记录为准；不要用「文件存在」代替恢复验证。

## 依赖和产物

- 无新源码产物、无 registry 变更、无发布包；`components.json` 与冻结清单均未改写。
- 补档位于本机 Git 排除目录 `local/archive/workspace-candidates`、`local/archive/eda/workspace-intermediates`、`local/archive/evidence/analysis-workspace-20261014`、`local/archive/source-import-before-format`。
- 记录位于 `local/manifests/workspace-retirement-20261114.{json,md}`、`merge-recheck-20261114.{json,log}`、`workspace-purge-20261114.log`、`workspace-reparse-scan-20261114.txt`。
- 未读取任何凭据；本轮不涉及签名密钥或生产口令。

## 生产状态和回滚

- 未接触生产：无 SSH、无部署、无重启、无升级、无业务写、无采集器启停。
- 生产仍为 2026-11-03 P3 部署完成态（`lab_team_web 19.0.1.2.0`、`DEPLOY_STATE=completed`），见 `maintenance/handoffs/2026-11-03-p3-production-deploy.md`。
- 唯一不可逆操作是本机删除旧工作区 `F:\lc_elc_workspace`；如需恢复，只能依赖 `local/archive/**` 补档副本与 `workspace-retirement-20261114.json` 的逐文件来源记录，且 187 个 SDK 缓存与 `output\`/`.workbuddy` 内容不可恢复。
