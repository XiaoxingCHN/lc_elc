# lab_team_web 第一阶段测试计划（欢迎 / 登录 / 仓库 / 详情）

## 0. 状态更新（2026-10-25 复跑后，覆盖下文过时描述）

本文件最初写于"本机没有 Odoo、L2 全部 blocked"的阶段。以下为**当前真实状态**，
下文与之冲突的句子一律以本节为准：

| 项 | 当前事实 |
|---|---|
| L1 用例数 | **65 通过 + 1 跳过**（Ran 66）。跳过项是 `test_team_web_http` 模块入口（纯 Python 环境无 odoo），不计通过 |
| L1 expectedFailure | **已无**：`quote_item_key` 的中文/非 BMP 编码缺陷已修（改为 ASCII 安全集 + UTF-8 百分号编码），L1-08 现在是普通断言 |
| L2 是否可执行 | **已执行**：WSL Ubuntu-22.04 + 私有 PostgreSQL 14.24 + 私有 venv（cp310 离线 wheelhouse）+ 私有库；**11/11 通过，0 失败 0 错误** |
| 本机是否有 Odoo | 宿主 Windows 无 Odoo；**私有 WSL 隔离环境有**，L2 在那里跑通。不能再说"本机无 Odoo，L2 全部 blocked" |
| L2-05 详情 | 旧写法"200 或 404 都可接受"**已废弃**：测试在隔离库创建确定性器件夹具，断言 **200 且含名称/型号/价格节点** |
| L2-11 CSRF 正分支 | **不再依赖 /web 抓 token、不再 skip**：token 从本模块自己的退出表单读取，取不到即判失败 |
| 视觉验收 | 仍**未做**（交由 Codex 浏览器）；窄屏 375px 正在验收，CSS 已改紧凑行 |

复跑命令见本文件第 7 节，环境搭建脚本见仓库 `local/build/`（Git 排除）。

- 模块：server/ubuntu22.04/odoo_addons/lab_team_web
- 版本：19.0.1.0.0
- 依赖：base, web, lab_catalog, lab_workflow
- 文档性质：**测试计划**，不是测试报告；本文不代表任何用例已执行、已通过或已验收。
- 编写日期：2026-10-25
- 源码基线：以执行时工作区实际文件为准（该模块处于第一批实现阶段，文件可能继续变化）

## 1. 范围与不变量

本阶段只覆盖第一批纵向流程：欢迎页、登录/退出、仓库检索页、器件详情页、
站点会话接口，以及这些页面依赖的纯函数。采购入库、领用归还、库位管理、
打印、扫码、管理后台均不在本阶段测试范围。

必须始终成立的不变量：

1. **认证边界**：页面路由使用 auth="public" + 控制器内显式判定；匿名访问
   仓库/详情必须 303 到本站 /team/login?next=...，不能跳到 Odoo 原生
   /web/login，也不能先渲染页面再由前端跳转。
2. **权限边界**：仓库与详情读取要求 lab_catalog 读取角色
   （group_lab_catalog_user / group_lab_catalog_manager / base.group_system
   任一）；已登录但无该角色必须 403，而不是 200、404 或 500。
   前端隐藏入口不能替代服务端校验。
3. **链接基址**：规范挂载前缀为 /team；根级别别名 /login、/logout、/lab
   由参数 lab_team_web.root_aliases 控制（默认开启）。base 为空串时链接必须是
   /login、/logout、/lab、/lab/items/...，不得出现 //login、//lab。
   关闭别名时，根级别路径应表现为不存在（404），不能静默放行或跳到别的页面；
   规范 /team 路径仍可用。
4. **itemKey**：lcsc:C<数字> 与 lab:<十进制 id> 是合法键；非法键返回 400；
   合法但查不到返回 404；详情查询异常走独立错误页，不得 500。
   具体某个编号是否存在属于数据依赖，测试不做硬编码断言。
5. **只读首批**：采购入库、领用归还、库位/记录等未实现能力不得呈现为可执行
   入口；页面只能展示为 planned/denied 状态。
6. **跳转安全**：next 只接受站内相对路径。协议相对 URL（//host）、带
   scheme/netloc 的 URL、反斜杠、控制字符、非字符串必须退回默认值；
   百分号编码最多解码三轮后仍须满足同一约束。itemKey 中的冒号必须允许
   （lcsc:C123、lab:42），不能因防跳转规则误伤合法详情链接。
