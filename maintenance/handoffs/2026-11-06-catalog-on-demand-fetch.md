# 维护交接：2026-11-06 器件库按需抓取

## 用户目标与已确认边界

搜索未命中时，允许对**精确 C 编号**或**精确 MPN**从立创抓一条中文资料存入器件库，然后自动刷新；期间不阻塞搜索、不写实验室库存。用户已确认：没有官方 LCSC API key；入库数据必须是中文。已明确不自动抓取名称/品牌/模糊关键词，不绕过 WAF，不把模糊匹配当作用户要的型号。

## 当前权威源码、分支和版本

- 分支 `feat/receipt-param-search`，工作区有大量既有未提交改动（Liquid Glass、参数搜索、待入库筛选等），本任务只改动下列文件。
- `lab_catalog`：`19.0.2.0.9 → 19.0.2.0.10`；`maintenance/registry/components.json` 已同步。客户端版本仍为 `1.2.0+7`。
- 权威源码仍是 `server/ubuntu22.04/odoo_addons/lab_catalog/` 与 `clients/app/`；没有新建第二份实现。

## 已完成工作与实际证据

服务端（新增/改动）：

- `lab_catalog/tools/lcsc_remote.py`、`tools/lcsc_electronics_filter.json`、`tools/__init__.py`
- `lab_catalog/models/lab_catalog_fetch.py`、`models/__init__.py`
- `lab_catalog/data/lab_catalog_cron.xml`、`__manifest__.py`
- `lab_catalog/controllers/catalog_api.py`、`controllers/envelope.py`
- `lab_catalog/security/ir.model.access.csv`、`security/lab_catalog_security.xml`
- `lab_catalog/tests/test_lcsc_remote.py`

客户端：

- `clients/app/lib/features/unified/models/unified_item.dart`
- `clients/app/lib/services/lab_api_client.dart`
- `clients/app/lib/features/unified/providers/catalog_providers.dart`
- `clients/app/lib/features/unified/screens/unified_catalog_screen.dart`
- `clients/app/test/features/unified/catalog_fetch_test.dart`

本机实际执行（Flutter 3.47.7 / Dart 3.13.5）：

- `flutter test --no-pub --reporter compact`：exit 0，**326 passed / 5 skipped / 0 failed**（基线 319/5）。
- `flutter analyze --no-pub lib test`：exit 1，**0 error / 0 warning / 120 info**（基线 118；新增 2 条与文件既有风格一致的 `prefer_initializing_formals`）。
- `python -I server/ubuntu22.04/odoo_addons/lab_catalog/tests/test_lcsc_remote.py`：exit 0，15/15。
- `python tools/repo_check.py`：exit 1，50 项通过；`frozen-source:client`（4 文件）与 `frozen-source:server`（13 文件）为尚未冻结的本轮源码；16 条 payload 警告为既有缺口。日志在 Git 排除的 `local/tmp/catalog_repo_check2.log`。
- `python tools/generate_routes.py`：重新生成 `maintenance/registry/routes.json`（94 条，含两个新接口）；`--check` exit 0；`git diff --check` exit 0。

## 剩余工作与阻塞

1. **Odoo 测试库验证（未执行）**：`lab.catalog.fetch.request` 建表、部分唯一索引、cron、分类映射、upsert 与 revision。本工作区没有可用的 Odoo/PostgreSQL 测试实例。
2. **真实网络端到端（未执行）**：C32445874、TLV77333PDBVR、TLV77733PDBVR 的抓取与中文入库；非电子样本应得到 `skipped_non_electronic` 且中文页请求数为 0。
3. **Flutter widget 测试（未做）**：空状态按钮、候选列表、状态卡的渲染与点击只有逻辑测试和现有布局测试间接覆盖。
4. **生产部署（未授权，未执行）**：需要升级 `lab_catalog` 才会建表并注册 cron；升级前应确认 `ir.cron` 不会与采集器并发压立创。
5. **源码冻结（未做）**：发布前需 `tools/release.py snapshot` 并 `--activate`。

判断完成的方法：在测试库完成模块升级后运行上述三个料号的抓取，状态到 `done` 且搜索能返回中文参数；非电子样本为 `skipped_non_electronic`；`stock.quant`/`stock.move` 计数不变。

## 依赖和产物

