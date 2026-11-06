# 任务：中文目录发现补齐评估（采集前置过滤非电子元器件）

- Status: needs-triage
- Category: enhancement

- 目标/用户场景：解释并修复“立创商城里有的芯片，服务器上搜不到”的问题；在不改变实验室库存权威口径的前提下，让中文电子元器件目录获得可持续、可断点续跑的发现来源，并且**在进入抓取队列前就排除非电子元器件**。
- 当前问题及复现方法：生产定时器仍活着，但中文队列已耗尽；`TLV77733PDBVR`（C54110218）和 `TLV77333PDBVR`（C32445874）在本地快照和当前中文队列中均无记录。两者在立创都真实在售，一级分类均为 380（电源管理），详情页均可访问，说明缺的是“发现”，不是页面不可用或前端搜索过滤。2026-11-06 复核更正了初版“`TLV77733PDBVR` 是笔误”的判断。
- 验收标准：目标料号经本地快照、导入器和 Odoo 查询全链路可查；任何非电子一级分类的候选都不会进入 `cn_queue`，也不会发起中文详情请求；覆盖率按一级分类可审计；全程可暂停、可续跑、不覆盖历史记录。
- 允许修改目录/接口：本阶段仅新增本评估文档。若获准实施，预计修改 `server/ubuntu22.04/crawler/`、`services/lcsc/` 的编排说明、`server/ubuntu22.04/odoo_addons/lab_catalog/tools/import_catalog.py` 及其测试；生产 unit、计划任务、生产库和既有快照不在本任务默认授权内。
- 业务不变量/依赖：实验室数量只以 `stock.quant`/`stock.move` 为权威；商城库存只作供应商资料，不混入实验室库存；`lab_catalog_item` 仍是只读资料索引；`cn_excluded` 不导入；搜索文本、C 码、MPN 语义不变。
- 负责人/协作者及分工：待分派。评估与只读核验已完成；实施需另行确认负责人。
- 分支/起始commit/源码manifest：`feat/receipt-param-search`，评估时 HEAD `c808065`。本轮未修改采集器、导入器或生产配置，不产生新的 source manifest。
- 环境与凭据获取方式（只写位置，绝不写值）：生产只读检查使用既有 SSH 连接。官方 API key 尚未取得，且本任务不依赖它：2026-11-06 复核确认英文站前端公开搜索接口可按 MPN 解析 C 码。若后续仍申请 key，只放 OS 安全存储/服务环境文件，绝不入 Git。本文不记录任何密码、cookie、token 或真实配置值。
- 实施步骤：见下文“建议路线”。本轮不执行实施和生产变更。

## 结论（先看）

