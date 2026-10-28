# LC_ELC 实验室库存系统

2026-10-28 P3 自有Web日常业务：**候选已完成冻结/构建/登记，未部署生产**（`lab_workflow 19.0.2.0.0`、`lab_team_web 19.0.1.1.0`、运维 `2026.10.28.1`；生产仍是 P2 `lab_team_web 19.0.1.0.5`/`lab_catalog 19.0.2.0.5`/`lab_workflow 19.0.1.2.0`，客户端 `1.1.3+6`、EDA `3.0.3` 不变）。冻结源 [source-server-p3-web-20261028.json](maintenance/registry/source-server-p3-web-20261028.json)：**250 文件**，treeSHA `fc2d538d…5ab43`，manifestSHA `0bfc1e3f…c164`，`active-sources.server` 已指向它，旧 manifest/产物未覆盖；候选包 `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`（13,186,981 B，SHA256 `9070800b…49e564`，纯源码、无 runtime/数据库/凭据、源码 ZIP 签名 N/A），登记 [artifact-server-p3-web-20261028.json](maintenance/registry/artifact-server-p3-web-20261028.json)；`repo-final-r1.json` **52 项 PASS / exit 0**，唯一 warning 为 `production-py312-rebuild`。**验收**：ORM 业务 **82/82（role wrapper 后重测，0 fail 0 error）**、HttpCase **21/21**、写业务 API **54 pass/0 fail/1 blocked**（total 55，blocked 为 Origin 项，未提供 Origin URL 故不改 PASS）、Nginx 1.26.2 与 1.30.6 各 **34/34**、独立并发 adapter **6/6**（负向自检 detected）、runner 17、core 17、XML 6、JS 15、routes 79；浏览器主链 **31 步 28 pass / 0 fail / 3 blocked**（3 blocked 为 cross-user / same-key-different-payload / unknown-outcome 的 DOM 场景未执行，由 API/HttpCase/core 覆盖，**不得伪称 DOM 通过**）。原 `--test-enable` 并发套件因 Registry 锁 blocked（Probe 证实 `Registry._lock` 主线程持有），wrapper exit 1，**不得称该命令全绿**。**未做**：生产部署与公网开放；**未闭合**：生产 Py3.12 与隔离 3.10.12 不等价、完整离线恢复、旧备份附件不完整/非一致快照、手机不挂 VPN 实测、实体摄像头/打印。[交接](maintenance/handoffs/2026-10-28-p3-web-workflows.md)｜[当前状态](docs/operations/CURRENT_STATE.md)。以下为此前时点记录。

2026-10-27正式入口：https://team.l-creation.club/ 。CNAME与证书有效，真实Netlify公网22项检查通过；用户已确认默认Netlify域名真实登录/功能正常。正式域名手机流量无VPN体验仍待最后确认，本机不同节点直连表现有差异，不宣称全网稳定。[正式验收](maintenance/audit/netlify-formal-domain-acceptance-20261027.md)｜[当前交接](maintenance/HANDOFF_CURRENT.md)。以下为此前时点记录。

2026-10-27最新：Netlify HTTPS回源已部署，实际前端22项检查通过，用户确认真实登录与功能正常。当前最后待办为team自定义域名与阿里云CNAME，正式域名TLS/会话尚未验收；不需要迁移DNS托管。[当前交接](maintenance/HANDOFF_CURRENT.md)｜[前端验收](maintenance/audit/netlify-frontend-acceptance-20261027.md)。以下为此前时点记录。

2026-10-27晚间：**IPv4 bore独立公网网关已部署，等待DNS切换及正常浏览器最终验收**。中继159.223.110.159:16443→回环TLS白名单18443→Odoo，systemd自动重连已验，内网vhost保持。生产本机49/0、合成Cookie/头/限速12/0、严格TLS链/域名校验但无SNI诊断公网19/0；正常SNI当前仍超时，不能宣称浏览器已通过。下一步用户将阿里云team A改为159.223.110.159，再验证 https://team.l-creation.club:16443/ 。见[部署审计](maintenance/audit/bore-public-ipv4-deploy-20261027.md)与[交接](maintenance/handoffs/2026-10-27-bore-public-ipv4-deploy.md)。下方记录均按各自时点理解。

