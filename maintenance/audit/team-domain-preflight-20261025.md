# team.l-creation.club 内网/VPN 迁移 · 只读预检 v2（2026-10-25）

状态：**仍为只读预检，未做任何生产写入**。本版按 Codex 审查修正 B1/B3/B4，修复候选脚本问题。
未读取/未重试被安全网拒绝的证书文件，也未要求任何工具绕过该拒绝。

## 1. 网络诊断：是 DNS 坏了，不是出口被封（修正 B1）

| 检查（只读） | 结果 |
|---|---|
| `/etc/resolv.conf` | `nameserver 127.0.0.1`（未修改） |
| 本机 53 | **无监听**（0.0.0.0:53 / 127.0.0.1:53 均无） |
| `getent hosts acme-v02.api.letsencrypt.org` | **无结果**（DNS 解析失败） |
| `curl --resolve acme-v02…:443:172.65.32.248 https://acme-v02…/directory`（正常 TLS 校验，无 -k） | **http=200，ssl_verify_result=0，exit=0** |
| `curl --resolve acme-staging-v02…:443:172.65.46.172 …/directory` | **http=200，ssl_verify_result=0，exit=0** |
| 直连 TCP `172.65.32.248:443` | **可连通** |

结论：**公网出口与 TLS 均正常**；失败原因是本机 DNS（127.0.0.1 无解析服务）。
因此 DNS-01 在网络层可行，但**运行 certbot 时需要能解析 ACME 域名**——可选：
(a) 仅为签发临时加两条 `/etc/hosts` 映射（用后删除，需单独批准；不改全局 DNS/路由/代理/隧道）；
(b) 修复本机解析（超出本任务范围）。

## 2. ACME 账号与客户端（修正 B3）

| 项 | 结果 |
|---|---|
| `/etc/letsencrypt/accounts` 一级目录 | `192.168.31.105`、`192.168.31.105:9000`、`acme-staging-v02.api.letsencrypt.org` |
| 生产 LE 账号 `accounts/acme-v02.api.letsencrypt.org/directory` | **不存在** |
| 测试 LE 账号 `…/acme-staging-v02…` | 存在，叶子账号目录 **1** 个 |
| 账号内文件 | **未读取**（不读 JSON/密钥/邮箱） |
| certbot | 1.21.0；插件 nginx / standalone / webroot |
| **manual 插件** | 磁盘存在 `certbot/_internal/plugins/manual.py`，可导入且 `Authenticator.perform` 存在 → **DNS-01 可用内置 manual，无需安装额外插件** |
| DNS-01 专用插件 | 未安装（本方案不需要） |
| 续期自动化 | 无 systemd timer；`/etc/cron.d/certbot` 带 `\! -d /run/systemd/system` 条件，本机有 systemd → 实际不续期 |

结论：**走公网 DNS-01 可行且只需 certbot 内置 manual**；但**没有生产 LE 账号**，
创建新账号须接受现行服务条款（TOS）——**需你明确授权**，我不会自行 `--agree-tos`。
续期在无 DNS API 凭据前**不自动**，只能手工（每 90 天），或后续由你放置 0600 凭据再谈自动化。

## 3. 证书结论（修正 B4）

旧证书 SAN 无法确认（读取被安全网拦截，且不绕过）→ **不复用旧证书**，
为 `team.l-creation.club` **独立签发新证书**；旧 lc.rm.com 证书与其内网 ACME 通道保持原样不动。

## 4. Nginx 候选修正（已更新文件）

- 每个 proxy location **显式重复完整公共头**（Host / X-Real-IP / X-Forwarded-For /
  X-Forwarded-Host / X-Forwarded-Proto / **X-Odoo-Database LcHardwareHouse**），
  不再依赖 server 级继承（`/websocket` 会设置 Upgrade/Connection，继承会失效）。
