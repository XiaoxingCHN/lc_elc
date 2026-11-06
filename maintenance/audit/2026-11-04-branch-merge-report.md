# 合并前报告：所有分支并入 main

- 报告时间：2026-11-04（Asia/Shanghai）
- 仓库：`F:\lc_elc`（当前分析 worktree：`F:\lc_elc\.claude\worktrees\read-tomc-memory-56e7a2`）
- 结论：**无合并冲突，建议 `git merge --no-ff`；`codex/receipt-search-feedback` 在内容上已包含其余所有分支。**
- 本报告只做只读分析；尚未修改 `main`、未推送远端、未删除或移动任何分支。

## 1. 分支清单与关系

| 分支 / 引用 | 指向 | 相对 codex | 是否已包含 | 说明 |
|---|---|---|---|---|
| codex/receipt-search-feedback（候选） | `5fa9ca4` | 基准 | — | 本地与 origin 一致，工作区干净 |
| main / origin/main | `0e14ffa` | 落后 9 | 内容已包含 | 仅多一个 PR #1 合并提交，内容与 `0716829` 相同 |
| codex/two-stage-receipt-plan | `14cf1ef` | 落后 3 | 是（祖先） | 本地与 origin 一致 |
| feat/p3-web-workflows-20261028 | `b3bcbf2` | 落后 2 | 是（祖先） | 本地与 origin 一致 |
| claude/read-tomc-memory-56e7a2（当前 worktree） | `0e14ffa` | 落后 9 | 内容已包含 | 与 main 同一提交，无独有内容 |
| tag archive-2026.10.19 | `3b3c3af` | 已包含 | 是 | 标签，不是分支 |

结论：只有 `codex/receipt-search-feedback` 需要实际并入；合并它即覆盖其余全部分支。

## 2. 提交与内容分析

- 合并基：`0716829` `feat: add two-stage receipt workflow and verified server deployment`
- main 独有提交：仅 `0e14ffa`（PR #1 合并提交）；`git diff 0716829 main` 为空，说明该提交没有独有内容。
- codex 独有提交共 9 个：

  1. `8df35b5` docs: plan server-connected client update delivery
  2. `66ced7b` feat(client): add signed updates and fix receipt picker
  3. `11f0380` fix(android): accept cache aliases and expose install failures
  4. `c4b067c` docs(release): record Android build6 publication and install limits
  5. `08186aa` feat(server): add standalone warehouse web and record deployed theme sources
  6. `14cf1ef` docs(server): record verified warehouse web production deployment
  7. `b3bcbf2` feat(server): complete P3 warehouse web workflows
  8. `0828d39` feat(web): unify receipt search feedback and ship p3 production deploy
  9. `5fa9ca4` chore: ignore machine-local materials and record projectgraph path-call task

- 内容规模（main → codex）：375 个文件，+79,212 / −514。
- 合并预演：`git merge-tree --write-tree main origin/codex/receipt-search-feedback` 退出码 0，零冲突；合并结果树 `f6d2347` 与 codex 树相同。
- 反向差异（codex → main）非空（375 文件），说明 main 的内容是 codex 的子集。

## 3. 合并方式建议

`main` 上的 `0e14ffa` 不是 codex 的祖先（codex 从其父提交 `0716829` 分出），因此 `--ff-only` 不适用。建议：

```bash
git switch main
git merge --no-ff origin/codex/receipt-search-feedback \
  -m "Merge branch 'codex/receipt-search-feedback' into main"
```

- 保留 PR #1 的合并提交，不改写历史。
- 预期零冲突；合并后树应等于 codex 树 `f6d2347`。
- 不采用 `git branch -f main ...`（会丢弃 `0e14ffa`），也不采用 rebase / force。

## 4. 实际检查结果

| 检查 | 结果 | 说明 |
|---|---|---|
| 工作区（当前 worktree / 主检出） | 均干净 | `git status --short` 无输出 |
| 合并预演 | PASS | `merge-tree` 退出码 0，无冲突 |
| repo_check（codex 检出 `F:\lc_elc`） | PASS：52 项通过、0 错误、1 警告 | 警告为既有 `production-py312-rebuild` 载荷未构建；未加 `--verify-payloads` |
| 路由登记一致性 | **FAIL**（退出码 1） | 生成 92 条、登记 79 条；缺 13 条 legacy 入口 |
| `git diff --check main codex` | **FAIL**（45 项） | 7 个既有文件的行尾空格 / EOF 空行；不阻塞合并 |
| 组件测试 | 未运行 | 本报告仅做合并前分析 |

