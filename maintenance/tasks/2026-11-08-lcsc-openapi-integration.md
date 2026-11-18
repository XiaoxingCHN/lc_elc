# 任务：用立创官方 OpenAPI 替换页面抓取（第一期）

- Status: in-progress
- Category: enhancement

- 目标/用户场景：用立创商城官方 OpenAPI（`jlc-openapi-sdk-lcsc-java-1.3.0` 对应的 HTTP 接口）替换现在对 `item.szlcsc.com` / `wmsc.lcsc.com` 页面的解析，让「候选列表 / 器件资料 / 价格 / 库存」来自官方接口；网页端与客户端仍走同一套 `/lab/api/catalog/*` 契约。
- 当前问题及复现方法：页面解析依赖 HTML 结构，页面一改就失效，且拿不到官方价格与库存。用户已取得官方 SDK 与密钥（2026-11-08）。SDK 里写死的接入地址 `https://openapi.jlc.com` 在本机、`223.5.5.5`、`8.8.8.8` 三处 DNS 均为 NXDOMAIN；官方开发指南（`open.jlc.com/develop-guide`，正文是 `/md/<name>.md`）的「SDK 使用」写明服务地址为 **`https://open-api.jlc.com`**（带连字符，DNS 可解析）。用户 2026-11-08 指定「走 SMT 的通道」，对应接口 `/smtOpenApi/smtComponent/selectComponentInfoByCodes`（详见 `local/private/查询元器件信息.pdf`）。
- 验收标准：只读探针能用真实凭据拿到 `search/global` 结果（HTTP 200 + `code` 成功 + 至少一条 `productCode`）；`json` 字段映射到本地候选形状（名称/型号/品牌/封装/C 码）；失败原因按中文错误码返回；凭据不出现在任何日志、仓库或文档里；切换后既有 `/lab/api/catalog/*` 契约不变。
- 允许修改目录/接口：`server/ubuntu22.04/odoo_addons/lab_catalog/`（新增 `tools/lcsc_openapi.py` 与其测试；后续 models/controllers 仅在探针通过后改动）、`maintenance/tasks/`、必要的文档与登记表。**不改** 客户端与网页端契约。
- 业务不变量/依赖：库存仍只认 `stock.quant`/`stock.move`；官方接口只用于"器件资料 + 价格 + 库存提示"，不得写入本地库存；供应商库存不得混入本地库存；凭据只放 `local/private/`（`/local/` 已被 Git 排除）。
- 负责人/协作者及分工：主代理实现与测试；用户提供接入地址、确认密钥字段含义、授权生产部署。
- 分支/起始commit/源码manifest：`feat/receipt-param-search`，起始 HEAD `605b427`；本轮完成后重新 snapshot 服务端清单。
- 环境与凭据获取方式（只写位置，绝不写值）：凭据文件 `local/private/密钥.csv`（2 行 × 2 列，第一列 9 字符、第二列 32 字符，无表头）；SDK jar 同目录。用户 2026-11-08 确认 appId 由控制台单独给出（18 位数字）；实测第 1 组第 2 列（32 位十六进制）才是 accessKey，第 1 列（9 位）不可能是 SecretKey（官方示例 SecretKey 为 32 位，疑似复制到遮罩值），**SecretKey 仍待补全**；签名头只用 appId + accessKey + secretKey，`keyId` 不参与签名。探针通过环境变量 `LCSC_OPENAPI_BASE_URL` / `LCSC_OPENAPI_APP_ID` / `LCSC_OPENAPI_ACCESS_KEY` / `LCSC_OPENAPI_SECRET_KEY`，或用 `--credentials <文件> --row N --app-id <ID>` 读取，**不打印任何凭据值**。
- 实施步骤：
  1. ~~只读拆解 SDK，确认签名与接口~~：签名 = `Base64(HMAC-SHA256(secret, METHOD\nPATH\ntimestamp\nnonce\nbody\n))`，头 `Authorization: JOP appid="…",accesskey="…",timestamp="…",nonce="…",signature="…"`；已用官方开发指南给出的「示例密钥 + 示例报文 + 期望签名值」对拍，逐字节一致。
  2. ~~Python 客户端与自检探针~~：`lab_catalog/tools/lcsc_openapi.py`（只读查询 + `--probe`），21 条纯函数/假传输测试。
  3. **接入地址与凭据已打通**：服务地址 `https://open-api.jlc.com`（官方文档写明，带连字符）。accessKey 取自 `密钥.csv` 第 1 组第 2 列（32 位），SecretKey 由用户在 2026-11-08 补全；真实 SMT 探针 `--probe C17414` 返回 `PROBE_OK`，字段齐（含 `paramTextAll` 与阶梯价）。凭据另存 `local/private/openapi-credentials.csv`（Git 排除）。
  4. 用户指定「走 SMT 通道」：`/smtOpenApi/smtComponent/selectComponentInfoByCodes`，body `{"componentCodeList":["C…"]}`，响应含 `componentName/componentModel/componentBrand/componentSpecification/stockNum/paramTextAll/smtComponentPriceInfoVOList`，**中文参数与阶梯价都有**，可以不再依赖页面解析。映射函数与测试已就位（`item_from_smt`）。
  5. ~~改数据源~~：`models/lab_catalog_fetch.py` 新增 `_official_item()`，在抓取 C 编号时先查官方 SMT 通道，再用 `lcsc_openapi.merge_into_parsed()` 覆盖名称/型号/品牌/封装/库存/价格/中文参数；分类与文档仍用页面解析。未配置 `LCSC_OPENAPI_*` 环境变量或官方接口报错时静默回退页面解析，**不改库存、不写任何业务库之外的系统**。版本已升到 `19.0.2.0.13` 并于 2026-11-08 09:16Z 部署生产，09:26–09:29Z 完成凭据注入与重启（用户当轮授权）。