1. **不是定时器死了。** 生产 `lcsc-crawler.timer` 和停止定时器均正常，最近一次采集成功退出；问题是中文发现图已经走完：生产约 695,217 条完成、`pending: 0`、阶段 `discovered_details_finished`。重启定时器不会新增商品。
2. **当前中文覆盖率约 9%，且分类严重偏科。** 中文目录总量 8,174,484；电子类 34 个一级分类合计 7,745,367 条；本地快照仅 662,768 条中文记录（约 8.56%）。连接器只有 0.07%，按键/开关 0.13%，电源模块 0.12%，光电器件 0.21%，二极管 1.20%，传感器 1.00%；相对较好的电容也只有 28.05%。
3. **两个料号都真实存在，都是发现缺口（2026-11-06 复核更正）。** `TLV77733PDBVR` = C54110218 = 中文商品 ID 57330406；`TLV77333PDBVR` = C32445874 = 中文商品 ID 34178661。两者一级分类均为 380（电源管理，属于允许采集的电子类），中文详情页均返回 200 并可解析参数，但本地快照都没有这两个 C 码。初版把 `TLV77733PDBVR` 判为笔误，是因为只查了不支持型号反查的 `wmsc` 详情接口，结论已被推翻。
4. **中文分类页和中文搜索页当前被 WAF 拦截。** `www.szlcsc.com/catalog/<id>.html` 会 302 到 `list.szlcsc.com/catalog/<id>.html`，返回 HTTP 203 和 Aliyun `_xvasu` 验证页；`so.szlcsc.com/global.html?k=...` 同样 203；中文 `sitemap.xml` 返回“访问受限”。**不应绕过 WAF**（不求解验证、不伪造 cookie、不换代理）。
5. **有两条合规可行的发现路径。**
   - 分类级全量枚举的首选：申请 LCSC 官方 API key，使用 `ips.lcsc.com/rest/api/agent/product/v1/` 下的 `categories`、`categoricalitemlist`、`keywordsearch`、`productdetails`。可按分类分页枚举，并在入队前按分类过滤。按需精确 MPN/单条补抓不需要它，见下一条。
   - 立即可用：英文站点 `sitemap-product-en-*.xml`（158 个文件 × 50,000 ≈ 790 万 C 码）+ `wmsc.lcsc.com/ftps/wm/product/detail?productCode=...` 详情接口。详情接口直接返回中文 `productId`、`parentCatalogId`、`catalogId`、MPN、`isMro`，可在调用中文详情页前判断是否电子类。
   - 立即可用（2026-11-06 复核新增）：英文站前端搜索接口 `POST https://wmsc.lcsc.com/ftps/wm/product/query/list`，请求体 `{"keyword": "...", "currentPage": 1, "pageSize": N}`。返回 `productCode`、`productModel`、`parentCatalogId`、`catalogId`、`isMro`、`stockNumber`，无需官方 key。仅用于用户显式提供的精确 MPN 解析和少量补抓；必须要求 `productModel` 与输入精确相等，不能把模糊结果自动当作用户要找的料。
6. **全量补齐是多月级工程，不是一次夜间任务。** 即使按每秒 10 个请求，约 790 万次详情接口 + 约 770 万次中文详情页也要约 18 天连续运行；按现行每天 2 小时窗口约需 7 个月。应优先补高价值/严重缺失分类，而不是一开始追求全量。

## 一、现状证据

### 1.1 数量与覆盖

| 项目 | 数值 |
|---|---:|
| 中文目录总量（`categories_cn.json` 的 `catalog_count`） | 8,174,484 |
| 电子类一级分类数（`lcsc_electronics_filter.json` 允许） | 34 |
| 电子类商品数（按一级分类 `groupProductCount` 求和） | 7,745,367 |
| 非电子类商品数（差值） | 429,117 |
| 本机快照 `market='cn'` 记录 | 662,768 |
| 本机快照 `cn_excluded` | 56 |
| 生产已完成中文详情 | 695,217（检查时 `pending: 0`） |
| 本机覆盖率（662,768 / 7,745,367） | 8.56% |
| 生产覆盖率（695,217 / 7,745,367） | 8.98% |

本机分类覆盖（只列主要分类，按目录量排序）：

| 一级分类 | 目录量 | 已采 | 覆盖率 |
|---|---:|---:|---:|
| 连接器 365 | 2,192,816 | 1,429 | 0.07% |
| 电阻 308 | 1,623,026 | 213,923 | 13.18% |
| 振荡器/谐振器 348 | 1,121,150 | 59,273 | 5.29% |
| 电容 312 | 992,791 | 278,439 | 28.05% |
| 三极管/MOS管/晶体管 320 | 220,021 | 26,194 | 11.91% |
| 电感/线圈/变压器 316 | 199,261 | 17,689 | 8.88% |
| 电源管理 380 | 180,971 | 35,276 | 19.49% |
| 按键/开关 423 | 179,241 | 232 | 0.13% |
| 二极管 319 | 132,424 | 1,586 | 1.20% |
| 电源模块 13485 | 117,313 | 136 | 0.12% |
| 光电器件 450 | 107,655 | 222 | 0.21% |
| 传感器 513 | 73,705 | 735 | 1.00% |
| 存储器 500 | 47,624 | 3,464 | 7.27% |
| 逻辑器件 487 | 44,819 | 538 | 1.20% |
| 通信接口芯片 575 | 39,094 | 1,150 | 2.94% |

