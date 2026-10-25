# lab_team_web 第一批验收报告（隔离验证）

日期：2026-10-25。范围：独立 Web 入口 + 欢迎/登录/仓库检索/器件详情（只读）。
结论边界：**本报告不含生产部署**；浏览器像素级验收留给 Codex，见第 9 节预览实例。

## 1. 交付物

新增模块 `server/ubuntu22.04/odoo_addons/lab_team_web`（19.0.1.0.0，17 个文件）：

| 文件 | 行数 | 作用 |
|---|---|---|
| controllers/common.py | 329 | 会话上下文、权限判定、挂载基址、根别名开关、management Host 根入口、编辑器/iframe 回退 |
| controllers/pages.py | 277 | 欢迎/登录/退出/仓库/详情页面路由（服务端渲染） |
| controllers/api.py | 45 | `/team/api/session` 会话态接口 |
| models/ir_http.py | 40 | 仅接管 management Host 根路径的 `_dispatch` 短路（含 QWeb flatten 修复） |
| tools/paths.py | 374 | 纯函数：next 校验、itemKey（对齐 lab_catalog_identity）、Host 决策、数量/错误文案 |
| views/pages.xml | 418 | 7 个 QWeb 模板：layout/welcome/login/lab/detail/detail_error/denied |
| static/src/css/team.css | 1671 | 深色 + 荧光绿，作用域限 body.lc-body，含窄屏与打印 |
| static/src/js/team.js | 883 | 登录、检索增强、防竞态、URL 同步、SSR 错误保留 |
| tests/test_paths.py | 488 | L1 纯 Python 用例（无 Odoo 依赖） |
| tests/test_team_web_http.py | 304 | L2 Odoo HttpCase 用例 |
| tools/paths.py 等其余 | — | `__manifest__.py`/`__init__.py`/security/tests/__init__ |

文档：[接口契约](../../docs/architecture/TEAM_WAREHOUSE_API_CONTRACT.md)、[测试计划](team-web-phase1-test-plan.md)。

## 2. 架构与挂载决策

- **不复用原生后台外壳**：不用 `web.assets_backend`、不继承 `website.layout`，页面自带布局与静态资源。
- **规范入口**：`/team`、`/team/login`、`/team/logout`、`/team/lab`、`/team/lab/items/<item_key>`。
- **根级别别名**：`/login`、`/logout`、`/lab`、`/lab/items/<item_key>`，由参数
  `lab_team_web.root_aliases`（默认 1）控制；关闭时这些路径**真实返回 404**（已验证，见 5.2）。
- **管理站点根入口 `/`**：默认关闭。配置 `lab_team_web.management_host` 后，仅当
  请求 Host 命中该配置、路径为 `/`、且**不在编辑器/iframe 上下文**时才由本模块渲染欢迎页；
  其余一切（含其它 Host 的 `/`、`/web/*`、`/website/*`）原样交回 Odoo。
  - 未通过"抢注册 `/` 路由"实现，而是在 `ir.http._dispatch` 决策后短路，避免规则冲突。
  - 编辑器回退信号：`Sec-Fetch-Dest: iframe/frame`、`Referer` 指向 `/website/`、
    `?edit/cedit/ql`、路径前缀 `/website/`。**不使用** `session.force_website_id` 全局回退。
- `/team` 定位为兼容/开发入口，**不是**最终对外地址。

## 3. 真实可访问入口（隔离实例）

| 入口 | 匿名 | 登录无角色 | 有目录角色 |
|---|---|---|---|
| `/`（管理 Host） | 200 欢迎页 | 200 | 200 |
| `/login`、`/team/login` | 200 登录页 | 303 回 next | 303 回 next |
| `/lab`、`/team/lab` | 303 → `<base>/login?next=…` | 403 | 200 |
| `/lab/items/lcsc:C1`、`lab:3` | 303 → 登录（带完整 next） | 403 | 200 / 404 |
| `/lab/items/not-a-key` | — | 400 | 400 |
| POST `/logout` | — | 缺 CSRF 拒绝 | 带 CSRF 303 |

