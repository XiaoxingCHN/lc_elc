# 参数关键词搜索使用独立的归一化检索字段

Status: accepted

Audit evidence: 2026-11-04 只读审计，见 `maintenance/audit/2026-11-04-catalog-parameter-audit.md`。

## Context

来料页的关键词搜索目前只看 `lab_catalog_item.search_text`（C 编号、名称、型号、品牌、分类、封装），参数行 `lab_catalog_param` 只参与目录页的精确参数筛选。用户经常只记得 `10k`、`100nF`、`1%` 这类参数，因此搜不到。

生产数据（2026-11-04 只读审计）：695,217 个目录件、4,110,477 条参数、940 个参数名；`parameterCode` 在数据中与中文名稳定对应（如 `param_10835_n`→阻值），但仓库不维护该映射。现有标签打印逻辑按中文参数名选取关键参数（`阻值/精度/功率`、`容值/耐压/介质` 等），其他类型取前 3 个。参数值原样存储，实际写法为 `10kΩ`、`±1%`、`1nF`、`50V/1kV`，没有归一化；现有筛选是大小写敏感的精确 `value IN`。本地档案的参数在 `product.template.lab_specifications`（JSON 字符串），同样不参与关键词搜索；生产库目前只有 2 条占位档案，规格为空。

## Decision

新增两份**只用于检索的派生文本**：

- `lab.catalog.item.search_params`：按标签同款中文参数名选取关键参数，把参数值归一化成“原值 + 常见等价写法”的 token 串（如 `10k 10K 10000 10kΩ`、`10Ω 10R`、`4.7Ω 4R7`、`0.1Ω R1`、`4k7`、`1k5`、`100nF 100nf 0.1uF 0.1uf`、`1% ±1%`、`1kV 1000V`）。
- `product.template.lab_search_specs`：对 `lab_specifications` 做同样的选取与归一化，覆盖未绑定立创目录的本地档案。

两列都建 trigram GIN 索引。关键词查询按空格分词，逐 token 用 AND 叠加，每个 token 在 `search_text` 或参数字段中命中；`search_text` 仍只保留身份字段。生产实测其长度为 30–203，512 上限当前未触顶；分离字段的目的是独立策展、独立回填、避免身份字段与参数耦合，而不是长度溢出。

排序不变：本地库存优先，再按编号；C 编号只是普通匹配字段，不做“精确 C 编号优先”。供应商库存只展示，不参与“有货”。待入库队列的筛选是独立功能：按追溯码/名称/MPN/封装/SN 分词 AND，加状态筛选和服务端 `total`，仍按当前用户 + 当前公司隔离。

参数检索字段在导入时全量写入，ORM 参数变更时增量重算；模块升级另提供分批回填脚本。搜索 API 保持 `/lab/api/catalog/search` 不变，队列 API 只增可选参数和 `total`，不改变登录链路。

## Consequences

- 新增字段、索引和回填步骤，`lab_inventory`/`lab_catalog`/`lab_workflow`/`lab_team_web` 需要版本升级；生产升级和回填是单独的授权动作。
- 生产规模：695,217 个目录件、4,110,477 条参数；`lab_catalog_item` 总大小 1,320 MB、`lab_catalog_param` 1,200 MB。新增 trigram GIN 和全量回填是重量级操作，必须分批、可重入、可观测、可回滚，不能阻塞 Odoo 主进程。
- 真实写法已抽样：阻值 `10kΩ/1.5kΩ/1MΩ`、精度 `±1%`、容值 `1nF/470pF`、额定电压 `50V/1kV`；`1%` 单独命中约 98,180 行，选择性低；Top 40 容值没有 `uF/µF`，`100nF = 0.1uF` 必须用合成用例覆盖。
- 本地档案只有 2 条占位记录，`lab_specifications` 为空；本地档案参数搜索只能用合成数据验证，不能宣称生产覆盖通过。
- Flutter 共用同一个搜索端点，服务端语义变化会自动影响 Flutter；本轮不改 Flutter UI，只要求后续回归。
- `search_text` 的既有导入行为不变；`search_params` 的新鲜度由导入器和参数 hook 共同保证，任何绕过 ORM 的批量写入都必须显式重算。

## Considered Options

- **扩展 `search_text`**：改动最小，但身份字段与参数混在一起，参数只能随导入重建、无法独立校准或回填；生产实测 `search_text` 长度 30–203，512 上限当前不是约束，因此拒绝理由是可维护性而不是长度；拒绝。
- **查询时对 `lab_catalog_param.value` 做 `EXISTS`/`ILIKE`**：不新增字段，但无法按 item 复用 `key_parameters` 的策展逻辑，多个 token 的相关子查询在 695,217 件目录上成本不可控，本地 `lab_specifications` 也没有索引；拒绝作为主路径。
- **精确 C 编号优先**：用户明确 C 编号通常不作为关键词查询，且要求“有库存的排前面”；不引入额外排序层。
- **为 Flutter/EDA 单独做一套搜索接口**：会分裂语义并重复维护；保持现有 JSON-RPC 契约，字段只增不改，后续客户端直接复用。