结论：当前发现来源明显偏向电容、电阻和少数被动件，连接器、开关、电源模块、光电、二极管、传感器等大量电子类几乎为空。芯片搜不到不是个别现象，而是分类发现缺口。

### 1.2 目标料号核对

| 检查 | 结果 |
|---|---|
| `TLV77733PDBVR` 精确查询本地 `records` | 0 条 |
| `TLV77733PDBVR` 通过 `wmsc` `productModel` 查询 | `405 This product does not exist`（该接口不支持型号反查，不能据此判定不存在） |
| `TLV77733PDBVR` 通过前端搜索接口 `product/query/list` | 1 条：C54110218，`productId` 57330406，`parentCatalogId` 380，`isMro=false`，库存 1865 |
| `TLV77733PDBVR` 的 `wmsc` `productCode=C54110218` | 存在，SOT-23-5 |
| `TLV77733PDBVR` 的中文详情页 | HTTP 200，`__NEXT_DATA__` 可解析，标题含“线性稳压器(LDO)” |
| `TLV77333PDBVR` 通过 `wmsc` `productCode=C32445874` | 存在 |
| C32445874 的中文商品 ID | 34178661 |
| C32445874 的 `parentCatalogId` | 380（电源管理，允许） |
| C32445874 的中文详情页 | HTTP 200，参数 9 条，SOT-23-5 |
| 本地快照是否含 C54110218 / C32445874 | 均为 0 条 |

因此问题只有一类：**真实发现缺口**。两个料号都在立创存在、分类允许，但从未被发现入队。

补充：`wmsc` 详情接口的 `productModel` 查询返回 405 只说明该接口不支持按型号反查；MPN→C 码要走前端搜索接口 `product/query/list`，并用 `productModel` 精确相等校验，避免把同系列不同封装当成同一料。

### 1.3 当前采集器的发现逻辑

`server/ubuntu22.04/crawler/lcsc_catalog_archive.py`：

- `chinese()`（约 545 行）只从中文首页种子和页面推荐位 `product_hints()` 扩展，不遍历分类树；队列为空时用首页 item 链接和 `__NEXT_DATA__` 里的推荐商品做种子。
- `catalog()`（约 348 行）只保存分类树和 `catalogCount`，没有把分类叶子转成商品列表。
- `discover()`（约 358 行）只解析 `www.lcsc.com/sitemap.xml` 中的英文产品 sitemap；中文模式没有调用它。
- `cn_enqueue()`（约 514 行）只校验数字商品 ID 和 `C\d+`，**不校验分类**；因此任何来源混入的非电子商品都会先入队、再抓详情，最后才由 `classify_electronics()` 排除。
- `cn_fetch_product()`（约 522 行）抓完中文详情后才分类；当前历史队列里只产生了 56 条 `cn_excluded`，是因为旧发现来源几乎都是电子推荐，不代表新来源也会如此。

这与新增要求“采集时就跳过非电子元器件”不一致，需要把过滤前移到“候选入队”之前。

### 1.4 为什么中文分类/搜索不能直接抓

只读探测结果：

| URL | 结果 |
|---|---|
| `https://www.szlcsc.com/robots.txt` | 允许 `/`，但禁止 `/*?*`、`/search/` 等 |
| `https://list.szlcsc.com/robots.txt` | 允许 `/catalog/*.html`，禁止 `/catalog/*/*.html*` |
| `https://www.szlcsc.com/catalog/313.html` | 302 到 list 主机，HTTP 203，Aliyun WAF |
| `https://list.szlcsc.com/catalog/313.html` | HTTP 203，Aliyun WAF |
| `https://so.szlcsc.com/global.html?k=TLV77733PDBVR` | HTTP 203，Aliyun WAF |
| `https://www.szlcsc.com/sitemap.xml` | HTTP 200 但内容是“访问受限”HTML |
| `https://list.szlcsc.com/sitemap.xml` | `{"code":403,"msg":"非法ACL-URL请求"}` |