- 无需 LCSC API key、cookie 或 token；只用公开前端接口与中文详情页。
- 电子分类白名单与采集器 `crawler/lcsc_electronics_filter.json` 同步，测试会校验两者一致（采集器不在本 checkout 时跳过）。
- 本任务没有新增二进制产物或 registry artifact；未构建安装包。

## 生产状态和回滚

没有触碰生产：未升级模块、未建表、未注册定时任务、未发起抓取、未导入、未重启。生产仍是 2026-11-04 参数搜索部署后的状态（`lab_catalog 19.0.2.0.6` 已在生产，本候选为 `19.0.2.0.10` 源码）。若后续部署，需先做数据库与源码备份，升级失败时回滚模块源码并恢复备份。

## 生产部署（2026-11-06T14:29–14:31Z，已完成）

上一节「生产状态和回滚」是部署前时点，已被本节取代。

- **执行**：`server/ubuntu22.04/upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261106/modules`（暂存目录 124 文件、不含 `tests/`），`-u lab_inventory,lab_catalog,lab_workflow` **退出码 0、ERROR/CRITICAL/Traceback 行数 0**；生产 `/opt/odoo/custom-addons` 现为 `lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2`，`lab_team_web 19.0.1.2.1` 未参与本次 `-u`。
- **备份与回滚点**：`/var/backups/lc-elc/20261106T142949Z-before-upgrade/`——`db.dump` **118,970,696 B** / `40863d500fffc8f36013cd99da8625d3ed988799826f6633cc178f41d3ba0d66`；`filestore.tar.gz` **12,819,190 B** / `5b9e5d42a03d339dcbab225ad3e1da09913b4b853dcded117fcb29614a3f5fc0`；`MANIFEST.json` 17,246 B、`odoo.log.tail`；旧三模块源码在 `module-source-before-upgrade/`（回滚时先移走新代码再移回，勿删除）。
- **健康检查的已知假阴性**：脚本步骤 5 见 `/web/login` 返回 **303**（→ `/web/database/selector`）即判失败，与 2026-11-04 相同的脚本缺陷，不是服务故障。独立复核：`X-Odoo-Database: LcHardwareHouse` 时 `/web/login` **200**、`odoo.service` **active/enabled**、14:31:36Z Odoo 打印 `Modules loaded`（55 模块）。
- **运行证据**：`/var/log/odoo/odoo.log` 自 2026-11-06 14:30Z 至 2026-11-07 13:11Z **0 条 ERROR/CRITICAL/Traceback**；`ir.cron` 任务「器件库：处理在线补抓队列」（id 25，每 1 分钟、`model._cron_process_queue(limit=2)`）自 **2026-11-06 14:31:16Z** 起每约 62 秒运行，累计 **1356 次启动、0 次失败**，每次 `fully done (#loop 1; done 0; remaining 0)`（队列为空）。这同时证明新模型已加载、`lab_catalog_fetch_request` 可用、cron 记录已入库。
- **DB 行核对（2026-11-07T13:17:07Z）**：`verify_deploy.sh` 在 root 下用 `runuser -u odoo psql` 查询（输出 `/home/hbut/lc-deploy-20261106/verify-20261107T131707Z.txt`）——四模块 `lab_catalog|19.0.2.0.10|installed`、`lab_inventory|19.0.1.1.0|installed`、`lab_workflow|19.0.2.0.2|installed`、`lab_team_web|19.0.1.2.1|installed`；`to_regclass('lab_catalog_fetch_request')` 存在；索引 7 个，含部分唯一索引 `lab_catalog_fetch_active_uniq`（谓词 `state IN ('queued','resolving','fetching')`）与 `lab_catalog_fetch_state_idx`；`ir_model_data` 的 `lab_catalog.ir_cron_lab_catalog_fetch` → `res_id=25`，与日志里每 62 秒运行的 job 25 一致。
- **仍未核对**：`lab_catalog_item` / `lab_catalog_param` / `lab_catalog_fetch_request` 行数——第一步脚本在 `ir_cron.model_id` 处报错中断（Odoo 19 中该列在 `ir_act_server` 而非 `ir_cron`），其后的 HTTP/服务段也未执行；第二步脚本 `verify_deploy2.sh` 已上传等待 sudo 密码。
- **仍未做**：真实网络端到端抓取（C32445874 / TLV77333PDBVR / TLV77733PDBVR 及一个非电子样本）、Flutter widget 测试、客户端包构建、`tools/release.py snapshot` 冻结与 `--activate`。回滚演练未做。
