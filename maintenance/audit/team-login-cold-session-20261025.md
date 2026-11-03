# team.l-creation.club 冷登录无反应 · 隔离复现与最小修复候选（2026-10-25）

当前状态：**冷会话修复已上线**，现vhost SHA256为
`e3674661515dbbd5852ae825b3c96bafeb36036956ce7b8519d2857c8561d1e6`，应用记录见第8节。
第1–7节保留上线前候选与隔离证据。用户补充“按钮和页面完全没有变化”，
随后用户于2026-10-25回复“可以了”，确认原登录无反应恢复。此为用户复验，
Codex未独立操作真实账号；刷新保持会话、退出与跨端流程未追加实测。

## 1. 已证实的会话故障原因（不等同于全部界面症状已解释）

team vhost 对**所有路径**固定发送 `X-Odoo-Database`。Odoo 19 在
`session 无 db 且请求带 X-Odoo-Database 头` 时会把会话标记为 **stateless**
（`session.can_save = False`），认证虽成功但**不写 session cookie**，
后续请求仍匿名 → 前端表现为"登录没有反应"。

隔离环境已精确复现：带 header 认证 **0 个 Set-Cookie**；去掉 header 认证
**写入 cookie 且会话可持久**，随后带 header + cookie 访问受保护页正常、退出正常。

## 2. 生产源码证据（只读，安装版本 19.0）

`/opt/odoo/odoo-19/odoo/http.py`：

- L1829-1838（`Request._get_session_and_dbname`）：
  ```
  if session.db and db_filter([session.db], host=host):
      dbname = session.db
      if header_dbname and header_dbname != dbname: raise Forbidden(...)
  elif header_dbname:
      session.can_save = False  # stateless
      if db_filter([header_dbname], host=host):
          dbname = header_dbname
  ```
- L2160-2174（`Request._save_session`）：
  ```
  if not sess.can_save:
      return
  ...
  if sess.is_dirty or cookie_sid != sess.sid:
      self.future_response.set_cookie('session_id', ...)
  ```

`/opt/odoo/odoo-19/addons/web/controllers/session.py` L32-55（原生 `authenticate`）：
无 `request.db` 或不同库时用 body 的 `db` 新建 `Registry(db)` 环境，
认证后 `request.session.db = db`，再 `request._save_session(env)`。
→ **认证端点本身完全支持"请求无 db 时按 body 的 db 建会话"**。

前端证据：`views/pages.xml` 登录表单带 `data-db`/`data-endpoint`；
`static/src/js/team.js` L252 使用 `data-endpoint`，默认 `/web/session/authenticate`。
未改前端。

## 3. 隔离复现（私有 WSL，未触生产；断言式）

- 环境：私有 PostgreSQL + `teamweb_test` 库 + 私有 Odoo 预览 `127.0.0.1:18069`；
  仅使用**合成账号** `teamweb_preview`（非生产账号）。
- 脚本：`local/build/team-login-cold-session-20261025/cold-session-assert.sh`。
  安全措施：`umask 077`、`mktemp -d` 唯一私有目录存 cookie/json、只清理**本目录内精确文件**、
  不输出密码/cookie 值（仅布尔/计数/状态）；**以断言决定退出码**，不把"无输出"当通过。
- 结果（脚本 exit 0）：

| 场景 | 断言 | 结果 |
|---|---|---|
| A1 | 带 header 认证返回 uid=10 | PASS |
| A2 | 带 header 认证**不写** session cookie | PASS（count=0） |
| A3 | 带 header 认证后会话不可用（**SessionExpired**） | PASS |
| B1 | 去 header 认证返回 uid=10 | PASS |
| B2 | 去 header 认证**写入** session cookie | PASS（count=2） |
| B3 | 冷 CookieJar 保存 session_id（不输出值） | PASS |
| B4 | 后续 `get_session_info` uid 与认证一致（=10） | PASS |
| C1 | 带 cookie+header 访问 `/team/lab` | PASS（200） |
| C2 | 页面含 `id="lc-results"` 容器 | PASS |
| C3 | 未出现数据库选择页 | PASS |
| D1 | 带 CSRF POST `/team/logout` | PASS（303） |
| D2 | 退出跳转 `/team/login` | PASS |
| D3 | 退出后会话失效 | PASS |

**SUMMARY PASS=13 FAIL=0**（任一失败脚本即非 0 退出，不会"看起来通过"）。

生产只读补充：`GET /login`（Host: team.l-creation.club）返回 200，**无 session_id Set-Cookie**，
与 `can_save=False` 的源码行为一致（当前生产 vhost 仍未修复）。

## 4. 最小修复候选

文件：`local/build/team-login-cold-session-20261025/nginx-team-login-fix.conf`
SHA256 **`e3674661515dbbd5852ae825b3c96bafeb36036956ce7b8519d2857c8561d1e6`**（3,357 B，77 行）