现有采集器已经把 203/WAF 标记视为阻塞（`AccessBlocked`），不应新增验证码求解、cookie 伪造或代理轮换。中文分类页因此不能作为第一版自动发现来源。

## 二、可选发现来源比较

| 方案 | 前置电子过滤 | 覆盖能力 | 请求量/成本 | 风险 | 结论 |
|---|---|---|---|---|---|
| A. LCSC 官方 API（需 key） | 可按分类枚举，最好 | 目录/关键词/详情/变更通知齐全 | 分类分页 100/页，发现请求约 7.7 万级；中文详情仍需逐条 | 需商务申请；字段、配额、CNY/中文名、productId 语义需实测 | **长期首选** |
| B. 英文 sitemap + `wmsc` 详情 | 详情返回 `parentCatalogId`，可在入队前过滤 | 约 790 万 C 码，接近中文总量 | 约 790 万次 sitemap 详情 + 770 万次中文详情 | 未公开文档；限流/条款未知；耗时长 | **当前可用的兜底** |
| C. 手工 C 码/商品 URL 种子 | 每条先查详情再判断 | 只覆盖指定料号 | 极小 | 依赖人工提供 C 码；MPN 搜索不开放 | **立即修复个例** |
| D. 中文分类页/搜索页抓取 | 理论上可在分类层过滤 | 全量 | 中 | WAF 203；绕过不可接受 | **否决** |
| E. 继续推荐位图扩展 | 无分类先验 | 已耗尽在约 69.5 万 | 小 | 无法保证覆盖；会继续偏科 | **只能补充，不能作为主来源** |
| F. 第三方 jlcsearch 等 | 可解析 C 码 | 非权威、字段不全 | 小 | 第三方依赖、数据滞后 | **只可辅助定位，不作核心** |

### 2.1 方案 A：官方 API

官方文档列出的产品接口：

- `GET https://ips.lcsc.com/rest/api/agent/product/v1/categories`
- `GET .../categoricalitemlist`
- `GET .../keywordsearch`
- `GET .../productdetails`
- `GET .../productchangenotifications`

鉴权参数：`key`、`nonce`、`signature`、`timestamp`。无 key 直接请求返回 403，说明不能把它当匿名接口。文档说明 `categoricalitemlist` 支持 `category_id`、`currency=CNY`、`page_size`、`current_page`、`user_type=2`；`user_type=2` 只返回 product ID、LCSC part number 和 quantity。`keywordsearch` 适合用 MPN 精确/模糊解析 C 码。

**必须先做小样本验证**：官方 API 的 product ID 是否等于中文 `item.szlcsc.com/<id>.html` 的数字 ID；`productdetails` 是否返回中文 `parentCatalogId`/分类；CNY 价格和中文名称是否可用。不能仅凭文档假设。

### 2.2 方案 B：英文 sitemap + `wmsc` 详情

已验证：

- `https://www.lcsc.com/sitemap.xml` 可访问，索引包含 158 个 `sitemap-product-en-*.xml`，每个约 50,000 条，合计约 790 万 C 码。
- `https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C32445874` 返回：
  - `productId=34178661`（可直接拼中文详情 URL）
  - `parentCatalogId=380`（与中文一级分类 ID 一致）
  - `catalogId=1032`、`catalogName=...LDO...`
  - `productModel=TLV77333PDBVR`、`isMro=false`
- 另外两个抽样：C25905 → `parentCatalogId=308`（电阻），C1512157 → `parentCatalogId=500`（存储器），均与中文分类树一致。这个映射目前只验证了 3 个样本，必须扩大抽样。

`wmsc` 的 `productModel` 查询不支持按 MPN 反查（返回 405），但同主机的 `POST /ftps/wm/product/query/list` 可以按关键词搜索并返回 `productCode`/`productModel`/`parentCatalogId`，因此“用户只给 MPN”的场景可在无官方 key 的情况下解析，前提是 `productModel` 与输入精确相等。模糊结果只能作为候选展示，不能自动入库。

### 2.3 方案 C：手工种子

最小闭环：

