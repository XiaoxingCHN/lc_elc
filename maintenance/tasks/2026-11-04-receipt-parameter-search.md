# 任务：入库关键词搜索扩展到参数值（Web 统一 UI）

- Status: ready-for-human
- Category: enhancement

- 目标/用户场景：来料页建袋/建档时，用户经常只记得“10k”“100nF”“1%”这类参数，不记得型号或 C 编号。当前关键词只搜名称/型号/品牌/封装/C 编号，参数值搜不到；待入库队列也只能翻页，不能按追溯码/器件/状态筛选。
- 当前问题及复现方法：在 `/team/lab/receipts` 的“料号 / 关键词”输入 `10k` 或 `100nF`，候选只返回名称/型号等字段命中项，参数行不参与；本地档案的 `lab_specifications` 也不参与。待入库表没有关键词和状态筛选，只能按当前用户逐页翻。
- 验收标准：
  1. 输入 `10k`、`10K`、`10000`、`10kΩ`、`100nF`、`0.1uF` 等参数写法，能在 8 条内联候选中找到参数匹配的器件；扫码路径不变。
  2. 空格分词后按 AND 匹配：每个词必须命中名称、型号、品牌、封装、C 编号或关键参数值之一；不做拼音、纠错、模糊匹配。
  3. 关键参数按现有标签逻辑选取：电阻 `阻值/精度/功率`；电容 `容值/容量/电容量/耐压/额定电压/介质/材质`；其他类型取前 3 个。参数名只用于选取，不作为搜索词。
  4. 参数值归一化覆盖大小写、`Ω/ohm`、`k/M` 前缀、`u/µ`、容值等价（`100nF` = `0.1uF`）、`±` 百分比，以及低阻值 R 记法（`10Ω` = `10R`、`4.7Ω` = `4R7`、`0.1Ω` = `R1`，并覆盖常见 `4k7`/`1k5`）；同一查询的不同写法结果一致。
  5. 本地档案 `lab_specifications` 参与参数搜索；未绑定立创目录的本地件也能按参数搜到。
  6. 排序保持“本地有货优先，再按编号”；不新增相关性排序；不因精确 C 编号改变排序；供应商库存只展示，不参与“有货”。
  7. 内联候选保留 250ms 防抖、min 2 字符、8 条、8s 超时、最多 2 在途、IME 组字不检索；新增“查看全部结果”链接到 `/team/lab?q=<关键词>`，不新增弹窗。
  8. 待入库队列增加关键词 + 状态筛选：关键词匹配追溯码/名称/MPN/封装/SN，空格 AND；状态默认“待入库”，可选“全部/已入库/已取消”；服务端返回过滤后的 `total`，UI 显示“共 N 条”，保留 cursor 分页。
  9. 队列仍按当前用户 + 当前公司隔离；只读用户可打开自己的队列但不能创建；不改变 `canReceipt` 写权限。
  10. API 向后兼容：`/lab/api/catalog/search` 请求/响应字段只增不改；`/lab/api/inventory/pending/list` 新增 `query/state/total` 为可选；Flutter 不改 UI 也能继续调用；登录链路不变。
  11. 参数检索字段在导入和参数变更后保持新鲜：导入全量重写、ORM 变更增量重算；模块升级/部署提供一次性回填脚本，未回填时明示“索引未就绪”，不能静默漏结果。
  12. 测试覆盖上述行为；未对真实目录数据验证的部分明确标注。
