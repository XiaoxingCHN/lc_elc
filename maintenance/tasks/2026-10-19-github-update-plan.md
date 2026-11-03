# 任务：上传本次更新并制定客户端自动更新方案

- 目标：将本轮已验收源码/部署交接提交并推送既有 GitHub origin，再梳理启动联网检查客户端更新方案；本轮不实现更新器或发布安装包。
- 允许修改：当前已完成工作树、方案及交接文档；沿用 codex/two-stage-receipt-plan，不覆盖 main、不强推、不改仓库可见性。
- 验收：暂存机密/大文件边界和repo_check通过，远端分支提交一致；方案覆盖三端、发布来源、连通判定、下载校验、安装权限、失败回退与验收。
- 依赖：现有Git认证；客户端1.1.0+3源manifest及服务端opsfix manifest；所有凭据/本地载荷/候选安装包继续Git排除。
- 分工：主代理独立完成。生产服务本轮不做新更改。
- 起始：分支 codex/two-stage-receipt-plan，HEAD 28dd8bf032404eee5d1196aff786fd96b2cf8b52。
- 实施：核对现有remote与分支→暂存源码/文档→staged检查→commit/push并核对远端→官方平台文档及现有客户端接入点→计划/交接。
- 验证与结果：65文件功能提交0716829已推送既有功能分支；新增docs/development/CLIENT_UPDATE_PLAN.md，后续文档同分支上传。staged和完整repo_check均49通过exit0；具体见同日 github-update-plan 交接。代码组件既有测试见上一轮audit，不重复冒称重测。
- 未测试：更新器尚未实现；安装升级、系统权限和真实设备需实现后验证。
- 回滚：本轮只新增提交，禁止强推或改旧manifest；安装包仍candidate。
