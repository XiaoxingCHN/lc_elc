# 维护交接：2026-10-28 P3 自有 Web 日常业务（冻结/构建/登记完成，未部署生产）

> 本文件取代 `2026-10-28-p3-in-progress.md` 的"下一步"。当前状态：**源码已冻结、候选包已构建并登记**；
> **未部署生产、未开放公网**，也不构成"生产等价通过"。

## 用户目标与已确认边界

- 目标：把自有 Web（`lab_team_web`）从"只读检索"补齐为日常业务闭环——两阶段入库、领用/归还、袋与追溯、库位、标签、流水、档案、管理、账号；**复用 `lab_workflow` 既有 stock.move/quant 业务层，不新建第二套库存逻辑**。
- 明确不做：新身份系统、通用 ORM 透传（`/web/dataset/call_kw`、`/jsonrpc` 恒拒绝）、复制 OCA/AGPL-3 实现、卸载网站/清库。
- 边界：测试只用隔离库与合成账号；不读真实凭据/数据库/备份内容；不连 NAS；不申请提权或 ACL 修复。
  子代理（bridge 子会话）的 `pwsh` 因沙箱前置 ACL 步骤失败（`SetNamedSecurityInfoW failed (Win32 5)`），
  **主代理 `pwsh` 正常**；本轮所有命令由主代理统一执行，不是磁盘普遍不可用。
- 版本/登记由 Lead 统一改（实现者不改 manifest 版本）。

## 当前权威源码、分支和版本

- 分支：`feat/p3-web-workflows-20261028`（既有无关本机改动保留；未合并 main。2026-10-28 用户已授权 Git 推送，提交以远端该功能分支为准）。
- 源码候选版本（`maintenance/registry/components.json` 已同步）：

| 组件 | 源码候选 | 上一版 | 生产实际 |
|---|---|---|---|
| `lab_workflow` | **19.0.2.0.0** | 19.0.1.2.0 | 19.0.1.2.0（P2） |
| `lab_team_web` | **19.0.1.1.0** | 19.0.1.0.5 | 19.0.1.0.5（P2） |
| `server-ops` | **2026.10.28.1** | 2026.10.27.3 | 2026.10.27.3 |
| `lab_catalog` | 19.0.2.0.5（不变） | — | 19.0.2.0.5 |
| `lab_inventory` | 19.0.1.0.0（不变） | — | 19.0.1.0.0 |
| `lab_theme` / `lab_site` | 19.0.1.0.2 / 19.0.1.0.0（不变） | — | 未涉及 |
| `client` | 1.1.3+6（**不变**） | — | 1.1.3+6 |
| `eda` | 3.0.3（不变） | — | 3.0.3 |

- 候选版本口径见 `local/build/p3-web-20261028/candidate-versions.json`（`status: verified-frozen-source-candidate`、`production_changed: false`、`client_changed: false`）。
- **冻结已完成**：`maintenance/registry/source-server-p3-web-20261028.json` 已生成并激活，包含 **250 个文件**；
  `active-sources.json` 的 server 指针已更新；旧 `source-server-netlify-https-origin-20261027.json`（211 文件）及其产物关联保持不变。
  最终 `python tools/repo_check.py` 为 **52 项通过、0 错误、exit 0**，仅保留生产 cp312 恢复载荷 warning。
- **路由表已同步**：`maintenance/registry/routes.json` 已由主代理重新生成并通过
  `python tools/generate_routes.py --check`（**79 条**），包含 P3 的 13 个页面与 8 个接口，不再是旧表。

### 本轮源码改动（写域互斥）