路由缺失的 13 条均来自 `server/ubuntu22.04/odoo_addons/lab_team_web/controllers/legacy_entries.py`：

- `/odoo/action-lab_workflow.action_lab_bag`
- `/odoo/action-lab_workflow.action_lab_issue_line`
- `/odoo/action-lab_workflow.action_lab_return_wizard`
- `/odoo/action-lab_workflow.action_lab_label_open`
- `/odoo/action-lab_workflow.action_lab_location`
- `/odoo/action-lab_workflow.action_lab_operation`
- `/odoo/action-lab_workflow.action_lab_scan_console`
- `/odoo/action-lab_catalog.action_lab_unified_catalog_client`
- `/odoo/action-lab_catalog.action_lab_catalog_item_action`
- `/odoo/action-lab_catalog.action_lab_catalog_binding_action`
- `/odoo/action-lab_inventory.action_lab_product`
- `/odoo/action-lab_inventory.action_lab_location`
- `/odoo/action-lab_inventory.action_lab_mapping`

建议合并后单独更新 `maintenance/registry/routes.json` 并复核，不混入本次合并提交。

行尾空格涉及：`portal-implementation-20261024.md`、`theme-enhancement-deploy-20261024.md`、`theme-final-deploy-20261024.md`、`lc_theme_dark.css`、`body_fragment.html`、`homepage.xml`、`global_dark_theme.css`。属既有格式问题，建议后续清理。

## 5. 风险与注意事项

- 主检出 `F:\lc_elc` 当前在 `codex/receipt-search-feedback` 上且干净；`main` 未被任何 worktree 检出，本 worktree 可安全切到 `main` 执行合并。
- `refs/stash` 存在一条 `format-churn-revert`（codex 上的 stash）；本次不动、不 pop。
- 合并只更新本地 `main`；`origin/main` 仍在 `0e14ffa`。是否推送需另行确认。
- 其他分支不删除、不改指向；合并后它们将成为新 `main` 的祖先。
- 合并后需重新运行 repo_check，并确认祖先关系、树一致、无未跟踪污染。

## 6. 执行计划（待确认）

1. 本 worktree 切换到 `main`（当前干净）。
2. `git merge --no-ff origin/codex/receipt-search-feedback`，预期零冲突。
3. 验证：`git rev-list --count main..codex` 为 0；`git diff --stat main codex` 为空；repo_check PASS。
4. 报告结果；除非单独授权，不推送 `origin/main`、不删除分支、不处理 stash。

## 7. 结论

合并条件满足：`codex/receipt-search-feedback` 是内容超集，其余分支均已被包含，预演无冲突。两项检查失败均为既有问题（路由登记缺 13 条、45 处行尾空格），不构成合并阻塞；建议合并后另开任务修复并重新冻结源清单。

## 8. 执行结果（2026-11-04 追加）

- 已在当前 worktree 切换到 `main` 并执行 `git merge --no-ff origin/codex/receipt-search-feedback`。
- 合并提交 `c808065`，父提交为 `0e14ffa` 与 `5fa9ca4`；ort 策略，退出码 0，零冲突。
- `main` 树 `f6d23475310d9939d80236d4c50c5ff79f98f316` 与 codex 树一致；`main..codex` 剩余 0 个提交；所有分支与标签均为 main 的祖先；`git diff main codex` 为空。
- 工作区仅多出未跟踪的本报告文件；`git diff --check` 通过（0 项）。
- 合并后 repo_check（本 worktree）：51 项通过、1 错误、15 个 `payload-missing` 警告。错误为 `frozen-source:client`，详情 `['clients/app/t.obj']`。
  - 根因：冻结清单 `source-client-receipt-search-feedback-20261102.json`（169 文件）把 Git 忽略的本机文件 `clients/app/t.obj` 计入；该文件不在 main 树中，干净 worktree 因而失败。主检出仍留有该本机文件，所以合并前在 `F:\lc_elc` 上的检查通过。
  - 处理建议：重新冻结客户端源清单时排除该文件；不要把 `t.obj` 提交进 Git。
- `payload-missing` 警告是 worktree 不含本机载荷所致，不是合并错误。
- 路由检查仍报 13 条 legacy 入口缺失（既有问题，见第 4 节）。
- 未推送 `origin/main`；未删除或移动分支；未处理 stash。
