# 任务：搜索未命中时按需抓取立创资料

- Status: ready-for-human
- Category: enhancement

- 目标/用户场景：在统一器件库搜索没有命中时，允许对**精确 C 编号**或**精确 MPN**从立创抓取一条商品资料，保存到 `lab_catalog_item`/`lab_catalog_param`，然后前端自动刷新显示；不阻塞当前搜索请求，不写实验室库存。
- 当前问题及复现方法：搜索 `C32445874`、`TLV77333PDBVR` 或 `TLV77733PDBVR` 时，本地索引没有对应行，界面只显示“没有匹配的器件”；用户必须等整批采集/导入后才能查到。这三个料号在立创均真实存在。
- 验收标准：精确 C 编号或精确 MPN 未命中时可提交抓取并在 60 秒内可查；重复提交只产生一个任务；非电子分类不入队、不抓中文详情；模糊词和多候选型号不会被自动选中；抓取失败返回明确原因而不是空列表；不产生任何 `stock.quant`/`stock.move` 变化。
- 允许修改目录/接口：本轮已实施 Phase 1，改动限于 `server/ubuntu22.04/odoo_addons/lab_catalog/`（fetch request 模型、控制器接口、cron、工具与测试）和 `clients/app/lib/features/unified/`、`clients/app/lib/services/lab_api_client.dart`、`clients/app/test/features/unified/`；生产 unit/定时任务/数据库变更仍未授权。
- 业务不变量/依赖：本地索引只读资料，库存仍只由 `stock.quant`/`stock.move` 决定；商城 `stockNumber` 只写 `catalog_stock`；非电子一级分类不进入资料库；来源只允许立创固定域名，不能由前端传任意 URL；不改写历史记录。
- 负责人/协作者及分工：待分派。
- 分支/起始commit/源码manifest：`feat/receipt-param-search`，评估时 HEAD `c808065`。本轮仅文档，不产生新 source manifest。
- 环境与凭据获取方式（只写位置，绝不写值）：**不依赖 LCSC 官方 API key**。使用英文站前端自身的公开接口 `wmsc.lcsc.com/ftps/wm/product/query/list`、`wmsc.lcsc.com/ftps/wm/product/detail`，以及中文公开详情页 `item.szlcsc.com/<productId>.html`。本文不记录任何凭据、cookie 或 token。
- 实施步骤：见下文“实现顺序”。本轮不执行代码、部署、导入或生产写入。

## 结论

**可行，而且不需要官方 API key。** 2026-11-06 复核发现英文站前端使用的公开接口可以直接完成 MPN→C 码解析，配合 `wmsc` 详情和中文详情页即可落库。

**入库数据是中文的。** 英文站接口只做“型号→C 码”的定位；名称、品牌、分类、参数、封装、CNY 价格全部从 `item.szlcsc.com` 中文详情页解析，和现有中文采集器共用 `parse_cn()`，不保存英文展示字段。

| 查询类型 | 能否自动补抓 | 方式 |
|---|---|---|
| 精确 C 编号（如 `C32445874`） | **可以** | `wmsc` 详情 → 分类校验 → 中文详情页 |
| 精确 MPN（如 `TLV77733PDBVR`） | **可以** | `POST /ftps/wm/product/query/list` 搜索 → 要求 `productModel` 精确相等 → 同上 |
| 名称/品牌/模糊关键词 | **不自动抓** | 搜索结果噪声大（实测 `solder wire` 返回 5000 条无关电子件），无法判断用户意图 |

已实测的三个料号：

| 输入 | C 码 | 中文商品 ID | 一级分类 | 结果 |
|---|---|---|---|---|
| `C32445874` / `TLV77333PDBVR` | C32445874 | 34178661 | 380 电源管理 | 存在，中文页参数 9 条 |
| `TLV77733PDBVR` | C54110218 | 57330406 | 380 电源管理 | 存在，中文页标题“线性稳压器(LDO)” |

> 更正：初版评估把 `TLV77733PDBVR` 判为笔误。实际原因是 `wmsc` 详情接口不支持按型号反查（返回 405），并不代表商品不存在。英文站前端搜索接口能查到它。

**不要做“搜索请求里同步等抓取”。** 一次外部抓取要请求两到三个站点，可能遇到超时、429、页面改版；直接放在 `/lab/api/catalog/search` 里会占住 Odoo worker 和数据库连接。应采用“未命中 → 入队 → 后台 worker 抓取 → 前端轮询 → 刷新”。

