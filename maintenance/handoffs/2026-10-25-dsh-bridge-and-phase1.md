# 维护交接：DSH桥接与仓库Web第一批

## 用户目标与已确认边界

用户已确认docs/architecture/TEAM_WAREHOUSE_FRAMEWORK_DRAFT.md并要求开始。DSH负责第一批代码和测试，可开子代理；Codex负责方案、决策与验收。第一批为独立欢迎/登录、仓库搜索和器件详情，本地实现与隔离验证，不包含生产上线。

## 当前权威源码、分支和版本

分支codex/two-stage-receipt-plan，起始commit c4b067c。新增权威源码为server/ubuntu22.04/odoo_addons/lab_team_web，19.0.1.0.0候选；18文件。175文件server来源已冻结并激活为当前候选，见maintenance/registry/source-server-team-web-phase1-20261025.json。现有工作树包含其他工作留下的改动，未重置或覆盖；原有五模块133文件哈希与实施前一致。

## 已完成工作与实际证据

- 使用已安装DeepSeek Harness技能，修正连接地址并按用户明确批准仅授权根项目和既有Flutter app项目。health为ready，autoApprove保持false，工作区创建未开放。
- 指定会话可见且空闲，实际preset为ptc。派发前发现已安装桥接0.2.0调用Host create时忽略sessionId，实际创建空白会话。两次create均因返回会话不符而在append前拦截；两个错误绑定已close，空白会话仍保留，未发出实现指令。
- 已备份并局部修正本机插件：采用已有会话前检查工作区成员和cwd，直接绑定并保留preset；不调用Host create。新对话创建、已有任务重放和权限检查仍保留；为Host list传递AbortSignal。
- Node v24.21.0下11项函数级回归全部通过，exit0；覆盖精确采用、工作区越界、失效附件、cwd不符、preset冲突、新建、幂等、关闭后重绑及signal传递。插件语法检查exit0。这些是隔离桩测试，不是Desktop端到端验证。
- 最终Python3.15全仓检查exit0、49项通过；当前登记和来源快照已修正。Python3.12仍有30项Python/既有3.15载荷语法不兼容，未算通过，也未删载荷。新模块在Python3.12逻辑测试65通过、1跳过；最终DSH复跑同样结果，真实隔离HTTP11/11。
- 第一次Node测试启动误把插件参数当作测试文件，未运行目标测试；改用普通Node脚本启动后完成上述11项。控制台编码错误已修正，结果以最终verification.json为准。

## 已完成的实施、验收与后续

后续用户结束旧后台进程并重开，桥接进程已更新；监听端口变化后按实际进程重新定位，未改凭据范围。真实采用指定既有会话成功，sessionId一致、preset为ptc；第一批append已接受并实际开始读取源码，observedConfig为ali / deepseek-v4.1-flash-1017 / high。两个错误空白绑定均已关闭且未append。隔离补丁现已通过真实采用验证。

DSH已完成首批源码与收尾，实际turn-completed已收到，绑定保持可用于后续同会话反馈。两个子代理分别负责CSS/JS与测试，主代理集成；Codex实际检查并退回修复路径回跳、空body、表单安全、资料链接、手机密度和缓存问题。独立浏览器已验证欢迎、登录直达详情、检索、库存筛选、空结果、详情刷新、前进后退、退出；375px手机卡片116px高、缩略图88px，桌面4:3保留。

后续批次为两阶段入库、领用归还等写入流程；未在本批实施。真实手机、读屏/放大字体、大目录/完整分类、网络故障注入、真实网站编辑器JS和保存流程未测。生产安装、域名/DNS切换等不在本批授权内。详见maintenance/audit/team-web-phase1-codex-review.md及2026-10-25-team-web-phase1.md交接。

## 依赖和产物

本机请求、任务上下文、插件备份、检查日志和合成数据截图在local/build/dsh-unified-web-phase1-20261025/（Git排除）。新server清单tree SHA256为9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4；已独立重算匹配。没有创建安装包或发布成品。真实凭据仍在专用本机位置，未复制进任务、文档或Git。

插件原文件SHA256：18f5ce8e5d1f0e5d15f16e16923d2c460954af2a27abda3f875fbe57d42c8c39；修正后SHA256：c2febde48dabbf092bee768675185b89a231cc8b75dd0f0092f3540a6499bd07。package版本仍为0.2.0，为本地补丁；将来重装可能覆盖，需复核采用语义。

## 生产状态和回滚

本轮没有生产写入、升级、重启、卸载、DNS/代理/爬虫或客户端更改。DSH仅对生产做过只读元数据核对，未安装lab_team_web。Windows侧18069已不可达、私有PG状态exit3（未运行），合成测试数据保留；未递归删除。未推送GitHub。插件回滚可恢复local原文件备份并完整重开Desktop；不涉及生产回滚。
