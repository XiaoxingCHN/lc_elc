# 交接：team.l-creation.club 内网 HTTP 上线（2026-10-25）

## 结果

- **内网 HTTP 入口已接通**：新增独立 vhost `team.l-creation.club`（80），
  文件 SHA256 `b86d8433…fdc66`（与用户批准一致）；`nginx -t` 通过并 reload（master PID 1092 未变）。
- Odoo 参数 **`lab_team_web.management_host=team.l-creation.club`** 已通过官方 shell 设置，
  commit + 显式 `registry.signal_changes()`；`root_aliases` 保持 **0**，`management_host_enabled` 未设置。
- 验收：新 Host `/` 200（自有欢迎页）、`/login` 200 且 `data-db=LcHardwareHouse`、
  `/lab` 与详情匿名 303 回 `/login` 且 `next` 保留冒号、`/team` 200 且链接仍 `/team`；
  三次独立 fresh CookieJar 结果一致（已跨 worker 生效）。
- 旧入口不变：`/` 200（旧官网）、`/web/login` 200、`/lab`/`/login` 仍 404、`/lab/scan` 303、
  Android 更新清单 200/1826 B/SHA256 `152d47ae…5cb65`。
- 未变：nginx master、odoo MainPID、443 关闭、DNS `192.168.31.1`、dnsmasq disabled、
  库存计数与模块版本、18 源文件哈希。

## 备份与回滚点

`/var/backups/lc-elc/team-http-20261025T2102Z`（0700）
- `odoo-vhost.conf` SHA256 `3d64e8fe…30fd`（与原件一致）
- `odoo-vhost.sha256` / `odoo-enabled.target` / `odoo-enabled.ls` / `attrs.txt` / `params-before.txt`
  （params 快照：仅 `root_aliases=0`）

回滚：删 `sites-enabled/team-l-creation-club` 软链（先校验指向）→ `nginx -t` → `reload`；
参数用 shell `set_param(..., False)` + commit + signal 恢复"未设置"。

## 未完成 / 待授权

1. **HTTPS 未启用**：等用户对 LE 生产账号与当前 TOS 的答复；未注册账号/未接受协议/未下单/未签证书。
2. 真实用户登录、VPN 跨网、LAN 客户端域名解析未测（服务端由 Codex 从真实 LAN 复核）。
3. 续期自动化未实现（无 DNS API 凭据，未注册计划任务）。
4. NM 重写 `/etc/resolv.conf` 的可能性未验证。

## 关键文件

- 审计：「maintenance/audit/team-domain-http-deploy-20261025.md」
- 批准 vhost：「local/build/team-domain-migration-20261025/nginx-team-http-approved.conf`
- 执行 runbook（后续 HTTPS 用）：「local/build/team-domain-migration-20261025/EXECUTION_PLAN.md`