## 4. 接口复用 / 新增

复用：`/lab/api/catalog/{search,detail,categories,facets}`、`/lab/api/asset`、
`/web/session/authenticate|destroy`、类模型 `lab.catalog.item.search_unified/detail`。
新增（非业务）：`POST /team/api/session`。详见 [接口契约](../../docs/architecture/TEAM_WAREHOUSE_API_CONTRACT.md)。

## 5. 测试证据

### 5.1 L1 纯 Python（本机 Python 3.15，无 Odoo）

```
python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v
Ran 66 tests — 65 通过 + 1 跳过（skip 为需 Odoo 运行时的 HTTP 模块入口，不计通过）
exit 0
```
skip 的 1 项是 `test_team_web_http`（需要 Odoo 运行时），不是通过。

### 5.2 L2 真实 Odoo 19 隔离库（WSL Ubuntu-22.04，私有 PostgreSQL 14.24）

环境：私有 venv（cp310 离线 wheelhouse）、私有 PG 集群（端口 55432、socket 在私有目录）、
私有数据库 `teamweb_test`、`--http-interface=127.0.0.1 --http-port=18069`。
命令：`odoo-bin ... -d teamweb_test -u lab_team_web --test-enable --http-port=18069 --stop-after-init`

```
0 failed, 0 error(s) of 11 tests
```
（统计里的 13 含 hooks，不是用例数。）覆盖：匿名欢迎 200、匿名仓库 303+next、无角色 403、
有角色 200、**确定性夹具** lab:<id> 详情 200 且含名称/型号、非法 key 400、匿名 session JSON、
已登录访问登录页 303、恶意 next 不出站、缺 CSRF 拒绝、本站退出表单取 CSRF 后 303。

### 5.3 dispatch / 编辑器兼容（同一隔离实例，逐阶段重启避免参数缓存）

| 场景 | 结果 |
|---|---|
| management_host=127.0.0.1，GET `/` | 200，`lc-body` 命中（本站欢迎页） |
| 同上 + `Sec-Fetch-Dest: iframe` | 200，17490B，命中 "您的旅程从这里开始/My Website"（旧官网） |
| 同上 + `Referer: /website/force/1?path=/` | 同上，旧官网 |
| 同上 + `?edit=1` | 同上，旧官网（编辑器不被抢占） |
| management_host=other.example，GET `/` | 200，17490B，旧官网（其它 Host 不受影响） |
| `/web/login` | 200，旧登录页（原生登录未受影响） |
| root_aliases=0，GET `/lab` `/login` | **404**（路由真实回退） |
| root_aliases=0，GET `/team/lab` | 303 → `/team/login?next=…`（规范入口仍可用） |

过程中由真实测试发现并修复的两个缺陷：
1. `_dispatch` 内直接返回 QWeb Response 未 `flatten()` → 200 但 body 为空（已修）。
2. `safe_doc_url('https://[')` 让 `urlsplit` 抛 ValueError → 详情页白屏（已修并加畸形 URL 用例）。

### 5.4 仓库自检

`python tools/repo_check.py` → **exit 1**，错误为既有项且与本批无关：
`component-source:odoo`、`component-tracked:odoo`、`frozen-source:server`
（含已废弃的 lab_portal 路径与未冻结的新增文件）。未删除任何目录来凑通过。
`production_access: false`。

## 6. 子代理分工

| 代理 | 独占写入范围 | 产出 |
|---|---|---|
| 前端代理 | `lab_team_web/static/src/{css,js}` | team.css（1671 行）、team.js（883 行） |
| 测试代理 | `lab_team_web/tests`、`maintenance/audit/team-web-phase1-test-plan.md` | 50 个 L1 用例、11 个 L2 用例、测试计划 |
| 主代理（集成） | controllers/、models/、tools/、views/、manifest、文档 | 集成修复：Codex 复审的 6 类缺陷、flatten、iframe 回退、savepoint |

共享文件由主代理统一改；代理未互相覆盖。

