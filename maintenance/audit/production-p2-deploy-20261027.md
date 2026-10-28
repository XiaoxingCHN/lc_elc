# 生产更新审计：2026-10-27 P2 模块上线

## 结论

`lab_team_web` **19.0.1.0.0 → 19.0.1.0.5**、`lab_catalog` **19.0.2.0.4 → 19.0.2.0.5** 已在本机生产 **LcHardwareHouse** 上线，`odoo.service` 与 `nginx` 均 active，TLS 登录入口返回 200。仅更新这两个模块，其它模块源码与数据库记录未变。

**未**改动 DNS、Nginx 配置、公网入口或客户端。公网仍不可用（见下）。

## 授权与范围

用户要求确认公网域名是否还需操作，不需要则更新服务器。公网需要额外资源（真实公网节点 + 标准 443），因此本轮只做内网生产更新；用户随后提供了该 SSH 账号的交互凭据。凭据仅用于 sudo 提权，未写入仓库、命令历史或任何文件。

## 变更内容

| 项目 | 变更前 | 变更后 |
|---|---|---|
| lab_team_web | 19.0.1.0.0 | **19.0.1.0.5** |
| lab_catalog | 19.0.2.0.4 | **19.0.2.0.5** |
| odoo.service | active | active |
| nginx / vhost / DNS | — | 未改 |

候选包 SHA256 `69b25e259df6e36087747b33c9bbaa700db7448468d41dc19525d7aca10d4dc6`，59 个文件逐字节匹配冻结快照 [source-server-p2-evidence-hardened-20261027.json](../registry/source-server-p2-evidence-hardened-20261027.json)。执行包由 root 保护在 `/var/lib/lc-elc-deployments/p2-20261027-92d2d6-final`（0600）。

## 验证（实测）

| 检查 | 结果 |
|---|---|
| 数据库模块版本 | catalog 19.0.2.0.5 installed；team_web 19.0.1.0.5 installed |
| 库存不变量 | stock_quant 2 行、数量 0.00、预留 0.00，升级前后一致 |
| 其它模块 | 文件哈希与数据库记录均未变 |
| 模块文件 | 与包内 MANIFEST 逐文件 SHA256 一致 |
| 服务 | odoo.service / nginx 均 active |
| 入口 | `/` 200、`/login` 200、`/lab` 303（未登录保护）、`/web/login` 200 |
| 静态资源 | `/lab_team_web/static/src/js/team.js` 200 text/javascript |
| 匿名搜索 | 返回 SessionExpiredException，无数据泄露 |
| 登录页 | 含「力创实验室」与 `/login` POST 表单 |

## 备份与回滚

备份目录 `/opt/odoo/backups/p2-update-20261027-20261027T092319Z/20261027T092321Z-before-p2-update`（0700，root）：

- `db.dump` 110,898,092 字节，SHA256 `87a93c3d61ebc52d8c42717234787289578808c8f670fe5b7ca839de02e3933b`
- `filestore-supplement.tar.gz` 12,863,133 字节，SHA256 `87899c6e3bc2feefdbf5d78c04f46b47bcbe49428e643997ba168b788c19d4be`，139 个真实附件文件
- 旧模块源码保留在 `state/.../rollback/original-code-*`
- 回滚：`sudo bash /var/lib/lc-elc-deployments/p2-20261027-92d2d6-final/rollback.sh --task-root <task> --yes`

## 过程中发现并修复的真实缺陷

1. **附件漏备（严重）**：备份工具把 `data_dir` 默认成 `/var/lib/odoo`，而生产 Odoo 实际使用 `/opt/odoo/.local/share/Odoo`，导致本次首份备份的 `filestore.tar.gz` 只有 59 字节空归档，而数据库实际有 217 条文件附件（139 个唯一文件）。
   - 已补备真实附件树并通过数量交叉校验。
   - 已修 `lc_odoo_conf.filestore_candidates()`：同时考虑配置、当前用户 home 与 `odoo` 服务用户 home，取文件最多的已存在目录。
   - 已修 `odoo_backup.py`：库内存在文件附件但 filestore 为空时**直接失败**，不再产出看似完整的空备份。
   - 新增 3 项回归测试（空附件拒绝、失败信息、候选覆盖），root 环境实测 115 通过 / 1 失败。
2. **通用升级脚本范围不符**：`upgrade_modules.sh` 硬编码三个模块且不含 `lab_team_web`，直接使用会漏升级；本次改用专用最小发布流程。

## 已知限制

- 剩余 1 项运维测试失败（模块扫描桩）源于测试用假 `odoo-bin` 在该临时目录不可执行，属环境限制；相关 7 项断言实际通过。
- 未做真实账号登录、写业务、客户端联调、真机与公网验收。
- 生产 Nginx 1.18 不支持 `proxy_cookie_flags`，候选模板本就用空占位；CSP 等安全头未在本轮改动。

## 公网状态

`team.l-creation.club` 的 A 记录仍为 **192.168.31.105（内网地址）**，无 AAAA。公网访问需要：真实公网节点 + 标准 443 + 反向隧道登记。本轮未做，也未改 DNS，避免破坏现有内网入口。

新源快照：[source-server-production-p2-20261027.json](../registry/source-server-production-p2-20261027.json)（202 文件，tree `cd1d18a4ea6a745da47a5252cfd8921f8d5e9234362e402f39fc3040ce94fbcb`）。`python tools/repo_check.py`：PASS，52 项检查、0 错误。
