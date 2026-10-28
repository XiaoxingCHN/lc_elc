# team.l-creation.club 内网 HTTP 上线 · 审计（2026-10-25）

状态：**已完成**。仅新增 1 个 Nginx vhost + 1 条 Odoo 参数；未启用 443/HTTPS，未注册 ACME 账号，
未接受协议、未下单、未签证书；未改旧 odoo vhost、default_server、dbfilter、web.base.url、DNS/NM/路由。

## 1. 授权与使用文件

- 用户已要求开始域名迁移并保存目标A记录，既定流程包含服务器新域名与首页路径。Codex在此范围内决定先接通沿用现有内网HTTP的过渡入口；这是Codex的实施决定，不记录为用户单独确认过HTTP或逐文件审查。HTTPS仍等待LE账号/协议答复。
- 使用 Codex 已审查并批准执行的**唯一配置文件**：
  `local/build/team-domain-migration-20261025/nginx-team-http-approved.conf`
  SHA256 **`b86d8433eb120c8deb7c5ae3aef3ede8e980d4c34ac97581d2481dd3c77fdc66`**（2392 B）。
- 未使用已拒绝的 3 个 helper，未新增自写工具；全部系统原生命令。

## 2. 执行前硬门槛（全部通过）

| 项 | 实测 |
|---|---|
| 旧 vhost `/etc/nginx/sites-available/odoo` SHA256 | `3d64e8fe98fdedd3125e632f987a901dd5ce9becef0a4887f3e54364d3ed30fd`（与基线一致） |
| `sites-enabled/odoo` | 是符号链接 → `/etc/nginx/sites-available/odoo` |
| 服务 | nginx **active**（master PID 1092）、odoo **active**（MainPID 124857） |
| 两个 team 目标 | `sites-available/team-l-creation-club`、`sites-enabled/team-l-creation-club` **均不存在**（含 dangling） |
| 父目录 | `readlink -f` 均为真实目录，无逃逸 |
| Odoo 参数 | 仅 `root_aliases=0`；`management_host`、`management_host_enabled` **均未设置** |
| 其它 | 443 无监听；DNS `192.168.31.1`；dnsmasq failed+disabled |
| 待部署文件 | 上传私有暂存后服务器复算 SHA256 **与批准值一致** |

## 3. 项目备份（唯一 0700）

目录：`/var/backups/lc-elc/team-http-20261025T2102Z`（0700 root:root；父目录真实路径校验通过）

| 文件 | SHA256 |
|---|---|
| `odoo-vhost.conf`（旧配置副本） | **`3d64e8fe98fdedd3125e632f987a901dd5ce9becef0a4887f3e54364d3ed30fd`**（与原件一致） |
| `odoo-vhost.sha256` | `95e3d6730434a537801f7acdc054584435c9f446afbdcb3256fae4c05ebea657` |
| `odoo-enabled.target` | `2771ed901ed4eea92fe1b22b9285e5b3338defe1e638b9a645c941b62f32bc3d` |
| `odoo-enabled.ls` | `030707a22fd4c586dd5cdacc5a6afb40c1f6a969358118a579ff690f30fe2db2` |
| `attrs.txt` | `5aa6a3cb1203d1b1be0625211d18da5362850648e7f26ba740801e793c098c54` |
| `params-before.txt` | `c9c919eb4110a51c3868e938b4bbf152c542e7ec6bbf27ddf6f67e816b5893ae`（内容：`lab_team_web.root_aliases|0`） |

## 4. 实际变更

### 4.1 Nginx（只新增）

```bash
install -m 0644 <staging>/nginx-team-http-approved.conf /etc/nginx/sites-available/team-l-creation-club
ln -s /etc/nginx/sites-available/team-l-creation-club /etc/nginx/sites-enabled/team-l-creation-club
nginx -t && systemctl reload nginx
```

- `nginx -t` 通过；`reload` 成功；输出 `INSTALL_OK`（exit 0）。
- 已部署文件 SHA256 **`b86d8433…fdc66`**，与批准文件一致。
- **nginx master PID 仍 1092**（reload 只换 worker），未重启服务。

### 4.2 Odoo 参数（官方 shell，ORM + 显式 signal）

- 方式：`sudo -H -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin shell
  --config=/etc/odoo.conf -d LcHardwareHouse --no-http --data-dir=/opt/odoo/.local/share/Odoo`
  读取一次性脚本（私有暂存 0600）。