- 允许修改目录/接口：
  - `server/ubuntu22.04/odoo_addons/lab_inventory/models/product_template.py`（新增 `lab_search_specs` 与索引）
  - `server/ubuntu22.04/odoo_addons/lab_inventory/tools/`（共享参数选取/归一化纯函数）
  - `server/ubuntu22.04/odoo_addons/lab_catalog/models/lab_catalog_item.py`（`search_params`、索引、分词 AND、`_lab_rows`/`_matched_codes_for_query`）
  - `server/ubuntu22.04/odoo_addons/lab_catalog/models/lab_catalog_param.py`（参数变更重算 hook）
  - `server/ubuntu22.04/odoo_addons/lab_catalog/tools/import_catalog.py`（导入写入 `search_params`、回填入口）
  - `server/ubuntu22.04/odoo_addons/lab_catalog/controllers/catalog_api.py`（仅必要校验/文档；端点不变）
  - `server/ubuntu22.04/odoo_addons/lab_workflow/models/lab_pending_receipt.py`（队列 query/state/total）
  - `server/ubuntu22.04/odoo_addons/lab_workflow/controllers/lab_inventory_api.py`（透传 query/state）
  - `server/ubuntu22.04/odoo_addons/lab_workflow/tools/label_parameters.py`（改为复用共享 helper，行为不变）
  - `server/ubuntu22.04/odoo_addons/lab_team_web/static/src/js/workflow_core.js`（combobox 可选“查看全部结果” footer）
  - `server/ubuntu22.04/odoo_addons/lab_team_web/static/src/js/pages/receipts.js`（队列筛选、view-all 链接）
  - `server/ubuntu22.04/odoo_addons/lab_team_web/views/workflow_receipt.xml`（队列筛选 UI、提示文案）
  - 对应测试：`lab_catalog/tests/test_param_search.py`（新增）、`lab_workflow/tests/test_p3_backend_api.py`/`test_workflow_business.py`（队列）、`lab_team_web/tests/test_combobox.mjs`/`test_workflow_core.mjs`、`lab_team_web/tests/test_p3_ui_consistency.py` 等
  - 文档：`docs/adr/0001-parameter-keyword-search.md`、`docs/development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md`（API 字段）、`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`、`maintenance/registry/components.json`（版本）、`maintenance/registry/routes.json`（无新路由，不预期改）
  - 不修改 `clients/app`、`plugins/jlc-eda`、`local/`、`clients/*/releases`、生产配置、DNS、Docker。
- 业务不变量/依赖：库存以 `stock.quant`/`stock.move` 为权威；供应商库存不得混入本地库存；待入库记录不是库存，确认前不增加总库存；绑定同 C 统一展示、库位/袋在详情展开；领用人必须是系统账号、归还关联原领料；搜索/筛选只读，不产生库存、袋或绑定写入；沿用现有 `/lab/api` JSON-RPC 与登录态，不新增认证方式。
- 负责人/协作者及分工：Main（实现、范围与验收闸门、最终复跑）；子代理仅做只读服务器审计和独立测试复核；生产写入、升级、回填执行需本轮或后续明确授权。
- 分支/起始commit/源码manifest：实现分支 `feat/receipt-param-search`，从 `main` 实施时 HEAD 切出并记录 SHA；当前 `main` 为 `c808065`（另有未提交设计文档与只读审计报告）；开工前不冻结、不提交、不推送；冻结时另建服务端源清单，旧 manifest/产物不改写。
- 环境与凭据获取方式（只写位置，绝不写值）：本机隔离 Odoo/PostgreSQL 测试环境按 `docs/development/SERVER.md` 与既有 runner 启动；服务器只读审计使用现有 `lc-nas` 运维连接，密码只在终端交互提示输入，不写入仓库、日志或任务文件；诊断只记录路径、计数、格式和哈希。
- 实施步骤：
  1. 只读服务器审计（2026-11-04 完成，见 `maintenance/audit/2026-11-04-catalog-parameter-audit.md`）：695,217 个目录件、4,110,477 条参数、940 个参数名、44,414 个不同值；实际写法 `10kΩ`/`±1%`/`1nF`/`50V/1kV`；`pg_trgm` 已装，`search_text`/`name` 已有 trigram GIN，参数表只有 B-tree；`search_text` 长度 30–203。只读，未改数据。
  2. 在低层模块 `lab_inventory` 提取共享纯函数：关键参数选取（复用 `key_parameters` 语义）与参数值归一化；补合成用例，覆盖 `10k/10K/10000/10kΩ`、`10Ω/10R`、`4.7Ω/4R7`、`0.1Ω/R1`、`4k7/1k5`、`100nF/0.1uF`、`±1%`、其他类型前 3 个。
  3. `lab_inventory.product.template` 新增 `lab_search_specs`（存储文本）与 trigram GIN；从 `lab_specifications` 解析、选取、归一化；模块升级回填本地档案。
  4. `lab_catalog.item` 新增 `search_params`（存储文本）与 trigram GIN；导入器按参数行写入；`lab.catalog.param` 的 create/write/unlink 增量重算；提供 batched 回填脚本。
  5. 改造 `_catalog_where`/`_lab_rows`/`_matched_codes_for_query`：查询按空格分词，AND 叠加，每个 token 在身份字段或参数字段中匹配；保留精确 C 编号路径和“本地有货优先”排序；facets 与 search 共用同一条件。
  6. 队列 API：`pending/list` 接受 `query`、`state`，返回过滤后的 `total`；保持 owner/company 隔离、默认行为向后兼容（API 不传 state 时不过滤；Web 默认传 `pending`）。
  7. Web UI：队列加关键词输入 + 状态选择 + “共 N 条”；combobox 加可选“查看全部结果” footer，链接 `/team/lab?q=<关键词>`；复用现有 250ms/8 条/2 在途/8s 超时逻辑。
  8. 测试：服务端 ORM/HTTP、JS 单元、真实浏览器（可执行时）；`python tools/repo_check.py`、`git diff --check`；记录命令、环境、退出码、通过/失败/跳过数量和未验证项。
  9. 版本与文档：更新 `lab_inventory`/`lab_catalog`/`lab_workflow`/`lab_team_web` 版本与 `components.json`；更新 CHANGELOG、CURRENT_STATE、API 文档；写交接。生产部署/回填不在本任务内。
