# 交接：lab_team_web 19.0.1.0.0 生产上线（2026-10-25）

## 结果

- 生产 **已上线**：新增 `lab_team_web 19.0.1.0.0`（installed），服务 `odoo.service` **active**（MainPID 124857）。
- 仅新增一个模块目录与一条参数；旧五模块**未升级、未覆盖**（133 文件部署前后 SAME）。
- 原首页（200/40,260 B My Website）、`/web/login`（200）、`/lab/scan`（303）保持不变；
  `/lab`、`/login` 维持 404（`root_aliases=0`）。
- 库存基线三次采集一致：quant 2 行 / 数量 0.00 / 预留 0.00 / move 1 / product 2 / active bag 1 / operation line 1 / 未归还领用 0。

## 生产配置（本次确定）

| 键 | 值 | 说明 |
|---|---|---|
| 模块 | `lab_team_web 19.0.1.0.0` | 仅 18 个源文件 |
| `lab_team_web.root_aliases` | `0` | 保留 `/login`、`/lab` 原 404；未来域名接入若要别名需单独启用 |
| `lab_team_web.management_host` | 未配置 | 管理根 `/` 不接管，仍为旧官网 |

## 备份与回滚点

`/var/backups/lc-elc/20261025T093227Z-before-team-web`
- db.dump 110,890,366 B `8c2e99e5…a6a7`
- filestore.tar.gz 13,596,659 B `770b465d…f728`
- existing-modules.tar.gz 12,796,060 B `ab622194…04e3`
- MANIFEST.json `050989dd…48a`（database=LcHardwareHouse，filestore_root=/opt/odoo/.local/share/Odoo/filestore）
回滚不得删除已安装模块目录；整体恢复前必须评估并保留部署后新业务数据，确认范围后再按 MANIFEST 及真实 data_dir 执行。不自动恢复，详见生产审计第8节的 Codex 修正。

## 入口说明（重要）

- 首次入口（多库环境需先选库）：`/web/login?db=LcHardwareHouse&redirect=/team/lab`；
  建立会话后 `/team`、`/team/login`、`/team/lab/*` 正常。
- 直接用 `/team?db=…` 首次打开在全新 CookieJar 下仍 404（nodb），属当前部署形态限制，
  未改 dbfilter、未删库。带 `X-Odoo-Database` 头可直连（脚本/客户端用）。
- `team.l-creation.club` 本轮未配置或验证解析；DNS/代理未动。

## 本批证据

- 安装包 sha256 `3b4858df…f72d`（60,610 B，18 源文件 + SOURCE-MANIFEST.json）；
  18 文件与冻结清单 raw SHA256 **18/18 匹配**。
- 源码关联：manifest `source-server-team-web-phase1-20261025.json`，
  tree `9a333b84…98c4`，commit `08186aa…4b58e`。
- 备份前的私有暂存 `/root/lc-elc-publish-20261025T0925Z`（0700）：保留安装包、来源清单与
  133 文件基线；其中的 backup.conf（唯一含真实配置的临时副本）已在核验为暂停存内普通文件后
  **仅 unlink 该文件**，未递归删除、未拷入 Git。

## 已知限制与后续

1. 全新会话需先选库才能进入 `/team`；若要"开箱即用"的域名入口，需单独决策（dbfilter/反向代理/域名），本批未做。
2. 入库/领用/归还/标签打印未接入；页面仅显示"暂未开放"。
3. 未验证：真实登录用户完整流程、大目录性能、编辑器保存、真机。
4. 旧五模块与冻结清单存在 2 处历史内容差异（lab_catalog CSS、lab_theme 部署脚本）与 13 处换行差异，
   本批**按要求保留未覆盖**；是否同步需单独任务。
5. Git 推送、README/CURRENT_STATE/CHANGELOG/registry 由 Codex 处理，本文件不覆盖其审查记录。