- `lab_team_web`：新增 `controllers/workflow_pages.py`（13 个页面路由，成对 `/team/...` + 根别名）、`views/{team_templates,workflow_receipt,workflow_issue,workflow_inventory,workflow_account}.xml`、`static/src/js/workflow_core.js`、`static/src/js/pages/*.js`（13 个）、`static/src/css/workflow_*.css`、`tests/test_p3_web_contract.py`、`tests/test_p3_workflows_http.py`；修改 `__manifest__.py`（版本 + data）、`controllers/{common,api,__init__}.py`、`views/pages.xml`、`tools/paths.py`、`static/src/css/team.css`、`tests/{test_paths,test_entry_contract}.py`。
- `lab_workflow`：新增 `controllers/lab_p3_api.py`（8 个 JSON-RPC 路由：`inventory/bags`、`inventory/bag`、`inventory/location_update`、`inventory/mapping_list|mapping_set|mapping_remove`、`inventory/members`、`inventory/member_set_role`）、`models/lab_p3_api.py`、`models/lab_location_mapping.py`（**新模型 `lab.location.mapping`**）、`tools/p3_rules.py`、`tests/test_p3_backend_api.py`、`tests/test_p3_contract_logic.py`；修改 `controllers/lab_web.py`（`GET /lab/scan` → **303 `/team/scan`**，旧 `resolve/submit` 标 deprecated）、`controllers/lab_labels_api.py`（新增 `POST /lab/labels/pdf`，表单 POST + CSRF，浏览器直出 PDF）、`lab_inventory_api.py`、`lab_web.py`、`models/{lab_workflow_api,lab_workflow_common,lab_pending_receipt,lab_legacy_stock,lab_labels}.py`、`security/{ir.model.access.csv,lab_workflow_rules.xml}`。
- `server-ops`（bore）：`nginx/bore-public-allowlist.conf.template` 新增 P3 页面 GET/HEAD 与逐端点 POST 白名单（**明确不登记** `adopt_stock`、`legacy_stock`、通用 ORM）；新增 `scripts/verify-p3-write.sh`、`tests/{browser_flow_p3.py,test_p3_runner.py,test_p3_gateway_contract.py}`。
- 客户端 / EDA / 采集：未改。

## 已完成工作与实际证据

全部证据在 `local/build/p3-web-20261028/`（Git 排除）。**"通过"只按下列计数成立，未列出的项一律未测。**

### 已通过（可复核）

| 项 | 结果 | 证据 |
|---|---|---|
| core | **17/17** | `core-r2.log` |
| XML | **6/6** 解析通过（`xml_errors: []`） | `repairs-r2-results.json` |
| JS 语法 | **15/15**（`team.js` + `workflow_core.js` + 13 个页面脚本） | `fast-r1-js-*.log`（早期 5 个逐文件）+ 本轮 Main 计数 |
| 路由表 | **79 条**，`generate_routes.py --check` 通过 | `maintenance/registry/routes.json` |
| 隔离 ORM 业务 | **82/82**（R7；**该轮在 role wrapper 之前**，新角色逻辑另由 standalone `test_06` 实测覆盖） | `backend-orm-r7.log`、`orm/manifest.json` |
| 进程内并发（独立 adapter） | **6/6**，负向自检 `negative_control.detected=true`，exit 0；`test_enable:false`、`registry_cursor_patched:false`、python 3.10.12 | `concurrency-standalone-r3.json`、`concurrency-standalone-r3.log` |
| 真实 HttpCase | **21/21**：`total=21 failed=0 errors=0 p3_class_ran=1`，`HTTPCASE_ONLY_RC=0` | `httpcase-r8.log` |
| 写业务 API 断言 | **54 pass / 0 fail / 1 blocked**（total **55**；1 blocked 为 Origin 断言，本轮未提供 Origin URL，**不得改判 PASS**） | `runs/run.KOJbZY/verify-summary.json` |
| Nginx 配置契约 | 1.26.2 **34/34**、1.30.6 **34/34**（源码层；**未部署**） | `real-nginx-r2-results.json` |
| linux runner | **17 项 OK** | `runner-linux-r2.log` |
| 浏览器主链（R8） | **31 步 28 pass / 0 fail / 3 blocked**，`unreached=0`；3 blocked 为 `p3-cross-user-denied`、`p3-receipt-same-key-conflict`、`p3-unknown-outcome-retry` 的 **DOM 场景未执行**（由 API/HttpCase/core 独立覆盖，**不得称 DOM 通过**） | `runs/browser-20261028T065311Z/browser-p3.json`、`browser-r8.log` |