- 测试命令、实际结果与退出码：只读审计已执行，实现测试待实施。计划：
  - 只读审计（2026-11-04）：`ssh -t lc-nas` + `sudo -u postgres psql -d LcHardwareHouse -At -F '|'`，仅 SELECT，两轮均完成并正常关闭；结果见 `maintenance/audit/2026-11-04-catalog-parameter-audit.md`。
  - `python tools/repo_check.py`（期望 exit 0；若有既有 error/warning，单独列明）
  - 既有隔离 Odoo runner：`<runner> --test-tags /lab_catalog,/lab_workflow`（记录实际命令、DB、exit code、tests/failures/errors/skips）
  - `node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_combobox.mjs`
  - `node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_workflow_core.mjs`
  - `git diff --check`
  - 真实浏览器（本机既有 `local/web-ui-implementation/browser/` 工具）：`10k`、`100nF`、`0.1uF`、多词 AND、队列状态筛选、`/team/lab?q=` 跳转。
- 未验证项及风险：
  - 真实目录参数名/值已做只读抽样（2026-11-04），但 `uF/µF` 未在 Top 40 出现、短 token `1%` 的选择性未用 `EXPLAIN` 验证；归一化别名仍需合成用例和实现后真实查询复核。
  - 本地档案只有 2 条占位记录且 `lab_specifications` 为空；验收标准第 5 条只能合成验证，不能宣称生产覆盖。
  - `search_params`/`lab_search_specs` 回填在 695,217 件 / 4,110,477 行参数上可能耗时；需分批、可重入、可观测，不能阻塞 Odoo 主进程。
  - 短 token（如 `1%`）的 trigram 效果有限；`1%` 单独命中约 98,180 行，参数值歧义可能产生误命中，需用真实样本评估。
  - Flutter 共用搜索语义但本轮不改 UI；Flutter 回归测试未跑，不能宣称三端一致通过。
  - 生产索引创建、模块升级、回填、HTTPS/传输配置均需单独授权与备份/回滚方案。
  - 供应商库存仍只展示；不得把 `catalog_stock` 当作本地“有货”。
  - `search_text` 生产长度 30–203，512 上限未触顶；ADR 已修正，不把长度当作分离字段的主要理由。
- 发布文件、hash和回滚点：本任务不产出安装包、不部署。冻结时用 `tools/release.py snapshot --component server ...` 建新源清单并记录 treeSHA/manifestSHA；旧 manifest 和产物不改写。代码回滚为 `git revert`/回到实现前 SHA；生产回滚需另建部署任务，先做一致备份并保留旧模块源码。

## 进展

### 2026-11-04 只读审计完成

