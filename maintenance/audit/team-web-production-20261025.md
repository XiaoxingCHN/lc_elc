# lab_team_web 生产发布 · 审计记录（2026-10-25）

**结论：上线成功。** 仅新增 `lab_team_web 19.0.1.0.0`，服务 `odoo.service` active，
原首页/登录/既有 API 基线未变，旧五模块 133 个文件部署前后**完全相同**，库存计数与合计不变。
未改 DNS/代理/dbfilter，未卸载 website，未升级旧模块。DSH 未操作 Git，Codex 的独立推送见发布核验。

## 1. 硬门槛核对（全部满足）

| 门槛 | 实测 |
|---|---|
| 服务目标 | `odoo.service`，User=`odoo`，ExecStart=`/opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin --config=/etc/odoo.conf` |
| 数据库 | `LcHardwareHouse`（2599 MB）；`lc_hardware` 未触碰 |
| 模块路径 | `/opt/odoo/custom-addons`（真实目录，非符号链接；odoo 可写） |
| 配置可读 | `odoo` 用户可读 `/etc/odoo.conf`（未输出内容/密码） |
| 真实 filestore | `/opt/odoo/.local/share/Odoo/filestore/LcHardwareHouse`（47 MB / 154 文件，非符号链接） |
| 旧五模块版本 | inventory 19.0.1.0.0 / catalog 19.0.2.0.4 / workflow 19.0.1.2.0 / theme 19.0.1.0.2 / site 19.0.1.0.0（与冻结清单一致） |
| 备份盘空间 | `/var/backups/lc-elc` 所在文件系统可用 205,070,213,120 B（≈191 GiB），需求 ≈4.2 GiB |
| 安装包 SHA256 | `3b4858dffe5e4b0f01b65cf0663f933a6e7fe06c6297d2976d4d18746800f72d`（上传后服务器复算一致） |
| 目标路径安全 | 所有目标均为绝对路径、真实目录、非符号链接；不在 addons 扫描根留暂存/备份 |

## 2. 关键命令与退出码

| 环节 | 命令（要点） | 退出码 / 结果 |
|---|---|---|
| 停服前基线 | 133 文件 `sha256sum` 存 `baseline-modules-before.sha256`；psql 只读计数 | 133 行；库存 2/0.00/0.00/1/2/1/1/0 |
| 停服 | `systemctl stop odoo` | active→**inactive/dead**，8069 监听 0，odoo 进程 0 |
| 停服后最终基线 | 同一 psql 只读查询 | 与停服前**完全相同** |
| 备份 | `odoo_backup.py --config <私有 backup.conf> --db LcHardwareHouse --out-root /var/backups/lc-elc --label before-team-web **--no-service**` | **exit 0**；未自动启动服务（安装窗口无并发） |
| 旧模块归档 | `tar -czf existing-modules.tar.gz -C /opt/odoo/custom-addons lab_inventory lab_catalog lab_workflow lab_theme lab_site` | 12,796,060 B |
| 安装 | `sudo -H -u odoo … odoo-bin --config=/etc/odoo.conf -d LcHardwareHouse -i lab_team_web --stop-after-init --data-dir=/opt/odoo/.local/share/Odoo` | **INSTALL_EXIT=0** |
| 参数 | psql 插入 `lab_team_web.root_aliases=0` | `INSERT 0 1` |
| 启服 | `systemctl start odoo` | **active/running**，MainPID 124857，8069 监听 |

**如实说明**：安装那条复合命令的**外层 shell 返回 1**，原因是脚本末尾 `grep -c … ERROR` 在
无匹配时按 grep 语义返回 1；Odoo 安装本身 **INSTALL_EXIT=0**，两者不是同一件事。
安装输出被配置的 `logfile` 重定向，stdout 为空属正常。

## 3. 备份（本次新建，非历史复用）

目录：`/var/backups/lc-elc/20261025T093227Z-before-team-web`

| 产物 | 字节 | SHA256 |
|---|---|---|
| db.dump | 110,890,366 | `8c2e99e5639ad625ac74bb47171792e42bc8e9caf998d5a3e2c6d13d10ee26a7` |
| filestore.tar.gz | 13,596,659 | `770b465d72718e6d452a410d4d63814cdc02d6378335137aac02ba86419af728` |
| existing-modules.tar.gz | 12,796,060 | `ab6221943e0805d1ce23ee5f7c72a6bef579118870c96d64f21e2f00f9bf04e3` |
| MANIFEST.json | — | `050989dd297a718de44cca96a515e8d8baf2a3f8aac29c4877b843997b68d48a` |

MANIFEST 复核（正确字段）：`database=LcHardwareHouse`、
`filestore_root=/opt/odoo/.local/share/Odoo/filestore`、
`filestore_archive_root=LcHardwareHouse`、`filestore_files_bytes=46,594,640`；
`artifacts` 内 db.dump/filestore.tar.gz 的字节与 SHA256 与上表一致。
校验：`pg_restore --list` 命中 **1375** 条 TABLE DATA/SEQUENCE；filestore 归档内**非目录成员 154**，
与源目录文件数 **154** 一致。