2026-10-27：**P2 模块已上生产**。`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5` 已在 LcHardwareHouse 生效，服务 active、TLS 登录入口 200，库存 2 行与其它模块未变。本轮修复了备份工具默认 data_dir 与生产实际不符导致**附件漏备**的缺陷（已补备 139 个真实附件、新增回归测试）。见[生产更新审计](maintenance/audit/production-p2-deploy-20261027.md)与[交接](maintenance/handoffs/2026-10-27-production-p2-deploy.md)。**公网仍未开通**：team.l-creation.club 仍解析到内网 192.168.31.105，无 AAAA；公网需真实公网节点 + 标准 443 + 隧道登记，本轮未改 DNS/Nginx。

2026-10-26：[bore公网安全与自有前端统一方案](docs/requirements/PUBLIC_ACCESS_AND_UNIFIED_UI_PLAN.md)已完成本地盘点与编写，待用户确认后交DSH实施。目标为仅Odoo登录、日常页面统一自有UI；公网默认拒绝非必要路由，原生后台保留为管理员内网维护。方案不是部署结果，尚未开放公网或卸载网站模块。

2026-10-25 HTTPS更新：管理入口现为 **https://team.l-creation.club/**，HTTP已308跳转；Codex离开内网前12项独立检查通过。用户已自行完成LE注册及签发，证书到期2027-01-23；自动续期尚未配置，HTTPS真实账号流程待用户复验。离开内网后DSH桥接不可用，最终生产备份/操作审计待恢复核验。见[HTTPS交接](maintenance/handoffs/2026-10-25-team-https-current.md)。

2026-10-25 登录补修：已修复新管理域名首次认证无法保存会话的问题，仅调整该域名的认证代理并重新加载Nginx。隔离环境4组场景、13条断言通过；生产匿名入口和错误账号响应已复核。用户随后回复“可以了”，确认原登录无反应已恢复；刷新后保持登录、退出和跨端流程未追加实测。见[登录审计](maintenance/audit/team-login-cold-session-20261025.md)。

2026-10-25：**lab_team_web 19.0.1.0.0 已安装生产**。新增独立欢迎、登录、仓库检索和详情；18 个新模块文件与冻结源一致，旧五模块133文件、库存计数与合计保持不变，服务 active。欢迎/登录/匿名保护、静态资源和原入口已做生产HTTP检查；真实账号完整流程、生产大目录和真机未重测。65项逻辑通过+1跳过、11项隔离HTTP通过属于同源候选证据。见[生产审计](maintenance/audit/team-web-production-20261025.md)与[发布核验](maintenance/audit/team-web-publish-codex-review.md)。

内网管理新入口为 **http://team.l-creation.club/**，自有 `/`、`/login`、`/lab` 已接通并自动选定生产库，首次会话无需进入旧数据库选择页。当前为HTTP，HTTPS待用户确认LE生产账号及订阅协议；真实账号全流程、VPN跨网与生产视觉未重测。旧IP/lc.rm.com与 `/team/*` 保留，未选库的旧入口仍需原登录选库方式；入库/领用新页面尚未接入。见[域名HTTP审计](maintenance/audit/team-domain-http-deploy-20261025.md)。


2026-10-24：lab_portal 方案已废弃并从源码移除（最近生产审计为 uninstalled），不再作为当前能力。替代方案为上述独立Web候选。

2026-10-24：**lab_catalog19.0.2.0.4 暗色主题已上线**。仅更新主题与资产配置，服务active、认证后台/主题CSS200、库存计数和更新通道不变；视觉及手机验收尚未完成。备份与验证见[主题交接](maintenance/handoffs/2026-10-24-dark-theme-deploy.md)。

这个仓库是后续人工和AI共同维护的唯一入口，归档基线日期为 **2026-10-19**。组件当前源码版本见[组件登记](maintenance/registry/components.json)，已发布成品按各端发布登记查询；Odoo模块分别独立版本管理。

生产更新接口 **lab_workflow 19.0.1.2.0 已上线**；Android **1.1.3+6已发布stable**，清单200、完整包下载/哈希核验通过，Windows/Linux仍204。用户反馈旧安装入口已授权仍失败，已发布[1.1.3+6安装入口修复](maintenance/handoffs/2026-10-19-android-install-fix.md)，见[部署交接](maintenance/handoffs/2026-10-19-update-endpoint-deploy.md)。