7. **CSRF**：POST /team/logout 必须校验 CSRF；缺失/错误 token 返回
   400/403，不能 200/303 成功。JSON-RPC 会话接口按 Odoo 路由类型处理。
8. **状态语义**：303 只表示"去另一个页面看"，不表示业务动作完成；页面用
   400/403/404 和独立错误页表达失败，不能用"跳回原生动作"冒充完成。
9. **数据来源**：仓库检索与详情复用 lab.catalog.item.search_unified /
   detail，不在本模块另写查询或复制库存规则；测试不直接改库存。
10. **环境隔离**：所有 Odoo 测试只允许在隔离测试库执行，不连生产、不安装
    到生产、不执行服务器操作；本文不包含任何真实凭据。

## 2. 测试分层与可执行性

| 层 | 文件/方式 | 依赖 | 本机可执行性 |
|---|---|---|---|
| L1 纯函数 | tests/test_paths.py（unittest） | Python 3.15，仅标准库 | 可执行（不需要 Odoo/数据库） |
| L2 HTTP 契约 | tests/test_team_web_http.py（HttpCase） | Odoo 19 + PostgreSQL + 隔离库 + 三个模块 | **已可执行**：私有 WSL 隔离环境，11/11 通过（宿主 Windows 无 Odoo） |
| L3 浏览器/人工 | 手工清单（本文第 3.3 节） | 可运行实例 + 浏览器 | 预览实例已常驻 `http://127.0.0.1:18069/`（仅回环）；像素级验收由 Codex 执行 |

L2 文件在缺少 odoo 时于导入阶段抛 unittest.SkipTest，因此 L1 的 discover
命令仍可执行；该跳过只说明"本机没有 Odoo"，不说明 HTTP 契约成立。

## 3. 测试矩阵

### 3.1 L1 纯函数用例（tests/test_paths.py）

前置：已安装 Python 3.15；无需 Odoo、数据库、网络。

| ID | 用例 | 步骤（要点） | 期望 | 自动化 | 本机 |
|---|---|---|---|---|---|
| L1-01 | 站内 next 保留 | 传 /lab?q=abc、/team/lab/items/lcsc:C1、/ | 原样返回 | 是 | 可执行 |
| L1-02 | 开放重定向拒绝 | 传 //evil.com、https://evil.com、javascript:、/\evil、非字符串、None | 返回 CANONICAL_BASE 或显式 default | 是 | 可执行 |
| L1-03 | 控制字符处理 | 中间嵌入 \x00/\x01/\x1f；尾部 \r/\n/\t/\x1f | 中间控制字符退回默认；尾部空白类控制符被剥离后不得再含控制字符 | 是 | 可执行 |
| L1-04 | 百分号编码绕过 | 传 /%2f%2fevil.com、/%252f%252fevil.com、/%5Cevil | 退回默认（最多三轮解码后仍须站内） | 是 | 可执行 |
| L1-05 | 业务路径冒号 | 传 /team/lab/items/lcsc:C1、/lab/items/lab:42 | 原样保留，不误判为 scheme | 是 | 可执行 |
| L1-06 | resolve_base | /team、/team/lab、/login、/lab/items/x、/web/login、/odoo、非字符串；关闭 aliases | 规范前缀->/team；别名->空串；未知->/team；关闭别名->/team | 是 | 可执行 |
| L1-07 | itemKey 校验/解析 | lcsc:C123456、lcsc:C1、lab:42；lab:abc、junk、lcsc:、空串、无前缀 C 码 | 合法为 True；非法为 False；parse 返回 kind/value | 是 | 可执行 |
| L1-08 | quote_item_key | 安全键、含空格、含 ?/#、含中文 | 安全键不变；空格/%3F/%23 编码且无 ?/#；中文与非 BMP 一律 UTF-8 百分号编码 | 是 | 可执行（已修复，无 expectedFailure） |
| L1-09 | clamp_limit | 1/24/100/50、0/-1、101/9999、abc/None/空串、自定义 default/max | 范围内保留；越界回落/封顶；非法回 default | 是 | 可执行 |
| L1-10 | parse_flag | 1/true/on/yes/y、TRUE/带空格、True；0/false/off/no/空/None/False/2 | 真值 True；其余 False | 是 | 可执行 |
| L1-11 | format_quantity | 5/5.0/0、1.5/1.500/0.25/12.345、None/空串、非数字 | 整数无小数点；小数去尾零；空/非数字显示 — | 是 | 可执行 |
| L1-12 | URL 拼接 | base="" 与 base="/team" 下 welcome/login/logout/lab/item；带 q/category_id/cursor/stock_only；next 编码 | 根级别不出现 //；查询参数可 parse 回读；next 完整往返 | 是 | 可执行 |
| L1-13 | 错误文案与常量 | 所有 ERROR_MESSAGES 码、未知码、None、显式 fallback；CANONICAL_BASE/DEFAULT_LIMIT/MAX_LIMIT/ROOT_ALIASES | 已知码命中；未知码落 INTERNAL_ERROR 或 fallback；规范前缀与分页上限固定，ROOT_ALIASES 至少含 /login、/lab 且都以单斜杠开头 | 是 | 可执行 |

