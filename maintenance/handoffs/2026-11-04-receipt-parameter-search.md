# 维护交接：2026-11-04 入库参数关键词搜索（源码候选）

## 用户目标与已确认边界

- 用户目标：来料页建袋/建档时，除名称/型号/品牌/封装/C 编号外，还能按参数值搜索（如 `10k`、`100nF`、`0.1uF`、`10R`），并给待入库队列加关键词/状态筛选。
- 已确认语义：空白分词、每词 AND；不做拼音/纠错/模糊匹配；关键参数与标签选取一致；本地实验室库存为权威，供应商库存不参与“有货”；排序保持本地有货优先，不新增相关性排序。
- 本轮只改服务端与 Web UI，不改 Flutter/EDA、不改登录链路；API 字段只增不改。生产升级、索引创建、参数回填、导入、重启、部署均未授权、未执行。

## 当前权威源码、分支和版本

- 分支 `feat/receipt-param-search`，从 `main` `c808065` 切出；工作区 `F:\lc_elc\.claude\worktrees\read-tomc-memory-56e7a2`。
- 版本：`lab_inventory 19.0.1.1.0`、`lab_catalog 19.0.2.0.6`、`lab_workflow 19.0.2.0.1`、`lab_team_web 19.0.1.2.1`；`maintenance/registry/components.json` 已同步。
- 服务端冻结源：`maintenance/registry/source-server-param-search-20261104-r2.json`，`file_count=264`，tree_sha256 `503e278221851fa129351bae12e95b6da5a8eeb5192d4e8ab2e5907c270ab378`，清单 sha256 `485c93c2ca3d1543bf8bb8838acb538f24c0a6f23ae4b68418cd4c8f3410b86a`；`active-sources.server` 已指向 r2，r1 与旧 r3 清单均未改写。r2 在 r1 基础上修正“参数全部移除时 ORM 把空文本写成 NULL，被就绪扫描误判为未回填”，改用单空格哨兵。
- `maintenance/registry/routes.json` 已重新生成至 92 项；本任务未新增路由，新增项来自合并后既有但此前未登记的 13 条 legacy 入口。

## 已完成工作与实际证据

- 共享归一化 `lab_inventory/tools/param_search.py`（无 Odoo 依赖）：
  - 关键参数选取与标签一致：电阻 `阻值/精度/功率`；电容 `容值/容量/电容量/耐压/额定电压/介质/材质`；其他前 3 个。
  - 归一化：大小写、SI 前缀、`Ω/ohm`、`100nF = 0.1uF`、`±1%`、`1kV = 1000V`；R 记法 `10Ω = 10R`、`4.7Ω = 4R7`、`0.1Ω = R1`、`4.7kΩ = 4k7`、`1.5kΩ = 1k5`；原始与 NFKC 写法同时保留（`±2℃` / `±2°C`）。
- `lab_inventory`：`product.template.lab_search_specs` 存储字段 + trigram GIN + `19.0.1.1.0/post-backfill_lab_search_specs.py` 分批回填。
- `lab_catalog`：`lab.catalog.item.search_params` + trigram GIN；`lab.catalog.param` create/write/unlink 增量重算；导入器在既有 COPY/upsert 中写入；新增 `tools/backfill_search_params.py`（`--batch/--start-id/--limit/--dry-run`，完整非 dry-run 后写 `lab_catalog.param_index_state=ready`）。
- 检索：`_catalog_where` 按 token AND，每个 token 在 `search_text`、`search_params`、精确 C 编号或该 token 对应的本地绑定 C 码中命中；`_lab_domain` 同步覆盖名称/SN/内部编码/MPN/C 编号/参数文本；facets 与 search 共用条件；排序不变。
- API：`/lab/api/catalog/search` 新增 `param_index_ready`（只增）；`pending/list` 新增可选 `query/state` 与过滤后的 `total`，不传 `state` 保持旧行为；Web 默认 `pending`。
- Web：队列关键词/状态筛选、“共 N 条”、慢响应序号保护；combobox 有结果时显示“查看全部结果”链接到 `/team/lab?q=`，空结果/失败隐藏；索引未就绪时显示提示。原有 250ms/8 条/2 在途/8s/IME 行为不变。
- 文档：`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`、`docs/architecture/TEAM_WAREHOUSE_API_CONTRACT.md`、`docs/development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md`、任务文件均已更新。

