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

## 二、存量数据修复：全库 8 个物料（一次修完）

**教训**：第一次只修了截图里那一条（#16），用户第二次截图换成 4P（#17）又报同样的错。
这是**系统性数据问题**，不是单条异常——应当第一轮就 `SELECT ... WHERE is_storable=false`
查全量。

`product_template` 里 `type='consu' AND is_storable=false` 共 **7 条**（#16 此前已修），
全部为 GH1.25 端子线系列，且 `tracking` 均为 `none`：

| id | SN | 名称 |
|---|---|---|
| 13 | LAB-000022 | GH1.25端子线 |
| 14 | LAB-000023 | GH1.25 3P |
| 15 | LAB-000024 | GH1.25 端子 3P |
| 17 | LAB-000026 | GH1.25 端子 4P |
| 18 | LAB-000027 | GH1.25 端子线 黑色 |
| 19 | LAB-000028 | GH1.25 端子线 红色 |
| 20 | LAB-000029 | GH1.25 成品端子线 7P 反向 |

**修法**（逐条按 `lab_ensure_storable_tracking` 的同一安全规则）：

1. 先查无批次正库存（`stock_quant` internal/transit、`lot_id IS NULL`、`quantity>0`）——
   7 条全部为 **0**，可以安全开启跟踪；
2. 写 `is_storable=True / tracking='lot'`。

**结果**：7 条全部修复，`REFUSED 0`；全库 `is_storable=false` 残留 **0**。

**以后遇到同类数据**：先 `SELECT id, lab_sn FROM product_template WHERE type='consu'
AND is_storable=false` 查全量，再逐条按上面的规则处理——不要只修报错的那一条。
若某条有无批次正库存，**不能**直接开跟踪，必须走「历史库存分袋适配」。

### 根因（追到底）

Odoo 19 的字段定义（`/opt/odoo/odoo-19/addons/stock/models/product.py:839`）：

```python
is_storable = fields.Boolean(
    'Track Inventory', store=True, compute='compute_is_storable', readonly=False,
    default=False, precompute=True, tracking=True, ...)
```

**默认 `False`**。所以任何忘记显式写 `is_storable=True` 的 `create()` 都会静默建出
不可库存的物料——制袋码照常生成，到上架时才报错。

我们代码里建 `product.template` 的地方只有三处：

| 位置 | 是否设置 | 结果 |
|---|---|---|
| `lab_pending_receipt.py`「新建器件」分支 | **原本漏设** | 7 个物料全部不可入库 |
| `lab_workflow_common._lab_create_minimal_material`（立创 C 码建档） | `is_storable: True` | 正常 |
| `lab_catalog/controllers/catalog_api.py`（create_material） | `is_storable: True` | 正常 |

数据佐证：7 个坏物料全部 `lab_lcsc_code` 为空、`create_date` 都是 2026-11-19、`create_uid=2`
——即用户当天连续用「新建器件」建了 7 条，每条都撞同一个 bug。

### 防回归

`test_workflow_business.py` 新增
`test_every_creation_path_makes_a_receivable_material`：**逐条**走两条建档路径
（手工新建 / 立创 C 码），断言建出的物料 `type=consu` + `is_storable=True` +
`tracking in (lot, serial)`，并真的执行一次 `lab_pending_confirm` 证明能入库。
不是只测修好的那一条。

### 在服务器上跑测试（此前误以为本机跑不了）

```bash
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin   --config=/etc/odoo.conf -d LcHardwareHouse   --test-tags /lab_workflow --stop-after-init --no-http   --workers 0 --http-port=8199 --log-level=test
```

四个必须项，缺一个就看不到结果：

- `--workers 0`：配置文件里是 `workers = 2`，workers 模式下 Odoo **不执行**测试，
  只打印「0 post-tests」；
- `--http-port=8199`：8069 被运行中的服务占用；
- `--log-level=test`；
- 结果**不在 stdout**：`/etc/odoo.conf` 的 `logfile` 会接管输出，要去
  `/var/log/odoo/odoo.log` 里 `grep "of N tests when loading"`。

### 顺带修掉的测试隔离缺陷

`test_p3_backend_api.test_01_bags_pagination_and_filters` 原先断言
`len(lab_bags(has_stock=False)) == 2`，但 `lab_bags` 是**全公司**范围，这个库又是生产库，
所以只要有真实袋就必失败。改为只断言「本测试的袋落在哪一侧」。

同时确认了 `has_stock` 的真实语义：`true` 加 `quantity > 0`；**`false` 不加任何条件**
（即返回全部）。注释里写清楚了，免得下一个人再按「false = 空袋」去写。

**最终：`/lab_workflow` 88 个测试全部通过（0 failed / 0 error）。**

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