浏览器同轮实测业务事实（UI+服务端两侧一致）：两种 canonical key 均可用、建袋**不增 quant**、
上架 **+2**、重复确认 **quant 不变**、领用 **−2**、部分归还 **+1**；role / materials / locations / mappings
管理页通过；`LABB:`/`LABL:`/SN/立创原厂码路径未改。

### 未通过 / 未闭合

| 项 | 现状 | 影响 |
|---|---|---|
| 3 个 DOM 场景未执行 | `cross-user`、`same-key-different-payload`、`unknown-outcome` 仅由 API/HttpCase/core 覆盖 | 报告中必须写"DOM 未覆盖"，**不得写成 DOM 通过** |
| 原 `--test-enable` 进程内并发套件 | **blocked（Registry 锁）** | **不得写"原进程套件通过"**；6 条断言由独立 process adapter 复用执行（6/6） |
| 冻结 / 构建 / artifact | **已完成**（250 文件快照 + 候选 ZIP + artifact 登记，见 §冻结与产物） | — |
| 公网 / 生产 | allowlist 仅源码未部署；生产仍 P2 | G1–G9 未逐项宣称通过；未部署 |

### 历史失败（已修复，保留追溯）

ORM R3 1 failed（last-manager fixture）→ R4 1 error → R5/R6 并发未执行 → R7 业务 82 全过；
HttpCase 21 项 9 error（`authenticate` AccessDenied，fixture 生命周期/RR 快照）→ R8 21/21；
API 曾 49 pass/4 fail/1 blocked → 54 pass/0 fail/1 blocked；浏览器曾缺 `websockets` 只记 5 步 →
R6 记录 30 步（19 pass/1 fail/10 blocked，fail=解析料号等待超时）→ **R8 31 步 28 pass/0 fail/3 blocked**。

**结论（准确口径）**：**候选功能验证完成**——各分项均有真实证据，浏览器主链 0 fail；
仍有 3 个 DOM 场景未执行、原进程套件 Registry 锁 blocked 两项**覆盖性说明**，以及**未部署/未开放**。
因此：可以进入 **Lead 冻结 → 构建 → artifact 登记**，**不能**写成"全部门槛通过"或"生产等价通过"，
也不代表已发布。冻结与产物已落地（见 §冻结与产物），无遗留 TBD。

### 候选内产品修复（本轮）

- `receipts.js`：`lcsc:<C码>` 正确转成**裸 `C…`** 再交 `resolve`；`lab:<id>` 走既有 `catalogDetail`
  适配以保住**具体本地档案**；`LABB:`/`LABL:`/SN/立创原厂码路径**不改**。
- 测试读 trace 的口径（Main 修）：只从**本轮新增的唯一 DOM 行 `td`** 读 `raw` trace；**仅扫码时**才补
  `LABB:` 前缀；**不得**要求表格文本里出现 QR 前缀（那是把测试写法当业务约束）。

### 测试口径修正（写报告时必须遵守）

1. 新 **role wrapper** 会正确重试并**重验授权**；两管理员并发互撤后仍保留 **1 名 manager**，
   另一侧返回 `FORBIDDEN` 属**合法权限撤销**，不是缺陷（`concurrency-standalone-r3.json` `test_06`：
   `successes=1`、`remaining_manager_ids=[28]`）。
2. `test_04` 的 quantity 断言由 Lead 改为**精确匹配实际成功请求**（并发成功方可能是 10 或 11），
   **不得硬编码 10**。
