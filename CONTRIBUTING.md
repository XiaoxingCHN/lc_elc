# 参与维护

人和AI遵守同一套流程：先读[README](README.md)和[AGENTS.md](AGENTS.md)，再读[开发流程](docs/development/WORKFLOW.md)与[当前交接](maintenance/HANDOFF_CURRENT.md)。

新需求先写任务单，确认修改组件与验收条件；分支完成后检查差异、测试和发布映射。不要直接修改已发布安装包或把缓存当源码提交。

GitHub 源码提交和 Release 附件均排除密码、私钥、业务数据和真实配置。源码推送、手动下载附件和应用内 stable 分别核验。大文件获取和备份见[依赖恢复](dependencies/README.md)与[文件获取登记](maintenance/registry/payloads.json)。
