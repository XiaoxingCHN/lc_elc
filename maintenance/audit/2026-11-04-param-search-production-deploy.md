# 2026-11-04 参数关键词搜索生产部署

## 范围

- 主机：`192.168.31.105`（`lc-nas`），DB `LcHardwareHouse`，Odoo 19，`/opt/odoo/custom-addons`。
- 授权：用户 2026-11-04 明确要求“先推送给服务器我试试效果”；本轮执行四模块升级与参数回填。
- 源：`maintenance/registry/source-server-param-search-20261104-r2.json`
  （264 文件，tree_sha256 `503e278221851fa129351bae12e95b6da5a8eeb5192d4e8ab2e5907c270ab378`，
  清单 sha256 `485c93c2ca3d1543bf8bb8838acb538f24c0a6f23ae4b68418cd4c8f3410b86a`）。

## 时间线（UTC）

| 时间 | 事件 |
|---|---|
| 2026-11-04T12:59:44Z | 一致备份完成，服务恢复 active |
| 2026-11-04T13:00:0xZ | 四模块 `-u` 完成，退出码 0、0 条 ERROR/CRITICAL/Traceback |
| 2026-11-04T13:00:08Z | `odoo.service` 启动并确认 active |
| 2026-11-04T13:05:25Z | 参数回填启动（`odoo` 用户） |
| 2026-11-04T13:08:58Z | 回填完成 695,217/695,217，写入 ready |

## 备份与回滚

- 备份目录：`/opt/odoo/backups/20261104T125944Z-before-upgrade/`
  - `db.dump`：110,948,317 B，SHA256 `2c8bd939ca46557b5b6353074c0a58eb175dd77065a67378f0fc96c56d810794`
  - `filestore.tar.gz`：12,819,190 B，SHA256 `c180ca54d33cec4c68a773b07f5368ff618a16bd5d56aac9bb47bc2c607c929f`
  - `MANIFEST.json`、`odoo.log.tail`
- 旧四模块源码：`/opt/odoo/backups/20261104T125944Z-before-upgrade/module-source-before-upgrade/{lab_inventory,lab_catalog,lab_workflow,lab_team_web}`
- 回滚工具：当前可用 `/tmp/lc-param-search-20261104/stage/odoo_restore.py`（及同目录依赖）；
  `verify_remote.sh` 会复制到备份内 `deploy-tools/`，重启后请使用该持久副本。
- 数据库回滚命令（先确认 `deploy-tools/` 已存在）：
  ```bash
  sudo /opt/odoo/venv/bin/python \
    /opt/odoo/backups/20261104T125944Z-before-upgrade/deploy-tools/odoo_restore.py \
    --backup /opt/odoo/backups/20261104T125944Z-before-upgrade \
    --db LcHardwareHouse --unit odoo.service --yes
  ```
  回滚会覆盖备份点之后的业务写入，执行前必须确认维护窗口。

## 版本（生产 installed）

| 模块 | 版本 |
|---|---|
| lab_inventory | 19.0.1.1.0 |
| lab_catalog | 19.0.2.0.6 |
| lab_workflow | 19.0.2.0.1 |
| lab_team_web | 19.0.1.2.1 |

## 日志与结果

- 升级日志：`/opt/odoo/backups/param-search-upgrade-20261104T125944Z.log`
  - 四模块预检通过；旧代码已保留；`-u` 退出码 0；ERROR/CRITICAL/Traceback 0。
- 回填日志：`/opt/odoo/backups/param-search-backfill-20261104T130525Z.log`
  - `processed=695217 updated=695217 last_id=695217`；`参数检索索引已标记 ready。`
  - Traceback/ERROR/CRITICAL 0。
- Odoo 日志：2026-11-04 13:00 后无 ERROR/CRITICAL/Traceback；仅有模块描述 CSS 权限和既有 access rule 警告。
- 服务：`odoo.service` active。

## 健康检查说明

`deploy_remote.sh` 内置健康检查要求 `/web/login` 返回 200，但本次 curl 无会话时返回
`303 → /web/database/selector`；带 cookie 跟随后最终为 `200` 登录页。这是数据库选择跳转，
不是服务故障。脚本因此在启动服务后以非零退出，未自动启动回填；随后用 `finish_remote.sh`
完成回填。标准 `server/ubuntu22.04/upgrade_modules.sh` 同时只升级三模块，且健康检查同样
只接受 200；后续应修正这两处，避免再次手工收尾。

## 已验证

- 四模块版本 installed。
- 参数回填全量完成并写 ready。
- 服务 active；登录页在数据库选择后 200。
- 部署后的 `receipts.js` 静态文件 200（75,312 B），含 `pendingTotal` / `viewAllLabel` 标记。
- `pg_trgm` 存在，`lab_catalog_item_params_trgm_idx` 存在。

## 未验证

- 真实浏览器搜索：`10R`、`4R7`、`R1`、`100nF` / `0.1uF`、多词 AND。
- 待入库队列关键词/状态筛选与“查看全部结果”跳转。
- Odoo ORM/HttpCase 用例（本机无测试实例）。
- Flutter 回归（本轮未改）。
- 目录导入与真实业务写入（未执行）。
- 短 token（如 `1%`）误命中率与查询性能。

## 部署包

- `local/build/param-search-20261104/param-search-20261104.tar.gz`
  SHA256 `99b339cc89340c97731a406b258b0f8d10e2d4dccee82546e086a23ad5ba128f`
  （192 条目；含四模块、四模块升级脚本、备份/回填/验证包装器、`SHA256SUMS`）。
- 服务器暂存：`/tmp/lc-param-search-20261104/`（重启后可能被清理；持久回滚工具已复制到备份目录）。