- `/websocket` 增加 `proxy_http_version 1.1` 并显式写 Upgrade/Connection。
- 静态资源改为 `location ^~ /web/static/`，去掉无锚正则，避免误匹配。
- 仍不加 default_server，不影响 lc.rm.com；443 段留注释，待证书。

## 5. apply/rollback 候选修正

- 备份**分离**：`odoo-vhost.conf`（真实内容）+ `odoo-vhost.sha256`（校验）+
  `odoo-enabled.target`/`odoo-enabled.ls`（链接指向与元数据），不再两次写同名文件。
- 备份任一步失败（`cp`/`readlink`/`sha256sum`/`sha256sum -c`）**立即终止**，不用 `|| true` 掩盖。
- 首次部署：`sites-available` 与 `sites-enabled` 两个目标**都必须不存在**才继续；`ln -s` 不用 `-sfn`。
- 备份根、目标父目录做 **readlink -f 边界校验**（必须等于自身，拒绝符号链接逃逸）；
  时间戳备份目录已存在则拒绝复用。
- `nginx -t` 或 `reload` 失败：`trap ERR` 移除本次新增的 enabled/avail，再验证 `nginx -t`
  与 `nginx is-active`，并打印结果（不静默）。
- rollback：先校验 enabled 是符号链接、指向本次 avail、且 avail 内容含
  `server_name team.l-creation.club` 与 `X-Odoo-Database LcHardwareHouse`，才移除；
  不盲删、不动旧 odoo vhost。

## 6. 参数候选修正（缓存与跨 worker）

- 脚本不再假设 cwd 进 `sys.path`：必须 `--odoo-root` 显式导入；去掉 `report_configuration`。
- 只处理 `lab_team_web.management_host`；`root_aliases 保持 0`。
- 若 `management_host_enabled` 原值为 0 → **先报告并退出**（需 `--force-enabled` 才继续），不暗改。
- **跨 worker 信号**：Odoo 19 的 `Cursor.commit()` 只跑 `postcommit`，不会自动发
  registry/cache 信号；HTTP 请求在 `service/model.py` 收尾调用 `registry.signal_changes()`，
  而独立脚本必须在 commit 后**显式** `registry.signal_changes()`（实现为向
  `orm_signaling_<cache>` 插入行）。候选脚本已按此实现，并在提交后重新读取参数核对。
- 提供 `--restore`：旧值为空 → `set_param(KEY, False)`（unlink）；否则写回旧值；同样 commit + signal。
- 当前参数实况：仅 `root_aliases=0` 存在；`management_host` 与 `management_host_enabled` **未设置**
  （后者代码默认 1，即启用；脚本会打印实际值）。

## 7. 最小应用方案（待批准；执行命令见 EXECUTION_PLAN.md）

具体命令已改为**短小、可逐条人工审查的原生命令**，见
`local/build/team-domain-migration-20261025/EXECUTION_PLAN.md`（本回合未执行）：

1. 只读快照：旧 vhost sha256 与 enabled 链接指向、Odoo 三个参数的存在性/值。
2. 新增 team vhost（80）：`install` + `ln -s`（不用 -sfn）+ `nginx -t` + `systemctl reload`；
   目标已存在、旧 vhost 哈希变化、`nginx -t` 失败 → 立即停止；失败则删除本次新增链接并复验。
3. Odoo 参数：用官方 `odoo-bin shell` 的 env 执行 `set_param` → `commit` → `registry.signal_changes()`；
   写前记录旧值**与存在性**（当前快照：management_host 不存在），回滚按快照恢复（不存在则 unlink）。
   不改 `root_aliases=0`、不改 `management_host_enabled`。
4. DNS（如获用户额外授权）：检查文件属性 → 备份 → 只换 nameserver 行 → 验证 → 失败 `cp -a` 还原。
5. TLS：DNZ 可用后 `certbot certonly --manual --preferred-challenges dns`（新生产账号 + TOS 需授权，
   TXT 由用户在阿里云手工添加）；启用 443 段；**续期不自动化**，不注册 cron/timer。