- 输出：`BEFORE exists=False value='<unset>' enabled='<unset>' root_aliases='0'` →
  `set_param('lab_team_web.management_host','team.l-creation.club')` → `env.cr.commit()` →
  `env.registry.signal_changes()` → `AFTER value='team.l-creation.club' root_aliases='0'`（exit 0）。
- 未改 `root_aliases`（仍 0）与 `management_host_enabled`（仍未设置，即默认启用）。
- **未重启 Odoo**。

## 5. 验收（服务端，多次独立 fresh CookieJar + Host header）

| 检查 | run1 | run2 | run3 |
|---|---|---|---|
| `/`（Host: team.l-creation.club） | 200 / 3876 B / `lc-body` | 200 | 200 |
| `/login` | 200 / 3902 B / 表单存在 | 200 | 200 |
| `data-db` | **LcHardwareHouse** | **LcHardwareHouse** | **LcHardwareHouse** |
| 匿名 `/lab` | **303 → /login?next=%2Flab** | 同 | 同 |
| 匿名 `/lab/items/lab:1` | **303 → /login?next=%2Flab%2Fitems%2Flab%3A1**（冒号保留） | 同 | 同 |
| `/team` 兼容路径 | 200 / 3921 B，链接仍 `/team/…` | 同 | 同 |

标题为「欢迎 · 力创实验室 · 战队仓库」；**未出现数据库选择页，未跳旧 Odoo 登录**。

### 旧入口基线（Host: lc.rm.com + X-Odoo-Database）

| 项 | 结果 |
|---|---|
| `/` | **200** / 40,230 B / `<title>Home | My Website</title>` |
| `/web/login` | **200** |
| `/lab`、`/login` | **404**（root_aliases=0 保持） |
| `/lab/scan` | **303** |
| 更新清单 `/lab/client/updates/manifest?platform=android&arch=universal&channel=stable` | **200** / 1826 B / SHA256 **`152d47ae1145b8c81200409a5af4e47b952e1ec1dcbe8d10c4105959a945cb65`** |

### 未变化的基线

- `nginx` master **1092**、`odoo` MainPID **124857**（均未重启）。
- 443 **无监听**；DNS `nameserver 192.168.31.1`；dnsmasq **failed + disabled**、无进程。
- 库存只读：quant **2** / 数量 **0.00** / 预留 **0.00** / move **1** / product **2** /
  active bag **1** / operation line **1** / 未归还领用 **0**；已安装模块 **55**。
- `lab_team_web 19.0.1.0.0` 源文件 **18** 个，合并 SHA256
  **`ba6d7b87f6160387181bdedef8c8243ccc710c4ac80867d4f6fc1f73605c4419`**（与上线时一致，未写入）。

## 6. 明确不声称

- **HTTPS 未启用**（443 关闭）；LE 生产账号与当前 TOS **未获答复** → 未注册账号、未接受协议、未下订单、未签证书；
  未自签、未忽略 TLS 告警。
- 真实用户完整登录流程**未测**（未创建测试账号、未伪造 session）。
- VPN 跨网访问**未测**；内网客户端 DNS 可能得到代理 fake-ip（服务端当前 team 解析为 `2001:2::5`），
  真实 LAN 域名验收由 Codex 从客户端独立进行。
- NM 在网络事件后是否重写 `/etc/resolv.conf` 仍未测。
- 续期自动化未实现。

## 7. 回滚

```bash
# 1) 下线新 vhost（只删本次新增链接，先校验指向）
readlink -f /etc/nginx/sites-enabled/team-l-creation-club   # 必须是 sites-available/team-...
sudo rm -f /etc/nginx/sites-enabled/team-l-creation-club
sudo nginx -t && sudo systemctl reload nginx

# 2) 参数回滚（快照为"未设置" → unlink）
sudo -H -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin shell \
  --config=/etc/odoo.conf -d LcHardwareHouse --no-http --data-dir=/opt/odoo/.local/share/Odoo <<'PY'
ICP = env['ir.config_parameter'].sudo()
ICP.set_param('lab_team_web.management_host', False)
env.cr.commit()
env.registry.signal_changes()
print('restored =', ICP.get_param('lab_team_web.management_host', '<unset>'))
PY
```

- 不删旧 odoo 配置、不恢复全库、不动 DNS/NM/路由/VPN/模块。
