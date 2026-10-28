# 交接：2026-10-27 P2 生产上线

## 状态

`lab_team_web 19.0.1.0.5` 与 `lab_catalog 19.0.2.0.5` **已在生产 LcHardwareHouse 上线**，服务 active、TLS 登录入口 200。完整记录见[生产更新审计](../audit/production-p2-deploy-20261027.md)。

## 做了什么

- 用冻结快照逐字节校验的两模块最小包（59 文件，SHA256 `69b25e25…d4dc6`）替换生产模块，`-u` 仅这两个模块。
- 停服前完成数据库 dump + 真实附件树 + 旧模块源码 + 配置副本备份。
- 启动前校验：版本、库存不变量、其它模块哈希、模块文件哈希；启动后校验服务与入口。

## 关键修复

备份工具原先默认 `data_dir=/var/lib/odoo`，与生产实际 `/opt/odoo/.local/share/Odoo` 不符，会静默产出空附件归档。现已修正候选解析并在“有附件但归档为空”时直接失败，附 3 项回归测试。生产本次已补备 139 个真实附件文件。

## 备份与回滚

备份：`/opt/odoo/backups/p2-update-20261027-20261027T092319Z/20261027T092321Z-before-p2-update`（root 0700）。
回滚：`sudo bash /var/lib/lc-elc-deployments/p2-20261027-92d2d6-final/rollback.sh --task-root <task> --yes`。

## 未完成

- **公网未开通**：`team.l-creation.club` 仍解析到内网 `192.168.31.105`，无 AAAA。需要真实公网节点 + 标准 443 + 隧道登记后才能公网访问；本轮未改 DNS。
- 未做真实账号业务流、客户端/EDA 联调、真机、写业务 UI。
- 证书手动续期，到期 2027-01-23，未配置自动续期。

## 登记

新快照 [source-server-production-p2-20261027.json](../registry/source-server-production-p2-20261027.json)（202 文件）。`repo_check` PASS 52/0。
