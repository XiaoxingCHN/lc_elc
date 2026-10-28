# 任务：P3自有Web日常业务补齐

> 2026-10-28 17:14（Asia/Shanghai）：用户明确授权“推送更新”。沿用既有 `origin`，提交并推送 `feat/p3-web-workflows-20261028`；范围为完整冻结服务器源码与相关登记、运维和验收文档。仅 Git 更新，不授权生产部署或强推。安装包/本机载荷及独立架构图工作不纳入本次提交。

- 目标/场景：继续补齐日常操作，复用已有后端，让自有Web支持两阶段入库、领用归还、袋追溯/扫码、库位和标签。
- 当前问题：P2目录/详情与真实登录正常，写业务页尚未接入。手机无VPN验收单列，不阻塞开发。
- 验收：隔离真实ORM/HTTP/浏览器；权限、stock.quant/stock.move权威、幂等/并发/失败回滚、跨账号归还、每袋单QR，保留实际命令/退出码与未测项。
- 分工：用户授权并行子代理数量不限，Qoder DeepSeek与WorkBuddy DeepSeek可用；主代理只协调关键契约/审查/来源登记。原生spawn被观察为GPT已停止，改用当前GUI3733/codex-bridge，实际模型以observedConfig为准。
- 首批：backend/ui使用magpie/qoder-cn/dfmodel，validation使用magpie/workbuddy-ai/deepseek-v4.1-flash，high。先只读盘点/上游研究，契约确定后给互斥业务写范围。会话ID与游标在local/build/p3-web-20261028，不保存凭据。
- 起点：server2026.10.27.3、team_web19.0.1.0.5、workflow19.0.1.2.0，active-sources为准。既有dirty改动保留，不覆盖旧manifest/包。
- 范围：本地业务实现/隔离测试/可审查候选；禁止生产测试用户或库存、真实凭据读取；生产发布须具备来源/备份/回滚，不执行网站卸载。
- 步骤：盘点→复用研究→契约→前后端并行实现→独立验收修正→版本/冻结/交接。
- 测试/未验证/发布文件：执行后补充，旧P2通过不等于本轮P3通过。

## 执行进展（2026-10-28，源码候选，未发布）

### 已交付源码（写域互斥）

- `lab_team_web`：13 个业务页面路由（`/team/lab/receipts`、`/team/scan`、`/team/lab/bags`、`/team/lab/bags/<id>`、`/team/lab/labels`、`/team/lab/issues/new`、`/team/lab/issues`、`/team/lab/history`、`/team/lab/locations`、`/team/lab/location-mappings`、`/team/lab/settings`、`/team/lab/materials`、`/team/account`，均有根别名）+ 外壳模板 + `window.LC` 运行时 + 13 个页面脚本。
- `lab_workflow`：8 个 JSON-RPC 窄接口（bags/bag/location_update/mapping_list/mapping_set/mapping_remove/members/member_set_role）、新模型 `lab.location.mapping`、`POST /lab/labels/pdf`、`GET /lab/scan` → 303 `/team/scan`、安全修复 S1 跨账号归还/S2 畸形入参/S3 adopt_stock savepoint/S4 按 id 读取公司复核/S5 停用库位。
- `server-ops`：公网 allowlist 模板新增 P3 页面与逐端点 POST（源码，**未部署**）；新增 `verify-p3-write.sh`、`browser_flow_p3.py`、`test_p3_runner.py`、`test_p3_gateway_contract.py`。

### 版本（Lead 已统一，`components.json` 已同步）

`lab_workflow 19.0.1.2.0 → 19.0.2.0.0`、`lab_team_web 19.0.1.0.5 → 19.0.1.1.0`、`server-ops 2026.10.27.3 → 2026.10.28.1`；`lab_catalog`/`lab_inventory`/`lab_theme`/`lab_site`/`client 1.1.3+6`/`eda 3.0.3` 不变。生产仍是 P2。

### 实际测试结果（分项；不等价生产通过）

