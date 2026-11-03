# 维护交接：2026-11-02 Web统一UI，移交其他模型

快照时间：2026-11-02 14:12（Asia/Shanghai）。用户显式要求保存TOMC后移交。本文是项目文件与验收产物的快照，不是完整聊天，不替代最新源码。接手先读AGENTS规定的README、maintenance/registry/components.json、docs/operations/CURRENT_STATE.md、docs/development/WORKFLOW.md；CURRENT_STATE/README部分生产结论过时，以下实测纠正优先核验。

## 用户目标与已确认边界

用户要所有端最终统一，目前明确网页先行；网页整站统一深色+荧光绿风格，包含旧Odoo入库/扫码操作台及日常菜单，来料编号/关键词搜索必须即时真实下拉候选、明确状态、实际选档。用户已授权实施，并明确“本地更新完之后直接推送服务器端”，部署授权持续有效，勿重复询问。这里指部署服务器，不是Git推送；未授权新建远端仓库/提交推送。大部分工作交DeepSeek，接手主模型负责最终审查和必要视觉审查，尽量节约主模型token。允许多个不限量DeepSeek，允许Qoder/WorkBuddy/CodeArts DeepSeek。

严格库存不变量：实验室stock.quant/move权威，供应商库存另列；建待入库袋/打印不增库存，上架确认才增；同C号聚合，多档案须明确选择；领用人为系统账号，归还关联原领用；每袋单追溯QR。当前不改Flutter/EDA源码，不绕过历史无批次库存保护。不得把凭据/真实配置/数据库/聊天日志入Git，不改全局权限设置。

## 当前权威源码、分支和版本

分支codex/receipt-search-feedback；基线b3bcbf244e44939c6d481e3f97f11579cdf9ee99。工作区大量未提交修改，必须保留，不重置。源码主域server/ubuntu22.04/odoo_addons/lab_team_web及bore精确白名单。lab_team_web当前manifest仍19.0.1.1.0，未给本次最终版本/冻结。active-sources.server仍maintenance/registry/source-server-p3-web-20261028.json（旧250文件）。计划通过最终审查后升team_web19.0.1.2.0、server-ops2026.11.02.1，未执行；workflow保持19.0.2.0.0。旧manifest/成品不可覆盖。

既有无关untracked包括Python/、clients/app/t.obj、docs/architecture多个ProjectGraph产物及旧10-28部署任务，勿清理。移交git status又出现undefined/，来源未核实，勿直接删除。

计划：docs/requirements/WEB_UI_UNIFICATION_PLAN_20261102.md。任务：maintenance/tasks/2026-11-02-web-ui-unification-implementation.md。旧交接：maintenance/handoffs/2026-11-02-web-ui-unification-implementation.md，内容有滞后。详尽本机接续：local/web-ui-implementation/ORCHESTRATOR_STATE.json（Git忽略），先用本文最新结果修正它。

## 已完成工作与实际证据

实现：1024断点桌面236px固定侧栏/窄屏抽屉；共用LC.combobox，250ms去抖、IME、即时loading、晚响应失效、最多2在途、8秒超时、错误重试、键盘/ARIA；来料候选真实C编号/本地库存/档案/供货信息，多档案显式SN选择；选档卡片同步；修复下拉在form外导致选中13却提交为空的真bug（实际从select取值）。提交未知状态锁保持。补receipt/labels行checkbox的44px label，manager表单命中区，drawer含toggle的焦点循环、main/account背景inert、Esc/真实遮罩关闭/回焦、桌宽恢复，receipt与labels页签关联和键盘。用户文案去除开发说明；业务错误显示具体中文指引，内部错误仅通用信息+编号。

旧入口13条精确/odoo/action-xmlid、9 act_url/12菜单改指。原actions保留。有效GET/HEAD303，其余405；Odoo GET装饰器会落核心兜底400，故显式列GET/POST/PUT/PATCH/DELETE再handler405是必要实现，不要改回。精确Nginx旧action白名单，不放开/odoo或通用ORM。hooks只恢复原模块默认action，保留后来用户自定义；不是安装前任意定制快照。此简化已接受，部署必须保存真实menu before，回滚以一致DB备份及before核验。