## 一、现有链路

- 搜索入口：`lab_catalog/controllers/catalog_api.py` 的 `/lab/api/catalog/search`，调用 `lab.catalog.item.search_unified()`。
- 搜索只查 Odoo 索引和本地物料；没有远程抓取分支。
- 客户端 `CatalogNotifier._loadFirstPage()` 在服务端返回空时只进入 `EmptyView`，没有“补抓”状态或轮询。
- `catalog_bind` / `catalog_create_material` 都要求 `lab_catalog_item` 已有该 C 码；不存在时返回 NOT_FOUND。
- 现有批量导入器 `tools/import_catalog.py` 从 SQLite 快照按批导入，不能用于单条在线抓取。
- 因此需要新增一个“单条抓取任务”模型和 worker，而不是改搜索 SQL 去访问外网。

## 二、已确认的公开接口

### 2.1 MPN → C 码

```http
POST https://wmsc.lcsc.com/ftps/wm/product/query/list
Content-Type: application/json

{"keyword": "TLV77733PDBVR", "currentPage": 1, "pageSize": 10}
```

返回 `result.dataList[]`，每项包含：

- `productCode`（C 码）、`productModel`（MPN）、`productId`（中文页数字 ID）
- `parentCatalogId`、`catalogId`、`parentCatalogName`、`catalogName`
- `isMro`、`stockNumber`、`encapStandard`、`brandNameEn`

使用规则：

- **只取 `productModel` 与输入精确相等（大小写归一）的第一条**；没有精确相等就返回候选列表让用户选，不自动抓取。
- 实测 `TLV77333` 前缀会返回 4 个同系列不同封装；模糊匹配不能当成用户要的料。
- `pageSize` 固定 ≤10，不翻页、不拿这个接口做批量枚举。关键词搜索可能返回 `totalRow=5000`，属于噪声，不追。
- 不需要 key、cookie 或签名；按普通浏览器请求头访问。

### 2.2 C 码 → 详情

```http
GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C54110218
```

返回 `productId`、`productModel`、`parentCatalogId`、`catalogId`、`isMro`、`stockNumber`、`encapStandard`。用于确认商品存在并在抓中文页前做分类过滤。

### 2.3 中文详情页

```http
GET https://item.szlcsc.com/<productId>.html
Referer: https://www.szlcsc.com/
```

返回 HTML，含 `__NEXT_DATA__`，可解析 `webData.productRecord`、`paramList`、`currentCatalog`、`files`。实测两个目标料号均 HTTP 200、可解析。中文站的分类页/搜索页仍被 WAF 203 拦截，**不要访问，也不要尝试绕过**；按需抓取只走上述商品详情页。

### 2.4 中文数据从哪里来

英文站接口**只负责把型号解析成 C 码**，不写入任何英文展示字段。入库的显示数据全部来自中文详情页，复用现有 `parse_cn()`：

| 入库字段 | 中文页来源 | 实测值（C54110218 / TLV77733PDBVR） |
|---|---|---|
| 名称 | `productRecord.productName` | `TLV77733PDBVR`（部分料号是描述性中文名，如 C32445874 为“300mA小尺寸高PSRR低压差稳压器”） |
| 型号 | `productRecord.productModel` | `TLV77733PDBVR` |
| 品牌 | `productRecord.productGradePlateName` | `TI(德州仪器)` |
| 分类 | `currentCatalog.catalogName` / `catalogId` / `parentId` | `线性稳压器(LDO)` / 387 / 380 |
| 参数 | `paramList[].parameterName` + `parameterDetailValue` | `输出极性=正极`、`工作电压=5.5V`、`输出电压=3.3V`、`输出电流=1A` |
| 封装 | `productRecord.encapsulationModel` | `SOT-23-5` |
| 价格 | `pageProps.price`，币种固定 CNY | 中文页面显示价 |
| 库存 | `productRecord.stockNumber` | 只写 `catalog_stock`，不写实验室库存 |

两个必须注意的点：

- 分类落库用**中文页** `currentCatalog.catalogId`（387），不能用英文搜索接口返回的 `catalogId`（1032 是英文叶子分类），否则会挂到错误节点。
- 部分芯片的 `productName` 本身就是型号，不是描述性中文名；这是立创中文站的数据如此，不是抓到了英文。界面展示应以型号 + 中文参数为主。

