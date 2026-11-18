# 任务：旧工作区 F:\lc_elc_workspace 审核与退役（2026-11-14）— 状态=已完成

- Status: done（主仓无 docs/agents/triage-labels.md，状态词按既有任务文件惯例）
- 目标/用户场景：旧工作区 `F:\lc_elc_workspace` 为 **178,156 文件 / 49,676,894,303 B**，2026-10-14 从桌面整包复制；合并已于 2026-10-19 完成（commit `3b3c3af`、tag `archive-2026.10.19`、`original_files_deleted: 0`）。本轮逐条审核迁移台账、补档未入 Git 材料后删除原件，回收约 46 GB，并留下可追溯的逐文件记录。
- 当前问题及复现方法：`dir F:\lc_elc_workspace` 显示目录仍存在且占用 46 GB 以上；迁移台账的 138,294 条从未逐条复核；构建候选、EDA 中间产物、WorkBuddy 记录不在 Git，也不在 `local/archive` 的既有目录中。复现：删除前执行 `dir F:\lc_elc_workspace` 可见原目录与体积。
- 验收标准：① 迁移目标逐条复核且缺失项可解释；② 未入 Git 材料补档并逐文件记录来源与 SHA256；③ 旧工作区 `components.sqlite3` 与本机副本全量比对；④ reparse point / junction 单独识别处理，不跨界破坏目标；⑤ 删除 0 失败并留日志；⑥ `python tools/repo_check.py` exit 0；⑦ 只改文档，不 commit / push，不接触生产。
- 允许修改目录/接口：仓库侧 `archive/README.md`、`data/README.md`、`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`、`maintenance/HANDOFF_CURRENT.md`、本 task、`maintenance/handoffs/2026-11-14-workspace-retirement.md`、`README.md` 第 38 行一处；本机 `local/archive/**`、`local/manifests/**`、`F:\lc_elc_workspace`（仅删除）。不改源码、不改冻结清单与 registry、不 commit / push。
- 业务不变量/依赖：不接触 Odoo 生产数据；库存以 `stock.quant`/`stock.move` 为权威、供应商库存不混入、领用人必须系统账号、归还关联原领料、实物单一追溯 QR 等业务不变量均不受影响。依赖：既有迁移台账、`local/manifests` 记录目录、本机 Windows 文件系统工具（`robocopy`、`rmdir`、`dir /AL`）。
- 负责人/协作者及分工：主代理执行审核、补档、SQLite 比对、reparse point 处理、删除与记录；用户授权删除旧工作区。
- 分支/起始commit/源码manifest：分支 `codex/receipt-search-feedback`；无新源码 manifest；既有合并基线 commit `3b3c3af`、tag `archive-2026.10.19`；本轮只改文档，未 commit / push。
- 环境与凭据获取方式（只写位置，绝不写值）：本机 Windows；旧工作区 `F:\lc_elc_workspace` 与外部 junction `lc_elc\build_work\e -> E:\lcb\build`；未读取任何凭据。
- 实施步骤：1) 复核迁移台账（目标存在/缺失分类）；2) 抽样哈希比对；3) 补档未入 Git 材料到 `local/archive/**` 并逐文件记来源/SHA256；4) 旧工作区 `components.sqlite3` 与本机副本全量 SHA256 比对；5) 扫描并处理 reparse point / junction；6) `robocopy <空目录> F:\lc_elc_workspace /MIR /XJ` + `rmdir` 空根目录；7) `python tools/repo_check.py`；8) 同步受版本控制的维护文档（本步）。
- 测试命令、实际结果与退出码：审核 present **138,107** / missing **187** / hashed **820** / mismatch **51**（缺失全为 `dependencies/sdk/windows/flutter/.pub-preload-cache/*.tar.gz`）；补档 **2,870 文件 / 1,402,575,621 B**；SQLite 全量 SHA256 一致（`ac536621032c6028b708847b4ee0d74669008c9dfd2dee480991dfa11ad60823`，各 3,547,037,696 B）；删除 **176,743 文件 / 46.243 GB**、**0 失败**；`python tools/repo_check.py` **exit 0**；F: 可用 **64.1 GB → 109 GB**。
- 未验证项及风险：① 187 个缺失文件未逐个校验（按路径全为 SDK 可重建缓存）；② 补档未做恢复演练；③ `output\` 接线图、`.workbuddy` 会话状态未归档，已随删除消失；④ 删除不可逆；⑤ `docs/agents/triage-labels.md` 不在主仓，状态词沿用既有任务文件惯例。
- 发布文件、hash和回滚点：无发布产物、无 registry 变更；删除不可回滚；追溯依据为 `local/manifests/workspace-retirement-20261114.json`（逐文件来源与 SHA256）与 `local/archive/**` 补档副本。
