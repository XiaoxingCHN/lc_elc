# 任务：立创资料改为纯按需抓取（停用夜间批量）

- Status: in-progress
- Category: enhancement

- 目标/用户场景：把「器件资料怎么更新」从夜间批量采集改为纯按需：整库搜索与入库/待入库搜索都能对精确 C 编号或完整 MPN 当场抓取（目标 20 秒内），已有条目只在打开该器件时单条刷新，绝不做全量刷新。
- 当前问题及复现方法：`lcsc-crawler.timer` 每天 03:30 启动，但采集器只抓 `cn_queue.state='pending'` 的行，69.5 万条全是 `done`，因此每次 2 秒退出（`completed_this_run=0`）、导入器重导同一份快照、`lab_catalog_item` 行数不变（2026-11-07 实测）。按需抓取只在器件库搜索页零结果时出现，入库表单没有入口，且要等每分钟 cron，最坏 60 秒。
- 验收标准：两个搜索入口零结果时都能看到抓取按钮；点击后 ≤20 秒得到 `done`/`candidates`/明确中文失败原因；锁被占用时退回队列且前端继续轮询；详情页「刷新资料」只更新当前这条（其它行 `fetched_at` 不变）；**大于 5 个字符且含字母的关键词给出带名称的候选，选定后才抓取**；≤5 字符/纯数字仍不可抓；多候选仍需人工选择；停用两个 timer 后采集器与导入器仍可手工运行。
- 允许修改目录/接口：`server/ubuntu22.04/odoo_addons/lab_catalog/`（tools/models/controllers/tests/data）、`clients/app/lib/features/unified/`、`clients/app/lib/services/lab_api_client.dart`、`clients/app/test/features/unified/`、`services/lcsc/README.md`、`docs/architecture/OVERVIEW.md`、`maintenance/registry/`、`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`、交接与任务单。生产 systemd 停用 timer 属生产变更，执行前需用户确认。
- 业务不变量/依赖：库存仍只由 `stock.quant`/`stock.move` 决定；抓取只 upsert `lab.catalog.item`/`lab.catalog.param`；来源限立创固定域名；非电子分类不入库；`normalize_query` 不放松（精确 C 码/MPN 才直接抓取）；关键词走独立的 `normalize_keyword`（>5 字符、含字母）且只返回候选；一次刷新只针对一个 C 编号。
- 负责人/协作者及分工：主代理实施，用户确认生产停用与部署。
- 分支/起始commit/源码manifest：`feat/receipt-param-search`，起始 HEAD `605b427`；冻结清单 `source-server-catalog-fetch-20261106.json` / `source-client-catalog-fetch-20261106.json`（本轮完成后需重新 snapshot）。
- 环境与凭据获取方式（只写位置，绝不写值）：本机 Python 3 / Flutter 3.47.7；生产 `lc-nas`（ssh 别名），sudo 密码由用户当场输入，不落盘。
- 实施步骤（已完成）：服务端 `sync`/`refresh` + `_process_inline`（事务级 advisory lock、预算与单次超时、`_upsert_item` 返回 changed）；客户端 `CatalogFetchController` + 公开 `CatalogFetchPanel`、三个入口接入、详情页单条刷新；版本与文档登记；新源码清单冻结；**生产部署 + 停用夜间 timer（用户 2026-11-08 授权并已执行）**。追加：关键词候选（`query_kind=keyword`、候选 `name`/`brand`、非电子过滤、客户端「选这个」），服务端 `19.0.2.0.12` / 客户端 `1.3.1+9`，**已部署 19.0.2.0.12**（2026-11-08 04:37Z，备份 `/var/backups/lc-elc/20261108T043724Z-before-upgrade/`，树哈希一致、`Modules loaded`、`/web/login` 200、时间戳行 0 错误）。剩余：真实端到端手测、DB 版本行查询、客户端包（Windows 构建因本机缺 Visual Studio/Build Tools 于 2026-11-08 13:01 失败，隔离副本内测试 334/5 通过；日志 `local/build/client-windows-20261108T130154694849/results.json`）。
- 测试命令、实际结果与退出码：
  - `python -I server/ubuntu22.04/odoo_addons/lab_catalog/tests/test_lcsc_remote.py` → **24 tests OK**，exit 0（新增 4 条关键词候选用例）。
  - 新增 `tests/test_catalog_fetch_inline.py`（Odoo `TransactionCase`，已加入 `tests/__init__.py`）→ **未运行**：本机无 Odoo/PostgreSQL，需隔离测试库 `--test-enable`。
  - `flutter test --no-pub --reporter compact` → exit 0，**334 passed / 5 skipped / 0 failed**（基线 326/5）；新增：`catalog_fetch_test.dart` +5（显式 query、`refresh` 透传、跨页面 query、关键词候选、候选名称）、`catalog_suggest_search_test.dart` +2（零结果按钮只在服务端建议时出现 / 无回调时不出现）、`pending_receipt_test.dart` +1（表单内 queued→done 面板）。
  - `flutter analyze --no-pub lib test` → exit 1（仓库既有 info 风格），**0 error / 0 warning / 120 info**。
  - `python tools/repo_check.py` → **exit 0 / PASS / 52 项 / 0 错误**（16 条既有 payload 警告）；`generate_routes.py` 重新生成 94 条后 `--check` exit 0；`git diff --check` exit 0。
- 未验证项及风险：Odoo ORM/HttpCase 未运行；真实网络端到端（C32445874 / TLV77333PDBVR 等）未做；同步抓取占用一个 worker 最多约 16 秒（15 秒预算 + 单次 socket 上限），全局锁保证串行；立创 WAF/限流仍可能导致 `failed`（映射中文原因）；停用批量后新品只靠按需抓取，手工全量重建保留；生产手测待部署。
- 生产部署（2026-11-08 01:00 本地）：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108/modules`；`lab_catalog 19.0.2.0.11` 已生效，三模块树哈希与暂存一致，odoo active、日志 0 错误；备份 `/var/backups/lc-elc/20261107T170002Z-before-upgrade/`（`db.dump` 119,011,646 B / `2654a241…cb4ca5`，`filestore.tar.gz` 12,819,190 B / `ae429c94…f9f414`）；`lcsc-crawler.timer`、`lcsc-crawler-stop.timer` 已 `disabled`/`inactive`。
- 发布文件、hash和回滚点：active 源码清单 `maintenance/registry/source-server-keyword-candidates-20261108.json`（272 文件，tree `21a6800c…31c8e`）与 `source-client-keyword-candidates-20261108.json`（180 文件，tree `c8057727…bd2160`）；上一版 `source-server-on-demand-fetch-20261108.json`（272 文件，77,370 B，sha256 `4f8a851d64fdec7e7143aa61fe2042f68f457f76f512196a015b1db9424fcd3a`，tree `cd6c86b3fd760fc59160d67643f41e7b202b78352f658687be0d6e7ab050e9aa`）与 `source-client-on-demand-fetch-20261108.json`（180 文件，46,125 B，sha256 `8bada64d942943a34f98950e51aaea69826ee7614d8f7997a251525581ddf46d`，tree `c7cc177a1b74fb61d2caa90ccfc0fde8c55cd55ee2e2195b64fe2adeea71da82`），`active-sources.json` 已切到这两份。无安装包产物。回滚：源码清单指针切回 `source-*-catalog-fetch-20261106.json`；生产回滚见交接文档。生产部署前备份仍由 `upgrade_modules.sh` 生成，本轮未触碰生产。
- 交接：`maintenance/handoffs/2026-11-08-on-demand-only-fetch.md`。