## 7. 未完成 / 阻塞

- **浏览器像素验收未做**：欢迎/登录/搜索/详情/窄屏/错误态的实际渲染由 Codex 用第 9 节实例验收。
- 移动端仅做了 CSS 断点与 375px 布局设计，未在真机/DevTools 逐屏确认。
- 真实网站编辑器 UI 未点开（已用 iframe/Referer 信号模拟并通过；编辑器 JS 与保存流程未测）。
- 缺 `gevent`（离线 wheelhouse 无该包）：长轮询/websocket 未测；只影响该通道，HTTP 页面不受影响。
- 分面筛选面板、两阶段入库、领用归还、标签打印未接入（第二批）。
- `repo_check` exit 1 的既有冻结/登记问题未在本批修正（需单独的冻结任务）。

## 8. 生产未变更证明（2026-10-25T05:23Z 采集）

| 项 | 值 |
|---|---|
| `systemctl show odoo` | SubState=running，ExecMainPID=99288，ActiveEnterTimestamp=2026-10-25 01:03:34 CST |
| 本批开始时间 | 2026-10-25 12:28 CST；进程自 01:03 起未重启 |
| 生产库列表 | LcHardwareHouse、lc_hardware、postgres（无新增库） |
| 生产模块 | 仍为 lab_catalog/lab_inventory/lab_site/lab_theme/lab_workflow installed，lab_portal=uninstalled；**未安装 lab_team_web** |

本批对生产只执行了只读命令（`grep`/`ls`/`psql SELECT`/`systemctl show`），
未安装、未升级、未重启、未卸载、未写入、未改 DNS/代理。

## 9. 隔离预览实例（浏览器验收后已关闭）

浏览器验收由 Codex 完成并通过本批核心范围（375px 卡片 116px、缩略图 88px、无横向溢出；
桌面图片 211×158、4:3 保留；普通 reload 后 DOM 加载 `team.css?v=7e9eee9d31f5` 且样式表含 88px）。
截图：`local/build/dsh-unified-web-phase1-20261025/warehouse-{desktop,mobile-compact}.jpg`（Git 排除）。

验收结束后已按 PID/命令行/端口/私有 data 目录逐项核对并关闭该实例，私有测试数据保留以便复现：

| 项 | 值 |
|---|---|
| 曾用地址 | `http://127.0.0.1:18069/`（仅回环） |
| 数据库 | 私有 `teamweb_test`（WSL 私有 PG 55432），合成数据，非生产 |
| 合成数据 | `[测试] 电阻 10k 0603`(lab:4,25)、`[测试] 电容 100nF 0603`(lab:5,8)、`[测试] 无库存样例 IC`(lab:6,0) |
| 复现启动 | `wsl.exe -d Ubuntu-22.04 bash <repo>/local/build/22_preview_upgrade.sh <repo>`（脱离进程启动：`Start-Process -WindowStyle Hidden`） |
| 关闭方式 | 只结束该预览的 python/odoo 进程与该 wsl 客户端；**不** pkill 全部 odoo、不碰 systemd/生产 |


## 10. 建议审查顺序

1. `controllers/pages.py` 路由与权限守卫（403/404/303 语义）→ 对照 5.2 用例。
2. `controllers/common.py` 的 `root_alias_denied` 与 `is_editor_context` → 对照 5.3。
3. `models/ir_http.py` 的短路与 flatten → 对照 5.2 的 `/` 200 且非空。
4. `tools/paths.py` 的 next 校验、itemKey 对齐、Host 决策 → 对照 L1 用例。
5. `static/src/js/team.js` 的 safeNext / SSR 错误保留 / 防竞态 → 建议在预览实例按 5.3 复现。
6. `views/pages.xml` 登录表单 POST、资料链接白名单、文案口径。


## 11. 预览 fixture 的一次真实故障与修复（2026-10-25 13:26）

**现象**：Codex 用浏览器在预览实例登录，报"账号或密码不正确"；但页面 DOM 的
`data-db=teamweb_test`、`endpoint=/web/session/authenticate`、`method=post`、`next=/lab` 均正确。

