# lab_team_web · 战队管理站点（仓库 Web 入口）

Odoo 19 模块。为战队仓库提供**独立于原生 WebClient** 的管理前端外壳：
自有布局、导航与页面路由；认证仍走 Odoo 原生会话，业务仍走既有 lab_* 接口。

## 版本与状态

- 源码候选：**19.0.1.1.0**（P3，2026-10-28，需配 `lab_workflow 19.0.2.0.0`）。
- 生产实际：**19.0.1.0.5**（P2，2026-10-27）。P3 页面**未部署**；候选**功能验证已完成**（见 §测试）。
- 模块版本与客户端版本（`1.1.3+6`）分别管理，不混用。

## 当前范围（P3，源码候选，未发布）

13 个业务页面，全部成对注册 `/team/...` 与根别名（`root_aliases=0` 时根别名真实 404）：

| 页面 id | 路径 | 主要角色 | 依赖接口 |
|---|---|---|---|
| receipts | `/team/lab/receipts` | operator | `pending/*`、`labels/plan|preview`、`catalog/search`、`bootstrap` |
| scan | `/team/scan` | operator | `resolve_code`、`pending/resolve`、`inventory/bags` |
| bags | `/team/lab/bags` | lab 角色 | `inventory/bags` |
| bag | `/team/lab/bags/<int:bag_id>` | lab 角色 | `inventory/bag`、`inventory/history` |
| labels | `/team/lab/labels` | operator | `labels/plan|preview`、`POST /lab/labels/pdf` |
| issue_new | `/team/lab/issues/new` | operator | `inventory/issue`、`bootstrap`、`resolve_code` |
| issues | `/team/lab/issues` | lab 角色 | `inventory/issues`、`inventory/return` |
| history | `/team/lab/history` | lab 角色 | `inventory/history` |
| locations | `/team/lab/locations` | lab 读 / manager 写 | `locations`、`location_create`、`location_update` |
| mappings | `/team/lab/location-mappings` | manager | `mapping_list|mapping_set|mapping_remove` |
| settings | `/team/lab/settings` | manager | `inventory/members`、`member_set_role` |
| materials | `/team/lab/materials` | 目录角色 | `catalog/search|bind|create_material` |
| account | `/team/account` | 已登录 | `/api/team/session` |

- 写操作一律 JSON-RPC（`window.LC` 的 `LC.submit` + 前端生成 `request_key`）；唯一表单 POST 是 PDF 下载。
- 页面只渲染骨架，数据全由 JS 调 API；API 全失败时仍可读（骨架 + 空态），不白屏、不伪造成功。
- 旧 `GET /lab/scan` 由 `lab_workflow` 一侧 **303** 到 `/team/scan`；旧 `resolve/submit`/标签端点标 deprecated，仍保留内网过渡。
- **验收状态：候选功能验证完成**（浏览器 0 fail；3 个 DOM 场景未执行）；快照与候选包登记状态见仓库 registry 和正式交接，见 §测试。

## 第一批（2026-10-25，只读，历史）

- 欢迎页、登录（复用 `/web/session/authenticate`）、退出（本站 POST + CSRF）
- 仓库检索：分类 / 关键词 / 只看有库存 / 游标分页（有库存优先）
- 器件详情：参数、实验室库存分布、实物袋、未归还领用、资料链接

**该批当时未实现**（页面只标"暂未开放"）：采购入库（两阶段）、
领用与归还、库位管理、标签打印、系统管理。这些已在 P3 接入（见上），
但 P3 自身尚未验收。

## 路由与挂载

| 路由 | 说明 |
|---|---|
| `/team`、`/team/` | 欢迎页 |
| `/team/login`、`/team/logout` | 登录页 / 退出（POST，需 CSRF） |
| `/team/lab` | 仓库检索 |
| `/team/lab/items/<item_key>` | 器件详情（`lcsc:C123` / `lab:42`） |
| `/team/api/session` | 会话态 JSON（匿名也可用，权限位全 false） |

根级别别名 `/login`、`/logout`、`/lab`、`/lab/items/<item_key>` 由参数
`lab_team_web.root_aliases`（默认 `1`）控制；设为 `0` 时这些路径**真实返回 404**。
`/lab/api/*`、`/lab/scan`、`/lab/labels/*` 等其它控制器路由不受影响。

> P3 新增的根别名（`/lab/receipts`、`/scan`、`/lab/bags`、`/lab/bags/<id>`、`/lab/labels`、
> `/lab/issues`、`/lab/issues/new`、`/lab/history`、`/lab/locations`、`/lab/location-mappings`、
> `/lab/settings`、`/lab/materials`、`/account`）已登记到 `tools/paths.py` 的别名白名单；
> 新增页面必须同时改白名单，否则 `root_aliases=0` 的安全回归会漏。

### 管理站点根 `/`

默认**不接管**。配置 `lab_team_web.management_host`（可逗号分隔多主机）后，
仅当请求 Host 命中该配置、路径为 `/`、且不在网站编辑器上下文时才渲染欢迎页；
其余情况（其它 Host 的 `/`、`/web/*`、`/website/*`、带 `edit/cedit/ql` 的请求）
原样交回 Odoo。实现方式是在 `ir.http._dispatch` 决策后短路，**不抢注册 `/` 路由**。