> 这三个接口都是立创网站自身前端在用的公开地址，不是官方文档 API。必须限流、缓存、失败即退避；接口变更时按“抓取失败”处理，不能影响搜索主流程。

## 三、推荐架构（MVP）

```text
搜索未命中（精确 C 码 / 精确 MPN）
        ↓
POST /lab/api/catalog/fetch
        ↓
lab.catalog.fetch.request（queued，按规范化查询去重）
        ↓
后台 worker（先 Odoo cron，1 分钟级）
        ↓
C 码？ ──否──→ query/list 精确匹配（无精确项 → candidates，等用户选）
        ↓ 是
wmsc 详情 → parentCatalogId 电子白名单？
        ├─ 否 → skipped_non_electronic（不抓中文详情）
        ├─ 未知 → review（不抓）
        └─ 是 → 中文 item 页 → 解析 → upsert lab_catalog_item/param
        ↓
done + bump catalog revision
        ↓
前端轮询 /lab/api/catalog/fetch_status → 成功后 refresh 搜索
```

### 3.1 为什么不直接同步抓

| 方案 | 优点 | 问题 | 结论 |
|---|---|---|---|
| 搜索请求内同步抓取 | 用户等待几秒即可看到 | 占住 Odoo worker/数据库连接；外部超时不可控；并发差；失败会污染搜索错误 | **不采用** |
| Odoo cron + 队列表 | 改动小、无新服务、请求线程不阻塞 | 延迟最多约 1 分钟；cron 运行在 Odoo 进程内，仍需限流 | **MVP 推荐** |
| 独立 resolver 服务 | 可做到 1–3 秒；与 Odoo 隔离 | 新增 systemd 服务、内部接口、部署和监控 | **延迟要求高时再做** |

建议先做 Odoo cron 版，UI 明确显示“已提交抓取，通常 1 分钟内完成”。

### 3.2 数据模型

新增 `lab.catalog.fetch.request`：

| 字段 | 说明 |
|---|---|
| `query_raw` | 用户原始查询，保留审计 |
| `query_norm` | 归一化后的 C 码或 MPN（大写、去空格） |
| `query_kind` | `c_code` / `mpn` |
| `state` | `queued` / `resolving` / `fetching` / `done` / `failed` / `skipped_non_electronic` / `review` / `not_found` / `candidates` |
| `catalog_code` | 解析出的 C 码 |
| `product_id_ext` | 中文商品 ID |
| `parent_catalog_id` | 一级分类 ID |
| `candidates_json` | 模糊匹配候选（C 码 + MPN + 封装），仅用于让用户选 |
| `requested_by` | 触发用户 |
| `attempts` | 重试次数 |
| `message` | 面向用户的中文原因 |
| `result_item_id` | 成功后关联 `lab.catalog.item` |
| `created_at` / `started_at` / `finished_at` | 审计与超时 |

约束与索引：

- 同一 `query_norm` 在 `queued/resolving/fetching` 状态只允许一个活动请求；重复搜索直接复用。
- `state` 索引供 worker 取任务；`created_at` 用于清理历史。
- 保留 30 天成功/失败记录；不删除资料行。
- ACL：普通资料库用户可创建/查看自己的请求；管理员可查看全部；worker 用 `sudo()` 处理。

### 3.3 抓取与入库

单条处理顺序：

1. 归一化输入：C 码匹配 `^C\d+$`；MPN 用大写去空格，长度和字符集设上限。
2. 若是 MPN：调 `query/list`，取 `productModel` 精确相等的唯一项；0 条 → `not_found`；多条精确相等或只有模糊项 → `candidates`，不自动抓。
3. 调 `wmsc` 详情，读 `productId`、`parentCatalogId`、`catalogId`、`isMro`。
4. 若 `isMro=true` 或 `parentCatalogId` 不在 `lcsc_electronics_filter.json` 白名单：标记 `skipped_non_electronic`，**不请求中文详情**。
5. 若分类未知：标记 `review`，不抓取。
6. 调中文详情页，复用现有 `parse_cn()` 解析 `webData.productRecord`、`paramList`、`currentCatalog`、`files`；名称、品牌、参数、分类全部取中文页字段。
7. 再校验一次分类一致；不一致标记 `review`，不静默覆盖。
8. 写入 `lab_catalog_item` 和 `lab_catalog_param`：
   - 不存在则创建；存在则只在来源指纹更新时更新；
   - 不删除已有行，不改本地绑定；
   - `market='cn'`，`catalog_stock` 只作供应商库存；
   - 分类必须能映射到现有 `lab.catalog.category`（380/387 已存在）。