3. 仓库检查：`repo-final-r1.json` **52 项 PASS，exit 0**，已无 credential-scan 失败；
   旧 active 源 hash 漂移已随冻结消除；`production-py312-rebuild` 仍为 warning，保留记录。

## 冻结与产物（本轮已完成）

- 源快照：`maintenance/registry/source-server-p3-web-20261028.json` — **250 源文件**，
  treeSHA `fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43`，
  manifestSHA `0bfc1e3f581d90109c3e8942ff85cd9880a22ceac950d3c6fd93c0e90389c164`；
  `active-sources.server` 已指向该快照；**旧 manifest 与旧产物未覆盖**。
- 候选包：`local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip` —
  13,186,981 B，SHA256 `9070800b65b8fa3c751b5d4ac0dc5d94910a97e27128adbd0ff4370c4549e564`；
  250 个文件逐条 raw + normalized 校验、**251 个归档条目重读**全部一致；
  构建环境 Windows 11 + Python 3.15 stdlib zip；**纯源码，无 runtime/数据库/凭据**；源码 ZIP **签名 N/A**。
- 登记：`maintenance/registry/artifact-server-p3-web-20261028.json`；构建摘要 `build-summary*.json`（同目录）。
- 仓库检查：`repo-final-r1.json` — **52 项 PASS，exit 0**，唯一 warning `production-py312-rebuild`。
- 运行环境收尾：合成测试库与证据保留；Lead 自建项目 PG 已按租约**精确停止**，**无活跃测试服务**。

## 后续事项（本轮不覆盖）

1. **3 个 DOM 场景**：cross-user / same-key-different-payload / unknown-outcome 目前只有 API/HttpCase/core 覆盖；
   如要 DOM 级覆盖需补浏览器场景，**不得以"已被其他层覆盖"写成 DOM 通过**。
2. **原 `--test-enable` 并发套件**：Registry 锁 blocked（Probe 证实 `Registry._lock` 主线程持有），wrapper exit 1；
   不得写"原套件通过/命令全绿"；6 条断言由独立 process adapter 覆盖。
3. **公网 / 生产**：Nginx allowlist 已就绪但**未部署**；Netlify 为 `/*` 通配透传、`_headers` 亦 `/*`、无 functions，
   **无需逐路径增补**；部署前须完成一致备份与回滚方案（见下节），G1–G9 不得整体宣称通过。
4. 根文档切换：`HANDOFF_CURRENT.md` 等由 Lead 决定时点。

## 依赖和产物

- 隔离运行资产（本机，非 Git）：runtime rootfs `/var/tmp/lc-elc-clean-apt-20261014-082927-594/rootfs`（Python 3.10，**不等同生产 3.12.15**）、WSL 私有 PG14、解包版 Chrome（`local/build/bore-p2-20261026/chrome/...`）。
- 依赖登记：`maintenance/registry/payloads.json`（Flutter/Android/JDK/VC/WSL 工具链/cp310 wheelhouse）；恢复入口 `python tools/fetch_payload.py --id <ID> --verify`。
- **未关闭的依赖缺口**：生产 cp312 wheelhouse 不存在（仅 `extras-barcode/python312` 的 `rl_renderPM` 1 个 wheel）、npm 离线缓存无包内容（`npm ci --offline` 从未通过）。
- 本轮**不产生**新客户端产物；无新 APK，因此不涉及签名/`release_sequence`。服务端候选包与登记见 §冻结与产物。

## 生产状态和回滚