1. 用户/维护者提供 C 码或中文商品 URL（例如 C32445874）。
2. 先调 `wmsc` 详情，读 `parentCatalogId`。
3. 只允许 `parentCatalogId` 在 `lcsc_electronics_filter.json` 白名单内才入队。
4. 再抓中文详情，导入 Odoo。

这可以在一两天内修复 `TLV77333PDBVR` 及一批已知缺料，但不能解决“很多芯片没有”的普遍问题。

## 三、建议路线

### Phase 0：只读/本地验证（不改生产）

1. 用 50–100 个跨分类 C 码抽样 `wmsc` 详情，验证 `parentCatalogId` 与中文分类树的一致性；记录 429/403、响应时间、失败率。
2. 若取得官方 API key，验证 `categories`/`categoricalitemlist`/`keywordsearch`/`productdetails` 的字段、分页、CNY、product ID 和配额。
3. 在本机复制一份快照，写最小测试脚本，验证 C32445874 从候选 → `cn_queue` → 中文详情 → `records` → 导入器 → 测试 Odoo 查询的完整链路。
4. 目标：确认哪条路径能“入队前知道分类”，以及全量成本；不启动生产采集。

### Phase 1：目标料号与已知缺料补齐

1. 增加种子入口（C 码/URL 文件）；每条先查 `wmsc`，分类允许才入队。
2. 若官方 key 已到，再验证 `keywordsearch` 与 `query/list` 的结果差异；已确认可以先用前端搜索接口按精确 MPN 解析，不需要等待 key。
3. 先补 C32445874 和一批用户提供的缺料，完成本地导入与查询验收。
4. 生产部署、启动采集、导入 Odoo 均需单独授权；不得因本评估自动执行。

### Phase 2：电子类发现层（推荐实现重点）

新增一个“发现源”抽象，所有来源统一走同一个电子过滤入口：

```text
official category / sitemap / manual seed
        ↓
candidate {code, product_id, parent_catalog_id, source_kind}
        ↓
parent_catalog_id ∈ 允许的一级分类？
   ├─ 否 → 记录 skipped_non_electronic，不入 cn_queue，不抓详情
   ├─ 未知 → cn_review 表，等待人工/映射，不抓详情
   └─ 是 → cn_queue(pending) → 中文详情 → records(market=cn)
```

具体约束：

- **不允许**先 `cn_enqueue()` 再在详情页分类；分类判断必须发生在 detail fetch 之前。
- 推荐位/相似商品只作为补充；新发现模式下关闭 hint 扩展，或只接受带明确分类的 hint。当前 `product_hints()` 不提供分类，因此不能用于新的电子过滤链路。
- 中文详情抓取后仍保留一次防御性分类校验；若与入队分类不一致，标记 `review`/`excluded`，不静默改写历史记录。
- 未知分类一律不抓详情，避免“先污染再清理”。

建议的最小数据变更（实施时再定）：

| 表/字段 | 用途 |
|---|---|
| `cn_queue.catalog_root_id` | 入队时记录一级分类，便于审计和断点 |
| `cn_queue.source_kind` | `official-category` / `sitemap-api` / `manual-seed` |
| `cn_queue.discovered_at` | 发现时间，不覆盖旧记录 |
| `cn_review`（新表） | 分类未知/映射冲突，暂不抓取 |
| `discovery_cursor`（新表） | sitemap 文件、分页、offset、状态，支持续跑 |
| `meta` 覆盖统计 | 各一级分类已发现/已抓取/跳过非电子数量 |

历史 `records` 和 `cn_queue` 不改写；只对旧记录补统计时可用 `fields_json` 读取，不重写原字段。

### Phase 3：按分类分批上线

不建议一开始全量。优先顺序可按“目录量大 + 当前覆盖极低 + 业务常用”确定：

1. 电源管理 380、存储器 500、逻辑 487、接口 575、时钟 493、ADC/DAC 601、MCU 470（芯片类，直接回应用户问题）。
2. 连接器 365、按键/开关 423、二极管 319、光电器件 450、传感器 513、电源模块 13485（当前几乎为空）。
3. 电阻/电容等已相对覆盖的分类，只做增量更新。