9. 提交后 bump `catalog_revision`；前端轮询到 `done` 后刷新搜索。

**代码复用建议**：把中文页解析、电子分类判断、字段扁平化抽成无 Odoo 依赖的小模块（如 `lab_catalog/tools/lcsc_remote.py`），Odoo worker 和采集器共用；不要从 addon import 整个 crawler 脚本。两处共用同一组 HTML/JSON fixture 测试。

### 3.4 接口

`POST /lab/api/catalog/fetch`

```json
{"query": "TLV77733PDBVR"}
```

返回：

```json
{
  "request_id": 123,
  "state": "queued",
  "query_kind": "mpn",
  "message": "已提交抓取，通常 1 分钟内完成。"
}
```

规则：

- 接受精确 C 码或完整 MPN；名称/品牌/短关键词返回 `VALIDATION_ERROR`，提示“请输入完整 C 编号或完整型号”。
- 已在索引中：直接返回 `done` + `item_key`，不建任务。
- 候选不唯一：返回 `candidates` 列表，用户选择后带 `catalog_code` 再次提交。
- 每用户最多 5 个进行中请求、每小时 20 次；全局外部请求并发 1；超限返回 `RATE_LIMITED`。
- 同一查询已有活动任务：返回已有 `request_id`。

`POST /lab/api/catalog/fetch_status`

```json
{"request_id": 123}
```

返回 `state`、`message`、`result_item_key`、`catalog_code`、`candidates`、时间戳。客户端只轮询自己的请求；管理员可查全部。

搜索接口增强：

```json
"fetch_suggestion": {
  "kind": "mpn",
  "query": "TLV77733PDBVR",
  "can_fetch": true,
  "message": "本地库尚未收录，可立即抓取。"
}
```

- 默认**不自动入队**，由用户点“立即抓取”触发；避免 450ms 防抖的 `onChanged` 每敲一个片段就打外网。
- 如果产品决定“搜索即自动抓”，也只对精确 C 码/完整 MPN 启用，并受同样限流和去重约束。

### 3.5 前端

- `CatalogState` 增加 `fetchRequestId`、`fetchState`、`fetchMessage`、`fetchCandidates`。
- `EmptyView` 在 `fetch_suggestion.can_fetch` 时显示：
  - 标题：“本地库尚未收录 TLV77733PDBVR”
  - 按钮：“立即抓取”
  - 说明：“只抓取该型号的公开资料，不影响实验室库存。”
- 提交后状态条：
  - `queued` / `resolving` / `fetching`：进度提示
  - `done`：“已收录，正在刷新…”
  - `candidates`：列出候选（C 码 + 型号 + 封装），让用户选，不自动取第一条
  - `failed`：中文原因 + “重试”
  - `skipped_non_electronic`：“该商品不属于电子元器件，未加入资料库。”
  - `not_found`：“立创未找到该型号。”
- 轮询间隔 1 秒、最多 60 秒；页面切走或查询变化时取消；成功后调用现有 `refresh()`。
- 离线模式不提供抓取按钮。

## 四、安全、限流与数据边界

- **固定域名**：只允许 `wmsc.lcsc.com` 和 `item.szlcsc.com`；绝不接受用户传入 URL，防 SSRF。
- **精确查询**：只对 C 码/完整 MPN 抓取；关键词不抓，避免“搜一个词抓全网”。
- **精确匹配**：MPN 必须 `productModel` 相等；模糊候选只展示，不自动入库。
- **分类前置**：`parentCatalogId` 不在白名单直接 `skipped_non_electronic`；未知进 `review`；中文详情请求前完成判断。
- **权限**：沿用 `auth='user'` 和资料库读权限；抓取写入只由 worker `sudo()` 执行。
- **限流**：每用户 5 个进行中、每小时 20 次；全局外部并发 1；同一查询去重；失败指数退避；`not_found` 负缓存 24 小时。
- **不写库存**：只写 catalog 表；不创建 `product.template`，不写 quant/move；建档仍走现有 `create_material` 流程。
- **不改历史**：已有 C 码不覆盖绑定/库存字段；只更新资料字段和来源指纹。
- **审计**：记录请求人、查询、结果、耗时、失败原因；日志不记录 cookie/token/完整响应。
- **WAF**：中文分类页/搜索页遇到 203 立即失败并记录，不求解验证、不伪造 cookie。
- **接口稳定性**：`query/list` 等是网站前端接口，不是合同化 API；变更或限流时按抓取失败处理，搜索主流程不受影响。不做批量枚举或深分页。