### 3.2 L2 HTTP 契约用例（tests/test_team_web_http.py）

前置：Odoo 19 已安装 lab_catalog、lab_workflow、lab_team_web；
隔离测试库；setUpClass 创建两个用户：

- team_web_no_role：仅 base.group_user（内部用户，无 lab 角色）
- team_web_member：base.group_user + lab_catalog.group_lab_catalog_user +
  lab_workflow.group_lab_user

data 依赖：lcsc:C1 是否存在不预判，只接受 200/404。

| ID | 用例 | 步骤（要点） | 期望 | 自动化 | 本机 |
|---|---|---|---|---|---|
| L2-01 | 匿名欢迎页 | GET /team | 200；HTML 含站点标题（ir.config_parameter 或默认标题） | 是 | 已执行（通过） |
| L2-02 | 匿名仓库回跳 | GET /team/lab，不跟随重定向 | 303；Location 含 /team/login 与 next=；不含 /web/login | 是 | 已执行（通过） |
| L2-03 | 无角色拒绝 | 以 no_role 登录后 GET /team/lab | 403 | 是 | 已执行（通过） |
| L2-04 | 有角色放行 | 以 member 登录后 GET /team/lab | 200 | 是 | 已执行（通过） |
| L2-05 | 详情确定性夹具 | 隔离库创建本地器件后 GET /team/lab/items/lab:<id> | **200**，页面含名称、型号与价格节点；不得 500；不含研发术语 | 是 | 已执行（通过） |
| L2-06 | 非法 itemKey | 以 member 登录后 GET /team/lab/items/not-a-key | 400 | 是 | 已执行（通过） |
| L2-07 | 匿名会话接口 | POST /team/api/session，JSON-RPC 空 params | HTTP 200；result.ok=True；authenticated=False；permissions 三项全 False；base=/team；urls 四键齐全 | 是 | 已执行（通过） |
| L2-08 | 已登录访问登录页 | 以 member 登录后 GET /team/login?next=/team/lab | 303；Location 指向 /team/lab | 是 | 已执行（通过） |
| L2-09 | 登录页开放重定向 | 已登录 GET /team/login?next=//evil.example | 303；Location 不含 evil.example，落在 /team/lab | 是 | 已执行（通过） |
| L2-10 | 退出缺 CSRF | 已登录 POST /team/logout（无 token） | 400/403，不得 303 | 是 | 已执行（通过） |
| L2-11 | 退出带 CSRF | 已登录 GET /team 取本站表单 token，再 POST /team/logout | 303；Location 含 /team/login；取不到 token 直接判失败（不 skip） | 是 | 已执行（通过） |

补充约定：

- L2-10/L2-11 的 CSRF token 优先取 HttpCase 暴露的 token，其次从已登录
  /web 页面的 odoo.csrf_token 解析；两者都拿不到时 L2-11 标记 skipped，
  并在报告中写明未验证正分支，不能把 skipped 当通过。
- L2 的断言只针对状态码、Location、JSON 字段与页面是否含标题；不硬编码
  分类、器件参数、库存数量等数据库内容。
- 如果模板/静态资源未齐（见第 6 节），HTTP 用例可能在渲染阶段 500；
  这是模块缺陷/未完成，不是测试本身失败，报告中必须单列。

### 3.3 L3 浏览器与人工检查（不自动化）

