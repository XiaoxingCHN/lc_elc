# 仓库Web第一批：Codex核心流程审查

2026-10-25。DSH负责实现与测试，Codex负责框架决策和验收。核心只读流程已通过本机隔离浏览器验收；不是上线许可，也不代表全量生产验收。

## 决策与范围

- 认可独立QWeb页面配合渐进JavaScript，不要求SPA；禁止iframe套旧后台。Odoo继续负责认证、权限和库存。
- 管理Host目标路径为 `/`、`/login`、`/lab`、`/lab/items/:itemKey`；`/team`是兼容开发入口。旧官网和已有API、扫码、后台保持原有职责。
- 第一批只读；采购入库两阶段、领用归还等后续实现。不部署生产，不切换DNS。

## 已反馈的实现问题

以下问题均已集成修正；回跳、退出、详情、手机密度和资源更新等核心流程已有独立浏览器证据。

1. 前后端回跳校验误拒itemKey冒号；合法 `lab:1` 被误拒。
2. 管理根首页与退出、会话接口基址不一致；别名关闭开关未真正拒绝请求。
3. 初始检索错误被JavaScript隐藏；数据库异常需回滚到savepoint后再渲染错误状态。
4. 登录表单默认GET可能把密码带入网址；应明确POST和安全action。
5. 资料URL应拒绝危险协议和畸形值；界面移除数据库模型名与开发批次说明。
6. HTTP详情测试应使用确定存在的隔离fixture；退出CSRF正分支应从本模块表单取token。
7. 真实分流发现根入口短路未处理QWeb延迟渲染，返回空body；已修，浏览器根欢迎页非空。编辑器已补真实iframe信号回退；畸形资料URL已拒绝并补逻辑测试。
8. 手机卡片的无图占位过高；已改为88px缩略图加信息行，375px浏览器实测整卡由约408px降为116px。
9. 普通刷新仍命中固定版本的旧CSS；已改为资源内容hash。浏览器再次普通刷新后实际加载 `team.css?v=7e9eee9d31f5`，DOM样式表含88px规则，渲染也为88px，证明新资源已生效。重置视口后桌面图片仍为211×158、4:3。

## 已执行的独立检查

- Python3.12.14独立运行 `python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v`，exit0，66项中65通过、1个Odoo HTTP测试模块跳过。DSH在最终源码上以Python3.15再次复跑，结果相同。JavaScript语法检查exit0、XML解析通过。普通Python下跳过的HTTP模块另在真实Odoo环境执行，不计入该65项。
- 原有lab_catalog、lab_inventory、lab_workflow、lab_site、lab_theme共133个文件对本轮实施前哈希逐项比较，0变化；Flutter源码未改动。
- 最终独立全仓检查：Python3.15.0执行 `tools/repo_check.py`，exit0，49项检查通过、0错误。过时portal当前登记与旧来源指针已修正。Python3.12.14执行同一检查仍exit1，30项错误全部位于既有 `Python/` 载荷的新语法；该目录未删除、未移动，也未冒称3.12全检通过。未运行 `--verify-payloads`，离线载荷重建warning仍保留。
- 最终真实HTTP回归：WSL Ubuntu22.04、Python3.10私有venv、PostgreSQL14.24私有集群，克隆库 `teamweb_verify`、端口18071；11项用例0失败、0错误。Codex独立核对最终 `verify-run.log`，SHA256为8e14f9b7dcb10b66098fb778e8d66ac315d364c3433b3cccd1c94a7a74818b5b。此前错误筛选的0项不计通过，13项stats包含hooks也不作为用例数；命令与环境见DSH报告第14节。
- 当前server候选源175文件，tree SHA256为9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4；Codex重新计算与新清单完全匹配。清单为 `maintenance/registry/source-server-team-web-phase1-20261025.json`，旧manifest与成品来源保持不变。

## apple-design基础审查

本产品是响应式Web应用，只应用可访问性、排版、颜色、布局和文案原则，不强加原生Apple导航惯例；深色与荧光绿来自用户既定品牌。

检查了技能参考的accessibility、layout、typography、color、designing-for-macos、search-fields、text-fields、dark-mode与cross-platform相关段落。

- `accessibility.md › Vision`：要求“Strive to meet color contrast minimum standards.” 按CSS原始色值计算，背景 `#111418` 上正文 `#f2f4ee` 为16.67:1，辅助字 `#9aa199` 为6.98:1，强调绿 `#c9ff3f` 为15.71:1，错误色 `#ff4b3e` 为5.57:1；主按钮黑字/绿底为17.05:1。这里只覆盖这些不透明颜色配对，未代表所有透明叠加态通过。
- `typography.md › Ensuring legibility`、`layout.md › Adaptability`：正文16px；已做375px和桌面浏览器核验，手机行布局和桌面网格均可用。放大字体未测，不从源码推断通过。
- `text-fields.md › Best practices`：模板提供持续可见的账号/密码标签、密码类型和autocomplete；脚本加载失败时的安全提交还需真实浏览器验证。
- 源码有skip link、focus-visible和减少动画规则。已验证Tab焦点和前进后退；完整键盘遍历、读屏顺序及动态错误的读屏播报未测。

## 浏览器结果与边界

已在真实本机隔离实例验证：管理根首页、匿名仓库/详情回本站登录、登录回到含冒号的同一详情、关键词检索、库存筛选3→2、空结果、详情刷新、浏览器前进后退、带CSRF退出。JS控制台在这些流程中无错误。合成数据只有3个器件，库存25/8/0，未复制生产数据。

375px登录输入框高46px，已检查欢迎、登录、详情和列表；键盘Tab焦点有2px可见轮廓。手机列表密度和缓存修复已实际复验，横向内容宽度未超出视口；桌面布局已复核。浏览器视口设置已恢复、测试账号已退出、验收标签已关闭。

基础设计评价为Good：品牌色来自官网约定；编码、名称和真实库存为主要信息，手机列表已去除大面积无图占位。读屏、放大字体、真实设备、完整2791分类/大目录压力、网络故障注入、实际网站编辑器JS和保存流程未验证，不计通过。没有生产视觉验收，也没有发布。

精选本机截图（均为合成测试数据，Git排除）：`local/build/dsh-unified-web-phase1-20261025/warehouse-desktop.jpg`、`warehouse-mobile-compact.jpg`；源测试与重现方式见模块README及DSH验收报告。来源冻结、最终测试计数和全仓检查以收尾记录为准。

清理核验：浏览器已退出测试账号并关闭标签，视口恢复默认；Windows侧18069不可达，私有PG的 `pg_ctl status` exit3（未运行）。仅停止本批测试进程，私有数据保留，无生产写入、无DNS切换或GitHub推送。