## 五、实现顺序

### Phase 1：C 码 + 精确 MPN 异步补抓

1. 新增 `lab.catalog.fetch.request` 模型、ACL、索引和状态机。
2. 新增 `/lab/api/catalog/fetch`、`/fetch_status`。
3. 搜索接口在精确 C 码/MPN 空结果时返回 `fetch_suggestion`。
4. 新增 Odoo cron（每分钟）处理 1–2 个 queued 请求；MPN 解析、分类过滤、upsert、bump revision。
5. 客户端空状态按钮 + 状态条 + 候选选择 + 轮询 + 成功刷新。
6. 用 C32445874、TLV77333PDBVR、TLV77733PDBVR 做端到端验收；用非电子样本验证不入库。

### Phase 2：低延迟（可选）

若 1 分钟延迟不可接受，把 worker 抽成独立 resolver 服务，Odoo 只负责入队/查询状态；不要在 Odoo 请求线程里直接发外网请求。

## 六、验收与测试

| 检查 | 通过标准 |
|---|---|
| C32445874 未命中 → 抓取 | 60 秒内 `done`，搜索返回该卡片，参数 9 条、分类电源管理/线性稳压器 LDO、币种 CNY |
| TLV77733PDBVR 未命中 → 抓取 | 解析到 C54110218，60 秒内可查；品牌 `TI(德州仪器)`、分类 `线性稳压器(LDO)`、参数为中文名，封装 SOT-23-5 |
| 同系列前缀 `TLV77333` | 返回 `candidates`，不自动选第一条 |
| 不存在的型号 | `not_found`，不模糊映射 |
| 非电子 C 码/型号 | `skipped_non_electronic`，中文详情请求数为 0 |
| 重复提交 | 同一查询只产生一个活动请求，第二次返回同一 `request_id` |
| 搜索已有 C 码 | 直接命中，不建任务、不发外网请求 |
| 抓取失败/超时 | `failed` + 中文原因；搜索不被错误状态污染；可重试 |
| 权限 | 普通用户只能看自己的请求；不能直接写 catalog 表 |
| 库存 | 抓取前后 `stock.quant`/`stock.move` 计数不变 |
| 客户端 | 空状态按钮、候选选择、轮询、成功刷新、切页取消轮询；离线模式无按钮 |

测试建议：

- 单元：C 码/MPN 分类、精确匹配、状态机、去重、限流、电子白名单、未知分类。
- 集成：用固定 JSON/HTML fixture 模拟 `query/list`、`wmsc` 详情和中文页，不访问真实网络；验证 ORM upsert、参数行、revision。
- Odoo 测试库：三个目标料号全链路；非电子样本；重复请求；`candidates` 分支。
- 客户端 widget 测试：空状态按钮、候选列表、状态条、轮询取消、刷新。
- 生产验收另行授权；不在本方案内直接部署或导入。

## 七、明确不做

- 不在搜索请求内同步抓取，不阻塞 Odoo worker。
- 不对名称/品牌/模糊关键词自动抓取。
- 不把模糊匹配结果自动当作用户要的型号。
- 不用 `query/list` 做批量枚举或深分页；全量发现另见目录发现评估。
- 不绕过 WAF，不访问中文分类/搜索页，不伪造 cookie。
- 不从客户端直接连数据库或调用立创。
- 不把商城库存写入实验室库存。

## 八、待确认的产品决策

1. 未命中时是“自动入队”还是“显示按钮由用户点”？建议先做按钮。
2. 可接受延迟是 60 秒内，还是必须 1–3 秒？前者用 Odoo cron，后者才需要独立 resolver。
3. 哪些角色可以触发抓取？建议所有资料库用户可用但限流；管理员可查看全部任务。
4. 失败/未找到记录保留多久？建议 30 天。