主模型独立：combo20/20；最终core19/19 exit0。主实施最近：JS语法15/15，纯Python144 tests OK skipped3（不是144个Odoo ORM），实际DOM主探针30/30，正常上架5/5，若干本机-u零ERROR/CRITICAL。更早真实Odoo52（含旧入口20、HTTP9、hook2），需区分时点。主模型真实浏览器r3 UI报告out/run-real-2026-11-02T03-32-13-433Z/report.json：13项=12P/0F/1主动分开interactions，exit3；receipt/labels桌窄、drawer、manager两页桌窄均P，已视觉复看receipt桌面和manager映射375。

主模型r3全量out/run-real-2026-11-02T03-37-12-393Z/report.json：54=44P/0F/10B，exit3。14页面桌窄、权限拒绝、manager、drawer全部P；业务因验收器错误r.url不是function/C2异步未就绪而B，不能称全业务通过。

【移交时新发现的最新实测】CodeArts后续实际业务分节已完成：local/web-ui-implementation/out/run-real-2026-11-02T03-49-52-014Z/report.json，22=19P/0F/3B，三B仅主动未选pages/drawer/manager。业务实际P：多档案显式13，create POST1，JSON-RPC params.product_template_id=13；新追溯TRC00000027确认被PRECONDITION_FAILED正确拒绝，legacy库存9→9，无新增袋，显示可执行历史适配指引。正常C2/14：新TRC00000028，create POST1匹配14；上架confirm1，库存13→14，bag25数量1；袋详情1440/375、扫码同袋均P；领用issue_line5/POST1，归还关联5/POST1，outstanding0，bag25数量恢复1。主模型已读JSON关键证据，但未对修后完整链独立再跑。中间03:43/03:46/03:48报告失败属于验收器迭代，不能当最终状态。

验收器local/web-ui-implementation/verify-web-ui.mjs / run-real-ui.mjs归CodeArts。真实write闸门必须loopback+env p3_+会话get_session_info实际db严格匹配；凭据只内存。支持--only=env,pages,interactions,drawer,manager、--pages=...，逐项partial/report、计时、有界操作。页面复用context+viewport快，不要重新每页启动Chrome。原生长任务用持久exec/job，不用run_code单次30秒结论。root入口run-root-final-r3.mjs已设WRITE C990000002/ARCHIVE14，MULTI C990000001/IDS12,13，LEGACY13。最终全量前可将WEBUI_BAG_ID设为已证实存在的合成bag25，避免初始静态bag-detail未传ID的两个占位B；本轮动态详情仍必须使用本轮上架的新bag，禁止拿历史袋代替业务链。

## 依赖、DeepSeek绑定与本机服务

使用deepseek-harness技能及其scripts/bridge.py；桥接最近URL http://127.0.0.1:11365/codex-bridge，workspace 8b11f62f-8a95-477c-afcf-39aea93c46a2。本机监测python local/legacy-web-team-monitor.py now；增量游标/转录在local/legacy-web-team/。复用同task，不每轮新建对话。

当前主实施/集成：task-web-plan-ux-20261102，Qoder magpie/qoder-cn/dfmodel high（原UX会话接任，有可用权限）；原主task-codex-team-web-phase1-1a236b6b-505a-46ed-95be-a8df122ee26c超过1M上下文已attention。曾新建task-web-ui-main-final-20261102遇workspace-write ACL Win325并请求提权，root已取消，无源码修改，不能改sandbox绕过。现主能正常工作。

浏览器：task-web-ui-browser-20261102，magpie/codearts/deepseek-v4.1-flash-1017（无effort配置）；安全：task-web-ui-security-20261102同CodeArts；部署：task-web-ui-deploy-20261102，现magpie/qoder-cn/dfmodel high，原WorkBuddy型号被当前目录删除导致UNKNOWN_MODEL，已在同任务切换；旧入口task-web-plan-entry-20261102完成。模型必须核observedConfig，不使用不在用户允许范围的模型。

移交14:12探测桥接WinError10061连接被拒绝。因此不能确认代理实时状态，也未能下发安全停工通知；last-status.json中running可能只是旧快照，不能当仍运行。恢复连接后先查任务/transcript/后台job，不重复派发可能仍待执行的请求；勿自动改权限或重启Desktop。移交只记录本机文件，不继续上线。

本机合成实例WSL Ubuntu-22.04 PG55432、DB p3_ui_20261102、HTTP127.0.0.1:18069，最后主报pid41496（03:30Z），当前需重新核实；不drop/reseed。synthetic env在browser/env.local.sh只读取到内存，别打印。C1模板12/13=tracking none，有旧quant15/9，confirm必须保护拒绝，不删quant或改后端凑P；C2模板14已lot/有袋，可正向。外壳用bash -c不要-lc，profile有敏感样式杂文，不复印/不改全局profile。

