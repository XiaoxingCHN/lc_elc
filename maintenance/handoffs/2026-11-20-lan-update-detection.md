# 维护交接：内网加速后检测不到更新

- 服务器 `lc-nas`（192.168.31.105），Odoo 19，服务 `odoo.service`
- 客户端 1.3.5+25，已发布到应用内更新通道

## 现象

用户在内网加速状态下（客户端指向 `http://192.168.31.105:8069`）点「关于与更新」，
检测不到任何更新，而公网状态下能检测到。

## 根因

`/lab/client/updates/manifest` 是 `auth='none'` 的路由，Odoo 必须先确定数据库：

| 链路 | 数据库怎么来的 | 结果 |
|---|---|---|
| 公网 | Cloudflare Tunnel → nginx `18443`；`location /` 里写死 `X-Odoo-Database: LcHardwareHouse` | 200 |
| 内网 8069 直连 | **没有 nginx**，`/etc/odoo.conf` 既无 `db_name` 也无 `dbfilter` | **404** |

Odoo 返回的是 `No database is selected and the requested URL was not found`。

同一个原因也解释了之前那次「内网 `/web/login` 返回 303 跳到库选择器」——
当时我误以为是正常重定向，其实是同一个缺陷。

## 修法

```ini
# /etc/odoo.conf
dbfilter = ^LcHardwareHouse$
```

原文件已备份为 `/etc/odoo.conf.bak-20261120`。改后 `systemctl restart odoo`。

## 实测

| 目标 | 结果 |
|---|---|
| 内网 `http://192.168.31.105:8069/lab/client/updates/manifest?...` | 200 × 3 |
| 内网 `/web/health` | 200 |
| 内网 `/` | 200 |
| 公网 manifest | 200 × 3 |
| 公网 `/team/login` | 200 |

## 注意：排查时的两个假线索

1. **`curl -k https://127.0.0.1:18443/...` 会得到 404**——因为没发 SNI，请求落到了
   `default-catchall` 这个 `listen 443 ssl default_server` 的块（自签占位证书，
   `return 404`）。测 18443 必须带 `--resolve team.l-creation.club:18443:127.0.0.1`，
   但那条路本机的证书链又不认，所以用 `-H "Host: ..."` 也会落到 catch-all。
   **结论：不要用本机 curl 去判断 18443 的业务状态**，用公网域名或直接测 8069。
2. **公网 `https://team.l-creation.club/` 偶发 000**——Cloudflare Tunnel 链路抖动，
   改动前后都存在，与本轮无关。判断服务健康请用 `/web/health` 或 manifest 接口。

## 未验证

- 客户端在内网加速状态下点「关于与更新」的完整下载与安装流程（需实机）