## 九、本轮边界

本文件只做方案与接口核验，没有修改任何代码、生产 unit、定时任务或数据库，没有发起批量抓取或导入。核验请求只访问了公开页面/接口：几个目标料号的搜索与详情，均为个位数请求。`python tools/repo_check.py` 在本轮新增文档前已存在 `frozen-source:server` 失败，不能把本次评估记为仓库检查通过；正式实施时需重新运行并记录真实结果。

## 十、Phase 1 实施记录（2026-11-06）

### 10.1 服务端（`lab_catalog` 19.0.2.0.9 → 19.0.2.0.10）

| 文件 | 内容 |
|---|---|
| `tools/lcsc_remote.py`（新） | 无 Odoo 依赖的取数层：`normalize_query`、`resolve_mpn`（要求 `productModel` 精确相等，否则只给候选）、`fetch_product_detail`、`fetch_cn_page`（`Referer` 中文站）、`parse_cn_page`、`classify_root`；主机白名单只有 `wmsc.lcsc.com`、`item.szlcsc.com`，15 秒超时，2 MB 上限 |
| `tools/lcsc_electronics_filter.json`（新） | 与采集器一致的 34 个电子一级分类白名单副本 |
| `models/lab_catalog_fetch.py`（新） | `lab.catalog.fetch.request` 状态机；`init()` 建状态索引与“同一 `query_norm` 只允许一个活动任务”的部分唯一索引；`_cron_process_queue` 用 `pg_try_advisory_lock(87431001)` 串行化；`_run` 先查分类再取中文页；`_upsert_item` 只写 `lab.catalog.item/param`，按来源指纹跳过未变化的行，写 CNY、`catalog_stock`、`search_text`，不碰产品/quant/move；成功后 bump catalog revision |
| `data/lab_catalog_cron.xml`（新） | 每分钟 `model._cron_process_queue(limit=2)`；Odoo 19 已移除 `numbercall`/`doall`，XML 未使用 |
| `controllers/catalog_api.py` | 搜索响应新增 `fetch_suggestion`（仅精确 C 码/MPN 且无任何筛选、无结果时）；新增 `POST /lab/api/catalog/fetch`、`/fetch_status`；已存在则直接 `done`；复用其他用户的活动同查询（唯一索引保证只读一条公开资料任务）；每用户 5 个进行中 / 每小时 20 次；抓取请求用 savepoint 创建并处理并发冲突 |
| `security/*` | 普通用户读自己的请求，管理员全量；worker 以 `sudo()` 处理 |
| `tests/test_lcsc_remote.py`（新） | 15 个纯 Python 用例：归一化、精确/模糊/重复候选、分类白名单、中文页解析（中文参数名）、C 码不匹配拒绝、主机白名单、内置策略与采集器一致 |

### 10.2 客户端（`1.2.0+7`，版本未变）

| 文件 | 内容 |
|---|---|
| `models/unified_item.dart` | `CatalogSearchPage.fetchSuggestion`；`CatalogFetchSuggestion` / `CatalogFetchCandidate` / `CatalogFetchStatus`（含 6 个终态） |
| `services/lab_api_client.dart` | `requestCatalogFetch`、`catalogFetchStatus` |
| `providers/catalog_providers.dart` | `fetchSuggestion` / `fetchStatus` / `fetchBusy`；`startFetch`、`chooseFetchCandidate`；1 秒轮询、最多 60 次、`dispose`/换查询取消；`done` 后自动 `refresh()`；请求或轮询失败都落为 `failed` 中文状态 |
| `screens/unified_catalog_screen.dart` | 空状态显示“立即从立创商城抓取”；状态卡展示排队/解析/抓取进度，终态带图标+文字；候选逐条给出“抓取”按钮；失败可重试 |
| `test/features/unified/catalog_fetch_test.dart`（新） | 7 个用例：建议透出、queued→done 轮询并刷新、候选选择带 `catalog_code` 重提且不轮询终态、限流失败文案、无建议不发请求、换查询清空抓取状态、终态集合 |

### 10.3 实际验证（Flutter 3.47.7 / Dart 3.13.5，本机）