## 剩余工作与阻塞

1 恢复桥接只读核实际代理状态；源码与本机DB最新状态先核。业务19P已取得，接手主模型应独立完整复跑，并查看展开候选、已选档、窄屏、袋详情/领用归还真实图。记录原始计数，主动skip不算P。无需再跑所有历史fixture当业务。
2 部署脚本在local/web-ui-implementation/scripts；安全报告按时间读deploy-script-review.md、deploy-script-final-review.md、security-r3-review.md。最后一份已累积到rev13，文件前面旧S1–S7不是最新状态，必须读尾部：最新结论代码侧0阻断，文档deploy-plan关键hash9条过期，建议以scripts/FROZEN-20261102.sha256唯一准。冻结文件mtime04:38Z。00-preflight现已含quantity/reserved总量+有序规范SHA；50verify含同指纹（实读），但接手需按当前文件hash复核这些与完整模块hash/菜单exact允许新增等是否都完成，不能只信早期报告。最新05/08/10/15/20/30/40/50/90/helper/bundle曾多轮硬化；不得随便重构，修确实未闭问题。
3 UI+业务最终验收后，主实施升版本、更新README/CHANGELOG/CURRENT_STATE及registry，新source snapshot --activate，生成新不可变候选ZIP/manifest/artifact记录含SHA/构建环境，跑python tools/repo_check.py、适当组件检查与git diff --check。当前旧source漂移曾唯一repo_check错误；尚未新冻结、未新包、未Git提交/推送。
4 只有拿到审过的新manifest和ZIP实际hash后，接手主模型对部署task发明确NOW DEPLOY（这是内部执行闸门，不再向用户重复索权）。提前告知维护窗口。完成真实停服一致备份、换码、仅-u lab_team_web、现有Netlify网关精确更新及真实验证，直到完成，不止提计划。
5 更新最终audit/handoff；所有未测真实账号/实体打印/摄像头/手机无VPN等明确列出，不伪称P。部署/回滚完成后才清理明确的DPAPI私有临时文件，不递归清理无关材料。

## 生产状态和回滚

本次仅生产只读探测，未给最终NOWDEPLOY；无本次生产写入/备份/重启/升级/导入。实际已查lc-nas项目Odoo19：DB team_web19.0.1.1.0、workflow19.0.2.0.0，mapping表存在，旧20/20静态hash与10-28冻结相同。因此旧文档“生产仍P2/DB未核实”已被实测推翻。quant2行/1产品，位置16，active用户3；附件423、distinct store_fname139、真实filestore139文件约42.7MB，DB约2599MB。公布入口team.l-creation.club根/login200，新P3页面与API404；严格TLS探测sslverify0。版本不等于公网入口已放行。

用户已提供提权凭据，已验证sudo只读可用；不把明文保存在本文/TOMC，也不再次索取。保护材料与固定hostkey helper路径见被Git忽略的ORCHESTRATOR_STATE和scripts/lc_root.py；保持DPAPI CurrentUser、secret仅stdin/askpass，不进argv/env/log。不可导出SSH插件存储密码。

备份必须先显式停odoo并证明无worker；默认odoo_backup.py见originally_active=False会保持停机且MANIFEST.service_managed=true/service_was_active=false。备份→真实store_fname集合核验→menu before→换码→升级连续维护，不在中途恢复业务写入；不改生产备份工具凑参数。旧P2空filestore59B+事后supplement不是一致回滚点，不能复用。新备份tar必须真实139引用路径集合覆盖、SQL失败即停、清单hash/size校验。回滚先停服，再还源码+DB/filestore+include，核真实before菜单与源hash，不能只查数据库版本。

只改项目服务，不动Docker/DNS/网络或其他业务。公网必须更新既有Netlify回源variant：/etc/nginx/conf.d/lc-bore-netlify.conf指向/var/lib/lc-elc-bore/releases/；loopback18445、origin-team.l-creation.club，使用render-netlify-gateway.py。不要误发plain-public variant。13旧动作GET/HEAD允许，写方法拒绝；不放开/odoo、/web/dataset、/jsonrpc。停机前只读确认项目catalog-import未active，不能擅停/注册crawler任务。部署后核quantity/reserved规范指纹、整模块文件hash、实际菜单、版本、严格TLS/public/login/新页/拒绝矩阵。生产无Odoo真实登录凭据，不猜SSH密码复用为网页登录。