编辑器上下文识别信号：`Sec-Fetch-Dest: iframe/frame`、`Referer` 指向 `/website/`、
`edit/cedit/ql` 参数、路径前缀 `/website/`。刻意不使用 `session.force_website_id`
做全局回退，否则管理员用过编辑器后普通欢迎页会一直变成旧站。

相关参数：

| 参数 | 默认 | 作用 |
|---|---|---|
| `lab_team_web.management_host` | 空 | 允许接管根 `/` 的主机名；空=关闭 |
| `lab_team_web.management_host_enabled` | 1 | 根入口总开关 |
| `lab_team_web.root_aliases` | 1 | 是否启用 `/login`、`/lab` 等根级别名 |
| `lab_team_web.site_title` | 力创实验室 · 战队仓库 | 页面标题 |

## 权限

- 目录页只要求 `lab_catalog` 读取角色（`group_lab_catalog_user` /
  `group_lab_catalog_manager` / `base.group_system`）。
- 实验室角色（`lab_workflow.group_lab_*`）与目录读取角色**不是一回事**，
  因此不用 `/lab/api/inventory/bootstrap` 的失败去阻断只有目录权限的用户。
- 页面 403/404/400 与接口 FORBIDDEN 都由服务端判定，前端只做显示层收敛。

## 依赖与兼容

`depends = base, web, lab_catalog, lab_workflow`。不改动既有 `/lab/api/*` 行为，
旧 Flutter / EDA 调用不受影响。不依赖 `web.assets_backend`，也不继承
`website.layout`；静态资源由本模块自己的页面按需 `<link>/<script>` 引入，
避免污染其它前台页面。

## 安装与升级

```sh
# 安装
odoo-bin --addons-path=<odoo>/addons,<odoo>/odoo/addons,<repo>/server/ubuntu22.04/odoo_addons \
    -c <odoo.conf> -d <db> -i lab_team_web --stop-after-init

# 改了 views/*.xml 或静态资源后必须升级，否则 DB 里仍是旧视图
odoo-bin ... -d <db> -u lab_team_web --stop-after-init
```

> 只重启服务**不会**重载 XML 视图；`views/pages.xml` 的改动必须 `-u` 才生效。
> 静态 CSS/JS 是普通文件，改完**不需要**升级：模板按文件内容哈希拼
> `?v=<sha1前12位>`（`lc_css_v`/`lc_js_v`），文件一变 URL 就变，浏览器自动拉新，
> 不依赖用户手动清缓存。**不要**把资源 URL 改回模块版本号常量。

## 测试

```sh
# L1 纯 Python（不需要 Odoo/数据库）
python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v

# L2 Odoo HttpCase（需要 Odoo 19 + PostgreSQL + 隔离库）
odoo-bin ... -d <isolated_db> -u lab_team_web --test-enable \
    --test-tags post_install --http-port=<port> --stop-after-init
```

最近一次结果（最终源码复跑，2026-10-25）：
- L1：`python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v`
  → `Ran 66 tests`，**65 通过 + 1 跳过**，exit 0。skip 是 `test_team_web_http` 模块入口
  （纯 Python 环境无 odoo），不计通过。
- L2：WSL Ubuntu-22.04 + 私有 PostgreSQL 14.24 + 私有 venv（cp310 离线 wheel）
  + 隔离库，`-u lab_team_web --test-enable --test-tags post_install`
  → **11/11 通过，0 失败 0 错误**，exit 0。
- 浏览器：Codex 验收 375px（卡片 116px、缩略图 88px、无横向溢出）与桌面
  （图片 211×158、4:3 保留）通过。

### P3（2026-10-28）实际结果：候选功能验证完成

旧 L1/L2 数字属于 19.0.1.0.5，**不代表** 19.0.1.1.0。P3 这一轮（证据均在
`local/build/p3-web-20261028/`，Git 排除）：