### 7.1 本目录 helper 状态

«apply-team-vhost.sh»、«rollback-team-vhost.sh»、«set-management-host.py» 均标为
**「未采用 / 禁止执行」**：分别存在"误判原有 enabled 为 symlink"、"备份校验对象错误"、
"«--restore» 使用执行时 current 而非写前快照"等缺陷；保留仅作记录，实际执行改用第 7 节的
原生命令（EXECUTION_PLAN.md）。

## 8. 阻塞项（更新）

| 编号 | 状态 | 需要 |
|---|---|---|
| B1 | **已澄清**：出口正常，仅本机 DNS 不可用 | 签发时是否允许临时 `/etc/hosts` 两条（用后删）；或先修本机解析 |
| B2 | 内网 ACME `:9000` 未运行（旧证书续期当前不可用，与本变更无关） | 由你方另行决定，本任务不动 |
| B3 | manual 插件可用，无需装软件；**无生产 LE 账号** | 是否授权新建 LE 生产账号并接受 TOS；TXT 由你手工添加 |
| B4 | 旧 SAN 无法确认 | 结论：**独立新证书，不复用** |
| B5 | 续期无自动化 | 明确「未实现」，需 0600 API 凭据或人工每 90 天 |

## 9. 未做 / 不声称

- 未改 Nginx、未 reload、未改参数、未申请证书、未装软件、未注册计划任务。
- 未改 DNS/代理/防火墙/VPN/53 服务；未动 website/旧模块/业务代码/库存。
- 未声称 HTTPS 已可用；未声称旧证书覆盖 team 域名。


## 10. 服务器 DNS 现状与最小修复提议（需用户另行授权，未执行）

### 10.1 实测事实

| 项 | 结果 |
|---|---|
| «/etc/resolv.conf» | **普通文件**（非 symlink），«root:root 644»，21 B，内容仅 «nameserver 127.0.0.1»，**无 search/options 行** |
| «127.0.0.1:53» | **connection refused**（无监听） |
| 本地解析器 | «dnsmasq.service» **enabled 但 failed**（2026-10-22 10:22:29 CST，exit 2/INVALIDARGUMENT），即 resolv.conf 指向的 127.0.0.1 早已不可用 |
| 解析器归属 | «systemd-resolved» inactive+disabled；«NetworkManager» **enabled+active**（netplan «01-network-manager-all.yaml»，renderer=NM）；«systemd-networkd» active 但 disabled；存在 «/run/NetworkManager/resolv.conf»（NM 自己生成的文件）；«/run/systemd/resolve/resolv.conf» 不存在 |
| 代理/网络形态 | 存在 «Meta» 接口 «198.18.0.1/30»（Clash.Meta TUN，fake-ip 网段），不是本任务要改的服务 |
| 直连上游 | «dig +time=2 +tries=1 @223.5.5.5» 与 «@1.1.1.1» 对两个 ACME 域名均 **rc=0 有应答**，答案均为 fake-ip «198.18.0.4/198.18.0.5» |
| fake-ip 连通性 | 按 fake-ip 用 «--resolve» 访问 LE «/directory» → **200、TLS 校验通过** |

结论：**上游 DNS 可达、代理出口可用**；唯一断点是本机 «127.0.0.1:53»（dnsmasq 挂了），
而 «/etc/resolv.conf» 仍指向它。这也解释为何 Codex 从 1.1.1.1（外部视角）看到的是真实 LE IP
（172.65.32.248），而本机经上游拿到的是 proxy fake-ip（198.18.0.x）——两者都能通。

### 10.2 最小修复选项（三选一，均需你向用户申请范围授权）