每批完成：采集小批 → 导入测试库/生产窗口 → 抽样查询 → 记录覆盖率 → 再扩大。不要在一次运行中把 770 万条中文详情全部拉完。

## 四、容量、时间与运行风险

### 4.1 存储

本机快照：3,547,037,696 字节 / 662,824 行 ≈ **5,351 字节/行**（含 `raw_json_gzip`、索引和参数）。

| 范围 | 估算 |
|---|---:|
| 电子类 7,745,367 行的 SQLite | 约 38.6 GiB |
| 中文全目录 8,174,484 行的 SQLite | 约 40.7 GiB |
| Odoo PostgreSQL + 参数表 | 另计；当前 695,217 条已有约 411 万参数行，全量约 4,500 万参数行，需单独估算 |
| 备份/临时空间 | 至少再留一份全量数据库空间 |

本机 F: 当前剩余约 106 GiB；生产 `/var/lib/lcsc-crawler` 和 Odoo 数据盘的空闲空间**本轮未复核**，实施前必须检查。建议门槛：采集盘和 Odoo 盘各自至少预留 100 GiB 以上，并在导入前做可回滚备份。现有采集器只在剩余空间低于 2 GiB 时暂停，这个阈值对全量导入远远不够。

### 4.2 请求量与时间

按现行 `--workers 16 --delay 0.1`（每主机约 10 请求/秒）估算：

| 阶段 | 请求量 | 连续运行时间 |
|---|---:|---:|
| 英文 sitemap 索引/文件 | 159 次 | 分钟级 |
| `wmsc` 详情（每个 C 码） | 约 790 万 | 约 9.1 天 |
| 中文详情（仅电子类） | 约 770 万 | 约 8.9 天 |
| 合计 | 约 1,560 万 | 约 18 天（无重试/无限流） |

按每天 2 小时窗口：约 **216 天（约 7 个月）**。如果官方 `categoricalitemlist` 能按 100 条/页枚举，发现请求可降到约 7.7 万次，但中文详情仍是约 9 天连续/108 天按 2 小时窗口。**因此“全量”必须作为长期后台任务，不能承诺短期完成。**

### 4.3 运行与合规风险

- **WAF**：中文 list/search 主机 203；不要实现验证码求解、cookie 伪造、UA 伪装或代理轮换。遇到 3 次验证响应应暂停并保留断点。
- **接口条款/限流**：`wmsc` 的详情与 `product/query/list` 都是网站前端在用的未公开文档接口，需保守限流；搜索接口只用于精确型号解析，不做批量枚举。官方 API 以 key 合同/配额为准。任何 429 应全局退避，不并发突刺。
- **分类映射漂移**：立创分类可能调整；`parentCatalogId` 未知时进入 `cn_review`，不能默认归入电子类。
- **导入锁/性能**：全量导入 Odoo 会长时间占用数据库；必须用维护窗口、批次导入、断点续跑，并先备份。导入器已按 `source_fingerprint` 跳过未变行，但首次全量仍是大事务量。
- **重复/陈旧**：按 `(code, market)` upsert；不覆盖历史快照；旧 `records` 不重写。新数据只补新行或更新同码。
- **库存语义**：商城 `stockNumber` 只写 `catalog_stock`，不得进入 `stock.quant`；本地库存仍由 Odoo 实物流转产生。
- **凭据**：API key 只放系统安全存储/受限环境文件，不入 Git、不入 TOMC、不出现在日志。诊断只输出路径、计数和哈希。
- **型号匹配**：只有 `productModel` 精确相等才可自动采用；同系列前缀或模糊结果只能展示为候选，不能自动替换 BOM。确实不存在的型号返回“无匹配”。

## 五、测试与验收

### 5.1 单元测试（新增，实施阶段）