**根因**（两处叠加，都是真实缺陷，不是环境噪音）：
1. 首版准备脚本用 `odoo-bin shell < prep.py` 跑，脚本中途在
   `stock.quant.create` 抛出 `ValidationError: Quants cannot be created for consumables or services.`
   （器件 `type='consu'` 未标 `is_storable`），而 `env.cr.commit()` 在最后，
   **整笔事务随 shell 退出回滚**——用户和器件都没有真正落库。
2. 该脚本用 `| grep -E '^PREP' || true` 过滤输出，把异常栈整段吞掉，
   于是"看到 PREP_USER_CREATED"却没有任何数据。
   教训：**准备脚本不得兜底吞错误，必须逐步 commit 并打印完整异常**。

**修复**（`local/build/prep_preview.py`，供 `09_preview.sh` 复用）：
- 用户创建后立即 commit；
- 每个器件创建后 commit；先写 `is_storable=True` 再用 inventory_mode 建 quant 并 commit；
- `step()` 捕获异常时打印完整 `traceback` 并回滚该步，绝不静默；
- 末尾输出 `CHECK_USER`/`CHECK_ITEM`（含实际 quant 合计）。

**复验**（隔离实例实测）：
- `POST /web/session/authenticate` → `result.uid = 10`；
- 登录后 `GET /lab` → 200，列表含 3 个 `[测试]` 器件、2 个 `lc-in-stock` 标记、`共 3 件`；
- `GET /lab/items/lab:4` → 200，`实验室库存：25`、库位 `WH/Stock`、型号 `TEST-R-10K`。

未触碰任何其它数据库或真实账号；仅在私有测试库 `teamweb_test` 内操作。


## 12. 集成阶段再修的 4 个真实缺陷（含 4 个 L2 用例先失败后通过）

1. **基址割裂**：测试库带着预览用的 `management_host=127.0.0.1` 时，
   `/team/lab` 的 303 跳到 `/login` 而不是 `/team/login`。
   修复：`current_base()` 改为**规范路径优先**——`/team/**` 永远以 `/team` 为基址，
   只有非 `/team` 路径在管理 Host 上才用根级基址。
   同时把测试改成**参数自给**（setUpClass 重置 management_host/root_aliases），
   避免测试依赖外部库状态。修复前 11 项中 4 项失败，修复后 **11/11 通过**（克隆库复跑）。
2. **XML 视图不随文件生效**：只改 `views/pages.xml` 而不 `-u lab_team_web`，
   DB 里仍是旧 arch，页面渲染不到新增节点。预览脚本已改为启动前先 `-u`。
3. **首屏与动态卡片价格不一致**（前端代理提出）：模板卡片脚注缺 `.lc-item-price`。
   已在模板补价格节点，并新增 `format_price()` 与 JS `formatPrice` **同一套符号规则**
   （CNY/RMB→¥、USD→$、EUR→€、其它→"CODE "），服务端预计算 `price_display`。
4. **无 JS 时筛选丢失**（前端代理提出）：检索表单的 checkbox 缺 `name`、缺 `category_id` 隐藏域。
   已补 `name="stock_only" value="1"` 与 hidden `category_id`。

### 预览实例最终验证（2026-10-25 05:44Z）

| 检查 | 结果 |
|---|---|
| 匿名 `/` | 200，含 `lc-body`（本站欢迎页） |
| `POST /web/session/authenticate` | `result.uid = 10`（teamweb_preview） |
| 登录后 `GET /lab` | 200，7840B，3 张卡片、3 个价格节点（测试数据无价格→"价格待询"）、2 个有库存标记 |
| `GET /lab/items/lab:4` | 200，`实验室库存：25`、`WH/Stock` |

### 测试数据说明