最新客户端候选 **1.1.2+5** 修复[器件选择白屏和更新状态](maintenance/handoffs/2026-10-19-receipt-picker-fix.md)。此前客户端 **1.1.1+4** 三端候选新增[启动检查与下载更新](docs/development/CLIENT_UPDATE_IMPLEMENTATION.md)，服务端开发候选 **19.0.1.2.0**；该开发阶段未发布stable或部署新接口，彼时生产为 **lab_workflow 19.0.1.1.0**，完整备份与候选未验收项见[当前交接](maintenance/HANDOFF_CURRENT.md)。

> 当前源码在本仓库，历史副本在local/archive。原F:/lc_elc_workspace保留用于来源追溯，不再作为新开发入口。初始归档没有上线；后续服务端按用户独立授权升级，未启动或重启采集器。

## 从这里开始

| 你要做什么 | 入口 |
|---|---|
| 了解真实架构、业务边界 | [架构](docs/architecture/OVERVIEW.md)、[需求](docs/requirements/SCOPE.md) |
| 看当前版本、线上状态和已知限制 | [当前状态](docs/operations/CURRENT_STATE.md) |
| 修改Windows/安卓/Linux客户端 | [clients](clients/README.md)，权威源码[clients/app](clients/app/) |
| 修改Odoo网页/库存业务/API | [server](server/README.md)，权威源码[三个模块](server/ubuntu22.04/odoo_addons/) |
| 修改嘉立创EDA插件/本机桥接 | [plugins](plugins/README.md)、[插件维护](plugins/jlc-eda/MAINTENANCE.md) |
| 维护立创采集和每日同步 | [services/lcsc](services/lcsc/README.md) |
| 找依赖、下载URL和恢复命令 | [依赖获取](dependencies/README.md)、[文件获取登记](maintenance/registry/payloads.json) |
| 找现成安装包 | [发布索引](releases/README.md)，三端各自releases目录 |
| 发布、上线或回滚 | [发布流程](docs/development/RELEASE.md)、[服务器维护](docs/operations/SERVER.md) |
| 从GitHub克隆/准备首次推送 | [GitHub说明](docs/operations/GITHUB.md) |
| AI接手/人机协作 | [AGENTS.md](AGENTS.md)、[开发流程](docs/development/WORKFLOW.md)、[交接模板](maintenance/templates/HANDOFF.md) |

## 目录规范

```text
clients/            一份Flutter源码 + 各端说明和编译成品
server/             Odoo模块、Ubuntu部署/备份/恢复，保留其内部相对布局
plugins/            EDA插件和Node本机桥接
services/           采集/同步编排、生产service/timer快照
 dependencies/      离线工具链与依赖；脚本入Git，载荷不入Git
 data/              本地历史资料快照；不入Git
 docs/              当前架构、需求、开发、运维和决策
 maintenance/       组件/依赖/源码/成品登记、检查与交接模板
 tools/             可维护工具：检查、隔离构建、获取依赖、冻结和打包
 releases/          发布入口索引；具体成品放各组件releases下
 evidence/          精选可公开于私有项目的验收摘要，不把会话日志当代码
 archive/           历史资料索引
 local/             本机缓存、完整迁移记录、历史原物、私有签名、构建输出
```

英文目录、中文正文。`local/`、数据、成品和离线大文件均不提交Git；**只克隆Git不能立即拥有离线SDK和安装包**，按依赖登记下载或用离线载荷包恢复。项目源码中的字体、许可证、Gradle wrapper jar等必要小型运行资产保留。

归档结果与限制见[验收交接报告](docs/operations/ARCHIVE_REPORT.md)。

## 首次核对

在仓库根目录运行（Python3.10以上）：

```sh
python tools/repo_check.py
python -m unittest discover -s maintenance/checks -v
python tools/build_client.py --platform android --dry-run
```

完整离线载荷核验额外运行 `python tools/repo_check.py --verify-payloads`，会读取大文件。实际构建前按各平台README恢复工具链。默认不连生产、不启动爬虫、不改系统配置。

## 维护原则

一个组件一个权威源码入口；版本、成品hash和测试结果互相引用。新改动先分支和任务单，再验证/发布；原始发布包不可覆盖。现有生产环境与全新Ubuntu离线安装并非相同Python ABI，详见当前状态，不能混装。
