# 独立仓库 Web 首批发布：Codex 核验

## 授权与分工

2026-10-25 用户要求“推送更新”，并明确“服务端也要相应更新上线”。延续既定分工：DeepSeek Harness 执行服务器预检、备份、单模块安装与验证；Codex 决策、核验并负责 Git 提交推送。使用既有会话，实际配置 ali / deepseek-v4.1-flash-1017 / high，自动批准保持关闭。

仅新增 lab_team_web 19.0.1.0.0；禁止批量升级原五模块、库存测试写入、网站卸载、DNS/代理或其他服务变更。

## 已完成的 Git 与产物核验

- 源提交 `08186aa73f0c0a8e88b1a4b5fe1e0c29ed64b58e` 已非强制推送至原 origin 的 `codex/two-stage-receipt-plan`，独立 ls-remote 与本地 HEAD 相同。
- 提交包含本批 Web、已部署但此前未提交的主题/站点依赖源码和相关维护记录。未加入 Python/ 载荷、临时 obj、Project Graph 备份、私有上下文或发布二进制；保留其他未提交材料。
- `source-server-team-web-phase1-20261025.json` 的 175 文件逐项与工作树和 Git index 的 LF 归一化哈希核对，0 差异；tree `9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4`。
- Windows / Python3.12.14 stdlib tarfile+gzip 打包，成员排序、固定时间、移除宿主用户名；完整源包 175 文件，安装包仅 lab_team_web 18 文件，均附原始来源清单。逐成员原始 SHA256 与冻结清单 raw_files 匹配，0 差异，无越界成员。
- 完整源包：`server/releases/2026-10-25-team-web-phase1/server-team-web-19.0.1.0.0-source.tar.gz`，12,678,545 bytes，SHA256 `a464caeeaa6fbcf56670e849ac858c71dd5739442dcd10cb521f9fbebae2a09d`。
- 单模块安装包：同目录 `lab_team_web-19.0.1.0.0.tar.gz`，60,610 bytes，SHA256 `3b4858dffe5e4b0f01b65cf0663f933a6e7fe06c6297d2976d4d18746800f72d`。服务器源码包无可执行文件签名或签名证书，未声称签名；二进制 Git 排除。

## 本轮本机检查

- Python3.15.0：`tools/repo_check.py --staged-only` exit0 / 49 项通过 / 0 错误；完整 `tools/repo_check.py` 同样 exit0 / 49 项通过。前者检查 600 个 Git 候选文件，后者含本地材料共 2911 个候选文件。保留 production-py312-rebuild 警告，未运行 --verify-payloads。
- 待提交文件机密扫描 0 命中；具体凭据从未写入请求、报告或 Git。
- 新 lab_team_web 范围 `git diff --cached --check` exit0。完整提交的 whitespace 检查 exit2，有 45 个旧主题/旧站点源码与历史报告的尾空格/末尾空行提示；保留已冻结字节，没有为格式检查改写旧模块或清单。首次命令误用 repo_check 的 --json 参数，随后按实际 --output 参数重新执行成功；编码错误的提示计数也已按 UTF-8 重新取得。
- 65 逻辑通过+1跳过、11隔离 HTTP 通过、浏览器核心流程属于前一候选轮的相同源证据；本轮没有在生产运行写入式测试或将历史用例冒称生产重测。

## 生产核验（已安装上线）

- Codex 独立匿名请求确认部署前 /team 为404；全新 IP/旧域名会话的原首页与登录入口进入数据库选择页。CookieJar 经 /web/login?db=LcHardwareHouse 选库后，旧首页200/40260 bytes、原生登录200。属于已有多库入口行为，不为此改配置或删库。
- DSH 预检发现旧五模块共133文件，13处原始哈希差异只涉及换行，另2处实际差异为旧主题 CSS 与主题部署脚本；均保留生产版本。安装后须以生产自身的部署前基线核对旧模块，不能声称整个175文件与生产完全相同。
- DSH 实际 `turn-completed` 已收到，服务 active/running，模块 installed@19.0.1.0.0。安装本身 exit0，外层 shell 的 grep 无匹配导致 exit1 已区分；按启服时间戳重筛 ERROR/CRITICAL 为0，未将历史日志错误计入本次。
- 本次备份 `/var/backups/lc-elc/20261025T093227Z-before-team-web`：DB dump 110,890,366B、filestore 13,596,659B、旧五模块源码归档12,796,060B；清单/产物SHA256、1375条恢复目录记录与154个filestore文件核对见生产审计。helper默认data_dir不符已通过私有0600备份配置修正，实际filestore被备份；真实服务配置未改，临时凭据副本已移除。
- 独立审阅执行输出：新18文件逐文件raw SHA256匹配，旧133文件部署前后SAME。库存三次基线均为 quant 2、数量0.00、预留0.00、move1、product2、active bag1、operation line1、未归还领用0；没有库存测试写入。
- Codex 独立HTTP复核：选库会话下 /team200/3921B、/team/login200、匿名/team/lab返回自有登录；原首页200/40260B、原登录200。Android正确更新清单接口200/1826B，SHA256 `152d47ae1145b8c81200409a5af4e47b952e1ec1dcbe8d10c4105959a945cb65`；Windows/Linux x64均204。DSH另核对CSS内容hash URL 200及匿名详情回跳。
- Codex再次直接读取线上CSS 36,406B和JS 34,613B，均HTTP200，原始SHA256与冻结raw_files相同，URL内容缓存键分别匹配7e9eee9d31f5/faa1bc0b6393，exit0。生产记录完成后提交范围检查exit0、49通过、605个Git候选文件；本次交接差异whitespace检查exit0。原源提交中45个旧空白提示仍按前述保留。
- 新增参数root_aliases=0，保留旧 /login、/lab 404；management_host未配置，旧根首页未接管。新会话直接 /team?db=… 仍404：首次需 `/web/login?db=LcHardwareHouse&redirect=/team/lab` 建立目标库会话，后续使用 /team/*。没有为此改dbfilter、代理或删除数据库；域名解析本轮未配置或验证。
- 真实账号生产端到端未测（未创建生产账号）；Codex生产浏览器验收遇绑定/快照超时，未取得生产视觉截图，不计PASS。首次停服中打开页面的拒绝连接为预期停服状态；后续HTTP已独立正常。之前同源本机浏览器证据与本次生产检查分开记录。
- Codex修正了DSH草稿的回滚建议：不得删除仍为installed的模块目录；整体DB恢复必须先评估并保留上线后新业务写入，不自动覆盖恢复。本轮只修正文档，未执行回滚/卸载。

## 未纳入范围

DNS/公网子域名切换、真实手机、读屏/字体放大、大目录压力、编辑器保存，以及下一批入库/领用/归还页面。
