# 维护交接：独立仓库 Web 第一批推送与生产上线

## 用户目标与已确认边界

用户明确要求推送更新并同步更新服务端。沿用 DeepSeek Harness 写实现/执行服务器操作、Codex 决策验收的分工；仅新增 lab_team_web，不切域名/DNS/代理、不卸载 website、不升级旧业务模块、不做库存测试写入。

## 当前权威源码、分支和版本

- 权威模块：server/ubuntu22.04/odoo_addons/lab_team_web，19.0.1.0.0。
- 现有分支 codex/two-stage-receipt-plan，源提交08186aa73f0c0a8e88b1a4b5fe1e0c29ed64b58e，已推送既有origin。
- 来源 source-server-team-web-phase1-20261025.json，175文件，tree 9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4；旧manifest未改写。

## 已完成工作与实际证据

- DSH实际配置ali/deepseek-v4.1-flash-1017/high，沿用指定会话，终态turn-completed；安装exit0，服务active。
- 完整备份后仅新增18文件模块，18/18 raw SHA256匹配；旧133文件前后相同，库存三次基线相同。
- Codex独立HTTP复核欢迎/登录/匿名保护与原首页/原登录，正确Android更新清单200、Windows/Linux x64更新204。真实账号完整登录与生产检索未重测，不能称全部业务验收通过。
- 本轮Python3.15全仓及提交范围检查各49通过；175文件与工作树/index匹配。新模块whitespace检查通过，旧主题/旧站点和历史报告45个空白提示保留，未改冻结字节。
- 具体命令、环境、退出码、备份全hash及未验证项见 maintenance/audit/team-web-production-20261025.md 和 team-web-publish-codex-review.md。

## 剩余工作与阻塞

- 当前多库环境全新会话须先通过 `/web/login?db=LcHardwareHouse&redirect=/team/lab` 选库，之后 `/team/*` 可用；直接 `/team?db=…` 为404。未改dbfilter或删除旧库。
- `root_aliases=0`，management_host未配置；目标子域名接入与根业务路径切换仍需单独决策和验证。
- 真实账号生产端到端、生产大目录性能、真机/读屏/放大字体、编辑器保存未测；本轮浏览器自动化超时，未取得生产视觉截图。后续入库、领用归还等页面未接入。
- 生产与当前全量来源的旧模块有2处历史内容差异及13处换行差异；已保留，不能称全175文件与生产一致。

## 依赖和产物

发布登记 server-team-web-phase1-20261025；artifact-server-team-web-phase1-20261025.json。完整源包175文件、安装包18文件，均附来源清单；成品位于 server/releases/2026-10-25-team-web-phase1/，Git排除。环境、SHA256和无可执行签名适用性的说明已登记；未生成客户端新包。私有请求/检查输出在local/build/team-web-publish-20261025/，未提交。

## 生产状态和回滚

生产服务已恢复，新模块已安装。备份位于 /var/backups/lc-elc/20261025T093227Z-before-team-web，含DB、真实filestore、旧模块源码及清单，校验已完成。备份用临时0600配置已仅删除该精确文件，原服务配置未动。

不得删除仍为installed的模块目录；若需整体恢复，必须先评估并保留上线后的新业务数据，复核真实data_dir和恢复范围，再另行执行。未做自动回滚或模块卸载。