- 测试命令、实际结果与退出码：
  - `python -I server/ubuntu22.04/odoo_addons/lab_catalog/tests/test_lcsc_openapi.py` → **21 tests OK**，exit 0。
  - 真实探针（只读 POST，未做任何写操作）：本机 `--probe C17414` → `PROBE_OK`（`PROBE_OK` 后 2026-11-08 取得正确 accessKey/SecretKey）；生产服务器用 `/etc/lc-elc/openapi.env` 再跑一次 → `CHANNEL smt`，`stock=49,948,000`、`price=0.0202`、`params=7`、`rc=0`。
  - 生产凭据注入（2026-11-08 09:26–09:29Z）：`/etc/lc-elc/openapi.env`（`root:odoo 0640`）+ `/etc/systemd/system/odoo.service.d/10-lc-elc-openapi.conf`，`daemon-reload` + `restart odoo` 退出码 0；进程环境四变量齐备（只记长度）、`/web/login` 带库头 200、日志 0 错误。
- 未验证项及风险：
  - 官方通道已在真实账号验签成功（本机、生产服务器、生产 Odoo 运行时各一次 `C17414` 查询）。**Odoo 运行时已实测**：`odoo shell` 内 `_official_item('C17414')` → `OFFICIAL_OK True`（`stock=49,941,126`、`price=0.0202`、`params=7`、`tiers=6`、`source=openapi_smt`）；不加载 `LCSC_OPENAPI_*` 时返回 `False`（静默回退），探针结束 `rollback`，未写库。
  - 仍**未验证**：从网页端/客户端走一次完整抓取入库（接口 → 模型 → 官方通道 → `_upsert_item` 落库）。
  - 生产已通过 `/etc/lc-elc/openapi.env` + systemd drop-in 注入 `LCSC_OPENAPI_*` 并重启验证；凭据值未写入任何仓库文件或日志。
  - 开放平台 IP 白名单：服务器带签名请求成功，说明出口 IP 已放行；控制台条目未逐条核对。
  - 价格/库存是否实时、是否含税未验证；SMT 通道的平台价与商城页面价口径可能不同。
  - `paramTextAll` 是按 `,` 与 `:` 拆分的展示文本，值里若含逗号会被截断，需在真实数据上抽查。
- 发布文件、hash和回滚点：尚未发布；生产无改动。回滚点 = 当前 `19.0.2.0.12` 与既有源码清单。
