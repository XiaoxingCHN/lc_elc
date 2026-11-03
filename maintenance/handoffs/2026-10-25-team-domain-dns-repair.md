# 交接：服务器 DNS 修复（2026-10-25）

## 结果

- `/etc/resolv.conf`：仅 nameserver 行由 `127.0.0.1` 改为 **`192.168.31.1`**（普通文件 644 root:root；
  原哈希 388b5f50…，新哈希 46607e45…）。
- 旧 `dnsmasq.service`：**disabled + 无进程（active=failed 未 reset）**，53 无监听；软件包/配置保留。
- 系统解析恢复；`acme-v02`/`acme-staging-v02` 的 `/directory` 均 **200 + TLS 校验通过**。
- nginx/odoo 仍 active；旧入口、`/team`、更新清单只读正常；IP/默认路由未变。

## 备份与回滚

`/var/backups/lc-elc/dns-resolv-20261025T2055Z`（0700）
- `resolv.conf.bak`（SHA256 388b5f50…，与原件一致）
- `resolv.conf.sha256`、`resolv.conf.bak.stat`（644 root:root）、`dnsmasq.state`（failed/enabled）

回滚：`sudo cp -a <备份>/resolv.conf.bak /etc/resolv.conf`。
如需恢复 dnsmasq 自启：`sudo systemctl enable --now dnsmasq`（**本批未做**，需另行授权）。

## 边界与未验证

- 手工指向路由器 DNS ≠ NM/DHCP 全自动管理；NM 仍是 `dns=systemd-resolved` 且 resolved 停用。
- **NM 在网络事件后是否重写 `/etc/resolv.conf` 未测**；若被改写，需按备份恢复或另议 NM 固化方案（审计第 11 节 2a）。
- `team.l-creation.club` 在服务器上解析为代理 fake-ip（当前 2001:2::5），非 192.168.31.105；
  这是既有 Meta 代理行为，未改；浏览器/内网客户端解析以各自环境为准。
- LE **生产账号与 TOS 未获答复**：未注册账号、未接受协议、未下订单、未签发证书、未启用 443。
- Nginx team vhost 与 Odoo `management_host` 参数**均未应用**（等待 Codex 对 EXECUTION_PLAN.md 的确认）。

## 下一步（待授权）

1. 用户对 LE 生产账号 + 当前 TOS 的答复 → 才能走 DNS-01 签发。
2. Codex 确认后按 `EXECUTION_PLAN.md` 原生命令应用 team vhost（80）与 `management_host`（ORM + signal）。
3. 证书就绪后再启用 443；续期仍手工（无 DNS API 凭据，不注册计划任务）。