| 轮次 | 结果 | 证据 |
|---|---|---|
| core | **17/17** | `core-r2.log` |
| XML | **6/6** 解析通过 | `repairs-r2-results.json` |
| JS 语法 | **15/15**（`team.js`+`workflow_core.js`+13 页面脚本） | `fast-r1-js-*.log` 及 Main 计数 |
| 路由表 | **79 条**，`--check` 通过 | `maintenance/registry/routes.json` |
| 隔离 ORM 业务 | **82/82，0 fail 0 error**（**role wrapper 之后重测**） | `backend-orm-final.log`、`backend-orm-final-evidence/` |
| 进程内并发（独立 adapter） | **6/6**，负向自检 `detected=true`；`test_enable:false`、`registry_cursor_patched:false` | `concurrency-standalone-r3.json` |
| 真实 HttpCase | **21/21**（`failed=0 errors=0 p3_class_ran=1`，RC=0） | `httpcase-r8.log` |
| 写业务 API 断言 | **54 pass / 0 fail / 1 blocked**（total 55；blocked=Origin 断言，未提供 Origin URL，不改 PASS） | `runs/run.KOJbZY/verify-summary.json` |
| Nginx 配置契约 | 1.26.2 **34/34**、1.30.6 **34/34**（源码，未部署） | `real-nginx-r2-results.json` |
| linux runner | **17 项 OK** | `runner-linux-r2.log` |
| 浏览器真实流程 | **31 步 28 pass / 0 fail / 3 blocked**（3 blocked=DOM 场景未执行，他层覆盖） | `runs/browser-20261028T065311Z/browser-p3.json` |
| 仓库检查 | **52 项 PASS，exit 0**；唯一 warning `production-py312-rebuild` | `repo-final-r1.json` |
| 历史（已修复，留档） | ORM R3 1 failed / R4 1 error / HTTP R2 6 failed / HttpCase 9 error / 浏览器缺 `websockets` | R3–R5 各日志、`httpcase-r5.log` |

### 本轮已完成（冻结 / 构建 / 登记）

- 源快照 `maintenance/registry/source-server-p3-web-20261028.json`：**250 文件**，
  treeSHA `fc2d538d…5ab43`，manifestSHA `0bfc1e3f…c164`；`active-sources.server` 已指向它，旧 manifest/产物未覆盖。
- 候选包 `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`：
  13,186,981 B，SHA256 `9070800b…49e564`；250 文件逐条 raw+normalized 校验 + 251 归档条目重读一致；
  Windows 11 + Python 3.15 stdlib zip；纯源码、无 runtime/数据库/凭据；源码 ZIP 签名 N/A。
- 登记 `maintenance/registry/artifact-server-p3-web-20261028.json`；构建摘要 `build-summary*.json`（同目录）。

### 后续事项（本轮不覆盖）

1. **3 个 DOM 场景未执行**（cross-user / same-key-different-payload / unknown-outcome），仅有 API/HttpCase/core 覆盖；如要 DOM 覆盖需补浏览器场景，不得记作 DOM 通过。
2. 原 `--test-enable` 并发套件 **Registry 锁 blocked**（Probe 证实 `Registry._lock` 主线程持有），wrapper exit 1；不得写"原套件通过/命令全绿"。
3. 公网联调与生产部署未做（精确门槛在 Nginx；Netlify `/*` 通配透传无需增补）；部署前需一致备份与回滚方案。
4. 测试口径：`test_04` quantity 精确匹配实际成功请求（10 或 11）；互撤后留 1 manager，`FORBIDDEN` 属合法撤销。
5. 产品修复留档：`receipts.js` `lcsc:`→裸 `C…`、`lab:<id>` 走 `catalogDetail`；trace 只取本轮新增 DOM 行 `td` 的 `raw`，仅扫码补 `LABB:`。

> 路由表已同步：`maintenance/registry/routes.json` 已重生成并通过 `python tools/generate_routes.py --check`（79 条）。
> `repo-final-r1.json`：**52 项 PASS，exit 0**，唯一 warning 为 `production-py312-rebuild`；旧 active 源 hash 漂移已随冻结消除，已无 credential-scan 失败。
> 合成测试库与证据已保留；Lead 自建项目 PG 已按租约精确停止，**无活跃测试服务**。

### 未验证 / 只能用户验收（以后事项，本轮不覆盖）

实体纸张打印、实体摄像头/扫码枪、公网正式域名手机流量不挂 VPN、真机安装升级、业务人工走查。
生产 **Python 3.12 与隔离 runtime 3.10.12 不等价**，生产 cp312 wheelhouse 缺失、"完整离线恢复"未闭合；
一致 filestore 备份仍未取得（P2 备份 filestore 空归档 + 独立 supplement、与 `db.dump` 非同一时刻）。

### 发布文件

本轮**无**新客户端产物、**无**生产部署。服务端候选包与登记**已完成**：
`local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`（13,186,981 B，
SHA256 `9070800b…49e564`）+ `maintenance/registry/artifact-server-p3-web-20261028.json`；
冻结源 `source-server-p3-web-20261028.json`（250 文件，treeSHA `fc2d538d…5ab43`）。旧 manifest/产物未覆盖。
构建器与说明见 `local/build/p3-web-20261028/build-candidate.py`、`build-candidate-plan.md`。
详细交接见 `maintenance/handoffs/2026-10-28-p3-web-workflows.md`。