仅私有库 `teamweb_test`：账号 `teamweb_preview`（[测试] 预览账号）、
器件 `[测试] 电阻 10k 0603`(lab:4,25)、`[测试] 电容 100nF 0603`(lab:5,8)、
`[测试] 无库存样例 IC`(lab:6,0)。**没有复制任何生产数据**，测试密码仅存在于该私有库，
未写入源码/仓库/文档。


## 13. 静态资源缓存键修复（2026-10-25 16:2x）

**现象**：源码里已有 88px 手机紧凑行规则，但浏览器 reload 后 DOM 里实际加载的
`team.css` 没有该规则，图片仍 245px、卡片 408px；`document.styleSheets` 显示
href 固定为 `team.css?v=19.0.1.0.0`。

**根因**：模板用硬编码 `lc_version` 作资源版本号，改 CSS、升级模块都不会改变 URL，
浏览器按旧 URL 命中缓存。

**修复**：`controllers/common.py` 新增 `asset_version()`，按文件内容算 SHA1 前 12 位
（以 `(mtime_ns, size)` 做缓存键避免每次重复哈希），`shell_context` 注入
`lc_css_v`/`lc_js_v`，模板改为 `?v=#{lc_css_v}` 与 `?v=#{lc_js_v}`；`lc_version`
不再参与资源 URL。

**验证**（预览实例）：页面 HTML 为 `team.css?v=7e9eee9d31f5`、
`team.js?v=faa1bc0b6393`；本地对两个文件算 SHA1 前 12 位与 URL 完全一致；
按该 URL 取回的 CSS 含 `flex: 0 0 88px`，且桌面 `aspect-ratio: 4 / 3` 仍在（2 处）。
这证明是**内容驱动**的版本，而不是再换一个常量。


## 14. 交付收尾（2026-10-25 16:2x）

### 最终源码复跑（缓存键与模板改动之后）

| 层 | 精确命令 | 环境 | 结果 |
|---|---|---|---|
| L1 | `python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v` | 宿主 Windows，Python 3.15，无 Odoo | exit 0；`Ran 66 tests`；**65 通过 + 1 跳过** |
| L2 | `odoo-bin ... -d <clone> -u lab_team_web --test-enable --test-tags post_install --http-port=18071 --stop-after-init` | WSL Ubuntu-22.04 + 私有 PostgreSQL 14.24 + 私有 venv（cp310 离线 wheel）+ 私有库克隆 | exit 0；**11/11 通过，0 失败 0 错误** |

L2 在**克隆库**上执行（`pg_dump`→`pg_restore` 到 `teamweb_verify`），不干扰预览库与生产。

### 源码冻结（候选，非发布）

| 项 | 值 |
|---|---|
| 命令 | `python tools/release.py snapshot --component server --output maintenance/registry/source-server-team-web-phase1-20261025.json --activate` |
| 清单 | `maintenance/registry/source-server-team-web-phase1-20261025.json` |
| 文件数 | **175** |
| tree SHA256 | `9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4` |
| active-sources | `server` → 上述新清单（旧清单与产物关联未改写） |

### 仓库自检

`python tools/repo_check.py` → **exit 0 / PASS**，49 项检查，errors 为空，
保留既有 warning `known-payload-not-built: production-py312-rebuild`；`payload_verification=false`。
说明：此前的 `component-source:odoo`、`component-tracked:odoo`、`frozen-source:server`
失败，是通过**移除废弃 lab_portal 登记 + 冻结当前 server 源**真实修掉的，不是屏蔽检查；
本次没有运行 `--verify-payloads`，不能据此宣称离线载荷全量校验通过。

### 预览实例关闭核对

关闭前逐项核对：PID 628 命令行为 `odoo-bin ... -d teamweb_test --http-port=18069 --http-interface=127.0.0.1`、
监听 `127.0.0.1:18069`、`--data-dir` 指向私有目录；只终止该 PID，未 pkill 全部 odoo、未动 systemd。
关闭后：WSL 内 odoo 进程 0、端口 18069 返回 000、私有 PG 已 `pg_ctl stop`；
私有数据保留（`pgdata` 约 130MB、`teamweb_test` 合成数据未删除），便于复现。