相对已批准版（b86d8433…）**唯一差异**：在第一个 `location` 之前新增
```nginx
location = /web/session/authenticate {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Odoo-Database "";   # 清掉（含客户端伪造值）
    proxy_pass http://odoo;
}
```

要点：
- `location = ` 为**精确匹配**，优先级高于 `location /`，只影响该单一 URL（含查询串）。
- nginx 对空值 header 的处理是**不发送该头**，因此客户端即使伪造 `X-Odoo-Database` 也会被清除。
- 其余四个 location 的完整头与 `X-Odoo-Database LcHardwareHouse` **保持不变**。
- 未改 `default_server`、全局 `dbfilter`、`web.base.url`、旧 odoo vhost、DNS/NM；未加模块。

## 5. 上线前应用计划（后续已由Codex审查执行，见第8节）

1. 备份当前 team vhost（内容哈希 b86d8433…）到唯一 0700 目录，校验副本哈希。
2. 上传候选到私有暂存并复核 SHA256 = e3674661…。
3. `install -m 0644` 覆盖 team vhost（**只改这个文件**）→ `nginx -t` → `systemctl reload nginx`。
4. 失败：恢复备份文件 → `nginx -t` → `reload`，复验旧服务。
5. 验收：真实浏览器全新无 cookie 打开 `http://team.l-creation.club/login`，用正常账号登录
   （用户侧操作，我不接触密码）→ 应成功跳转且刷新后仍登录；服务端用隔离同型流程与
   `get_session_info` 复核；退出后回到 `/login`。
6. 回滚：把备份文件写回 team vhost → `nginx -t` → `reload`；参数与其它配置不动。

## 6. 关于 HTTPS 与 Netlify（只说明，不执行）

- 官网托管在 Netlify 属**公网主站**，与本内网 `team.l-creation.club` 无直接关系；
  本任务**不动 Netlify**、不改公网 DNS/证书。
- team 的 HTTPS 仍需 Let's Encrypt 生产账号与当前协议同意（**用户尚未同意**），
  因此本任务**不注册账号、不接受协议、不下单、不签发、不启用 443、不自签**。
  在获得同意前，team 入口维持 **HTTP（内网/VPN）**。

## 7. 未测 / 不声称

- **真实用户完整登录未测**：本轮只用合成账号在隔离库验证；生产未创建测试账号、
  未伪造 cookie/session、未读取任何真实密码。
- 生产证书/HTTPS、VPN 跨网、移动端未测。
- 候选配置的 `nginx -t` 需在服务器应用时执行（本地无 nginx 可离线校验；已静态核对结构）。
- 浏览器自动化工具本轮不可用；界面层结论以生产只读 HTTP + 隔离认证往返为准。


## 8. 生产应用记录（2026-10-25；时间标签来自原备份名称，不据Z推断时区）

### 8.1 应用前复核

| 项 | 值 |
|---|---|
| 当前 team vhost SHA256 | `b86d8433eb120c8deb7c5ae3aef3ede8e980d4c34ac97581d2481dd3c77fdc66` |
| enabled 指向 | `/etc/nginx/sites-available/team-l-creation-club` |
| 服务 | nginx active（master 1092）、odoo active（MainPID 124857） |

### 8.2 备份（唯一 0700）

目录：`/var/backups/lc-elc/team-login-fix-20261025T2142Z`
- `team-vhost.before.conf` SHA256 **`b86d8433…fdc66`**（副本与原件一致）
- `team-vhost.before.sha256`、`team-enabled.ls`

### 8.3 安装（仅改该文件）

| 步骤 | 命令要点 | 退出码/结果 |
|---|---|---|
| 上传并校验 | 私有暂存 `/root/lc-elc-login-fix-20261025T2142Z/`，`sha256sum` | 与批准值 **e3674661…** 一致 |
| 应用前再校验 | 当前文件哈希必须仍为 b86d8433…（否则中止） | 通过 |
| 安装 | `install -m 0644 <staging> /etc/nginx/sites-available/team-l-creation-club` | 0 |
| 配置校验 | `nginx -t` | 通过 |
| 生效 | `systemctl reload nginx` | 成功；输出 `INSTALL_OK`，exit **0** |
| 应用后哈希 | `sha256sum` | **`e3674661…d1e6`** |

失败路径（未触发）：`nginx -t` 或 `reload` 失败即用备份写回并复验（脚本已内置）。

### 8.4 应用后只读验证（生产）

| 项 | 结果 |
|---|---|
| nginx master / odoo MainPID | **1092 / 124857**（均未重启） |
| 443 | **无监听**（HTTPS 未启用） |
| 新域名 `/login` | **200**，3902 B，**无 session_id Set-Cookie** |
| 新域名 `/`、`/lab`（匿名） | **200**、**303** |
| 认证端点（随机不存在账号） | **200 + odoo.exceptions.AccessDenied**，**无 Set-Cookie**（失败路径无状态变更） |
| 旧站 `/`、`/web/login`、`/lab`、`/login`、`/lab/scan` | **200 / 200 / 404 / 404 / 303**（与基线一致） |
| Android 更新清单 | **200 / 1826 B / SHA256 `152d47ae…5cb65`**（与基线一致） |