| 选项 | 做法 | 影响面 | 风险/注意 |
|---|---|---|---|
| **A（任务最小）** | 仅为签发临时在 «/etc/hosts» 加两行 ACME 域名→可用 IP（真实 172.65.x 或 fake-ip 198.18.0.x），签发后删除 | **同属全局主机解析配置**（只是影响时长短、可逆） | **更正**：此前"不改全局 DNS"的说法不准确；«/etc/hosts» 与 «resolv.conf» 都是全局主机解析配置，均需用户授权 |
| **B（修好服务器 DNS）** | 把 «/etc/resolv.conf» 的 «nameserver» 改为可用上游（«223.5.5.5»、«1.1.1.1»），保留文件其余内容 | **全局网络配置**，影响所有解析 | NM 处于 active/enabled，网络重连时可能重写该文件；须用 NM 配置固化才持久 |
| **C（修根因）** | 诊断并恢复 «dnsmasq»（它本应提供 127.0.0.1:53） | 影响本机所有 DNS | 属「其它服务」，需单独授权；失败 3 天可能另有配置原因 |

**推荐**：本次签发走 **A**（不碰全局）；若要长期修复选 **C** 或 **B**（并固化到 NM）。

### 10.3 备份与回滚策略（若选 B）

1. 备份：«cp -a /etc/resolv.conf /var/backups/lc-elc/dns/resolv.conf.<UTC>»（«0700» 目录、保留属主与权限）。
2. 修改：只替换/新增 «nameserver» 行，**保留 search/options**（当前文件无这两项，若有必须原样保留）；
   建议两个上游，主备顺序 «223.5.5.5» → «1.1.1.1»。
3. 验证：«dig +time=2 +tries=1 @127.0.0.1 acme-v02.api.letsencrypt.org»（若仍走本地）
   或直接 «getent hosts»；再 «curl https://acme-v02.api.letsencrypt.org/directory» 期望 200。
4. 回滚：«cp -a /var/backups/lc-elc/dns/resolv.conf.<UTC> /etc/resolv.conf»（不重启任何服务）。
5. 注意：NM 可能在网络事件后重写；若发生，应改由 NM（«nmcli con mod … ipv4.dns …»）持久化，属另一变更。

### 10.4 明确边界

- 本轮**未修改** «/etc/resolv.conf»、未动 netplan/NM/dnsmasq/路由/VPN/DNS 服务、未重启任何服务。
- 上述任何一项落地都需要用户对「全局网络配置」的额外授权；本任务当前仍只读。
- **«/etc/hosts» 临时映射不是"非全局"方案**：它同样改变本机全局主机解析，只是可逆、影响时长短。
- 修 DNS 前必须先确认：文件是否 symlink、权限/属主、备份成功、NetworkManager 是否会在网络事件后重写
  （本任务**未验证** NM 重写时机）；任一步失败按备份 «cp -a» 还原，不重启网络服务。
- 续期自动化**未实现**：不注册 cron/timer，不创建 DNS API 凭据。

## 11. DNS 归属实测（用户澄清"已关掉路由器指定 DNS、改自动 DHCP"之后）

> 用户澄清：旧 DNS 是挂在本机的解析服务，路由器侧指定 DNS 已关闭、改为自动获取 DHCP；
> **要求不恢复旧 dnsmasq / 内网 CA / DNS 服务，也不默认推进固定 223.5.5.5 方案。**
> 旧"把 resolv.conf 固定为 223.5.5.5/1.1.1.1"方案据此**作废/被替代**，仅保留为历史记录。

### 11.1 实测（只读）

