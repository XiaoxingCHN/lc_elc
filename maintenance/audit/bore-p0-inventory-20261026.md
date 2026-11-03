# P0 盘点与恢复交接 · 审计（2026-10-26）

阶段：方案 **P0**（盘点与恢复交接）。**只读**，未改任何生产配置/DNS/网络，未安装软件。
证据：`local/build/bore-p0-20261026/inventory.json`。

## 1. HTTPS 最终审计（补回上次断线缺失部分）

| 项 | 实测 |
|---|---|
| team vhost 当前 SHA256 | **`b7df809d04ab19b8888b9668759e387a9516950ae508728876b0d1b349413040`** |
| 旧 lc.rm.com vhost SHA256 | `3d64e8fe98fdedd3125e632f987a901dd5ce9becef0a4887f3e54364d3ed30fd`（未变） |
| nginx master / odoo MainPID | **1092 / 124857**（未重启） |
| 443 监听 | **有**（1 个） |
| 证书（TLS 握手读取公开信息） | CN=team.l-creation.club；issuer=Let's Encrypt YR2；有效期 2026-10-25 13:22:48Z → **2027-01-23 13:22:47Z**；SAN=team.l-creation.club；SHA256 指纹 `8707d3cf…2526a` |
| 校验 | **Verify return code: 0 (ok)**，TLSv1.3 |
| 证书文件读取 | **被 DSH 安全策略拒绝（.pem 敏感路径），未重试、未绕过**；改用正常 TLS 握手读取公开证书信息 |

三份项目备份（均为 0700、内容与哈希已复核）：

| 目录 | 关键内容 | SHA256 |
|---|---|---|
| `/var/backups/lc-elc/team-http-20261025T2102Z` | odoo 旧 vhost、链接元数据、参数快照 | `3d64e8fe…30fd` |
| `/var/backups/lc-elc/team-login-fix-20261025T2142Z` | 修复前 team vhost | `b86d8433…fdc66` |
| `/var/backups/lc-elc/team-https-20261025T2226Z` | HTTPS 前 team vhost | `e3674661…d1e6` |

证书为**手动 DNS-01 签发，无自动续期**（未注册任何 timer/cron，未创建 DNS API 凭据）。

## 2. 数据库与模块

- 数据库：**LcHardwareHouse 2600 MB**、`lc_hardware` 23 MB；已安装模块 **55**。
- lab_catalog 19.0.2.0.4 / lab_inventory 19.0.1.0.0 / lab_workflow 19.0.1.2.0 /
  lab_theme 19.0.1.0.2 / lab_site 19.0.1.0.0 / **lab_team_web 19.0.1.0.0**；
  lab_portal uninstalled；website installed；website_sale uninstalled；portal installed。
- website 规模：1 个站点、**6 个页面**、19 个 website 视图；
  依赖 website 的已安装模块：**lab_site、theme_default、website_mail、website_sms**（P5 退役必须逐个审计）。

## 3. 路由与客户端调用（源码证据）

- 路由装饰器 **38 个**（lab_team_web 6、lab_workflow 25、lab_catalog 7），与方案阶段盘点一致。
- 自有 UI 现有路径：`/team`、`/team/login`、`/team/logout`、`/team/lab`、`/team/lab/items/<key>`、`/team/api/session`（含根级别名）。
- 旧调用点（公网收敛前必须迁移）：
  - EDA `plugins/jlc-eda/src/main/panel.js:84` 仍生成 `/odoo/action-*` 链接；
  - Flutter `clients/app/lib/providers/products_provider.dart:23` 仍用 `search_read`（底层 `/web/dataset/call_kw`）。

## 4. Nginx vhost 现状

| vhost | listen | server_name |
|---|---|---|
| default-catchall | 80 default_server | `_` |
| odoo | 80 | lc.rm.com |
| team-l-creation-club | 443 ssl（80 → 308） | team.l-creation.club |

`default-catchall` 为已存在的兜底 server（来源与用途未核实，P1 前需确认，不擅自删改）。

## 5. 站点参数（只读）

- `lab_team_web.management_host=team.l-creation.club`、`root_aliases=0`、`management_host_enabled` 未设置（默认启用）。
- **`web.base.url=http://team.l-creation.club`** —— HTTPS 已启用但该参数仍是 http，
  会影响 Odoo 生成的链接/邮件；属 P2 前应评估的最小修正项（改动影响旧客户端，未擅自修改）。

## 6. 公网节点可行性（只读探测，未安装 bore）

| 项 | 结果 |
|---|---|
| 生产是否已装 bore | 否 |
| 生产解析 bore.pub | `2001:2::20`（Meta fake-ip） |
| 生产 HTTPS 访问 bore.pub | **000（超时，走代理路径失败）** |
| 生产 TCP 到真实节点 | `159.223.110.159:7835` **OPEN**、`:443` **OPEN**、`bore.pub:7835` **OPEN** |
| 本机 Windows | `bore.pub:443` 不通、`bore.pub:7835` 通；本机未装 bore |
| 标准 443 入站 | **未知**（无外部验证、无端口映射审计） |

结论：**出站 7835 可用**，说明隧道客户端具备基本连通条件；但公共节点是否稳定、能否提供标准 443、
真实访客 IP 如何保留均未验证，不能据此承诺"免费+标准443+稳定"。

## 7. P1 前需要决策（阻塞）

1. 节点选择：公共 `bore.pub` 还是自建/受控节点？是否接受非 443 端口。
2. 来源 IP：是否必须保留真实访客 IP（PROXY protocol），以及 Odoo 登录限速按 remote_addr 计数的处理。
3. 管理员维护入口：是否保留独立内网入口（不经公网转发）。
4. 灰度策略：先只读（P2）还是直接排 P3 写业务。
5. `web.base.url` 是否调整为 https（会影响旧客户端链接）。
6. `default-catchall` 兜底 vhost 的归属与保留策略。

## 8. 未做 / 未验证

- 未安装 bore、未开公网端口、未改 DNS/防火墙/路由/Nginx/Odoo 参数。
- 未做真实公网登录、PROXY 链路、并发/写操作、限速实验、卸载演练。
- 证书自动续期未实现；`.pem` 文件按策略未读取。