**data_dir 处理**：真实配置未设 `data_dir`，helper 默认 `/var/lib/odoo` 并不存在；
实际运行目录为 `/opt/odoo/.local/share/Odoo`（odoo 用户 HOME=/opt/odoo，启动日志可证）。
为此生成**仅备份用 0600 配置**（staging 内）强制该 data_dir，未改真实服务配置、未输出凭据。
成功后已**仅 unlink 该精确文件**，未递归删除、未拷入 Git；备份与证据保留。

## 4. 安装与变更

- 新增目录：`/opt/odoo/custom-addons/lab_team_web`（**18 个文件**，owner odoo:odoo）；
  addons 根除该目录外无任何新增/残留。
- 18 个文件与冻结清单 **raw SHA256 逐文件比对：18/18 匹配，0 不一致**。
- DB：`lab_team_web=installed@19.0.1.0.0`；已安装模块 54 → **55**。
- 参数：`lab_team_web.root_aliases=0`（保留 `/login`、`/lab` 原有 404 行为）；
  **未配置** `lab_team_web.management_host`（管理根 `/` 仍为旧官网）。
- 旧五模块 133 文件：部署前后逐文件 `sha256sum` **diff 为空（SAME）**。
- 库存基线（安装后）：**2 / 0.00 / 0.00 / 1 / 2 / 1 / 1 / 0**（quant 行数/数量合计/预留合计/
  move/product/active bag/operation line/未归还领用），与停服前、停服后三次采集**完全一致**。

## 5. 验收（本机实测，均只读）

| 项 | 结果 |
|---|---|
| `/team`（带 `X-Odoo-Database: LcHardwareHouse`） | **200**，3921 B，含 `lc-body` |
| `/team`（先经 `/web/login?db=…` 建立会话） | **200**，3921 B |
| `/team/login` | **200**，含登录表单 |
| 匿名 `/team/lab` | **303 → /team/login?next=%2Fteam%2Flab** |
| 匿名 `/team/lab/items/lab:1` | **303 → /team/login?next=%2Fteam%2Flab%2Fitems%2Flab%3A1**（冒号保留） |
| 页面 CSS | **200**，36,406 B，URL 为内容哈希 `?v=7e9eee9d31f5` |
| 原 `/` | **200**，40,260 B，`<title>Home | My Website</title>` |
| 原 `/web/login` | **200** |
| `/lab`、`/login` | **404**（root_aliases=0，保持原状） |
| `/lab/scan` | **303**（既有行为） |
| `/lab/client/updates/manifest?platform=android&arch=universal&channel=stable` | **200**，1826 B，sha256 `152d47ae1145b8c81200409a5af4e47b952e1ec1dcbe8d10c4105959a945cb65`（与 Codex 独立结果一致） |
| 同上 windows/linux `arch=universal` | **204**（无发布内容） |
| `/lab/api/catalog/search` 匿名 POST | HTTP 200 + JSON-RPC `Session expired`（未返回数据） |

## 6. 已知限制（不改 dbfilter/代理/DB）

- **全新 CookieJar 直接 `/team?db=LcHardwareHouse` 仍 404（nodb）**：当前多库环境下，
  `db` 查询参数不足以在选择库之前路由到模块控制器。可用首次入口：
  `/web/login?db=LcHardwareHouse&redirect=/team/lab`（选库建会话后，自有 `/team/*` 路径可用）；
  或带 `X-Odoo-Database` 头。**不声称**带 db 的 `/team` 链接可首次直开。
- `root_aliases=0` 是保留旧 `/login`、`/lab` 404 的安全决定；未来接入域名若要启用别名需单独评估。

## 7. 警告如实记录（非本批缺陷，未处理）

- 安装时：「Failed to render module description … html4css1.css 权限不够」（docutils 模块描述渲染回退；本批页面 HTTP 检查正常）。
- 启动时：配置中 `xmlrpc_port`、`longpolling_port` 为未知选项；未设 `http_interface` 使用 0.0.0.0（既有配置，本批未改）。

## 8. 回滚建议（Codex审查后修正）

1. 备份目录与现行模块源码保持不动。新入口发生问题时先继续使用原后台/客户端与既有 API；不要通过删除已安装模块目录来下线，那会留下 installed 元数据并可能破坏注册表加载。
2. 若需要卸载新模块或切换代码，须先评估依赖、确认本次故障及操作范围，再制定并授权执行；本轮未做卸载或自动回滚。
3. 数据库与 filestore 整体恢复仅作最后手段：先确认部署后是否有新业务写入，保存当前状态、明确可接受的数据回退范围，再按经过复核的 MANIFEST 和恢复脚本停服恢复。不得直接用发布前备份覆盖上线后的新业务数据。
4. 仓库有 `odoo_restore.py`，本轮未上传/执行；真实 data_dir 与 helper 默认不同，恢复时也须显式核对备份清单和目标目录。

## 9. 未验证 / 不声称

- 真实登录用户的完整会话流程（本批无可用测试账号，未创建生产测试账号）。
- 生产大目录检索性能、分面筛选、真实网站编辑器保存、真机。
- 入库/领用/归还/标签打印（页面标"暂未开放"，未接入）。
- `team.l-creation.club` **本轮未配置或验证解析**；DNS/代理未改；管理根 Host 未启用。
- 未推送 Git、未改 README/CURRENT_STATE/CHANGELOG/registry（由 Codex 维护）。