- 生产库只读核查：695,217 个目录件、4,110,477 条参数、940 个参数名、44,414 个不同值；`pg_trgm` 已装，`lab_catalog_item.search_text/name` 已有 trigram GIN，`lab_catalog_param` 只有 B-tree。
- 实际写法：阻值 `10kΩ/1.5kΩ/1MΩ`，精度 `±1%`，容值 `1nF/470pF`，额定电压 `50V/1kV`；`detail_value` 与 `value` 相同。
- 修正假设：`search_text` 长度 30–203，512 上限未触顶；`parameterCode` 与中文名稳定对应；本地档案只有 2 条空规格。
- 证据：`maintenance/audit/2026-11-04-catalog-parameter-audit.md`。未执行任何写操作、升级、重启或导入。
- `python tools/repo_check.py` exit 1：51 项通过、1 错误、16 警告；错误为既有 `frozen-source:client`（`clients/app/t.obj` 本机文件被旧冻结清单计入），与本次文档/审计修改无关；`git diff --check` exit 0。
- 下一步：按任务步骤 2 开始实现；生产索引/回填需单独授权。

### 2026-11-04 源码实现完成（待 Odoo 环境复测）

- 分支/工作区：`feat/receipt-param-search`，工作区 `F:\lc_elc\.claude\worktrees\read-tomc-memory-56e7a2`；基线 `main` `c808065`。未提交、未推送。
- 版本：`lab_inventory 19.0.1.1.0`、`lab_catalog 19.0.2.0.6`、`lab_workflow 19.0.2.0.1`、`lab_team_web 19.0.1.2.1`；`components.json` 已同步。
- 已实现（对应验收 1–12）：
  - 共享 helper `lab_inventory/tools/param_search.py`：关键参数选取与标签一致；归一化覆盖 SI 前缀、`Ω/ohm`、`100nF = 0.1uF`、`±1%`、`1kV = 1000V`、`10Ω = 10R`、`4.7Ω = 4R7`、`0.1Ω = R1`、`4k7`、`1k5`；保留原始与 NFKC 写法。
  - `product.template.lab_search_specs`（存储 + trigram GIN + `19.0.1.1.0` 分批迁移回填）；`lab.catalog.item.search_params`（trigram GIN）+ 参数 create/write/unlink 增量重算 + 导入器写入 + `tools/backfill_search_params.py` 独立分批回填；完整回填后写 `lab_catalog.param_index_state=ready`。
  - `_catalog_where` / `_lab_domain` / `_matched_codes_for_query` 改为空白分词 AND；身份字段或参数文本命中即可；排序不变；`search` 与 `facets` 共用条件。
  - `/lab/api/catalog/search` 响应新增 `param_index_ready`；`pending/list` 新增可选 `query`、`state`、`total`（不传 state 保持旧行为）。
  - Web 队列关键词/状态筛选、"共 N 条"、combobox "查看全部结果"（空结果/失败隐藏）、索引未就绪提示。
- 测试实际执行：
  - `python server/ubuntu22.04/odoo_addons/lab_catalog/tests/test_param_search.py -v` → **8/8 OK**。
  - `node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_combobox.mjs` → **21/21 passed**。
  - `node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_workflow_core.mjs` → **19/19 passed**。
  - `python -m py_compile`（改动 Python 文件）→ OK；`git diff --check` → 0。
  - 新增 `lab_catalog/tests/test_catalog_param_search_orm.py`（参数检索、R 记法、容值、AND、本地档案、索引就绪）与 `lab_workflow/tests/test_workflow_business.py` 队列用例，**未执行**：本工作区无可用 Odoo/PostgreSQL 测试实例；不得记作通过。
- `python tools/repo_check.py` exit 1：51 项通过；唯一错误为既有 `frozen-source:client`（`clients/app/t.obj` 缺失，与本轮无关）；16 条 payload 缺失为既有警告。已新建并激活 `maintenance/registry/source-server-param-search-20261104-r2.json`（264 文件、tree_sha256 `503e278221851fa129351bae12e95b6da5a8eeb5192d4e8ab2e5907c270ab378`、清单 sha256 `485c93c2ca3d1543bf8bb8838acb538f24c0a6f23ae4b68418cd4c8f3410b86a`；r1 保留为历史未改写），`frozen-source:server` 已消除。`generate_routes.py --check` exit 0（routes.json 重新生成至 92 项，含合并后既有的 13 条 legacy 入口；本任务未新增路由）。
- 未做/阻塞：模块升级、生产索引创建、参数回填、目录导入、重启、部署、真实业务写；真实浏览器、Flutter、生产数据验证。均需单独授权或在具备 Odoo 的环境执行。
- 交接：`maintenance/handoffs/2026-11-04-receipt-parameter-search.md`。