| ID | 检查项 | 前置 | 期望 |
|---|---|---|---|
| L3-01 | 视觉与响应式 | 隔离实例 + 模板/静态资源 | 欢迎、登录、仓库、详情在桌面与窄屏可读，无原生后台外壳混入 |
| L3-02 | 深链接与历史 | 直接打开 /team/lab/items/lcsc:C1、刷新、前进/后退 | 地址栏保持业务路径；刷新不丢状态；不跳 /odoo |
| L3-03 | 根级别别名 | root_aliases=1 | /login、/lab、/lab/items/... 可访问，页内链接保持根级别；关闭参数后根级别路径应 404（等价不存在），规范 /team 路径仍可用 |
| L3-04 | 权限页面 | 三个测试用户 | 403/400/404 页面有明确说明与返回入口，不出现白屏/堆栈 |
| L3-05 | 登录/退出闭环 | 正确账号与错误账号 | 登录成功回 next；退出后受保护页回登录页；刷新后会话状态正确 |
| L3-06 | CSRF 表单 | 页面包含退出表单 | 表单带 token；删掉 token 后退出被拒绝 |
| L3-07 | management Host 根入口 | 配置 management_host 且开启 | 仅该 Host 的 / 渲染欢迎页；/web、/odoo、edit/cedit 请求原样回退；未配置时不影响官网 |
| L3-08 | 未实现入口 | 欢迎页/导航 | 入库、领用、库位、记录只显示 planned/denied，不可点击执行业务 |

## 4. 权限矩阵

角色定义：

- 匿名：未登录/public user。
- 登录无角色：内部用户，仅 base.group_user。
- 角色用户：base.group_user + lab_catalog.group_lab_catalog_user +
  lab_workflow.group_lab_user（后端组已 imply 前者，测试仍显式加入三者，
  避免建出非内部用户）。
- 管理员：lab_workflow.group_lab_manager（imply operator -> user ->
  catalog user，并 imply catalog manager）。
- 系统管理员：仅 base.group_system（不属于实验室角色，单独列一行防止误判）。

| 身份 | 欢迎 /team | 登录 /team/login | 仓库 /team/lab | 详情 /team/lab/items/<key> | 会话 /team/api/session |
|---|---|---|---|---|---|
| 匿名 | 200 | 200 | 303 -> /team/login?next=... | 303 -> 登录（守卫先于 key 校验） | 200；ok=true；authenticated=false；三项权限 false |
| 登录无角色 | 200 | 303 -> next | 403 | 403 | 200；authenticated=true；三项权限 false |
| 角色用户 | 200 | 303 -> next | 200 | 200 或 404 | 200；can_catalog=true；can_lab=true；is_manager=false |
| 管理员 | 200 | 303 -> next | 200 | 200 或 404 | 200；三项权限 true |
| 系统管理员（仅 base.group_system） | 200 | 303 -> next | 200（can_catalog 走 base.group_system） | 200 或 404 | 200；can_catalog=true；can_lab=false；is_manager=false |

补充：

- 非法 itemKey 的 400 只在"已登录且有目录权限"时可达；匿名先 303，
  登录无角色先 403。
- 403 必须渲染 page_denied；不得用 303 回后台或 200 空页代替。
- 权限判定以服务端 has_group 为准；会话接口在前端只作导航提示。

## 5. 路由与回跳表

### 5.1 路由

| 规范路径 | 根级别别名 | 方法 | auth / CSRF | 匿名 | 已登录无目录角色 | 有目录角色 | 备注 |
|---|---|---|---|---|---|---|---|
| /team、/team/ | — | GET | public | 200 | 200 | 200 | 欢迎页；站点标题 |
| /team/login | /login | GET | public | 200 | 303 -> next | 303 -> next | 已登录不再显示表单；next 先 normalize |
| /team/logout | /logout | POST | public，csrf=True | 400/403（无 token） | 400/403（无 token） | 303 -> /team/login（有 token） | 成功后清 session |
| /team/lab | /lab | GET | public | 303 -> /team/login?next=... | 403 | 200 | search_unified；参数 q/category_id/cursor/stock_only/limit |
| /team/lab/items/<item_key> | /lab/items/<item_key> | GET | public | 303 -> 登录 | 403 | 200 / 404 / 400（非法键） | 守卫 -> 校验 -> detail |
| /team/api/session | /api/team/session | POST | jsonrpc，public | 200 JSON | 200 JSON | 200 JSON | 不复制业务接口 |

### 5.2 基址选择

