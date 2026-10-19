# 人机共同维护规范

先读 README.md、maintenance/registry/components.json、docs/operations/CURRENT_STATE.md 和 docs/development/WORKFLOW.md。当前工作不是旧原型。目录可移动，不要把本机用户名或F盘路径写入正式脚本。

## 权威源码

- clients/app：三端共享Flutter源码，一处修改后验证受影响平台。clients/<platform>/releases 是不可变成品，不能当源码改。
- server/ubuntu22.04/odoo_addons：三个Odoo模块唯一源。保持运维脚本和辅助Python同目录；crawler也保留在现有部署布局，services/lcsc负责服务编排说明和生产unit快照。
- plugins/jlc-eda：EDA3插件与Node本机桥接；禁止误用历史2.0.1或_reference运行时。
- dependencies：恢复工具和离线载荷；local、data、archive、全部releases为本机材料，Git排除，来源登记不能省略。

## 每次接手

1. 查看 git status，阅读相关目录README和最近交接文档，确认需求、当前版本、未完成项。
2. 以 registry/component、release-source与验收记录为准；文件存在或构建exit0不等于业务通过；历史通过不等于当前已重测。
3. 用 maintenance/templates/TASK.md 记录任务目标、可修改目录、依赖、测试和交付。不相互覆盖源码。并行只在用户授权或指令要求时使用。
4. 改动前确定是否只是归档、文档、本地开发或生产部署。不得因读到历史脚本而自动执行上线/清库/卸载模块。

## 业务不变量

实验室数量以Odoo stock.quant/stock.move为权威；供应商库存不能混入。绑定同立创料号应统一展示、有本地库存前置、库位/袋在详情展开。领用人必须系统账号；归还关联原领料。实物标签仅一个追溯QR，库位另用库码。离线仅公开缓存只读；十天无成功登录要求重新输密码；凭据使用OS安全存储。

## 安全与权限边界

- 禁止把密码、cookie、token、真实odoo.conf、Android签名私钥、数据库或聊天日志提交到Git，即使是私有仓库。诊断输出只显示路径、计数和哈希。
- 模板是模板；192.168.31.105、LcHardwareHouse、lc.rm.com只是既有环境说明，不是默认测试靶场。
- 生产写入、重启、升级、恢复、卸载、导入、爬虫启动/计划任务注册需本轮用户授权或持续有效的明确授权。归档任务不授权这些动作。
- 库存依赖stock/product/mrp等不能按应用名字删除。服务器只允许项目相关更改；Docker/网络/其他业务服务不在范围内。
- 备份、恢复、递归删除需校验绝对目标包含关系；不要跨junction/symlink破坏原目录。不得读取真实凭据来补文档。

## 完成与发布

运行 python tools/repo_check.py，必要时 --verify-payloads。对改动运行有意义的组件测试，保存命令、环境、退出码、非零测试数量和未测试项。无法执行的检查标blocked/skipped，禁止算PASS。

发布前冻结完整源清单，用 tools/release.py snapshot 登记文件和版本；新快照用--activate更新active-sources.json，旧manifest和产物关联不可改写；成品必须记录source manifest、SHA256、构建环境和签名公证书。客户端版本不要与Odoo模块版本混为一个版本。更新CHANGELOG和CURRENT_STATE；旧包不可覆盖。

任务结束写maintenance/templates/HANDOFF.md规定的交接，不记录隐私。没有通过的事项写清剩余工作。不要自创远端仓库或推送；GitHub准备流程见docs/operations/GITHUB.md。

## 本机 TOMC 记忆

本机可选项目笔记位于 `.tomc/memory.sqlite3`，整个 `.tomc/` 已排除 Git。使用已安装 TOMC 的原生 notebook 存储；运行 `python .tomc/memory.py list`，按实际任务用 `recall <name> <task>` 读取。使用和来源说明见 `.tomc/README.md`；若该目录不存在，直接按上述权威文档接手，无需阻塞维护。记忆是有日期的文档快照，不替代最新源码/登记表，不扩大生产授权。只显式保存已授权项目资料，不自动收集当前对话或任何凭据。
