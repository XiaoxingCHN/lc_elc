# Issue tracker: 本地维护任务单

本仓库的问题、任务单和规格以 `maintenance/tasks/` 下的 Markdown 文件为准，不使用 GitHub Issues。工程技能从这里读取和创建任务。

## 约定

- **建任务**：复制 `maintenance/templates/TASK.md` 到 `maintenance/tasks/<YYYY-MM-DD>-<slug>.md`，填写目标/用户场景、验收标准、允许修改目录、依赖、测试命令和交付。
- **读任务**：直接读取用户给出的任务文件；也可按日期前缀或 slug 在 `maintenance/tasks/` 中查找。
- **列表**：`ls maintenance/tasks/`，按文件名中的日期排序。需要状态时读取每个文件顶部的 `- Status:` 行；没有该行视为未 triage。
- **规格/方案**：较大的需求文档放在 `docs/requirements/`，由任务文件链接过去。
- **交接**：任务结束后按 `maintenance/templates/HANDOFF.md` 写入 `maintenance/handoffs/<YYYY-MM-DD>-<slug>.md`。
- **过程记录**：追加到任务文件末尾的 `## 进展` 段，不覆盖原目标与验收标准。
- **状态**：triage 状态记录为任务文件顶部的 `- Status: <label>` 行，取值见 `triage-labels.md`。分类记录为 `- Category: bug|enhancement`。
- **wayfinder**：本仓库暂未使用；如启用，map 用 `maintenance/tasks/<effort>-map.md`，子任务用 `maintenance/tasks/<effort>/issues/NN-<slug>.md`。

## 当技能说 “publish to the issue tracker”

从 `maintenance/templates/TASK.md` 创建一个新的 `maintenance/tasks/<YYYY-MM-DD>-<slug>.md`，不要创建 GitHub issue。

## 当技能说 “fetch the relevant ticket”

读取用户给出的 `maintenance/tasks/...md` 路径，或按日期/slug 匹配到的任务文件。

## 权限与证据

生产写入、重启、升级、恢复、导入、爬虫启动等操作仍按 `AGENTS.md` 的授权规则执行；任务单中的“已提交/exit 0”不等于业务验收通过。