| 项 | 结果 | 证据 |
|---|---|---|
| L2 HttpCase（P3 写路径，真实） | **21/21 通过**：`total=21 failed=0 errors=0 p3_class_ran=1`，RC=0 | `httpcase-r8.log` |
| 写业务 API 断言 | **54 pass / 0 fail / 1 blocked**（total 55；blocked 为 Origin 断言，未提供 Origin URL，不改判 PASS） | `runs/run.KOJbZY/verify-summary.json` |
| 浏览器真实流程 R8 | **31 步 28 pass / 0 fail / 3 blocked**，`unreached=0`；3 blocked 为 cross-user、same-key-different-payload、unknown-outcome 的 **DOM 场景未执行**（由 API/HttpCase/core 独立覆盖，不得称 DOM 通过） | `runs/browser-20261028T065311Z/browser-p3.json`、`browser-r8.log` |
| 浏览器实测业务事实 | 两种 canonical key（`lcsc:C…`→裸 `C…` 给 `resolve`；`lab:<id>` 走 `catalogDetail` 保具体本地档案）、建袋不增 quant、上架 +2、重复确认 quant 不变、领用 −2、部分归还 +1；role/materials/locations/mappings 管理页可用；`LABB:`/`LABL:`/SN/立创原厂码路径未改 | 同上 |
| 纯静态/契约 + JS 语法 | 108 项通过 + **JS 语法 15/15**（`team.js`、`workflow_core.js`、13 个页面脚本） | `fast-r1-results.json`、`fast-r1-js-*.log` |
| 新增纯逻辑 | `backend_logic` 25/25、`web_contract` 25/25；早期 `core_behavior` exit 1 与 5 份 XML 格式失败已修 | `p3-unit-r1-results.json` |
| core / XML | core **17/17**、XML **6/6** 解析通过 | `core-r2.log`、`repairs-r2-results.json` |
| 路由表 | `routes.json` **79 条**，`generate_routes.py --check` 通过 | `maintenance/registry/routes.json` |
| 历史（已修复） | HttpCase 曾 9 error（`authenticate` AccessDenied）、浏览器曾缺 `websockets` 只跑 5 步 | `httpcase-r5.log`、`runs/browser-20261028T043355Z/` |

**状态：候选功能验证完成，未部署生产；源快照与候选包以仓库 registry 登记为准。**
- 已通过项见上表；浏览器本轮 **0 fail**，3 个 blocked 是 DOM 场景未执行（对应断言由 API/HttpCase/core 覆盖，不重复计为 DOM 通过）。
- 收尾由 Lead 执行：`release.py snapshot --activate` → 构建候选包 → `release.py artifact` 登记。
  本文件随 server 源码进入冻结树；快照的 `file_count` / `tree_sha256` 仅记录于仓库 registry 与正式交接，不回填本文件以免改变已冻结的源树。
- 生产仍是 19.0.1.0.5；本模块 `views/*.xml` 变更必须 `-u lab_team_web` 才生效。
- 不等价声明：隔离 runtime 为 Python **3.10.12**，生产为 **3.12.15**；本表结果不能写成"生产等价通过"。
- 详细证据与未验证项见 `maintenance/handoffs/2026-10-28-p3-web-workflows.md`。

## 已知限制

- 视觉/窄屏验收由人工在浏览器完成；仓库内不声称像素级通过。
- 缺 `gevent` 时长轮询/websocket 不可用（仅 HTTP 页面场景不受影响）。
- 分面筛选面板仍未接入；两阶段入库、领用归还、标签打印已在 P3 源码接入，HttpCase 21/21、写 API 断言
  54 pass、浏览器主链 0 fail 已过；仍有 3 个 **DOM 场景未执行**（cross-user / same-key-different-payload /
  unknown-outcome），其断言由 API / HttpCase / core 覆盖。
- 处理立创料号时的前端约定（P3 修复）：`lcsc:<C码>` 先转成**裸 `C…`** 再交 `resolve`；`lab:<id>`
  走既有 `catalogDetail` 以保住具体本地档案；`LABB:`/`LABL:`/SN/立创原厂码路径不变。
- 测试读 trace 的约定：只从**本轮新增的那一行 DOM `td`** 取 `raw`，仅扫码时补 `LABB:` 前缀；
  **不要**要求表格文本里出现 QR 前缀（那是测试写法，不是业务要求）。
- P3 页面只在隔离环境（Odoo 19 + Python 3.10.12）验证过，**不等价生产 Python 3.12.15**；
  公网 allowlist 模板虽已逐端点列出但**未部署**。精确门槛在 Nginx 层（源码已过 1.26.2 与 1.30.6
  各 34/34）；Netlify 侧是 `/*` 通配透传、`_headers` 亦为 `/*` 全局、无 functions，
  **不需要为 P3 逐路径增补** → 公网候选联调/部署未做。
- 旧 `/lab/scan/resolve|submit`、`/lab/labels/plan|download` 仍存在（deprecated，内网过渡），新页面只用 JSON-RPC 与 `/lab/labels/pdf`。
- 实体打印、实体摄像头/扫码枪、手机流量无 VPN 正式域名登录、真机：**只能用户验收，均未测**。
- 图片经 `/lab/api/asset` 代理；该接口受 `lab_catalog.asset_cache_enabled` 控制，
  关闭时页面显示"无图"占位而不是伪造图。

## 设计要点（改动前请先读）

1. `_dispatch` 里直接返回 QWeb Response 必须手动 `flatten()`，否则 200 但 body 为空。
2. 页面内所有数据库读取包 `SAVEPOINT`，异常在 savepoint 外捕获后渲染错误页，
   避免 InFailedSqlTransaction 导致整页白屏。
3. 深链接回跳（`next`）按 URL 解析校验：允许 `lcsc:C123` 这类冒号，拦截
   `//host`、反斜杠、控制字符与百分号编码绕过；前后端（`tools/paths.py` 与
   `static/src/js/team.js`）必须保持同一套规则。
4. 手机断点（≤560px）列表卡片是**紧凑信息行**（88px 缩略图 + 右侧可换行信息），
   桌面为网格、详情主图维持原样；调整时注意不要让空图占位重新撑高首屏。