- 允许分类 380 → 入队；非电子 11358/11370 → 不入队、不调用中文详情。
- 未知分类 → 进入 `cn_review`，不进入 `cn_queue`。
- `isMro=true` → 不入队。
- `cn_queue` 重复 C 码/商品 ID → 幂等，不重复计数。
- `discovery_cursor` 中断后续跑：不重复、不跳页。
- `parentCatalogId` 与中文详情 `currentCatalog.parentId` 不一致 → `review`，不静默覆盖。

### 5.2 集成测试（本机隔离）

1. 用 C32445874 走“候选 → 入队 → 中文详情 → `records`”链路。
2. 用 100 个非电子 C 码走同一入口，断言 `cn_queue` 不增加、中文详情请求数为 0。
3. 导入测试 PostgreSQL，断言 `market='cn'` 行存在、`cn_excluded` 为 0、参数行数量正确。
4. Odoo 搜索 `TLV77333PDBVR`、`TLV77733PDBVR` 和对应 C 码均返回该卡片；不存在的型号返回空，不做模糊替换。

### 5.3 生产验收（另行授权后）

- 目标料号在生产 Odoo 可检索，卡片分类为电源管理，价格币种/库存字段符合导入口径。
- 覆盖率报告：按一级分类列出 `目录量 / 已发现 / 已抓取 / 跳过非电子 / review`。
- 非电子审计：任一非电子分类的入队数为 0；`lab_catalog_item` 中非 `cn` 行数为 0。
- 采集器停止/重启后从断点继续，不重复抓取已完成 C 码。
- 记录真实命令、环境、退出码、失败数、未测试项；无法执行的项目标 blocked/skipped，不能算 PASS。

## 六、授权边界与下一步

本文件是评估，不是实施或上线授权。当前没有修改采集器、导入器、生产 unit、计划任务、数据库或任何快照；没有启动/重启采集，没有导入数据，没有读取或输出凭据。

建议的下一步（按顺序，逐项确认）：

1. **批准 Phase 0 本地只读验证**：抽样 `wmsc` 分类映射，评估限流；不改生产。
2. **是否申请 LCSC 官方 API key**：只影响“按分类全量枚举”的干净程度；精确 MPN 和单条补抓已确认可走前端搜索接口，不阻塞实施。
3. **批准 Phase 1 代码与测试**：种子入口 + 入队前电子过滤 + 目标料号本地闭环；仍不部署生产。
4. **生产试点另行授权**：部署、启动采集、导入 Odoo、调整定时窗口、备份与回滚，逐项单独授权。
5. 若要追求全量覆盖，再评估是否延长采集窗口、增加磁盘/备份和分批导入计划；不能把“每天 2 小时”当成全量完成的时限。

## 七、未验证项

- 官方 API key 未取得，未实际调用 `categories`/`categoricalitemlist`/`keywordsearch`/`productdetails`；字段和 product ID 语义待验证。本轮已实测英文站 `product/query/list` 与 `product/detail`、中文详情页，均无需 key。
- `wmsc` 只做了 3 个跨分类样本，未做限流/批量/长稳测试；其公开性和使用条款需确认。
- 生产磁盘空闲空间、Odoo 数据库增长和备份窗口本轮未复核；容量估算基于本机快照的字节/行比例。
- 未执行全量发现、未启动采集、未导入生产、未修改任何定时器。
- 未编写代码和测试，因此没有新增测试结果；本文所有覆盖率数字来自本地快照和生产只读检查，不能替代实施后的复测。

## 八、本轮检查结果

| 命令 | 结果 |
|---|---|
| `python tools/repo_check.py` | exit 1；51 项通过，1 项错误 `frozen-source:server`，涉及 9 个既有服务端文件晚于 active r2；另有 16 条离线载荷警告。该错误在本轮新增文档之前已存在，不是本评估引入。 |
| `git diff --check` | exit 0，仅有既有 CRLF 提示。 |
| 生产访问 | 本轮仅沿用此前的只读检查结论；没有新增生产写入、重启、导入、采集或定时任务变更。 |
| 代码/单元测试 | 未运行；本轮只新增 Markdown 评估，没有可执行代码变更。 |
