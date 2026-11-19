# 维护交接：服务端部署 + 作业页覆盖外壳

- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 客户端 `1.3.5+21 → 1.3.5+22`；服务端已部署到 lc-nas。

## 一、服务端部署（已完成）

用户授权后执行。目标机 `lc-nas`（192.168.31.105），Odoo 19，`/opt/odoo`，服务 `odoo.service`。

**部署前核对**：逐文件比对本地与线上 121 个 py/xml/js/css 文件，只有 **7 个**不同，
没有意外差异。其余全部一致。

**过程**：

1. 打包 7 个文件 → `/tmp/lc-deploy.tgz` → 服务器 `/tmp/lc-new`；
2. 用线上现成的两个模块 + 新文件构建完整代码树 `/tmp/lc-code`
   （`upgrade_modules.sh --code-dir` 要求每个模块有 `__manifest__.py`）；
3. 手动备份 7 个原文件到 `/opt/odoo/backups/20261119T135357Z-before-upgrade`；
4. 跑 `upgrade_modules.sh --code-dir /tmp/lc-code --modules lab_workflow,lab_team_web`。

**注意**：服务器上**没有** `/opt/odoo/upgrade_modules.sh`，脚本在
`/home/hbut/lc-deploy-workflow-20261119/`（已核对与本仓 `server/ubuntu22.04/` 下四个文件
SHA256 完全一致）。

**结果**：

| 项 | 值 |
|---|---|
| 升级退出码 | 0，ERROR/CRITICAL/Traceback 行数 0 |
| 数据库备份 | `/var/backups/lc-elc/20261119T135447Z-before-upgrade` |
| 代码备份 | 同目录下 `module-source-before-upgrade/` |
| `lab_workflow` | 19.0.2.0.3 → **19.0.2.0.4** |
| 模块状态 | lab_workflow / lab_team_web / lab_catalog / lab_inventory 全部 installed |
| 服务 | active |
| `/web/health` | 200 |
| 公网 `https://team.l-creation.club/` | 200 |

**脚本最后报「健康检查未通过」是误报**：它要求 `/web/login` 返回 200，实际返回 303
（重定向到 `/web/database/selector`），因为 `/etc/odoo.conf` 没有 `db_name`。这是**既有**
配置形态，不是本次升级造成的——升级前日志显示 Odoo 一直正常服务 `LcHardwareHouse`。
服务本身健康。

## 二、存量数据修复：模板 #16

截图报错的 `GH1.25 端子 2P`（`product.template` id=16，`lab_sn=LAB-000025`）在库里是
`is_storable=False / tracking=none`。代码修复只影响**新建**物料，所以单独改了这条：

1. 先查无批次正库存：`stock_quant` 里 internal/transit、`lot_id IS NULL`、`quantity>0`
   的记录数 = **0**；
2. 按 `lab_ensure_storable_tracking` 的同一规则写成 `is_storable=True / tracking=lot`。

**如果以后遇到别的 `is_storable=False` 物料**：同一流程——先查无批次正库存，
为 0 才能直接开跟踪；不为 0 必须走「历史库存分袋适配」，否则那些库存会失去追溯。

## 三、作业页带着分区切换器（客户端 bug）

用户截图：采购入库页底部还有「库存 / 仓位 / 器件库」切换器。

**根因**：`context.push` 从 `StatefulShellRoute` 分支内部发起时，推到的是**该分支自己的
导航器**，所以根级的作业页被套在外壳里显示。

**修法**：`lib/routes/navigator_keys.dart`（新）暴露 `rootNavigatorKey`；
`unified_routes.dart` 里 7 条作业路由全部加 `parentNavigatorKey: rootNavigatorKey`。
key 抽成独立文件是因为 `app_router` 已 import `unified_routes`，反向 import 会成环。

**顺带修掉的重复定义**：`/catalog` 同时在 shell 分支和 `unifiedRoutes` 里定义，根级那份
赢得匹配 → 器件库其实不在外壳里，切走再切回会丢页面栈。已删掉根级那份。

**回归测试**：`widget_test.dart` 新增「an operational page covers the shell」，
断言 `/receipt/prepare`、`/receipt`、`/labels` 上 `WarehouseSectionSwitcher` 不存在。

## 实测

- `flutter test --no-pub` → **510 passed / 5 skipped / 0 failed**
- `flutter analyze --no-pub lib test` → 0 error / 0 warning
- Windows 1.3.5+22 三步 exit 0
- `repo_check.py` → PASS 53

## 产物

- Windows `clients/windows/releases/1.3.5+22/LC_ELC-Windows-1.3.5+22-x64.zip`
  （37,739,348 B，sha256 `7e5b6a72…c900e6fa`，30 文件）
- 清单 `source-client-1.3.5-22-20261119.json`（221 文件）、
  服务端 `source-server-storable-deployed-20261119.json`（274 文件），均已 `--activate`

## 未验证

- **Android 实机**（本轮只构建了 Windows 并打包；APK 另构建）
- 真实打印与扫码
- 升级脚本的「健康检查」误报没有改——它要求 200，而本机配置下 `/web/login` 恒为 303。
  下次升级还会看到同样的警告，按上面的说明判断即可。
- 未 commit / 未 push