| 请求路径 | root_aliases=1 | root_aliases=0 |
|---|---|---|
| /team、/team/... | /team | /team |
| /login、/login/... | 空串（根级别链接） | /team |
| /logout、/logout/... | 空串（根级别链接） | /team |
| /lab、/lab/... | 空串（根级别链接） | /team |
| 其它（/web/login、/odoo、/） | /team | /team |

关闭 root_aliases 时，控制器的 root_alias_denied() 会让 /login、/logout、
/lab、/lab/items/... 直接返回 404（management Host 命中时除外）；这不是
重定向，不能用 303 代替。规范 /team 路径不受影响。

### 5.3 next 回跳判定

| 输入 next | 期望结果 | 说明 |
|---|---|---|
| /lab?q=abc | /lab?q=abc | 站内相对路径原样保留 |
| /team/lab/items/lcsc:C1 | 原样 | 合法业务冒号不能误拒 |
| //evil.com | 默认值 | 协议相对 URL |
| https://evil.com | 默认值 | 带 scheme |
| javascript:alert(1) | 默认值 | 非站内 |
| /\evil | 默认值 | 反斜杠 |
| /lab + NUL/中间控制字符 | 默认值 | 控制字符 |
| /%2f%2fevil.com、/%252f%252fevil.com | 默认值 | 百分号解码绕过 |
| None / 非字符串 / 空串 | 默认值 | 类型与空值 |
| /lab\r、/lab\n、/lab\t、/lab\x1f | 剥离尾部后为 /lab | 当前实现把尾部空白类控制符 strip 掉；安全，但与"一律回退"的措辞不同（见第 6 节） |

默认值有两处不同，测试需区分：

- 控制器守卫 redirect_to_login：默认 CANONICAL_BASE=/team（但实际传入了
  当前完整路径，正常不会用到默认）。
- 登录页 login()：默认 base + /lab（规范前缀下是 /team/lab）。

## 6. 已知缺口与风险（仅记录，不在本任务修复）

1. **阻塞级：模板/视图缺失。** 截至编写时静态检查：views/ 与 data/ 目录为空，
   manifest 引用的 views/pages.xml 不存在，pages.py 引用的
   lab_team_web.page_welcome / page_login / page_lab / page_detail /
   page_denied / page_detail_error 在仓库内未找到定义。按现状 Odoo 安装会
   该风险已消除：`views/pages.xml` 与静态资源已提交，页面路由可渲染（L2 11/11 通过）。改 XML 后必须 `-u lab_team_web` 才会生效，重启服务不等于升级视图。
   若并行任务随后补齐，须重新核对本文件并以实际文件为准。
2. **303 回原生动作不算完成。** 任何"跳回后台/跳回旧动作"都不能作为第一阶段
   完成证据；本计划只按状态码和页面断言，不把 303 当业务成功。
3. **浏览器视觉未验证。** 响应式、字体、空状态、错误提示、焦点与可访问性均
   未在真实浏览器检查；L3 未执行。
4. ~~Odoo HttpCase 本机未跑~~ → **已在私有 WSL 隔离环境执行并通过 11/11**；宿主 Windows 仍无 Odoo，L2 需在该隔离环境复跑。
   待执行契约，不能写成已通过。
5. **quote_item_key 非 ASCII 编码缺口。** 当前用 str.isalnum() 判断安全字符，
   中文会被原样保留（例如 lab:测试 -> lab:测试），而契约要求百分号编码。
   该缺陷已修复（ASCII 安全集 + UTF-8 百分号编码）；原 expectedFailure 已转为普通断言，
   修复后该用例会变成 unexpected success，应删除装饰器。
6. **400 错误页语义错位。** render_denied 只按 status==403 区分
   FORBIDDEN，其余一律 NOT_FOUND；非法 itemKey 的 400 页面会显示
   "无访问权限"/NOT_FOUND 文案，状态码仍是 400。需业务侧补 VALIDATION_ERROR
   分支；本任务只记录。
7. **normalize_next 与文档措辞差异。** 尾部 \r/\n/\t/\x1f 等被
   str.strip() 当作空白剥离后返回 /lab，而不是退回默认值；结果安全，但
   与"控制字符一律退回默认"的表述不完全一致。测试断言改为"结果不含控制
   字符"，不强制具体值。
