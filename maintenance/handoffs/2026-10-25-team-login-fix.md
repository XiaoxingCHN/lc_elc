# 交接：team 冷登录修复上线（2026-10-25）

## 结果

- team vhost 已更新为修复版 **e3674661…d1e6**（仅新增精确
  `location = /web/session/authenticate`，清空 `X-Odoo-Database`）。
- `nginx -t` 通过、`systemctl reload nginx` 成功（exit 0）；**nginx master 1092 / odoo 124857 均未重启**。
- 应用后只读验证：`/login` 200、无 session_id；旧站 `/`200、`/web/login`200、`/lab`/`/login` 404、
  `/lab/scan` 303、Android 更新清单 200/1826B/hash 一致；443 仍关闭。

## 备份与回滚

`/var/backups/lc-elc/team-login-fix-20261025T2142Z`
- `team-vhost.before.conf` SHA256 `b86d8433…fdc66`（副本一致）
- `team-vhost.before.sha256`、`team-enabled.ls`

回滚：`cp -a <备份>/team-vhost.before.conf /etc/nginx/sites-available/team-l-creation-club`
→ `nginx -t` → `systemctl reload nginx`（参数/数据库/其它 vhost 不动）。

## 前端静态核查（未改源码）

- 生产登录 HTML：脚本 1 开 1 闭、无自闭合/转义异常、`defer`、表单/`required`/提交按钮/错误节点齐全。
- 服务端 JS 34,613 B，SHA256 `1951e05a…7d93` 与冻结源一致；`node --check` 通过；
  `DOMContentLoaded→init→initLogin` 正常；未发现钩子缺失。

## 待办 / 未验证

1. 2026-10-25用户回复“可以了”，确认登录无反应已恢复；按用户复验记录，DSH/Codex未独立操作真实账号。
2. 刷新保持会话及退出未追加实测，未改前端；后续状态以[主交接](2026-10-25-team-login-cold-session.md)为准。
3. HTTPS 仍等 LE 账号/TOS；Netlify/公网主站未动；VPN 与移动端未测。
