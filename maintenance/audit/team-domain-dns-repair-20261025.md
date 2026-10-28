# 服务器 DNS 修复（改用路由器 DNS）· 审计（2026-10-25）

状态：**已按用户明确授权执行完毕**。仅两处动作：改 `/etc/resolv.conf` 的 nameserver、停用旧 `dnsmasq`。
未改服务器 IP/DHCP/路由/VPN/NetworkManager，未重启网络服务，未动 Nginx/Odoo 参数，未注册 ACME 账号。

## 1. 用户授权原文要点

1. 「允许服务器改用路由器DNS」——授权备份后**仅把 nameserver 127.0.0.1 改为 192.168.31.1**，
   不改 IP/DHCP/路由/VPN/NetworkManager，不重启网络，验证失败还原。
2. 「你可以停掉服务器上自己的dns服务器了」——授权停用旧 dnsmasq。

## 2. 执行前只读复核（硬门槛）

| 项 | 结果 |
|---|---|
| `/etc/resolv.conf` 类型 | **普通文件**，非符号链接 |
| 权限/属主 | `644 root:root`，21 B，inode 5374158 |
| `lsattr` | `--------------e-------` → **无 immutable** |
| 内容 | `nameserver 127.0.0.1`（与预期一致，未被他人改动） |
| 原 SHA256 | **`388b5f50173389e3c7648e1c2180883dd1c27ae7739f7b9f9de82b293f3a3b6f`** |
| `192.168.31.1` 解析 | acme-v02→198.18.0.4；team.l-creation.club→198.18.0.8；lc.rm.com→192.168.31.105（rc=0） |
| 基线服务 | nginx **active**、odoo **active** |
| 基线监听 | 53 **无监听**；8069 监听正常 |
| 基线网络 | enp0s31f6 `192.168.31.105/24`；默认路由 `via 192.168.31.1 … proto dhcp` |
| dnsmasq | 单元 `/lib/systemd/system/dnsmasq.service`，**active=failed / enabled** |

## 3. 备份（唯一、已验证）

目录：`/var/backups/lc-elc/dns-resolv-20261025T2055Z`（**0700 root:root**；
父目录 `/var/backups/lc-elc` 经 `readlink -f` 校验为真实目录、非符号链接；目录名此前不存在）

| 文件 | 内容 |
|---|---|
| `resolv.conf.bak` | 原文件副本，SHA256 **`388b5f50…a3b6f`**（与原件逐字节一致） |
| `resolv.conf.sha256` | 记录原文件哈希 |
| `resolv.conf.bak.stat` | 副本属性：`644 root:root` |
| `dnsmasq.state` | `active=failed`、`enabled=enabled`（停用前状态，供恢复参考） |

> 说明：首次命令因 `grep -v` 过滤导致退出码 1 误报"备份失败"，随后核对目录内容：
> 副本与原件 SHA256 完全一致、状态文件齐全，备份有效，故未重建目录（避免复用/重名）。

## 4. 实际变更（仅一行）

- 只替换 `nameserver 127.0.0.1` → `nameserver 192.168.31.1`；
  **保留其余行**（当前文件无 search/options）；以「临时副本 + `cat > /etc/resolv.conf`」写入，
  **保持 inode/属主/权限**（仍是普通文件 644 root:root）。
- `diff` 备份 vs 现在：**仅 1 行变化**（1c1）。
- 新 SHA256：**`46607e45205411140c910740991c74e9a8d208c199e45ec327f8ed7ffa5e2002`**。

## 5. 验证（正常系统解析，未用 --resolve/-k）

| 项 | 结果 |
|---|---|
| `getent hosts acme-v02.api.letsencrypt.org` | **2001:2::4**（代理 fake-ip，非 LE 真实 IP） |
| `getent hosts team.l-creation.club` | **2001:2::5**（同为代理 fake-ip） |
| `getent hosts lc.rm.com` | **192.168.31.105**（正确指向本机） |
| `curl https://acme-v02.api.letsencrypt.org/directory` | **http=200，ssl_verify_result=0**，remote 198.18.0.4 |
| `curl https://acme-staging-v02.api.letsencrypt.org/directory` | **http=200，ssl_verify_result=0** |

结论：**系统解析恢复，公网 ACME 端点 TLS 校验正常**（经既有 Meta 代理/fake-ip 出网；
未改 Meta、未加 hosts、未固定公网 DNS）。

## 6. 停用旧 dnsmasq（保留软件包与配置）

- 执行：`systemctl disable --now dnsmasq`（移除 `multi-user.target.wants` 下的自启链接），
  随后 `systemctl stop dnsmasq` 确保无进程。
- 结果：**`disabled`**；`active=failed`（原就是 failed，未做 reset-failed，符合"不必为漂亮状态重置"）；
  **进程数 0**；**53 无新增监听**。
- 未执行：purge/删除配置、stop NetworkManager/systemd-networkd/systemd-resolved/Meta/Docker、
  未杀同名进程、未启动旧 DNS 或内网 CA。

## 7. 变更后健康（只读）

| 项 | 结果 |
|---|---|
| nginx / odoo | **active / active** |
| 旧入口 `/`（Host lc.rm.com + X-Odoo-Database） | **200** |
| 旧 `/web/login` | **200** |
| `/team`（同头） | **200** |
| 更新清单 `/lab/client/updates/manifest?platform=android&arch=universal&channel=stable` | **200**，1826 B，SHA256 `152d47ae…5cb65`（与之前一致） |
| 接口 IP / 默认路由 | `192.168.31.105/24` / `via 192.168.31.1 … proto dhcp` **未变** |

## 8. 明确不声称

- 这是**手工把服务器 DNS 指向路由器地址**；路由器上游 DNS 仍自动，但**不是**"已实现 NM/DHCP 全自动管理"。
- NetworkManager 仍为 `dns=systemd-resolved`、resolved 仍 disabled；**NM 在网络事件后是否会重写
  `/etc/resolv.conf` 未验证**。
- 未获得 LE 生产账号/TOS 答复 → **未注册账号、未接受协议、未申请订单、未签发证书**。
- 未改 Nginx（team vhost 未安装）、未改 Odoo 参数、未启用 443。
- 续期自动化**未实现**，未注册任何 cron/timer。

## 9. 回滚

```bash
# 仅回滚 resolv.conf（不改其它）
sudo cp -a /var/backups/lc-elc/dns-resolv-20261025T2055Z/resolv.conf.bak /etc/resolv.conf
cat /etc/resolv.conf
# 如需恢复 dnsmasq 自启（本次未做，需另行授权）：sudo systemctl enable --now dnsmasq
```
