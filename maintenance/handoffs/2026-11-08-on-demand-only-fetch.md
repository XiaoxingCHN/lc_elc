# 维护交接：2026-11-08 立创资料改为纯按需抓取

## 用户目标与已确认边界

- 目标：把「器件资料怎么更新」从夜间批量采集改为纯按需。整库搜索与入库/待入库搜索在零结果时能对**精确 C 码或完整 MPN**当场抓取（目标 20 秒内）；已有条目只在打开该器件时**单条**刷新。
- 用户明确要求：「刷新不能全量刷新，只在访问某一个器件时刷新」。因此详情页入口带 `refresh: true` + 单个 `catalog_code`；没有列表级/全库刷新按钮，服务端也不提供批量刷新接口。
- 用户选择：同步抓取最多等 20 秒；停用夜间定时任务但保留采集器代码；已有条目加「刷新」按钮。
- 生产动作：用户本轮明确「部署并停用」授权，已于 2026-11-08 执行（见下）。

## 当前权威源码、分支和版本

- 分支 `feat/receipt-param-search`，起始 HEAD `605b427`；本轮改动尚未提交。
- `lab_catalog` **19.0.2.0.11**（`__manifest__.py`、`maintenance/registry/components.json`）。
- 客户端 **1.3.0+8**（`clients/app/pubspec.yaml`、`components.json`）。
- 新 active 源码清单：`maintenance/registry/source-server-on-demand-fetch-20261108.json`、`source-client-on-demand-fetch-20261108.json`（旧 2026-11-06 清单未改写）。

## 已完成工作与实际证据

### 服务端 `server/ubuntu22.04/odoo_addons/lab_catalog`

- `tools/lcsc_remote.py`：`_request/_json_request/search_products/resolve_mpn/fetch_product_detail/fetch_cn_page/fetch_one` 全部接受可选 `timeout`/`deadline`；每次 HTTP 的 socket 超时取 `min(timeout, 剩余预算)`，预算耗尽抛 `LcscRemoteError(..., 'budget_exhausted')`。域名白名单检查仍在预算检查之前。
- `models/lab_catalog_fetch.py`：新增 `_process_inline(record, budget_seconds=15)`，只处理刚创建的这一条；`pg_try_advisory_xact_lock(87431001)`（事务结束自动释放，worker 被杀也不会遗留锁），锁被占用直接返回、状态留 `queued`；`budget_exhausted` 写回 `queued` 并把 `attempts` 回退 1（不吃 cron 的重试次数）。`_upsert_item` 现返回 `(item, changed)`，`_run` 仅在内容变化时写库并 bump `catalog_revision`，否则消息为「资料未变化，无需更新。」。
- `controllers/catalog_api.py`：`/lab/api/catalog/fetch` 解析 `sync`（默认 true）与 `refresh`（默认 false）；`refresh` 缺 `catalog_code` 报 `VALIDATION_ERROR`；已有条目短路只在 `not refresh` 时生效；创建成功后 `sync` 才调用 `_process_inline`。`_fetch_suggestion` 的判定（零结果 + 无筛选 + `normalize_query`）未放松。
- `tests/test_lcsc_remote.py`：新增预算测试（过期 deadline 在联网前拦截、白名单优先、`fetch_product_detail`/`resolve_mpn` 透传、socket 超时受剩余预算限制）。
- `tests/test_catalog_fetch_inline.py`（新）：锁占用保持 `queued`、成功 `done` 且只 upsert 一次、预算耗尽回队列、非电子不请求中文页；已加入 `tests/__init__.py`。
- `maintenance/registry/routes.json` 已重新生成（94 条，仅 decorator 行号变化）。

### 客户端 `clients/app`