8. **management Host 根入口未纳入本套件。** 新增的
   models/ir_http.py + paths.decide_root / normalize_host 等纯函数只在静态
   审阅中看过，本计划未写其单测；该入口默认关闭，启用前需补独立测试
   （Host 命中/不命中、edit/cedit 回退、非根路径回退、未配置不影响官网）。
9. **数据与配置依赖。** lcsc:C1 是否存在未知；root_aliases 默认值可被
   ir.config_parameter 改写；测试库若预置不同参数，别名用例前提需重设。
10. **未覆盖的页面行为。** 搜索关键词/分类/库存优先/游标分页只验证页面
    200，不验证结果正确性；这些属于 lab_catalog 的既有测试范围，本计划
    不重复造数据。
11. **CSRF 正分支可能 skip。** 取决于 Odoo 小版本是否暴露 token；skip 必须
    在报告中单列，不能计入通过。
12. **静态资源未纳入断言。** static/src/css/team.css、js/team.js 存在，但
    本计划不验证其加载、交互、XSS 转义或 CSRF 表单注入。

## 7. 执行命令与所需环境

### 7.1 L1：本机纯 Python

在仓库根目录执行：

    python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v

环境：Python 3.15（宿主）；不需要 Odoo、PostgreSQL、网络。**当前结果：65 通过 + 1 跳过**。
当前行为：test_paths.py 用例全部执行并通过；test_team_web_http.py 因缺 odoo 在导入阶段整体 skip（1 个 ModuleSkipped，不计通过）；中文编码用例已修复，不再是 expectedFailure。

### 7.2 L2：Odoo 19 隔离库

环境要求：

- Odoo 19 源码（记录实际 commit/tag）；addons-path 同时包含 Odoo 自带
  addons 与本仓库 server/ubuntu22.04/odoo_addons。
- PostgreSQL（与 Odoo 19 兼容的版本），仅使用专用测试库，禁止指向生产库。
- 已安装 lab_catalog、lab_workflow 及其依赖（stock/product/mrp 等）。
- 端口未被占用；测试库可随时重建，不要求保留业务数据。
- 不执行任何生产部署、模块卸载、DNS/代理修改或爬虫任务。

命令示例（尖括号为占位符，不写入真实凭据）：

    odoo-bin \
      --addons-path=<odoo>/addons,<repo>/server/ubuntu22.04/odoo_addons \
      -d <isolated_test_db> \
      -i lab_team_web \
      --test-enable --test-tags /lab_team_web:post_install \
      --http-port=18069 --stop-after-init --log-level=test

若模块已在测试库安装，用 -u lab_team_web 代替 -i；数据库连接参数通过
本机配置/环境变量提供，不写进文档或仓库。测试后保留命令、退出码、
测试计数与失败堆栈；必要时重建测试库复跑。

### 7.3 L3：浏览器人工检查

使用 7.2 的隔离实例，浏览器访问：

    http://127.0.0.1:18069/team
    http://127.0.0.1:18069/team/login
    http://127.0.0.1:18069/team/lab
    http://127.0.0.1:18069/team/lab/items/lcsc:C1

分别以匿名、无角色用户、角色用户、管理员登录检查第 3.3 节清单；
需要截图时只截测试数据，不包含真实凭据/个人信息。

## 8. 判定标准与证据

执行后的判定口径：

1. L1 全部用例通过，**不允许再有 expectedFailure**；若出现即视为缺陷回归（原 expectedFailure 已修复）；
   unexpected success，说明代码已修复，应删除装饰器并转为正式断言；其它
   失败必须定位为代码缺陷或测试缺陷，不得直接改断言掩盖。
2. L2 必须逐条满足状态码、Location、JSON 字段与"不得 500"；skipped 用例
   单独列出，不能折算为通过。
3. L3 按清单人工确认；视觉与交互不以 HTTP 200 代替。
4. 任何模板缺失、安装失败、500、权限误放行、开放重定向、CSRF 失效都视为
   阻塞缺陷，先修代码再复跑；测试计划与实现契约不一致时，先更新契约文档
   与用例，再改代码。
5. 证据至少包含：命令、执行时间、Odoo 版本/commit、PostgreSQL 版本、
   测试库名（非凭据）、退出码、测试计数、失败/跳过清单、必要截图。
   不记录密码、cookie、token、真实 odoo.conf 或数据库连接串。
6. 在隔离环境实际执行并核对证据之前，本计划不给出"通过/已验收"结论。
