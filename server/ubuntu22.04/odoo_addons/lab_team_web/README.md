# lab_team_web · 战队管理站点（仓库 Web 入口）

Odoo 19 模块。为战队仓库提供**独立于原生 WebClient** 的管理前端外壳：
自有布局、导航与页面路由；认证仍走 Odoo 原生会话，业务仍走既有 lab_* 接口。

## 当前范围（第一批，只读）

- 欢迎页、登录（复用 `/web/session/authenticate`）、退出（本站 POST + CSRF）
- 仓库检索：分类 / 关键词 / 只看有库存 / 游标分页（有库存优先）
- 器件详情：参数、实验室库存分布、实物袋、未归还领用、资料链接

**未实现**（页面不显示为可执行，只标"暂未开放"）：采购入库（两阶段）、
领用与归还、库位管理、标签打印、系统管理。这些接口已存在于 `lab_workflow`，
留给第二批接线。

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

**状态：候选源码，未部署生产。** 详细证据与未验证项见
`maintenance/audit/team-web-phase1-report.md`。

## 已知限制

- 视觉/窄屏验收由人工在浏览器完成；仓库内不声称像素级通过。
- 缺 `gevent` 时长轮询/websocket 不可用（仅 HTTP 页面场景不受影响）。
- 分面筛选面板、两阶段入库、领用归还、标签打印未接入。
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