### 实际执行并通过的测试

| 命令 | 结果 |
|---|---|
| `python server/ubuntu22.04/odoo_addons/lab_catalog/tests/test_param_search.py -v` | 8/8 OK |
| `node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_combobox.mjs` | 21/21 passed |
| `node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_workflow_core.mjs` | 19/19 passed |
| `python -m py_compile`（全部改动 Python 文件） | OK |
| `python tools/generate_routes.py --check` | exit 0 |
| `git diff --check` | exit 0 |
| `python tools/repo_check.py` | exit 1；51 项通过，唯一错误为既有 `frozen-source:client`（`clients/app/t.obj` 缺失），16 条 payload 警告为既有缺口 |

### 新增但未执行的测试

- `lab_catalog/tests/test_catalog_param_search_orm.py`：参数检索、R 记法、容值、多 token AND、本地档案 `lab_specifications`、`param_index_ready`。
- `lab_workflow/tests/test_workflow_business.py` 中 `test_16_pending_list_query_state_and_total`、`test_17_pending_list_is_owner_scoped`。
- 本工作区没有可用的 Odoo/PostgreSQL 测试实例，以上 ORM/HttpCase **未运行，不得记作通过**。

## 剩余工作与阻塞

0. 生产部署包已生成：`local/build/param-search-20261104/param-search-20261104.tar.gz`（SHA256 `f8b4b617576d1aff9e09496df6d9a4d20112bf906dcf1fb5255d079af306bbfc`，192 条目），含四模块、四模块升级脚本、备份/回填包装器与 `SHA256SUMS`；部署说明见同目录 `DEPLOY.md`。当前阻塞：`lc-nas` 密钥认证被拒，需用户在本机终端输入一次服务器密码安装公钥；尚未上传、备份、升级或回填。
1. 在隔离 Odoo 19 + PostgreSQL 环境执行模块升级与测试，至少覆盖 `lab_catalog`、`lab_workflow`、`lab_team_web`；记录真实命令、DB、exit code、tests/failures/errors/skips。
2. 用真实或生产副本目录验证归一化命中率与短 token（如 `1%`）误命中；本轮只有合成用例和只读审计样本。
3. 真实浏览器验证：`10k`、`100nF`、`0.1uF`、多词 AND、队列状态筛选、`/team/lab?q=` 跳转、索引未就绪提示。
4. Flutter 本轮未改、未回归；不能宣称三端一致通过。
5. 生产动作全部未执行：`pg_trgm`/字段索引创建随模块升级发生，参数回填需运行 `backfill_search_params.py`，目录导入、服务重启、部署、真实业务写均需单独授权与一致备份。
6. 回填建议在低峰/维护窗口执行，并确保回填完成后不再有并发导入写入未回填行；否则 `ready` 标记可能早于实际数据完整。

## 依赖和产物

- 源码：本分支工作区；服务端冻结清单见上。
- 回填命令（需在服务器 Odoo venv 中运行，凭据从 OS/环境获取，不写入仓库）：
  ```bash
  python3 backfill_search_params.py --dbname <db> --dbuser <user> --dry-run
  python3 backfill_search_params.py --dbname <db> --dbuser <user>
  ```
- 目录导入：`import_catalog.py` 原有命令不变；完整非 `--limit` 成功运行且无 NULL 时自动写 `ready`。
- 无新安装包、无 artifact 登记；本任务不产出可部署包。

## 生产状态和回滚

- 未接触生产、未执行升级/回填/导入/重启/部署/真实业务写。生产仍为 2026-11-03 r3 状态（`lab_team_web 19.0.1.2.0`、`lab_workflow 19.0.2.0.0`、`lab_catalog 19.0.2.0.5`、`lab_inventory 19.0.1.0.0`）。
- 代码回滚：切回 `main` / 回到本轮实现前 commit，或 `git revert` 本轮提交；旧 r3 服务端源清单和既有产物未改写。
- 若后续部署：先做停服态一致备份，保留旧模块源码，再升级；回填脚本可重入，失败时可按 `--start-id` 续跑，未完成前 `param_index_ready=false`。
- 工作区还包含前一轮未提交的 `AGENTS.md`、`GLOSSARY.md`、`docs/adr/`、`docs/agents/` 与审计/任务文档；它们不是本轮参数搜索的源码改动，提交时需分开处理。
