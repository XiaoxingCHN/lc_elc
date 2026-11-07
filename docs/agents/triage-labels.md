# Triage Labels

本仓库使用默认的五个 triage 状态角色。任务是本地 Markdown 文件，没有真正的 label 系统，因此状态写在任务文件顶部：

- `- Status: needs-triage`
- `- Category: bug` 或 `- Category: enhancement`

| 角色 | 本仓库记录值 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 维护者需要评估 |
| `needs-info` | `needs-info` | 等待报告者补充信息 |
| `ready-for-agent` | `ready-for-agent` | 已充分说明，可交给 AFK agent |
| `ready-for-human` | `ready-for-human` | 需要人工实现 |
| `wontfix` | `wontfix` | 不会处理 |

技能提到某个角色时，使用表中的“本仓库记录值”。每个已 triage 的任务应恰好有一个状态角色和一个分类角色；没有 `- Status:` 行视为未 triage。