- `flutter test --no-pub --reporter compact`：exit 0，**326 passed / 5 skipped / 0 failed**（改动前基线 319/5，新增 7 个用例全部通过）。
- `flutter analyze --no-pub lib test`：exit 1，**0 error / 0 warning / 120 info**（基线 118 info；新增 2 条 `prefer_initializing_formals`，与文件既有构造风格一致）。
- `python -I .../tests/test_lcsc_remote.py`：exit 0，15/15。
- `python tools/repo_check.py`：exit 1，50 项通过；错误为 `frozen-source:client`（4 个改动文件）与 `frozen-source:server`（13 个改动文件）——本轮源码尚未冻结，符合预期；16 条 payload 警告为既有缺口。
- `python tools/generate_routes.py`：重新生成 `maintenance/registry/routes.json`（94 条，新增 `/lab/api/catalog/fetch`、`/fetch_status`，并补齐本分支此前未登记的路由）；`--check` exit 0。`git diff --check` exit 0（仅 CRLF 警告）。

### 10.4 未验证 / 未做

- 未在 Odoo/PostgreSQL 测试库运行 ORM 用例；`lab.catalog.fetch.request` 的状态机、cron、分类映射只做了静态检查与纯函数测试。
- 未做真实网络端到端（C32445874 / TLV77333PDBVR / TLV77733PDBVR 入库验收）。
- 未做 Flutter widget 测试（空状态按钮/候选列表的渲染只由逻辑测试与现有布局测试间接覆盖）。
- **未部署生产、未升级模块、未注册定时任务、未创建数据库表**：`lab_catalog` 升级需另行授权。（该时点状态已由第十一节取代：2026-11-06 已部署，模块/表/cron 已生效。）
- 未冻结 source manifest，未提交、未推送、未构建安装包。

## 十一、Phase 1 生产部署（2026-11-06T14:29–14:31Z）

- **授权**：本轮用户明确要求「更新到服务器」，授权范围仅 `lab_catalog`（连同同批源码的 `lab_inventory`、`lab_workflow`）升级，不含导入、爬虫启动、清库或回滚演练。
- **执行**：`server/ubuntu22.04/upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261106/modules`；步骤 4 `-u lab_inventory,lab_catalog,lab_workflow` **退出码 0、ERROR/CRITICAL/Traceback 行数 0**。生产磁盘版本：`lab_catalog 19.0.2.0.10`、`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2`；`lab_team_web 19.0.1.2.1` 未参与。
- **备份**：`/var/backups/lc-elc/20261106T142949Z-before-upgrade/`（`db.dump` 118,970,696 B / `40863d500fffc8f36013cd99da8625d3ed988799826f6633cc178f41d3ba0d66`；`filestore.tar.gz` 12,819,190 B / `5b9e5d42a03d339dcbab225ad3e1da09913b4b853dcded117fcb29614a3f5fc0`；旧三模块源码在 `module-source-before-upgrade/`）。
- **健康检查**：脚本把 `/web/login` 的 303 判为失败（既有脚本缺陷，303 → `/web/database/selector`）；独立复核带 `X-Odoo-Database` 为 200、`odoo.service` active/enabled、14:31:36Z `Modules loaded`。
- **运行证据**：Odoo 日志自升级至 2026-11-07T13:11Z 0 条 ERROR/CRITICAL/Traceback；cron「器件库：处理在线补抓队列」（id 25，每 1 分钟）自 2026-11-06T14:31:16Z 起 1356 次运行、0 失败、队列为空。
- **DB 行核对（2026-11-07T13:17:07Z）**：四模块 `installed`（`lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2` / `lab_team_web 19.0.1.2.1`）；`lab_catalog_fetch_request` 表存在、7 个索引含部分唯一索引 `lab_catalog_fetch_active_uniq`（`state IN (queued,resolving,fetching)`）；`lab_catalog.ir_cron_lab_catalog_fetch` → `res_id=25` 与运行中的 job 25 一致。
- **仍未核对**：catalog/param/fetch_request 行数——第一步脚本在 `ir_cron.model_id` 处中断（Odoo 19 该列在 `ir_act_server`），第二步 `verify_deploy2.sh` 待密码。
- **仍未做**：真实网络端到端（C32445874 / TLV77333PDBVR / TLV77733PDBVR + 非电子样本）、Flutter widget 测试、客户端包构建、source manifest 冻结。