- **生产未变更**：`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5`、`lab_workflow 19.0.1.2.0`（P2，2026-10-27）。本轮无部署、无 `-u`、无重启、无 DNS/公网改动、无生产库读写。
- 若将来发布：必须**新做一份一致备份**（`odoo_backup.py`，服务停服后同时取 `db.dump` + `filestore.tar.gz`），核对 `pg_restore --list` 与 filestore 文件数；回滚用发布包 `rollback.sh`，数据库级回滚才用 `odoo_restore.py`（会 `DROP DATABASE`，覆盖备份后所有业务写入），回滚后复核库存不变量。
- **旧备份不能当回滚点（未解决）**：P2 备份 `20261027T092321Z-before-p2-update` 的首份 `filestore.tar.gz` 只有 59 字节空归档，139 个真实附件在**独立** `filestore-supplement.tar.gz`、不在 `MANIFEST.artifacts`，且是服务恢复后补做、与 `db.dump` **非同一时刻**；`odoo_restore.py` 只解 `filestore.tar.gz` → 用它恢复会得到不完整附件。2026-10-18 的 `module-cleanup-production-20261018T153740Z` 仅登记路径与 db dump sha256，未离机、未做恢复演练。`upgrade_modules.sh` 硬编码三模块、**不含 `lab_team_web`**，不能直接用。
- 公网：`team` A 记录在文档中两处记载冲突（`159.223.110.159` vs `192.168.31.105`），发布前须现测；`8069` 原始端口曾在 `bore.pub` 暴露约 13 分钟，**禁止再现**。

## 仍需用户亲自验收（未关闭）

1. 手机流量**不挂 VPN** 打开正式域名 → 登录 → 刷新保持 → 退出。
2. 实体摄像头/扫码枪扫码（`LABB:`/`LABL:`/立创原厂袋码）。
3. 实体纸张打印（A4 标签、字号、单 QR 可扫）。
4. 真机安装/升级（Android/Windows/Linux）。
5. 业务人工走查：建袋 → 上架 → 领用 → 部分归还 → 追溯。

## 调度备注（不计入用户阻塞）

- bridge 子会话的 `pwsh` 因沙箱前置 ACL 步骤失败，**主代理 `pwsh` 正常**；所有命令由主代理执行，
  不改宿主 ACL、不申请提权。
- 曾出现"派发消息漏写具体 objective 导致新代理停问"：已取消该无写入回合并补发完整 objective 恢复，
  属调度操作问题，**不计为用户阻塞**，也不改变本文件的验收口径。
- 子任务写域互斥：`concurfix`（进程内并发框架）、`apifix`（API 断言）、`browserfix`（浏览器依赖/流程）、
  `validation`（HttpCase fixture）各自独占文件，不得互改。

## 验收与冻结摘要（无 TBD）

| 字段 | 值 |
|---|---|
| source manifest | `maintenance/registry/source-server-p3-web-20261028.json`（**已生成**，250 文件） |
| tree_sha256 | `fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43` |
| manifest_sha256 | `0bfc1e3f581d90109c3e8942ff85cd9880a22ceac950d3c6fd93c0e90389c164` |
| 候选 ZIP | `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`，13,186,981 B，SHA256 `9070800b…49e564` |
| artifact | `maintenance/registry/artifact-server-p3-web-20261028.json` |
| ORM `business_total` | **82/82，0 fail 0 error**（role wrapper 之后重测，`backend-orm-final.log`） |
| 并发（独立 adapter） | **6/6**，负向自检 `detected=true`（`concurrency-standalone-r3.json`） |
| API 断言 | **54 pass / 0 fail / 1 blocked**，total 55（Origin URL 未提供，blocked 不改 PASS） |
| HttpCase | **21/21**（`httpcase-r8.log`） |
| 浏览器 31 步 | **28 pass / 0 fail / 3 blocked**（DOM 场景未执行） |
| Nginx / runner / core / XML / JS / routes | 34+34 / 17 / 17 / 6 / 15 / 79 |
| repo | `repo-final-r1.json` 52 项 PASS，exit 0；唯一 warning `production-py312-rebuild` |
| 未覆盖 | 3 个 DOM 场景；原 `--test-enable` 并发套件 Registry 锁 blocked（非通过） |