- 新增 `lib/features/unified/providers/catalog_fetch_controller.dart`：单次抓取 + 轮询（默认 1 秒、最多 60 次）+ `onDone`/`onChanged` 回调；`start(query:, catalogCode:, refresh:)`。
- 新增 `lib/features/unified/widgets/catalog_fetch_panel.dart`：公开 `CatalogFetchPanel`（从 `unified_catalog_screen.dart` 抽出）与 `CatalogFetchRunning`。
- `providers/catalog_providers.dart`：`CatalogNotifier` 内部改用 `CatalogFetchController`；`startFetch` 增加显式 `query`/`refresh`。
- `services/lab_api_client.dart`：`requestCatalogFetch(..., refresh = false)`，仅在 true 时发送 `refresh`。
- `widgets/catalog_suggest_search.dart`：保存 `page.fetchSuggestion`，零结果面板在服务端给出精确建议时显示「立即从立创商城抓取」；状态类改为公开 `CatalogSuggestFieldState` 并提供 `research()`。
- `screens/receipt_screen.dart` / `pending_receipt_screen.dart`：字段下渲染抓取进度/结果；`done` 后重跑检索，不自动选中。
- `screens/unified_item_detail_screen.dart`：新增 `_CatalogRefreshSection`，仅带 C 码的卡片显示「刷新资料」，一次只发一个 `catalog_code`，成功后 invalidate `catalogDetailProvider`/`catalogRowProvider`。

### 测试与检查（本机真实执行）

| 命令 | 结果 |
|---|---|
| `python -I server/ubuntu22.04/odoo_addons/lab_catalog/tests/test_lcsc_remote.py` | 20 tests, OK |
| `flutter test --no-pub --reporter compact` | exit 0，332 passed / 5 skipped / 0 failed（基线 326/5） |
| `flutter analyze --no-pub lib test` | exit 1（仓库既有风格），**0 error / 0 warning / 120 info** |
| `python tools/repo_check.py` | exit 0 / PASS / 52 项 / 0 错误；16 条既有 payload 警告 |
| `python tools/generate_routes.py --check` | exit 0（94 条） |
| `git diff --check` | exit 0 |

## 已完成的生产部署（2026-11-08 01:00 本地 / 2026-11-07T17:00Z）

- 停用夜间 timer：`sudo systemctl disable --now lcsc-crawler.timer lcsc-crawler-stop.timer`；复核两个 timer `disabled`/`inactive`，`lcsc-crawler.service`、`lcsc-catalog-import.service` 均 inactive，unit 与源码保留。
- 暂存：三模块 + ops 脚本上传到 `lc-nas:/home/hbut/lc-deploy-20261108/`；`lab_catalog` 为 `19.0.2.0.11`，关键文件 SHA256 与本机一致。首次运行在备份步骤因 ops 目录缺 `lc_archive.py` 中止（未停服务、未换代码）；补齐后重试成功。
- 升级：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108/modules`，退出前完成备份、停服务、换代码、`-u`、健康检查、起服务。备份 `/var/backups/lc-elc/20261107T170002Z-before-upgrade/`：`db.dump` 119,011,646 B / `2654a241910351418d16f148f2e9ad3979811fb483561db62330952d04cb4ca5`；`filestore.tar.gz` 12,819,190 B / `ae429c940b705c184c7f34511a97299a69d06b424cb47a36b6f8a9d989f9f414`；`MANIFEST.json` 16,420 B / `bed14d02762e723bca87738b417d5d6cac982c84937cf44df97b529b4b49e4c3`；旧模块源码在 `module-source-before-upgrade/`。
- 验证：`/opt/odoo/custom-addons` 中 `lab_inventory`/`lab_catalog`/`lab_workflow` 的逐文件树哈希与暂存副本完全相同；`lab_catalog` 版本 `19.0.2.0.11`；`odoo.service` active；`/web/login` 带 `X-Odoo-Database` **200**；17:00Z 起日志 **0 条 ERROR/CRITICAL/Traceback**，17:00:56Z `Modules loaded`（55 模块）。

## 追加：关键词候选（2026-11-08，源码 `19.0.2.0.12` / `1.3.1+9`，未部署）

用户确认的边界：**大于 5 个字符的搜索**不再要求完整型号。这类查询只换候选，候选列表显示立创
的显示名；只有真正选定某一条之后才抓取该器件的完整资料。

- `lcsc_remote.normalize_keyword`：NFKC + 去多余空白，`len >= 6` 且至少一个字母才放行
  （纯数字、≤5 字符直接拒绝，不联网）。`search_candidates` 只调用一次公开搜索接口；
  `candidates_from` 增加 `name`（结果里的 `title`）与 `brand`，并按一级分类过滤掉非电子产品。
- `lab.catalog.fetch.request.query_kind` 增加 `keyword`；`_run` 的关键词分支只写
  `candidates_json` 并停在 `candidates`，**不打开中文详情页、不写库**。选定后客户端带
  `catalog_code` 重新提交，走原有 `c_code` 分支才会真正抓取。
- `/lab/api/catalog/fetch` 接受关键词；`/lab/api/catalog/search` 的 `fetch_suggestion`
  对零结果的长关键词返回 `kind=keyword`。客户端 `CatalogFetchCandidate` 显示
  `name · package (C码)`，按钮为「选这个」。
- 测试：`test_lcsc_remote.py` **24/24**；`flutter test --no-pub` **334 passed / 5 skipped**；
  `flutter analyze` 0 error / 0 warning / 120 info。
- 仓库：新冻结并激活 `source-server-keyword-candidates-20261108.json`（272 文件，tree `21a6800c…31c8e`）与 `source-client-keyword-candidates-20261108.json`（180 文件，tree `c8057727…bd2160`），旧清单未改写；`repo_check.py` exit 0 / PASS / 0 错误。
- **生产部署（2026-11-08 12:37 本地 / 04:37Z）**：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108b/modules`，退出码 0；`/opt/odoo/custom-addons` 为 `lab_catalog 19.0.2.0.12`，三模块树哈希与暂存一致；04:38:52Z `Modules loaded`，`/web/login` 200，时间戳行 0 条 ERROR/CRITICAL/Traceback，两个 `lcsc-*.timer` 仍 disabled。备份 `/var/backups/lc-elc/20261108T043724Z-before-upgrade/`（`db.dump` 119,023,251 B / `a6ad4c1b…4b55c3`，`filestore.tar.gz` 12,819,190 B / `08670f20…4e0ea3`，`MANIFEST.json` 18,045 B / `f97b887e…c948ba0d`）。脚本自身健康检查仍把 `/web/login` 的 303 判为失败（既有缺陷），独立复核为 200。
- 未做：未构建 `1.3.1+9` 包、未做真实网络手测、DB 版本行未查、未提交。