| 项 | 结果 |
|---|---|
| 承载 192.168.31.105 的接口 | **«enp0s31f6»**（dynamic），NetworkManager 连接名 **«有线连接 1»** |
| 该连接 ipv4 字段 | «ipv4.method=auto»、«ipv4.dns=»（空）、«ipv4.ignore-auto-dns=no»、«ipv4.dns-search=»（空）、«autoconnect=yes» → **纯 DHCP，无静态 DNS** |
| DHCP 实际下发 DNS | «DHCP4.OPTION[4]:domain_name_servers = 192.168.31.105»（**就是本机自己**） |
| NM 的 DNS 模式 | 生效配置 «dns=systemd-resolved»（来自 «/usr/lib/NetworkManager/conf.d/10-dns-resolved.conf»），«/etc/NetworkManager» 下无覆盖 |
| systemd-resolved | **inactive + disabled** |
| «/run/NetworkManager/resolv.conf» | «nameserver 127.0.0.53» + «options edns0 trust-ad» → 指向已关闭的 resolved stub，**不可用** |
| «/etc/resolv.conf» | **普通文件** 644 root:root 21 B，内容仅 «nameserver 127.0.0.1»；«lsattr» 只有 extent 标志（**无 immutable**）；**不是 NM 托管**（NM 未替换它） |
| 网络下发的 DNS 可用性 | «dig @192.168.31.105» → **connection refused**（本机无 53 监听） |
| 网关自身 DNS | «dig @192.168.31.1 example.com» → **有应答**（198.18.0.7，rc=0）→ 路由器自身可解析 |
| 默认路由 | «default via 192.168.31.1 dev enp0s31f6 proto dhcp» |

### 11.2 结论（为什么"自动 DHCP DNS"当前不成立）

DHCP 把 DNS 指回**本机 192.168.31.105**，而本机已无 53 服务（dnsmasq failed，且用户明确不恢复）；
同时 NM 把 DNS 交给 **已停用的 systemd-resolved**（127.0.0.53），«/etc/resolv.conf» 又是无人托管的
静态文件（仍写 127.0.0.1）。三者叠加，导致任何依赖系统解析的程序都失败。
**这不是"改一个 nameserver 行"能回归的**，需要同时满足：网络下发一个真实可用的 DNS + 本机有消费它的组件。

### 11.3 最小具体方案（两层，均需用户授权；本任务未执行）

**第 1 层（用户/路由器侧，本机零改动）**：把 DHCP 下发的 DNS 从 «192.168.31.105» 改为
«192.168.31.1»（网关自身 DNS，实测可用）或路由器上游。这是"自动 DHCP DNS"能成立的前提。

**第 2 层（服务器侧，任选其一，均为全局网络配置，需授权）**：

| 选项 | 做法 | 影响 | 说明 |
|---|---|---|---|
| **2a（最少文件改动）** | 新增 «/etc/NetworkManager/conf.d/99-dns-default.conf»：«[main]» + «dns=default» + «rc-manager=file»，然后 **重启 NetworkManager**（或对应连接重激活） | 让 NM 用 DHCP 下发的 DNS 直接写 «/etc/resolv.conf» | 需重载 NM；不改 IP/网关/路由/DHCP 方式；不写静态 DNS |
| **2b（不动 NM 配置）** | 启用并启动 «systemd-resolved»（当前 disabled+inactive），使 127.0.0.53 stub 生效并向上游转发 | 多一个常驻 DNS 服务 | 用户已表示不要恢复"DNS 服务"，此项需明确同意 |

- 两者都**不需要**恢复 dnsmasq/内网 CA，也**不改成静态 IP/静态 DNS**；保留 «ipv4.method=auto» 与原路由。
- 若用户暂不愿意动路由器，也暂不愿意动 NM/resolved，则本任务的证书签发只能回到
  "临时全局主机解析映射（«/etc/hosts»，用完删）"——**同属全局配置**，需单独授权。

### 11.4 未验证边界（必须保留）

- «/etc/resolv.conf» 非 NM 托管，但 NM 在 DHCP 续约/网络事件时是否会替换它**未验证**；任何改动前须记录
  inode/哈希，改后复核；失败按备份 «cp -a» 还原。
- 用户"已关闭路由器指定 DNS"的说法与「DHCP 仍下发 192.168.31.105」存在时间差/未生效的可能，
  需在路由器侧复核 DHCP DNS 选项（本机只读已给出精确证据）。
- LE 生产账号/TOS 仍未获答复 → **不签发、不注册账号**。