## 9. 前端静态核查（只读，未改任何前端源码）

> 用户症状为「按钮和页面完全没有变化」。冷会话修复解释了"看起来没反应"的循环：
> 认证返回 uid（无错误）→ JS 跳转到 `next` → 因无 cookie 又被 303 回登录页 → 视觉上等于没变化。
> 但按审查要求，先静态确认页面与脚本本身没有结构性问题。

### 9.1 生产登录 HTML（Host: team.l-creation.club，3902 B）

| 检查 | 结果 |
|---|---|
| `<body class="lc-body" data-base="" data-authenticated="0">` | 正常 |
| `<script defer="defer" src="/lab_team_web/static/src/js/team.js?v=faa1bc0b6393"></script>` | **1 开 1 闭**，无自闭合，位置在 `</body>` 前 |
| `</script>` 被转义/嵌进属性 | **无**（`&lt;script` / 属性内 `</script>` 均为 0） |
| CSS `team.css?v=7e9eee9d31f5` | 存在（内容哈希版） |
| 表单 | `<form id="lc-login-form" method="post" action="/login" data-db="LcHardwareHouse" data-next="/lab" data-endpoint="/web/session/authenticate">` |
| 输入 | 账号/密码均 `required="required"`，autocomplete 正确 |
| 提交按钮 | `<button class="lc-btn lc-btn-primary" type="submit">登录</button>` |
| 错误节点 | `<p class="lc-form-error" role="alert" hidden="True"></p>` —— **存在**（布尔属性渲染为 `hidden="True"`，HTML 语义仍为隐藏） |
| `<noscript>` 提示 | 存在（无 JS 时明确提示不提交密码） |

### 9.2 服务端返回的 JS（`/lab_team_web/static/src/js/team.js`）

| 检查 | 结果 |
|---|---|
| 响应 | 200，**34,613 B**，`Content-Type: text/javascript; charset=utf-8`，`X-Content-Type-Options: nosniff` |
| SHA256 | **`1951e05a7fdfc8dd41d784baf063b1901987082fd481be2e3c5c34ed38407d93`** —— 与冻结源/上线时**完全一致** |
| 语法 | `node --check` **通过** |
| 选择器与钩子 | `#lc-login-form`、`.lc-form-error`、`button[type=submit]` 在 HTML 中均存在；`$()/setHidden()` 实现正确（移除 hidden 属性） |
| 启动顺序 | `DOMContentLoaded → init() → initLogin()`；`initLogin` 内有 `if (!form) return` 保护 |
| 提交处理 | `preventDefault` → `postJson(data-endpoint)` → 成功 `window.location.assign(next)`；失败按 `error.data.message` 显示中文提示 |

**静态结论**：未发现「脚本未加载 / 标签未闭合 / 事件未绑定 / 表单按钮缺失」类问题；
前端源码本轮**未修改**。本轮已证实冷会话不落cookie；实际浏览器中的脚本执行、
缓存和按钮事件仍需Console/Network或真实点击证据，不能由静态结果排除运行时问题。

### 9.3 DOM 模拟（不可用，未安装）

尝试使用既有 DOM 测试工具模拟「启动 → 提交 → 错误提示」，但本机**没有**任何可用实现：
«jsdom» / «happy-dom» / «linkedom» / «domino» / «cheerio» 均 **MISSING**
（Node v24.13.0；DSH 自带 node_modules 与用户全局 npm 目录均无）。
遵守"不新安装浏览器/不绕过安全"，**未安装任何依赖**，因此**没有**做 DOM 级提交模拟；
前端源码也**未修改**。其余结论仅基于生产只读 HTTP + 服务端源码 + 静态检查。

### 9.4 未验证（必须保留）

- **真实用户点击登录未验证**（不接触密码）。Codex浏览器IAB快照超时、Edge窗口最小化，未取得可操作状态；已请求用户强制刷新重试及Console错误信息。
- 若复验仍"无变化"，需要浏览器 Console/Network 证据（哪个请求、什么状态码），再决定是否做最小前端修复。
- 生产原生 `POST /login` 在无 JS 时因 CSRF 缺失返回 **400**（预期行为，非缺陷；`<noscript>` 已提示）。

## 10. 隔离断言口径说明

- 上文第 3 节 **13 条断言 ≠ 13 个独立业务场景**：A/B 各 3–4 条断言围绕同一认证行为，
  C/D 各 3 条围绕受保护页与退出。
- A3 的实测是**明确返回 SessionExpired**（不是"任意无 uid 错误"）；后续若重测应保持
  严格判定（SessionExpired 或合法 JSON 且 uid 非 10），不得把任意错误算成功。