## 剩余工作与阻塞

1. **真实网络端到端手测**：整库搜索与入库搜索各搜一个未收录 C 码（如 C32445874），≤20 秒得到 `done`/候选/明确失败原因；详情页「刷新资料」后只有该行 `fetched_at` 变化；锁被占用时返回 `queued` 且前端继续轮询。需要客户端登录，由用户执行。
2. **DB 侧版本行未查询**：`ir_module_module.latest_version` 需 DB 访问（生产以 `runuser -u odoo psql` 只读查询），本轮未执行。
3. **Odoo ORM 用例未运行**：本机无 Odoo/PostgreSQL，`test_catalog_fetch_inline.py` 需在隔离测试库执行，不得对生产库跑测试。
4. 客户端 `1.3.0+8` 安装包未构建；真实 GUI/触控未验证。
5. 本轮改动未提交、未推送。

## 依赖和产物

- Python 3 / Flutter 3.47.7（`F:/lc_elc/dependencies/sdk/windows/flutter/bin/flutter`，`--no-pub`）。
- 无新增 pub / pip 依赖。
- 源码清单见 `maintenance/registry/active-sources.json`；回滚把指针切回 `source-*-catalog-fetch-20261106.json` 即可，旧清单未被改写。
- 凭据：生产 sudo 由用户在终端当场输入，未落盘。

## 生产状态和回滚

- 生产已变更（用户授权）：`lab_catalog 19.0.2.0.11` 生效，`lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2` 同树重装（哈希与 2026-11-06 部署内容一致）；`lab_team_web 19.0.1.2.1` 未参与。夜间两个 timer `disabled`。
- 回滚点：`/var/backups/lc-elc/20261107T170002Z-before-upgrade/`（DB dump + filestore + 旧模块源码）。回滚 = 恢复旧模块源码并 `-u`；如要恢复批量采集再 `systemctl enable --now lcsc-crawler.timer lcsc-crawler-stop.timer`。注意 `ir.cron` 25（队列回退）不要停。
- 风险：同步抓取占用一个 Odoo worker 最多约 16 秒（15 秒预算 + 单次 socket 超时上限），全局 advisory lock 保证同一时间只有一条抓取；停用批量后新品只靠按需抓取，手工全量重建仍可用。
