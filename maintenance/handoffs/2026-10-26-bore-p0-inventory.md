# 交接：bore 公网入口与自有 UI · P0 完成（2026-10-26）

## 本轮结论

方案 **P0（盘点与恢复交接）已完成，全程只读**。上次断线缺失的 HTTPS 最终审计已补回：
当前 team vhost `b7df809d…3040`、旧 vhost `3d64e8fe…30fd`、nginx 1092 / odoo 124857 未重启、
443 已监听、证书 SAN/有效期/链校验正常（到期 **2027-01-23**）、三份项目备份目录与哈希齐全。

## 关键事实

- 库：LcHardwareHouse 2600 MB；模块 55；lab_team_web 19.0.1.0.0。
- website 仍被 4 个已安装模块依赖（lab_site/theme_default/website_mail/website_sms），P5 退役需审计。
- 路由 38 个；自有 UI 仅 6 条路由（欢迎/登录/退出/检索/详情/会话）。
- 旧调用未迁移：EDA `/odoo/action-*`（panel.js:84）、Flutter `search_read`（products_provider.dart:23）。
- **`web.base.url` 仍是 http://team.l-creation.club**（HTTPS 下会生成 http 链接，待评估最小修正）。
- 公网可行性：生产未装 bore；出站 TCP 7835/443 到节点 **OPEN**；经代理解析 bore.pub 为 fake-ip 且 HTTPS 超时；
  标准 443 入站未知。

## 阻塞与待决策

见审计第 7 节：节点选择（公共/自建、是否非 443）、真实访客 IP 与登录限速、管理员内网入口、
只读灰度顺序、`web.base.url` 是否改 https、`default-catchall` 归属。

## 下一步（P1，需确认后实施）

1. 按选定节点在**隔离环境**搭隧道（生产数据不参与），验证 TLS 透传与 Host/方法/路径白名单。
2. 验证真实访客 IP 方案（PROXY protocol）与限速不误伤。
3. P1 通过后才允许只读内网/公网试运行（P2）。

## 产物

- 审计：`maintenance/audit/bore-p0-inventory-20261026.md`
- 证据：`local/build/bore-p0-20261026/inventory.json`
- 方案：`docs/requirements/PUBLIC_ACCESS_AND_UNIFIED_UI_PLAN.md`

未改生产配置/DNS/网络，未安装软件，未推送 Git。
