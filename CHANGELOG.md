# 变更记录

## 2026.11.18 Flutter 客户端 Linux 1.3.2+10 构建（WSL Ubuntu 22.04；未实机验收）

- 在 WSL Ubuntu 22.04 用归档工具链（Flutter 3.47.7 + `dependencies/wsl-build-tools/wsl-build-tools-20261019.tar.gz` 的 pubcache/sysroot/prebuilt）执行 `tools/build_client.py --platform linux --test`，pub get / flutter test / flutter build linux 三步 **exit 0 / 0 / 0**，`flutter test` **340 passed / 5 skipped**。
- 产物：`clients/linux/releases/1.3.2+10/LC_ELC-Linux-1.3.2+10.tar.gz`，**16,503,485 B**，sha256 `4f20594cfeadd040fa8d7116550560b9d4b314ec63e30eece8d036b64df78e5a`；bundle 39 MB，`client-install.json` = 1.3.2 / build 10 / linux；`lib/libapp.so` 含“已选中，正在读取内部档案”等字符串；可执行文件 sha256 `1f555b91…1201e`。登记 `artifact-client-linux-1.3.2-10-20261118.json`。
- 边界：**未附 `deps/` 离线 DEB**，运行时需系统 GTK3/libsecret/cups；未做真实登录、打印、扫码、SecretService 与桌面实机验收；未提交签名发布清单、未推送。

## 2026.11.14 旧工作区审核与退役（F:\lc_elc_workspace 已删除；补档 2,870 文件；F: 可用 64.1 GB → 109 GB；`repo_check` exit 0；未提交/未推送）

- 对象与结论：`F:\lc_elc_workspace` 原为 **178,156 文件 / 49,676,894,303 B**（2026-10-14 从桌面整包复制）；合并已在 **2026-10-19** 完成（commit `3b3c3af`、tag `archive-2026.10.19`、`original_files_deleted: 0`）。本次审核补档后删除原件，目录已不存在。
- 审核（`local/manifests/merge-recheck-20261114.json` / `.log`）：台账 138,295 条，138,294 条有目标、1 条无目标跳过；**138,107** 个目标仍在；缺失 **187** 个全部是 `dependencies/sdk/windows/flutter/.pub-preload-cache/*.tar.gz`（SDK 可重建缓存）；抽查 **820** 个哈希，**51** 个与当时不同（迁移后仓库继续演进的源码），旧修订已补档。`lcscmigration/components.sqlite3` 与 `data/catalog/checkpoint-20261015/components.sqlite3` 全量 SHA256 一致：`ac536621032c6028b708847b4ee0d74669008c9dfd2dee480991dfa11ad60823`（各 3,547,037,696 B）。26 个 reparse point 目标全在工作区内部；外部 junction `lc_elc\build_work\e -> E:\lcb\build` 用 `rmdir` 单独删除，`E:` 未受影响（该目标本就不存在）。
- 补档（Git 排除，**2,870 文件 / 1,402,575,621 B**；逐文件见 `local/manifests/workspace-retirement-20261114.json`）：`local/archive/workspace-candidates/` **570** 个未发布构建候选（965,324,105 B，含 560 MiB 服务端离线重建包与两个 Linux 客户端 tar.gz）；`local/archive/eda/workspace-intermediates/` **30** 个 EDA 3.x 只留原件的构建产物（186,794,874 B）；`local/archive/evidence/analysis-workspace-20261014/` **2,219** 个 WorkBuddy 记录（249,753,330 B）；`local/archive/source-import-before-format/` 新增 **51** 个不在 Git 的旧修订（703,312 B；该目录原有 4 个）。
- 删除：`robocopy <空目录> F:\lc_elc_workspace /MIR /XJ` 删除 **176,743 文件 / 46.243 GB**、**0 失败**，随后 `rmdir` 空根目录；F: 可用空间 **64.1 GB → 109 GB**；删除日志 `local/manifests/workspace-purge-20261114.log`。`python tools/repo_check.py` **exit 0**。
- 未归档、随删除消失：可重建的构建缓存/运行时状态、`output\` 的接线图、`.workbuddy` 会话状态。
- 未做：未 commit / 未 push（分支 `codex/receipt-search-feedback` 仍在工作区）；未改源码；未执行任何生产操作。

## 2026.11.10 修复制袋贴标“选择器件无反应”，客户端 1.3.2+10（Windows / Android；未上更新通道）

- 版本：`clients/app` `1.3.1+9 → 1.3.2+10`（`pubspec.yaml`、`components.json` 一致）。`1.3.1+9` 成品已存在，按“旧包不覆盖”新开 `clients/{windows,android}/releases/1.3.2+10`。服务端未动。
- **为什么改**（用户原话“选择器件无反应，你能不能调试好再给我”，截图：输入 `STM32F401CCU` 后提交仍提示“请选择器件…”）：选中建议后有三条静默路径——
  - `_selectSuggestion` 经 `_run()` 执行，而 `_run()` 在 `_busy` 为真时直接 return，点击被吞掉；
  - 档案 `detail()` 返回前不改任何界面状态，慢就“没反应”；抛错时旧代码把选中整条丢弃（`catch { rethrow; }`）；
  - 建议面板被外部点击/失焦关闭后输入框仍有文字，再点输入框不会重新搜索（`TextField` 没有 `onTap`）。
  - 另修：`_releaseSuggestion` 用 `item_key` 比对，而详情会把 `lcsc:C…` 换成 `lab:…`；键不同就不清除，改词后仍保留旧选中，可能给旧器件制袋。
- **修复**：`pending_receipt_screen.dart` 选中**当帧提交**（`_item` 立即赋值），随后异步读档案；读取中显示“已选中，正在读取内部档案…”并禁用建袋；失败仍保留选中并提示原因；新增 `_selectionFromSuggestion`，按“是否来自建议”清除选中。`catalog_suggest_search.dart` 增加 `onTapAlwaysCalled` + `_onFieldTap`（关闭的面板再次点输入框会重新搜索）与 `_pickedLabel`（选中回写的标签不会当成查询再发一次）。
- **测试（本机真实执行）**：`flutter test --no-pub test/features/unified/catalog_suggest_search_test.dart` **28 passed**（新增 6 条：再次点输入框重开面板、选中后点输入框不搜标签、跨帧触摸点击仍提交、选中当帧可见且档案读取中禁止建袋、详情换 `item_key` 后改词仍清除、详情失败仍提交并提示）；全量 `flutter test` **340 passed / 5 skipped / 0 failed**；`flutter analyze --no-pub lib test` **0 error / 0 warning / 119 info**。
- **产物**
  - Windows：`clients/windows/releases/1.3.2+10/LC_ELC-Windows-1.3.2+10-x64.zip`，**18,391,710 B**，sha256 `35695044b14c5ad9da502246dd23db0b402d079238e72d0659a391537c992ba0`，19 文件；`lab_inventory_client.exe` sha256 `d9d5be41dcd933ccff936fc718561110d3d7f076c41445daf8f268b241d21764`；`client-install.json` = 1.3.2 / build 10 / windows；`Get-AuthenticodeSignature` = `NotSigned`（与既往一致）；冒烟进程 RUNNING 6s → STOPPED。
  - Android：`clients/android/releases/1.3.2+10/LC_ELC-Android-1.3.2+10.apk`，**74,876,669 B**，sha256 `ae6df079106f983aaad2960c969f30d2c77c13a30b1353f8a0517f78d974c493`；`com.example.lab_inventory_client`、versionName 1.3.2、versionCode 10、minSdk 24 / target 36；证书 SHA-256 `8b4c2409…9ff43` 与 `local/private/signing/windows-debug.keystore` 一致；三个 ABI 的 `libapp.so` 均含“已选中，正在读取内部档案”。
- **构建（本机真实执行）**：Windows `pub get / flutter test / flutter build windows --release` **exit 0 / 0 / 0**，构建 68.9s；Android 三步 **exit 0 / 0 / 0**，Gradle `assembleRelease` 175.6s。Windows 两个环境坑已在交接写明：`--pub-cache` 相对路径会被解析到构建副本目录（`pub get --offline` 报 json_serializable 缺失），必须传绝对路径；`dependencies/pub-cache-windows` 的 `printing 5.15.1` 无 `PDFIUM_LOCAL_ARCHIVE` 支持会去 GitHub 下 pdfium（本机 0 字节失败），必须用本工作区 `local/pub-cache-windows` 的已打补丁副本。
- **清单与登记**：active 客户端清单 `maintenance/registry/source-client-1.3.2-10-20261110.json`（180 文件，tree `d7aca661f9949ee0dfa88a2636d7863423b9487d3c84e512ffebb3f42293cfdb`）；产物登记 `artifact-client-windows-1.3.2-10-20261110.json`、`artifact-client-android-1.3.2-10-20261110.json`；两个 release 目录各附 `SOURCE_MANIFEST.json`。
- **未做/边界**：签名发布清单（需真实 `source_commit`）、客户端更新通道发布（生产写入需授权）、真实登录后的搜索/档案读取、实机点击手感、Android 实机安装与升级、打印、扫码、应用内更新下载均未验证；未提交/推送。

## 2026.11.10 Flutter 客户端 1.3.1+9 打包发布（Windows / Android；未上更新通道）

- 版本保持 `1.3.1+9`（`pubspec.yaml` 与 `components.json` 一致）：这批改动此前只有源码与 11-08 的 `local/build` 候选，从未生成可安装包；Windows 已发布版仍是 1.0.1、Android 仍是 1.1.3+6。
- **产物**
  - Windows：`clients/windows/releases/1.3.1+9/LC_ELC-Windows-1.3.1+9-x64.zip`，**18,386,856 B**，sha256 `c0b2e2f01ec09ab1416a84f9f40b02c1c622b13a7243669b7bc91e702388df73`，19 文件；`lab_inventory_client.exe` sha256 前 16 位 `0e9a9bd8f98e1f05`；`client-install.json` = 1.3.1 / build 9 / windows；`Get-AuthenticodeSignature` = `NotSigned`（与既往一致）。
  - Android：`clients/android/releases/1.3.1+9/LC_ELC-Android-1.3.1+9.apk`，**74,876,669 B**，sha256 `87c0f8cd64003635e2f1a7dd01cf9e1e39a2da79d074e77f56e50904c3e34594`；`com.example.lab_inventory_client`、versionName 1.3.1、versionCode 9、minSdk 24 / target 36；`apksigner` 证书 SHA-256 `8b4c2409604fcd6fdd65dc5344afca7bffb81f07df2c77c210bcef1a78a9ff43` 与 `local/private/signing/windows-debug.keystore` 逐位一致，未生成新签名身份。
- **构建与测试（本机真实执行）**：`tools/build_client.py` 两个平台均 `pub get / flutter test / build` 三步 **exit 0 / 0 / 0**；`flutter test` 各 **334 passed / 5 skipped**；Android Gradle `assembleRelease` 602.1s；Windows 冒烟进程 RUNNING→STOPPED。两个包的 AOT 载荷均含“立即从立创商城抓取”“刷新资料”“选这个”，确认打包的是当前工作区源码。
- **内容**：器件库按需抓取（整库搜索空态、入库/待入库表单内“立即从立创商城抓取”、关键词候选选择）、详情页「刷新资料」只刷新当前 C 码、参数搜索；登录记忆与离线只读边界不变。
- **默认连接**：构建写入 `--dart-define=LAB_ODOO_URL=http://192.168.31.105:8069`、`LAB_ODOO_DB=LcHardwareHouse`，新装即走内网直连（不经 Netlify → bore）；登录页仍可改，运行期输入优先。
- **清单与登记**：active 客户端清单 `maintenance/registry/source-client-1.3.1-9-20261110.json`（180 文件，tree `c8057727f4775d278c75254fa3d5817103ddf8fca89b86041353d282e5bd2160`）；产物登记 `artifact-client-windows-1.3.1-9-20261110.json`、`artifact-client-android-1.3.1-9-20261110.json`；两个 release 目录各附 `SOURCE_MANIFEST.json`。`python tools/repo_check.py` exit 0。
- **未做/边界**：签名发布清单（`client_release.py publish` 需真实 `source_commit`，而改动仍在工作区）、客户端更新通道发布（生产写入，需另行授权）、真实登录/入库/领用、实体打印、扫码、Windows DPAPI、Android 实机安装与覆盖升级、应用内更新下载均未验证；未提交/推送。

## 2026.11.09 器件详情链路彻底修复：官方通道兜底 + 占位档案回填（19.0.2.0.17 / 19.0.1.2.7 已部署）

- 版本：`lab_catalog 19.0.2.0.15 → 19.0.2.0.17`、`lab_team_web 19.0.1.2.4 → 19.0.1.2.7`（manifest、`controllers/common.py` 的 `lc_version`、`tests/test_entry_contract.py`、`components.json` 同步）。
- **为什么改**（用户截图 + 原话"我的器件详情呢"、"修BUG要彻底不要每次都等我去说你的的逻辑问题"）：
  - `F407IGH6` 页面同时出现立创候选面板和"没有匹配的器件 / 立即从立创商城抓取"空态；
  - 选定 `C503071` 后卡片有「查看器件详情」，点进去只有本地档案、没有参数/文档；
  - 生产抓取记录显示 `C503071`（id 16）连续 3 次 `failed`，"立创返回了验证页"——中文详情页 `item.szlcsc.com` 返回阿里云 WAF 的 JS 验证页（响应里是 `aliyun_waf_aa` + `renderData`），而旧代码把"中文页不可用"当成整条抓取失败，连官方 SMT 接口已经给出的名称/型号/品牌/封装/库存/价格/13 条参数一起丢掉。
- **后端（`lab_catalog`）**：
  - `models/lab_catalog_fetch.py`：中文页抛出 `verification_page` 且官方通道有数据时，改用 `_parsed_from_official()` 按官方事实入库（分类优先按官方 `componentType` 名称匹配本地分类树，匹配不到退回 wmsc `parentCatalogId`）；请求如实置 `done` 并在 message 写明"已按官方接口收录（中文详情页被立创风控拦截…）"。没有官方数据时仍按可重试错误处理（不假装成功）。**不求验证、不伪造 cookie**，与工具模块既有边界一致。
  - `_upsert_item()` 新增 `_enrich_stub_templates()`：资料入库后把该 C 编号下"立创物料 Cxxx（待补全）"的最小档案就地补全（名称/型号/品牌/封装/文档/规格，只填空字段、人工值优先），并 bump inventory revision。此前网页入库建的档案没有 `lab.catalog.binding` 行，资料到了也不会回填，袋标签会一直打印"（待补全）"。
  - `models/lab_catalog_item.py`：新增 `_template_ids_by_codes()`，`_decorate()`（搜索/列表）与 `_detail_catalog_item()`（详情）由"只查绑定表"改为"绑定表 ∪ 档案自身归一化 C 码"，让网页入库建的档案在搜索/详情里能看到自己的库存、袋与流水。
  - 验证页错误文案改为"立创中文详情页触发了访问验证（风控，不是实验室系统故障）；官方接口资料不受影响，稍后重试即可。"
- **前端（`lab_team_web`）**：
  - `pages/receipts.js`：`renderCandidates()` 先收起下拉（候选与旧空态不再同屏，19.0.1.2.5）；`startFetch()` 同样收起旧空态；新增 `normQuery()` 让比较与服务端一致（去空白 + NFKC + 大写），修掉 `STM32 G437` 这类输入永远挂不上建议、自动接续不触发的问题；候选点击在建袋锁定时直接提示并返回（不再改输入/继续抓取）；`done` 但拿不到 `item_key`、或建袋锁定期间只提示成功，不再拿旧输入去解析（避免把上一个器件结果当成这一次）。
  - `views/pages.xml`（器件详情）：`local_only` 时显示说明"这个 C 编号还没有从立创抓取资料：下面只有实验室档案与流水…"，不再给用户一张看不出原因的空参数页。
- **生产验证（2026-11-09 22:12–22:28 CST）**：
  - 用部署后的代码对 `C503071` 真实抓取（`odoo shell`，只写资料）：`request 18 done`，留言为官方兜底文案；`lab_catalog_item` 695220 收录，`STM32F407IGH6 / ST(意法半导体) / UFBGA-201 / 13 条参数 / 分类 单片机(MCU/MPU/SOC)`；占位档案 #10 名称已从"立创物料 C503071（待补全）"回填为真实名称，`lab_mpn=STM32F407IGH6`、`lab_package=UFBGA-201`；`detail('lcsc:C503071')` 返回 13 条参数且 `lab_template_ids=[10]`（此前因无 binding 为空）。
  - 四次部署均 `-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback，服务 active、`/web/login` 带库头 200、部署后日志 0 错误；DB 现为 `lab_catalog|19.0.2.0.17`、`lab_team_web|19.0.1.2.7`（`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2` 未变）。
  - 备份：`20261109T141243Z`（19.0.1.2.5，filestore sha256 `4ac71554…b60c`）、`20261109T142322Z`（.16/.6，`7dfc749b…2ba8`）、`20261109T142603Z`（.7，`85cd4dea…13c9`）、`20261109T142847Z`（.17，`da583eee…26a1`）。脚本健康检查仍把 303 判失败（既有缺陷），已独立复核带库头 200。
- **测试（本机真实执行）**：`test_catalog_fetch_inline.py` 新增 3 条（验证页 + 官方事实 → `done` 且参数保留；无官方事实 → 仍 `queued` 可重试；`_enrich_stub_templates` 回填占位档案）；`test_catalog_param_search_orm.py` 新增 1 条（无 binding 的档案在 `_template_ids_by_codes`/`detail` 可见）；`test_p3_ui_consistency.py` **27/27**（新增 `normQuery`、候选点击锁定、`done` 无 item_key、抓取开始收起空态、详情页 local_only 说明）；`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_lcsc_remote.py` 25/25、`test_lcsc_openapi.py` 23/23；`test_combobox.mjs` 23/23、`test_workflow_core.mjs` 19/19、`node --check receipts.js` OK；`repo_check.py` exit 0、`generate_routes.py --check` exit 0（94 条）、`git diff --check` 0。两条 Odoo ORM 用例需数据库环境，本机未执行，已用生产 `odoo shell` 只读/只写这一条真实数据复核等价断言。
- 清单：依次冻结并激活 `source-server-web-fetch-entry-20261109-r6.json`（19.0.1.2.5）、`…-r7.json`（19.0.2.0.16 / 19.0.1.2.6，tree `1f509b6d…54e6da`）、`…-r8.json`（19.0.1.2.7，tree `03811a23…7afcf56`）、`…-r9.json`（19.0.2.0.17，274 文件，tree `4144e419…c9b6`，当前 active）；更早清单原样保留。
- **仍未验证/边界**：立创中文页的 WAF 是否会自行解除（不做验证码破解，官方通道兜底已能给出参数；分类细分与文档仍等中文页恢复）；官方兜底路径的浏览器端到端手测；`C503071` 的中文文档（PDF）暂时为空；请求 17（`STM32F103C8T6` → `C8734`）是修复前失败的旧记录，未自动重跑。未提交/推送。

## 2026.11.09 采购入库「无感接续检索」+ 已选器件详情入口（19.0.1.2.4 / 19.0.2.0.15 已部署）

- 版本：`lab_team_web 19.0.1.2.2 → 19.0.1.2.3`（`components.json`、`controllers/common.py` 的 `lc_version` 同步）；`lab_catalog`/`lab_inventory`/`lab_workflow` 与客户端源码不变。
- **为什么改**：用户在手机端明确要求两条——"无感搜多，不要每次都要专门点一下搜索立创商城"，以及"关键词先检索本地，真正选定后再快速把信息拉下来"；另外抓到器件后，手机上看不到入口去查看它的完整详情（参数/文档/档案/流水）。
- 网页端（`lab_team_web/static/src/js/pages/receipts.js`）：
  - **本地优先、零结果自动接续**：下拉仍先查本地库；只有本地零结果且服务端返回 `fetch_suggestion` 时，输入停止 800ms 后**自动**发起立创查询，不再需要点按钮。关键词 → 只列候选（人选定后才抓）；精确 C 码/完整 MPN → 直接抓资料。同一关键词本次页面只自动打一次；输入一变立即取消计时器；抓取中或建袋锁定时不触发。原空态按钮保留为失败后的显式重试入口。
  - **候选选定后才拉详情**：候选面板点选某个 C 码后才 `catalogFetch` 抓完整资料（与上一版一致），抓到后输入收敛为 `lcsc:Cxxxx` 并继续走既有解析。
  - **已选器件详情入口**：物料卡片新增「查看器件详情（参数 / 文档 / 档案与流水）」，指向 `/lab/items/<item_key>`（新标签页，`rel="noopener noreferrer"`）；冒号按 `team.js itemHref`/后端 `quote_item_key` 约定保留，地址形如 `/lab/items/lcsc:C54110218`。没有 `item_key` 时隐藏入口。
- `views/workflow_receipt.xml`：`data-slot="material-detail"` / `material-detail-link` 标记，模块升级后视图 arch 已含该标记。
- 测试（本机真实执行）：`test_p3_ui_consistency.py` **19/19**（新增 4 条：只在零结果分支排队、800ms 去抖 + `onQuery` 取消、每个关键词只自动一次、详情链接的 `target/rel` 与 URL 约定）；`test_p3_web_contract.py` **28/28**、`test_entry_contract.py` **11/11**；`test_combobox.mjs` **23/23**、`test_workflow_core.mjs` **19/19**；`node --check receipts.js` OK；`repo_check.py` exit 0、`generate_routes.py --check` exit 0（94 条，无新增路由）、`git diff --check` 0。
- 清单：新冻结并激活 `source-server-web-fetch-entry-20261109-r3.json`（274 文件，tree `106ef58b…e15b4819`，清单 sha256 `0ef9d7c7…c835067`）；`…-r2.json` 与更早清单原样保留。
- **生产部署（2026-11-09 13:58 CST / 05:58Z）**：`upgrade_modules.sh --code-dir ~/lc-deploy-teamweb-20261109T135736Z/mods --modules lab_team_web`——备份 `/var/backups/lc-elc/20261109T055838Z-before-upgrade`（归档 sha256 `3a7cafb6…949b87`）→ 停服务 → 换代码（归属 132:141 已校验）→ `-u` **退出码 0、0 条 ERROR/CRITICAL/Traceback** → 起服务。DB 复核 `lab_team_web|19.0.1.2.3|installed`（其余三模块版本未变）；`odoo.service` active；`/web/login` 带库头 **200**（脚本仍把 303 判失败，既有缺陷）；`/lab_team_web/static/src/js/pages/receipts.js` 由 Odoo 直接返回且含新逻辑；`ir_ui_view` 中该视图 arch 已含 `material-detail-link`；重启后日志 0 条 ERROR/CRITICAL/Traceback。
- 部署脚本首次执行在"归属修正/校验"处中止（`ops/` 暂存目录漏了 `lc_archive`/`lc_service`/`odoo_restore` 三个同目录依赖，服务已停止、代码已替换）。补齐依赖后**原样重跑**同一脚本成功；数据未回滚、未执行 `-u` 以外的写操作。
- **19.0.1.2.4（同日 14:21 CST，按用户实测修正）**：用户反馈"为什么还要自己点从立创抓取"——截图显示输入 `STM32G434` 得到"立创未找到"后再输入 `STM32G437`，只剩手动按钮。根因：前一笔抓取尚未结束时计时器触发，`state.fetching` 为真就直接丢弃，且结束后没有补排。修正：`scheduleAutoFetch` 在抓取中记下 `state.autoFetchPending`，`startFetch` 结束时 `resumeAutoFetch()` 按当时的输入与建议补排一次（仍受"同一关键词只一次"和输入一致性约束）；同时 `finishFetch(result, query)` 先比对当前输入，十几秒后才返回的旧结果不再覆盖用户已改的输入、也不弹旧关键词的候选/错误。版本 `19.0.1.2.3 → 19.0.1.2.4`；备份 `/var/backups/lc-elc/20261109T062109Z-before-upgrade`（归档 sha256 `898baf77…34aa9a`），`-u` 退出码 0 / 0 条 ERROR·CRITICAL·Traceback；DB `lab_team_web|19.0.1.2.4|installed`，静态 `receipts.js` 86,734 B 含新逻辑，重启后日志 0 错误。测试：`test_p3_ui_consistency.py` **21/21**（新增 2 条：抓取中改词要补排、旧结果不得覆盖输入）。清单切到 `source-server-web-fetch-entry-20261109-r4.json`（274 文件，tree `63c10f8c…a2b11fc`，清单 sha256 `a940dc97…baf7fa`）。
- **19.0.2.0.15（同日 17:21 CST，抓取慢的根因修复）**：用户输入 `STM32F427IIH6`（立创有 C503072）后仍只看到手动按钮，并出现"找不到该对象"。查生产抓取记录（`lab_catalog_fetch_request` id 13）确认自动抓取确实发出了，但 15 秒预算内只走完搜索就被迫转后台；进一步在生产机计时发现 `lcsc_remote.search_products` 单次耗时 **120.6 秒**，而同一时刻 `curl` 只要 0.7 秒。根因：`wmsc.lcsc.com` 是 CloudFront，AAAA 记录在本机网络上不可达，`urllib` 按 `getaddrinfo` 顺序逐条尝试 IPv6（每条 socket 超时 15 秒），把同步预算和后端队列全部拖死（当时 cron 也卡在同一行 5 分钟以上）。修复：`lcsc_remote` 改用只解析 IPv4 的 `_IPv4HTTPSConnection`（证书仍按域名 SNI 校验），并在读响应时逐块核对预算，慢速吐数据也会在预算处中止。生产机用同一份代码实测：搜索 0.55s、详情 0.48s、中文页 0.36s，合计约 1.4 秒。测试 `test_lcsc_remote.py` **25/25**（新增 IPv4 断言；请求层测试改为替换 `_open_response` 这个接缝）。部署：备份 `/var/backups/lc-elc/20261109T092100Z-before-upgrade`（归档 sha256 `6bc3cf32…c701c`），`-u lab_catalog` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_catalog|19.0.2.0.15|installed`，服务 active、`/web/login` 带库头 200。清单切到 `source-server-web-fetch-entry-20261109-r5.json`（274 文件，tree `18007fa1…14b48`，清单 sha256 `460ff5ae…f5e4`）。
- **未验证**：手机端真实打字触发自动接续（去抖/取消的实际手感）、`not_found`/失败态呈现、限流（每用户 5 个进行中 / 每小时 20 次）与"锁被占用退回 cron"；自动关键词查询会增加立创调用量，需观察。

## 2026.11.09 网页端「采购入库」接入按需抓取（19.0.2.0.14 / 19.0.1.2.2 已部署）

- 版本：`lab_catalog 19.0.2.0.13 → 19.0.2.0.14`、`lab_team_web 19.0.1.2.1 → 19.0.1.2.2`（`components.json` 已同步）；客户端源码不变（`1.3.1+9`）。
- **为什么改**：用户在网页端采购入库输入 `tlv77`，本地库无结果时页面只说"没有匹配的器件"，没有任何到立创抓取的入口（截图 2026-11-08 23:02）。客户端（Flutter）早有这个入口，网页端一直没有。
- 网页端（`lab_team_web`）：
  - `static/src/js/pages/receipts.js`：料号输入零结果时，**只有服务端 `fetch_suggestion` 存在**才在空态追加按钮——精确 C 号 / 完整 MPN 显示「立即从立创商城抓取」，≥5 字符含字母的关键词显示「到立创商城查候选」。点击后 `sync` 抓取（客户端超时 30 秒）；服务端 15 秒预算内没抓完则每 1.5 秒轮询 `/lab/api/catalog/fetch_status`（最多 60 秒）。`done` → 输入收敛为 `lcsc:Cxxxx` 并走既有 `resolveItem()`；`candidates` → 在表单内渲染候选面板（名称/型号/封装/品牌/C 码），选定后只抓该 C 码；`not_found` / 失败 → 中文提示。**不写库存、不自动建袋、不改选中**。
  - `static/src/js/pages/receipts.js` 的候选建议只对应当前输入（晚到的响应不会给新关键词挂旧按钮）；输入一变立刻作废按钮与候选面板。
  - `controllers/common.py`：登记 `catalogFetch` / `catalogFetchStatus` 两个端点（指向既有 `/lab/api/catalog/fetch`、`/fetch_status`，不新增路由）；同时把页面展示版本 `lc_version` 从 `19.0.1.1.0` 修正为 `19.0.1.2.2`（与 manifest 一致，`test_entry_contract.py` 原有的 2 条失败正是这个不一致）。
  - `static/src/css/team.css`：新增 `.lc-fetch-panel/.lc-fetch-candidate` 样式，并给空态按钮补上 `[data-kind="empty"]` 的样式（原来只有失败态有）。
- 服务端（`lab_catalog`）：关键词候选门槛 `MIN_KEYWORD_LEN` **6 → 5**（仍要求至少一个字母，纯数字照旧拒绝），因为用户实际输入的是 `tlv77` 这类 5 字符型号前缀；校验文案同步改为"至少 5 个字符"。关键词仍**只换候选、不打开详情页、不写库**，选定 C 码后才抓取。
- 测试（本机真实执行）：`test_lcsc_remote.py` **24/24**（门槛用例改为 `TLV9` 拒绝 / `TLV90` 放行）；`test_lcsc_openapi.py` **23/23**；`test_p3_web_contract.py` **28/28**、`test_p3_ui_consistency.py` **15/15**、`test_entry_contract.py` **11/11**（修正版本后由 2 失败转全过）；`node tests/test_combobox.mjs` **23/23**（新增 2 条：`emptyAction` 只在给出动作时渲染按钮、点一下才执行且先关面板 / 只对当前关键词有效）、`node tests/test_workflow_core.mjs` **19/19**；`node --check receipts.js` OK。
- 部署脚本：`upgrade_modules.sh` 原来把模块列表写死成 `lab_inventory,lab_catalog,lab_workflow`，`lab_team_web` 根本不在可部署范围。新增 `--modules a,b,c`（默认仍是原来三个），预检/换代码/归属校验/`-u` 全部按该列表执行。**同时把仓库里该脚本转回 LF**：Windows 工作区的 CRLF 会让远端 `set -euo pipefail` 直接报 `pipefail: 无效的选项名`（第一遍部署就是这样在 16 行退出的，未备份、未停服）。
- 仓库：新冻结并激活 `source-server-web-fetch-entry-20261109.json`（274 文件，tree `a3ee3678…a899472`，77,944 B，清单 sha256 `b204f65c…39cbbeb`）；本轮先冻结的 `…-20261108.json` 与 `…-r2.json` 保留未改；`repo_check.py` exit 0；`generate_routes.py --check` exit 0（94 条，无新增路由）；`git diff --check` 0。
- **生产部署（2026-11-09 00:27 CST / 2026-11-08T16:27Z）**：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261109/modules --modules lab_catalog,lab_team_web`——备份 → 停服务 → 换两模块代码（旧代码保留）→ `-u` **退出码 0、0 条 ERROR/CRITICAL/Traceback** → 起服务。备份 `/var/backups/lc-elc/20261108T162707Z-before-upgrade`（归档 sha256 `35d17e9e…9ce4d`）。DB 复核：`lab_catalog|19.0.2.0.14|installed`、`lab_team_web|19.0.1.2.2|installed`（`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2` 未变）。`odoo.service` active；`/web/login` 无库头 303、带 `X-Odoo-Database` **200**（脚本把 303 判失败是既有缺陷）；部署后 10 分钟日志 **0 条 ERROR/CRITICAL/Traceback**。磁盘与 HTTP 双重复核：`/opt/odoo/custom-addons` 两模块版本正确、`common.py` 与 `receipts.js` 各含 2 处 `catalogFetch`、`workflow_core.js` 含 `emptyAction`、`MIN_KEYWORD_LEN = 5`；`/lab_team_web/static/src/js/pages/receipts.js` 由 Odoo 直接返回的也是新代码。
- **浏览器实测（2026-11-09 01:0x CST，用户手机）**：网关补齐后重试 `tlv77` 已正常，按钮→候选链路可用。仍未制造"锁被占用"与限流场景，未验证 `not_found`/失败态的真实呈现。
- **未做**：未在真实浏览器手测（按钮、轮询、候选面板、错误态）；未验证限流与并发（锁被占用时退回 cron）；客户端不需要改（服务端门槛变化对客户端同样生效）。生产上的 `tlv77` 现在会走关键词候选。
- **公网入口修复（2026-11-09 01:00 CST / 16:59Z）**：手机浏览器点击抓取返回 `INTERNAL_ERROR`。定位结果：请求**根本没到 Odoo**——`team.l-creation.club` 走 Netlify→bore→网关（`/etc/nginx/conf.d/lc-bore-netlify.conf`），该 allowlist 只登记了 catalog 的 search/detail/categories/facets/bind/create_material，`fetch`/`fetch_status` 在网关层直接 404（11-06 的两条 404 日志也是同一原因，说明这两个端点从未在公网可用）。新建 release `p3-web-20261109T010500Z`：从在用的 `p3-web-20261103T002651Z` 原样复制，只插入两条精确 `location`（规范化 diff 仅 +2 行），`nginx -t` 通过、`nginx -T` 确认 include 生效（出现 2 次）、`systemctl reload nginx` 后公网两个端点均 **200 且到达 Odoo**（日志 `POST /lab/api/catalog/fetch 200`）。回滚点 `…/p3-web-20261109T010500Z/rollback/project-include.before`（原 include sha `34289f26…08ef`，新 `7e9566d6…2371`）。仓库模板 `bore/nginx/bore-public-allowlist.conf.template` 与 `tests/test_p3_gateway_contract.py` 同步补上两条（契约 34 tests OK / 13 skipped）；旧的直连公网网关 release `20261027-a2` **未改**（若走 16443 直连，仍无这两个端点）。
- **官方接口边界（生产实测）**：C 码抓取走官方 SMT 通道 `/smtOpenApi/smtComponent/selectComponentInfoByCodes`（`C17414` 已验证）；官方关键词搜索 `/lcsc/openapi/product/search/global` 用当前账号返回 `接口权限不足, 访问被拒绝`，所以 `tlv77`/`100nF` 这类关键词候选只能继续走 LCSC 网页搜索接口（只读候选、不写库），选定 C 码后才进官方 SMT 抓详情。`search_candidates` 里过时的"至少 6 个字符"提示同步改为 5。
- 仓库：公网白名单/契约/门槛文案改动后又冻结并激活 `source-server-web-fetch-entry-20261109-r2.json`（274 文件，tree `6946414f…3cb4c2`，清单 sha256 `fb459a5f…3469f9`），上一份 `…20261109.json` 原样保留；`repo_check.py` exit 0、`generate_routes.py --check` exit 0、`git diff --check` 0。

## 2026.11.08 接入立创官方 OpenAPI（SMT 通道；19.0.2.0.13 已部署，凭据已注入 systemd）

- 版本：`lab_catalog 19.0.2.0.12 → 19.0.2.0.13`（`components.json` 已同步）；客户端源码仍 `1.3.1+9`。**`19.0.2.0.13` 已于 2026-11-08 09:16Z 部署到生产**（见下）。
- 接入地址：官方开发指南「SDK 使用」写明 `https://open-api.jlc.com`（带连字符）；SDK jar 里写死的 `openapi.jlc.com` 是 NXDOMAIN。签名 `Base64(HMAC-SHA256(secretKey, METHOD
PATH
timestamp
nonce
body
))` 已用官方文档给出的示例密钥、示例报文与期望签名值对拍，**逐字节一致**。
- 服务端：新增 `lab_catalog/tools/lcsc_openapi.py`（只读：`smt_components`、`item_from_smt`、`parameters_from_text`、`merge_into_parsed`；默认地址 `https://open-api.jlc.com`；凭据只从 `LCSC_OPENAPI_*` 环境变量读取）。`models/lab_catalog_fetch.py` 新增 `_official_item()`：抓 C 编号时先查 SMT 通道 `/smtOpenApi/smtComponent/selectComponentInfoByCodes`，用 `merge_into_parsed()` 覆盖名称/型号/品牌/封装/库存/价格/中文参数；分类与文档仍用页面解析；未配置凭据或官方接口报错时静默回退页面解析，**不写库存、不新增写接口**。
- 真实探针（本机只读，2026-11-08）：`--probe C17414` → `PROBE_OK`，`componentName=厚膜电阻 10kΩ ±1% 125mW`、`componentModel=0805W8F1002T5E`、`componentSpecification=0805`、`stockNum=49,946,661`、首档价 `0.0202`、`paramTextAll` 7 条。凭据值只在 `local/private/`（Git 排除），未写入日志、清单或文档。
- 测试：`test_lcsc_openapi.py` **23/23**（签名对拍、SMT 映射、参数拆分、覆盖合并、凭据文件解析）；`test_lcsc_remote.py` **24/24** 仍全过。
- **Odoo 运行时实测（2026-11-08 13:0xZ，生产库 `LcHardwareHouse`，只读，结束 `rollback`）**：`odoo shell` 里手工构造 `Environment` 后调用 `env['lab.catalog.fetch.request']._official_item('C17414')` → `OFFICIAL_OK True`，`code=C17414 stock=49,941,126 price=0.0202 params=7 tiers=6 source=openapi_smt`。同一探针在**未加载** `LCSC_OPENAPI_*` 时返回 `False`（静默回退页面解析），与设计一致。探针进程用 `set -a; . /etc/lc-elc/openapi.env` 取环境，与服务单元加载的是同一份文件；服务进程本身四个变量此前已由 `/proc/<pid>/environ` 复核。官方接口只读，未写库，实测后 `journalctl` 无新增 ERROR/CRITICAL/Traceback。
- Windows 客户端候选包（本机）：`build_client.py --platform windows --work-root C:/lcw --test` 三步均 exit 0，`flutter test` **334 passed / 5 skipped**；产物 `local/build/windows-1.3.1/candidate-20261108-r1/LC_ELC-Windows-1.3.1+9-x64.zip`（18,386,822 B，19 文件，sha256 `ebf74cb9231fba6052585191e555027b8c96ea16ea9b8688deb659498b66728a`）。冒烟只验证进程能启动，未测登录/打印/扫码/OS 安全存储。构建所需三处本机适配（pdfium 离线包、ATL、260 字符路径）已写进 `docs/development/CLIENT.md`，`tools/build_client.py` 新增 `--work-root`。
- 清单：新冻结并激活 `source-server-lcsc-openapi-20261108.json`（**274 文件**，tree `740bc540293b96e1d2b7510e7e39dc1a381d6488409f481645e50e14056e903e`，77,944 B，sha256 `f1754c7902535779e6cf02766657ec331b00e24479b22a7228fc897f6a4121e0`），旧清单未改写；`repo_check.py` **exit 0 / PASS / 52 项 / 0 错误**（16 条既有 payload 警告照旧）；`generate_routes.py --check` exit 0（94 条路由）。
- **生产部署（2026-11-08 09:16–09:18Z）**：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108c/modules`，备份 → 停服务 → 换三模块代码 → `-u lab_catalog,lab_inventory,lab_workflow` **退出码 0、输出 0 条 ERROR/CRITICAL/Traceback** → 起服务。生产 `/opt/odoo/custom-addons` 现为 **`lab_catalog 19.0.2.0.13`**（`ir_module_module` 复核：`lab_catalog|19.0.2.0.13|installed`、`lab_inventory|19.0.1.1.0|installed`、`lab_workflow|19.0.2.0.2|installed`）；部署目录与暂存副本源码哈希一致（排除 `__pycache__`：两侧均 `132338bc…7f6ae3`）。`odoo.service` active，`/web/login` 带 `X-Odoo-Database` **200**（脚本把无库头的 303 判失败，是 2026-11-06 已记录的既有缺陷）。`Modules loaded` 09:18:00Z，09:16Z 起时间戳行 **0 条 ERROR/CRITICAL/Traceback**，cron 25「器件库：处理在线补抓队列」正常运行。备份 `/var/backups/lc-elc/20261108T091631Z-before-upgrade/`（归档 sha256 `087c2fe7…ff79fe`，旧三模块源码在 `module-source-before-upgrade/`）。服务器侧对 `https://open-api.jlc.com` 的连通性已测（无签名的请求返回 `400 请求认证信息不能为空`）。
- **官方凭据注入生产（2026-11-08 09:26–09:29Z）**：经用户授权的部署范围内，在服务器建立 `/etc/lc-elc/openapi.env`（`root:odoo 0640`，4 个 `LCSC_OPENAPI_*` 键）与 `/etc/systemd/system/odoo.service.d/10-lc-elc-openapi.conf`（`[Service]` + `EnvironmentFile=-/etc/lc-elc/openapi.env`），`systemctl daemon-reload && systemctl restart odoo` **退出码 0**。复核：`EnvironmentFiles=/etc/lc-elc/openapi.env (ignore_errors=yes)`；odoo 主进程（PID 655516）环境里四个变量齐备，只记录长度（`BASE_URL 24`、`APP_ID 18`、`ACCESS_KEY 32`、`SECRET_KEY 32`），**未输出任何凭据值**；临时传输文件已从 `/tmp` 删除，本地临时副本已删，凭据仅存于 `local/private/`（Git 排除）与服务器 root 可读文件。重启后 `odoo.service` active、`/web/login` 无库头 303 / 带 `X-Odoo-Database: LcHardwareHouse` **200**、`journalctl -u odoo` 自 09:27Z 起 **0 条 ERROR/CRITICAL/Traceback**。
- **服务器侧签名探针**（用同一份 env 文件、只读）：`--probe C17414` → `CHANNEL smt`，`C17414 | 厚膜电阻 10kΩ ±1% 125mW | 0805W8F1002T5E | 0805 | stock=49,948,000 | price=0.0202 | params=7`，`rc=0`。说明生产机的出口网络、IP 白名单与签名链路均通。
- **未做**：Odoo ORM/HttpCase 用例未跑；未经网页端/客户端做一次真实抓取入库（只直接调了模型方法）；未提交/推送；Windows 候选包未进 `clients/windows/releases/`。
- 任务单：`maintenance/tasks/2026-11-08-lcsc-openapi-integration.md`；交接：`maintenance/handoffs/2026-11-08-windows-1.3.1-and-openapi.md`。

## 2026.11.08 按需抓取支持关键词候选（源码；未部署）

- 版本：`lab_catalog 19.0.2.0.11 → 19.0.2.0.12`、客户端 `1.3.0+8 → 1.3.1+9`（`components.json` 已同步）。生产仍是已部署的 `19.0.2.0.11`，本轮**未部署**。
- 服务端：`lcsc_remote` 新增 `normalize_keyword`（规范化后**大于 5 个字符**且至少含一个字母才放行，纯数字与短词直接拒绝）、`search_candidates`（只调用一次公开搜索接口）与 `candidates_from`（新增 `name`/`brand`，用结果里的 `title`/`brandNameEn`，并过滤非电子一级分类）。`lab.catalog.fetch.request.query_kind` 增加 `keyword`；`_run` 的关键词分支**只返回候选、不打开中文详情页、不写库**。`/lab/api/catalog/fetch` 接受关键词并把状态停在 `candidates`；`/lab/api/catalog/search` 的 `fetch_suggestion` 对零结果的长关键词给出 `kind=keyword`。只有人选定某个 C 码（`catalog_code`）后的请求才真正抓取详情。
- 客户端：`CatalogFetchCandidate` 增加 `name`/`brand`，候选行显示立创显示名（如 `TI TLV9001IDBVR · SOT-23-5 (C398363)`），没有名称时退回「品牌 + 型号」；候选面板文案改为「选定一个之后才会抓取它的完整资料」，按钮为「选这个」。选中的请求仍只带一个 `catalog_code`。
- 真实候选检索（本机，2026-11-08，只读公开接口）：`TLV9001` → 10 条，首条 `C398363 | TI TLV9001IDBVR | TI | SOT-23-5`；`STM32F103` → 10 条，首条 `C8734 | ST STM32F103C8T6 | ST | LQFP-48(7x7)`。全程只调用一次搜索接口，未打开中文详情页。
- 测试（本机真实执行）：`test_lcsc_remote.py` **24/24**（新增 4 条：关键词门槛、候选名称与非电子过滤、只发一次搜索请求、短词不联网）；`flutter test --no-pub` exit 0，**334 passed / 5 skipped / 0 failed**（原 332/5，新增关键词候选与候选名称 2 条）；`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 120 info**（与基线一致）。
- 仓库：新冻结并激活 `source-server-keyword-candidates-20261108.json`（272 文件，tree `21a6800c095c508461f19495b591219a9947b8f7164eb757222af4205cc31c8e`，77,370 B，sha256 `24b41905ec528a12b9163067225f3b3f3d6190493fcb1b821b4242b763febb2e`）与 `source-client-keyword-candidates-20261108.json`（180 文件，tree `c8057727f4775d278c75254fa3d5817103ddf8fca89b86041353d282e5bd2160`，46,125 B，sha256 `c0f405c14e0bba6e28b86427065ade2b41f68a89a9742d90fa6a17269cfef80f`），旧清单未改写；`repo_check.py` **exit 0 / PASS / 0 错误**（16 条既有 payload 警告照旧）。
- **生产部署（2026-11-08 12:37 本地 / 04:37Z）**：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108b/modules`，备份 → 停服务 → 换三模块代码 → `-u lab_inventory,lab_catalog,lab_workflow`（退出码 0、输出 0 条 ERROR/CRITICAL/Traceback）→ 起服务。`/opt/odoo/custom-addons` 现为 **`lab_catalog 19.0.2.0.12`**，三模块树哈希与暂存副本逐一相同（`lab_catalog 8db3b984…19a5c3fc`、`lab_inventory b8b4134f…7da311b5`、`lab_workflow 26b03357…eab15f08`）；04:38:52Z `Modules loaded`，`/web/login` 带 `X-Odoo-Database` **200**，04:37Z 起时间戳行 **0 条 ERROR/CRITICAL/Traceback**；两个 `lcsc-*.timer` 仍 `disabled`/`inactive`。备份 `/var/backups/lc-elc/20261108T043724Z-before-upgrade/`：`db.dump` 119,023,251 B / `a6ad4c1b…4b55c3`，`filestore.tar.gz` 12,819,190 B / `08670f20…4e0ea3`，`MANIFEST.json` 18,045 B / `f97b887e…c948ba0d`，旧模块源码在 `module-source-before-upgrade/`。脚本自身健康检查仍把 `/web/login` 的 303 判为失败（2026-11-06 已记录的既有缺陷），独立复核为 200。
- **客户端包构建尝试（2026-11-08 13:01 本地，失败）**：`build_client.py --platform windows --test` 在隔离副本里 `pub get` 与 `flutter test` 均 exit 0（**334 passed / 5 skipped**），`flutter build windows --release` **exit 1**：`Unable to find suitable Visual Studio toolchain`。本机 `vswhere` 返回空数组、无 `cl.exe`，即未安装 Visual Studio / Build Tools（含 Desktop C++ 工作负载）。未生成安装包，未改动已发布目录。
- **未做**：未构建客户端 `1.3.1+9` 包（生产客户端仍无该功能）、未做真实网络手测（关键词候选、选定后抓取）、DB 侧 `ir_module_module.latest_version` 未查、未提交/推送。

## 2026.11.08 立创资料改为纯按需抓取（源码候选；未部署、未停用夜间 timer）

- 版本：`lab_catalog 19.0.2.0.10 → 19.0.2.0.11`、客户端 `1.2.0+7 → 1.3.0+8`（`components.json` 已同步）。
- 服务端：`/lab/api/catalog/fetch` 新增 `sync`（默认 true，15 秒预算内当场处理这一条）与 `refresh`（默认 false，必须带 `catalog_code`，只重抓该一条）。`_process_inline` 改用事务级 `pg_try_advisory_xact_lock`（连接中断也不会遗留锁），锁被占用立即返回 `queued`；`lcsc_remote` 每次 HTTP 的超时取 `min(6 秒, 剩余预算)`，预算用完抛 `budget_exhausted` 退回队列且不消耗 cron 的 3 次重试。`_upsert_item` 返回 `(item, changed)`，内容未变化时不写库、不 bump `catalog_revision`，消息为“资料未变化，无需更新。”。
- 客户端：新增 `CatalogFetchController` 与公开 `CatalogFetchPanel`；`CatalogNotifier.startFetch` 支持显式 `query`/`refresh`；`CatalogSuggestField` 保存服务端 `fetch_suggestion`，零结果面板提供“立即从立创商城抓取”，成功后 `research()` 重查且不自动选中；入库与待入库表单在字段下显示抓取进度/结果；器件详情页新增「刷新资料」（仅带 C 码的卡片，`refresh: true`，一次只刷这一条，没有批量入口）。
- 测试（本机真实执行）：`test_lcsc_remote.py` **20/20**；新增 Odoo 用例 `tests/test_catalog_fetch_inline.py`（已加入 `tests/__init__.py`，**未运行**：本机无 Odoo/PostgreSQL）；`flutter test --no-pub` exit 0，**332 passed / 5 skipped / 0 failed**（基线 326/5）；`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 120 info**；`git diff --check` exit 0。
- 仓库：新冻结并激活 `source-server-on-demand-fetch-20261108.json`（272 文件，tree `cd6c86b3fd760fc59160d67643f41e7b202b78352f658687be0d6e7ab050e9aa`，77,370 B，sha256 `4f8a851d64fdec7e7143aa61fe2042f68f457f76f512196a015b1db9424fcd3a`）与 `source-client-on-demand-fetch-20261108.json`（180 文件，tree `c7cc177a1b74fb61d2caa90ccfc0fde8c55cd55ee2e2195b64fe2adeea71da82`，46,125 B，sha256 `8bada64d942943a34f98950e51aaea69826ee7614d8f7997a251525581ddf46d`）；`python tools/repo_check.py` **exit 0 / PASS / 52 项 / 0 错误**（16 条既有 payload 警告照旧）；`generate_routes.py` 已重新生成（94 条）且 `--check` exit 0。
- **生产部署（2026-11-08 01:00 本地 / 2026-11-07T17:00Z）**：先停用 `lcsc-crawler.timer`、`lcsc-crawler-stop.timer`（现均 `disabled`/`inactive`，采集器与导入器 `inactive`，unit 保留可手工全量重建）。随后 `upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108/modules`：`-u` 完成、`odoo.service` active、55 模块加载、`/web/login` 带 DB 头 **200**、17:00Z 起日志 **0 条 ERROR/CRITICAL/Traceback**；`/opt/odoo/custom-addons` 三个模块的树哈希与暂存副本逐一相同（`lab_catalog` **19.0.2.0.11**）。备份 `/var/backups/lc-elc/20261107T170002Z-before-upgrade/`：`db.dump` 119,011,646 B sha256 `2654a241…cb4ca5`；`filestore.tar.gz` 12,819,190 B sha256 `ae429c94…f9f414`；`MANIFEST.json` 16,420 B sha256 `bed14d02…b49e4c3`；旧模块源码在 `module-source-before-upgrade/`。首次尝试在备份步骤因暂存目录缺少 `lc_archive.py` 中止（未停服务、未换代码），补齐后重试成功。
- **未做**：DB 侧 `ir_module_module` 版本行未单独查询（需 DB 访问）；真实网络端到端（两个搜索入口 + 详情页单条刷新）待客户端手测；未运行 Odoo ORM/HttpCase；未构建客户端包、未提交/推送。
- 任务单：`maintenance/tasks/2026-11-08-on-demand-only-fetch.md`。

## 2026.11.07 冻结按需抓取源码清单（repo_check 归零）

- 新增并激活两份不可变源码清单：`maintenance/registry/source-server-catalog-fetch-20261106.json`（**271 文件**，tree `10c3aa4ad450dfb4bd1b127777b6c5f05cc0d9fdfc51f7287845e4b41cf7757f`，77,062 B，sha256 `fd0870000b5372eb72f0a778aa059231866ca444708941095a0507ddece555f0`）与 `source-client-catalog-fetch-20261106.json`（**178 文件**，tree `a2d5d42c5fa58ba8f07c70e5f95b831b3dc9de40b274134646955f6add70abeb`，45,543 B，sha256 `dd872ded69a47b849b9a2d1e506bc70e17150e0444f60cd8910f6b8dbaedf250`）；`active-sources.json` 的 `server`/`client` 指针已切换，旧清单未改写。
- 检查结果：`python tools/repo_check.py` 由 exit 1（`frozen-source:client` 4 文件、`frozen-source:server` 13 文件）变为 **exit 0 / result=PASS / 52 项通过 / 0 错误**；16 条既有离线载荷警告照旧存在（未执行 `--verify-payloads`，不记作全仓零告警）。`generate_routes.py --check` exit 0、`git diff --check` exit 0。
- 边界：只登记源码哈希，未改业务代码、未升级模块、未部署、未推送、未构建安装包；生产仍是 2026-11-06 部署的四模块版本。任务单见 `maintenance/tasks/2026-11-07-freeze-catalog-fetch-sources.md`。

## 2026.11.06 器件库按需抓取部署到生产（2026-11-06T14:29–14:31Z；cron 已运行）

- 部署：在 `192.168.31.105`（DB `LcHardwareHouse`）执行 `upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261106/modules`，`-u lab_inventory,lab_catalog,lab_workflow` **退出码 0、ERROR/CRITICAL/Traceback 行数 0**。生产 `/opt/odoo/custom-addons` 现为 `lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2`；`lab_team_web 19.0.1.2.1` 未参与，客户端仍 `1.2.0+7`（未构建/发布）。
- 备份：`/var/backups/lc-elc/20261106T142949Z-before-upgrade/`——`db.dump` 118,970,696 B / `40863d500fffc8f36013cd99da8625d3ed988799826f6633cc178f41d3ba0d66`；`filestore.tar.gz` 12,819,190 B / `5b9e5d42a03d339dcbab225ad3e1da09913b4b853dcded117fcb29614a3f5fc0`；`MANIFEST.json`、`odoo.log.tail`；旧三模块源码在 `module-source-before-upgrade/`。
- 健康检查：脚本把 `/web/login` 的 303 判为失败（既有缺陷，303 → `/web/database/selector`）；独立复核 `/web/login` 带 `X-Odoo-Database` 为 200、`odoo.service` active/enabled、14:31:36Z `Modules loaded`。
- 运行证据：`/var/log/odoo/odoo.log` 自升级后到 2026-11-07 13:11Z **0 条 ERROR/CRITICAL/Traceback**；`ir.cron`「器件库：处理在线补抓队列」（id 25，每 1 分钟）自 2026-11-06 14:31:16Z 起每约 62 秒运行，累计 1356 次启动、0 失败，每次 `fully done (#loop 1; done 0; remaining 0)`。
- DB 行核对（2026-11-07T13:17:07Z）：四模块 `installed`（`lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2` / `lab_team_web 19.0.1.2.1`）；`lab_catalog_fetch_request` 表存在，7 个索引含部分唯一索引 `lab_catalog_fetch_active_uniq`（谓词 `state IN ('queued','resolving','fetching')`）；`lab_catalog.ir_cron_lab_catalog_fetch` → `res_id=25`，与运行中的 job 25 一致。数据未受影响（2026-11-07T13:32Z 补查）：`lab_catalog_item` **695,217** 行（与 2026-11-04 部署时相同）、`lab_catalog_param` 4,110,477 行、`lab_catalog_fetch_request` 0 行（队列空）；`ir_cron` 25 号行存在，列清单证实 Odoo 19 用 `ir_actions_server_id` 而非 `model_id`（第一步脚本中断的原因）。
- 未做：真实网络端到端（三个目标料号）、Flutter widget 测试、客户端包构建、source manifest 冻结。

## 2026.11.06 器件库搜索未命中按需抓取（源码候选；【已部署】见上一条）

- 版本：`lab_catalog 19.0.2.0.9 → 19.0.2.0.10`（`components.json` 已同步）；客户端源码变更但版本仍为 `1.2.0+7`。
- 服务端：新增 `lab_catalog/tools/lcsc_remote.py`（固定域名、无 Odoo 依赖）：精确 C 码直取详情，精确 MPN 走英文站公开搜索并**只在 `productModel` 完全相等时**采用，否则返回候选；中文名称/品牌/分类/参数/封装/CNY 价格全部取 `item.szlcsc.com` 中文详情页。新增 `lab.catalog.fetch.request` 状态机、部分唯一索引去重、`pg_try_advisory_lock` 串行的 cron worker（每分钟 2 条）、ACL/记录规则；`/lab/api/catalog/search` 在精确查询零结果时返回 `fetch_suggestion`，新增 `/lab/api/catalog/fetch` 与 `/fetch_status`（每用户 5 个进行中、每小时 20 次）。抓取只 upsert `lab.catalog.item/param` 与 `catalog_stock`，不创建产品、不写 quant/move；非电子一级分类在请求中文页前即跳过，未知分类转人工复核。
- 客户端：空结果页显示“立即从立创商城抓取”，轮询 1 秒、最多 60 次，`done` 后自动刷新；`candidates` 逐条列出封装让用户选择，不自动取第一条；失败显示服务端中文原因并可重试；换查询或销毁时取消轮询。
- 测试（本机真实执行）：新增 `catalog_fetch_test.dart` 7/7；`flutter test --no-pub` exit 0，**326 passed / 5 skipped / 0 failed**（基线 319/5）；`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 120 info**（新增 2 条与既有风格一致的 `prefer_initializing_formals`）；`test_lcsc_remote.py` 15/15。
- 仓库检查：`python tools/repo_check.py` exit 1，50 项通过，错误为本轮尚未冻结的 `frozen-source:client`（4 文件）与 `frozen-source:server`（13 文件）；16 条 payload 警告为既有缺口。`generate_routes.py` 已重新生成 `routes.json`（94 条），`--check` exit 0；`git diff --check` exit 0。
- **未做**：未在 Odoo/PostgreSQL 测试库运行 ORM 用例、未做真实网络端到端、未做 Flutter widget 测试；未升级模块、未注册定时任务、未建表、未部署生产、未冻结 source manifest、未提交/推送、未构建安装包。任务单见 `maintenance/tasks/2026-11-06-catalog-on-demand-fetch.md`。该时点状态已被上一条部署取代：模块已升级、表与 cron 已生效、改动已提交 `e563da0`；仅 source manifest 仍未冻结。

## 2026.11.06 Flutter Liquid Glass 源码候选（未构建/未发布）

- 客户端 `1.1.3+6 → 1.2.0+7`：默认深色玻璃 + 荧光绿，保留路由、业务文案、协议、登录记忆、参数搜索、待入库服务端筛选和库存语义。零新增 pub 依赖。
- 新增 `lib/ui/glass/` 设计系统与 `lab_ui.dart` 兼容层；只有 `GlassSurface` 创建 `BackdropFilter`，真实模糊仅用于 chrome/抽屉/搜索建议/浮层，滚动卡片与内容面板无模糊。高对比度、减少动效、44×44 目标与 prominent accent/onAccent 配对已实现。
- 登录、目录、详情、收/领/还、离线、标签和两阶段入库接入视觉层；`StatusBanner` 提供图标+文字状态；A4 预览固定白底黑字。保留 `UpdateHost` 与既有业务慢响应保护，不机械替换全部 Material 按钮。
- 验证：`flutter analyze --no-pub lib test` exit 1，0 error / 0 warning / 118 info；`flutter test --no-pub --reporter compact` exit 0，**319 passed / 5 skipped / 0 failed**。已查看 6 张深色离屏截图；真机、性能、读屏、实体打印未验证。
- 冻结 `maintenance/registry/source-client-liquid-glass-20261106.json`（177 文件，tree `a19e0ddf2f7cdba420ae7605763c40926c3745d3ab5de60387c8aab7da1d0e4e`）并激活；未构建/发布安装包，未部署生产、未推送。`generate_routes.py --check` 与 `git diff --check` exit 0；`repo_check` 仅剩另一项服务端源码晚于 active r2 的 `frozen-source:server` 差异，不记作全仓 PASS。

## 2026.11.04 入库关键词搜索扩展到参数值（生产已部署 2026-11-04T12:59–13:09Z；真实浏览器验收待做）

- 版本（`components.json` 已同步）：`lab_inventory 19.0.1.0.0 → 19.0.1.1.0`、`lab_catalog 19.0.2.0.5 → 19.0.2.0.6`、`lab_workflow 19.0.2.0.0 → 19.0.2.0.1`、`lab_team_web 19.0.1.2.0 → 19.0.1.2.1`；client/eda/theme/site 不变。
- 共享归一化：新增 `lab_inventory/tools/param_search.py`（无 Odoo 依赖），按现有标签逻辑选取关键参数（电阻 `阻值/精度/功率`、电容 `容值/容量/电容量/耐压/额定电压/介质/材质`、其他前 3 个），生成归一化检索文本。覆盖大小写、SI 前缀、`Ω/ohm`、`100nF = 0.1uF`、`±1%`、`1kV = 1000V`，以及低阻 R 记法 `10Ω = 10R`、`4.7Ω = 4R7`、`0.1Ω = R1`、`4.7kΩ = 4k7`、`1.5kΩ = 1k5`；原始写法与 NFKC 写法同时保留（如 `±2℃` / `±2°C`）。
- `lab_inventory`：`product.template` 新增存储字段 `lab_search_specs`（由 `lab_specifications` 计算）与 trigram GIN；迁移 `19.0.1.1.0/post-backfill_lab_search_specs.py` 分批回填。
- `lab_catalog`：`lab.catalog.item.search_params` + trigram GIN；参数 create/write/unlink 增量重算；导入器在既有 COPY/upsert 中写入；新增独立可重入回填脚本 `tools/backfill_search_params.py`（批大小、起始 ID、dry-run），完整回填后写 `lab_catalog.param_index_state=ready`。检索改为空白分词、每词 AND，身份字段或参数文本命中即可；facets 与 search 共用同一条件；`/lab/api/catalog/search` 响应新增 `param_index_ready`（只增不改），前端在未就绪时提示"参数索引未就绪"。排序仍为本地有货优先、再按编号。
- `lab_workflow` + `lab_team_web`：`pending/list` 新增可选 `query`、`state`（`pending/done/cancelled/all`）并返回过滤后的 `total`；不传 `state` 保持旧行为，Web 默认只看待入库。来料页新增关键词输入、状态筛选与"共 N 条"；combobox 有结果时显示"查看全部结果"链接到 `/team/lab?q=`，空结果/失败时隐藏，原有防抖、8 条、2 在途、8s 超时与 IME 行为不变。
- 测试（本机真实执行）：纯归一化 `test_param_search.py` **8/8**；`test_combobox.mjs` **21/21**（新增 view-all 用例）；`test_workflow_core.mjs` **19/19**；改动 Python `py_compile` OK；`git diff --check` 0。新增 Odoo ORM 用例 `test_catalog_param_search_orm.py` 与待入库 query/state/total/owner 用例，但本工作区**没有可用的 Odoo/PostgreSQL 测试实例，未执行**（不得记作通过）；真实浏览器、Flutter 未验证；生产目录数据已回填但未做人工搜索验收。
- 冻结：新建 `maintenance/registry/source-server-param-search-20261104-r2.json`（file_count **264**、tree_sha256 `503e278221851fa129351bae12e95b6da5a8eeb5192d4e8ab2e5907c270ab378`、清单 sha256 `485c93c2ca3d1543bf8bb8838acb538f24c0a6f23ae4b68418cd4c8f3410b86a`）并 `--activate`；r1 与旧 r3 清单未改写。r2 修正参数全部移除时空文本被 ORM 写成 NULL、导致就绪扫描误判的问题（改用单空格哨兵）。`maintenance/registry/routes.json` 已重新生成（**92** 项，包含合并后既有但此前未登记的 13 条 legacy 入口；本任务未新增路由）。
- `python tools/repo_check.py` exit 1：51 项通过，唯一错误为既有 `frozen-source:client`（`clients/app/t.obj` 缺失，与本轮无关）；`frozen-source:server` 已随新快照消除；16 条 payload 警告为既有离线载荷缺口。`generate_routes.py --check` exit 0，`git diff --check` 0。
- 生产部署（**2026-11-04T12:59–13:09Z**，`192.168.31.105` / `LcHardwareHouse`）：四模块 `-u lab_inventory,lab_catalog,lab_workflow,lab_team_web` 退出码 0、0 条 ERROR/CRITICAL/Traceback；服务 active；四模块版本 installed；参数回填 **695,217/695,217**、`lab_catalog.param_index_state=ready`。一致备份 `/opt/odoo/backups/20261104T125944Z-before-upgrade/`（`db.dump` 110,948,317 B / `2c8bd939…810794`；`filestore.tar.gz` 12,819,190 B / `c180ca54…c929f`），旧四模块源码在同目录 `module-source-before-upgrade/`。`/web/login` 303 → `/web/database/selector`（带 cookie 最终 200），标准升级脚本把它误判为失败；本次用四模块副本 + `finish_remote.sh` 收尾。**未做**：commit/push、真实浏览器验收、Flutter、目录导入、真实业务写；未执行回滚。

## 2026.11.03 P3 Web 生产部署（r3 → 生产 LcHardwareHouse；公网回归通过；`DEPLOY_STATE=completed`）

- 部署：**2026-11-03 00:16–00:36Z** 在 `192.168.31.105`（DB `LcHardwareHouse`，Odoo19 / Python 3.12.15 / base 19.0.1.3 / 55 模块 / nginx 1.18.0）执行 r3。`LC_DEPLOY_MODULES=lab_site,lab_team_web,lab_theme`（`lab_site` 仅权限归一、内容=冻结；`lab_theme` 仅由 `deploy-theme.sh` 换冻结版），`-u` 只跑 `lab_team_web`：**19.0.1.1.0 → 19.0.1.2.0**，`UPGRADE_EXIT=0`、错误行 **0**；`lab_workflow 19.0.2.0.0` / `lab_catalog 19.0.2.0.5` / `lab_inventory 19.0.1.0.0` 未变。
- 一致备份（停服态）`/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`：`db.dump` **110,944,415 B** / `40c76d0679d2a7915ba5857d5009c291c18f17fdf239803a484246228993ba19`；`filestore.tar.gz` **12,819,190 B** / `305b841f50f0b3417b120a3ff0b52e61800d533f3a2337418f3114a2d85abfda`（**611 条目**）；`MANIFEST.json`、`odoo.log.tail`；`store_fname` distinct **139** / tar 成员 **140** / 缺失 **0**；`service_was_active=false`。源码回滚快照 `/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`。
- 菜单：before **234 行**（lab_* 21 行，sha `3eb392d032ae1c0ed7a78456cd837c89aa1dc9f7ffc3f167c2e211b24a5e7c2a`）→ `removed=0 / added=1 / changed=12 / match=1`；新增 `lab_team_web.menu_legacy_label_wizard`（id 382、parent `lab_workflow.menu_lab_config`、action `lab_workflow.action_lab_label_open`），12 条仅 action 变；tree stable sha `bafa905fc5f5fdb65fe3ea72af42647e78300b685d5323b9764db26e9ec64b8c`。
- 网关：release `/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z`，`/etc/nginx/conf.d/lc-bore-netlify.conf` 现 include 该 release 的 `gateway.conf`，include sha **`34289f2612c9adb460c787c6765f72525bd1db5359eff515164cbb1ab42508ef`**（切换前 `bb3164e5630cc70cb24e9a1f95bdf8b5e40492ddee721c5ec5d01de2f2d8c4e9`，回滚点同目录 `rollback/project-include.before`）；allowlist pages **24** / apis **5** / legacy **13**；未动 `lc-bore-public.conf`、DNS、Docker、其他服务。
- 验收：`50-verify.py` = **PASS，129 项检查 / 0 失败**（`/var/tmp/lc-deploy/verify-20261103T003528Z.json` + `verify-facts-…env`）；三模块逐文件与冻结清单逐字节相等（`lab_site 19` / `lab_team_web 58` / `lab_theme 6` 文件）；13 条 legacy action GET/HEAD 全过、POST 全拒；`/web/login`、`/database`、`/jsonrpc`、ORM 404；`workflow_core.js` sha `6942f733fddaf4b3183a0251ad5d2ac99913d4c339921ca48dc59b7346cc0936`。
- 收口：`90-close.sh` 写 **`DEPLOY_STATE=completed`**、`DEPLOY_COMPLETED_UTC=20261103T003543Z`、`DEPLOY_FACTS_PROVEN=43`；run env `/var/tmp/lc-deploy/run-20261103T001600Z.env` sha `20f5b3fe34c2ed6c1c3f35a6141368a729a4e3baf4532ccdafe5dfb7905ec008`，close log `/var/tmp/lc-deploy/close-20261103T003543Z.log`；close 后服务 active、HTTP `/web/login` 200。
- 公网回归（`team.l-creation.club`，Netlify→bore→网关）：`/ 200`、`/login 200`、`/team/login 200`、`/team/lab/receipts 303`、`/team/scan 303`、`/lab/bags 303`、`/odoo/action-lab_workflow.action_lab_scan_console 303`、`/odoo/action-lab_inventory.action_lab_mapping 303`、`/web/login 404`、`GET /lab/api/inventory/bags 403`、`POST /team/lab/receipts 403`、`POST /lab/api/catalog/search 415`、`workflow_core.js` sha 一致、`pages/receipts.js 200`、`workflow_receipt.css 200`。
- 产物：**最终实际部署包** `deploy-bundle-web-ui-20261102-r3.tar.gz` = **93,486 B** / `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / **27 条目** / FROZEN **18** / shipped **15** / `bundle-meta` freeze `f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`；部署前中间包 91,307 B / `8215a795…`、91,586 B / `e453db43…`、92,857 B / `085945a2…` **均非最终**。源码候选 ZIP 13,251,571 B / `3800e2a2…` / 259 条目；r3 冻结清单未改写（258 文件、tree `95baea91…`、清单 sha `2192a354…`）。
- 部署期修复的脚本缺陷（真实、已修）：`05-bootstrap.sh`（tar 选项顺序 / mawk 转义斜杠正则 / `members.txt` 误判顶层，`f2d46931a5ddf15d430f63c469f78476345a22aa20be367526301e70b6755fde`）、`00-preflight.sh`（网关 include 闸门改声明式，`c48bbfddb5070f35e7724761b7a865ed3e0ab7a32d2abb1385b88577bd8ef99a`）、`lib.sh`（`http_login_code` 多路径 + `X-Odoo-Database`，`d5da44ed05aa46fab3e90bf53fe2215bbc490c1bbff315b63445db261817ba98`）、`40-gateway.py`（reload 优雅切换竞态加有界 settle，`487283ee6ee844a0ca81af66f57cda70fcc1a74579bb506be2096125cb231e7b`）、`50-verify.py`（`ir_ui_menu.action` Char vs res_id int、origin 探针补 DB 头、公网 5xx 有界重试，`14d4c1e084691486c5b231028848a553b948f269aae802c5238ee55a64997f0d`）；`FROZEN-20261102.sha256` 已同步，`check-scripts` `SYNTAX_ERRORS=0`、`USED_BUT_MISSING none`。
- 证据与凭据：`local/web-ui-implementation/evidence/production/p3-deploy-evidence-20261103.tar.gz`（**21,344 B** / `53433008c3bb6ae48da899105e64d2fd6e814b24a47d5b2617a3fe9cdc8069b5` / 20 条目）；`local/private/web-ui-20261102.dpapi` 已删除（`BLOB_DELETED`），本机不再存生产口令。
- 未做：未 commit/push（分支 `codex/receipt-search-feedback` 仍在工作区）；未建/发布客户端包（客户端 `1.1.3+6` 不变）；未做真实业务写；未动 DNS/Docker/其他服务；未执行回滚；未读 CI。

## 2026.11.02 战队管理站点统一 UI r3（两处深色视觉修复 + 53/53 下拉证据 + 55/55 真实套件全绿；新增 artifact 登记 r3；未提交/未推送；**部署见 2026.11.03 条目**）

- 源码变更（r3 相对 r2，**共 2 处，只改 `server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css`**）：① `team.css:38-41`（`body.lc-body` 令牌块内，`--lc-ease` 之后、`display:flex` 之前）新增 `color-scheme: dark`，令原生滚动条 / select / input 按深色 UA 渲染；② `team.css:2181` 的 `.lc-combobox-pop` 由 `max-width: min(540px, calc(100vw - 28px))` 改为 `min(780px, calc(100vw - 28px))`，桌面 1440 时候选弹层与 770px 输入框同左同宽，窄屏仍受视口约束（注释补句 `team.css:2166`）。其余 CSS 属性、JS、XML、Python 均未改；manifest 差异仅此一个文件，258 个源文件不变。
- 遗留 B / C 已修复（原记于 r2 artifact 的 limitations，此处给实测值）：B「深色主题缺 `color-scheme`、原生控件按浅色渲染」→ 5 个下拉用例 `colorScheme` 实测均为 `dark`（修复前 `normal`）；C「1440 下拉偏窄」→ 1440 视口 `input=770px`、`pop=770px`（gap 0，修复前 540px），375 视口 `input=pop=277px` 且 `document.scrollWidth=375` 无横向溢出。
- 升级验证（隔离 WSL Odoo19 实例，r3 源码，真实退出码，**不是生产**）：`upgrade-only-test.sh` → RUN=`upgrade-keepdb-20261102T134429Z`、`ODOO_EXIT=0`，`lab_team_web` **52 tests**、FAIL: / ERROR: 计数 **0**，日志 `local/web-ui-implementation/evidence/upgrade-keepdb-20261102T134429Z.log`；DB 实测 `lab_team_web=19.0.1.2.0`（installed）。
- 真实浏览器（r3 源码重跑）：下拉截图 `capture-receipt-dropdown.mjs` = **53/53 pass / 0 fail**（`local/web-ui-implementation/out/receipt-dropdown-20261102/evidence.json`：total 53 / pass 53 / fail 0 / failedIds `[]`；补充截图 `width-fix-1440.png` 118,206 B / 1440×900、`width-fix-375.png` 67,712 B / 375×812、度量 `width-fix-measure.json`；headless Chrome 156.0.8078.74）；全站真实套件 `run-real-ui.mjs` = **55 项 55 pass / 0 fail / 0 blocked**（exitCode 0、writeGate 全 true，report `local/web-ui-implementation/out/run-real-2026-11-02T13-38-39-691Z/report.json`），r2 时 3 项 blocked 全部补齐：静态袋详情 1440/375（`/team/lab/bags/41`，lab.bag id=41、trace `TRC00000045`、company=1；httpStatus 200 / errCount 0 / horizontalOverflow false / smallTargetCount 0）、`real-receipt-multi-create-lock`（archiveId=13、C990000001、tracking=none、无批次库存 12.00，createPosts=1、payloadMatch true、trace `TRC00000046`）、`real-receipt-legacy-precondition`（`PRECONDITION_FAILED`、`legacy_untracked_stock`、库存 12→12 未变、hasBag false、提示可见）。
- 套件证据缺陷（工具问题，非产品缺陷；未改工具源码）：给了 `WEBUI_BAG_ID` 后静态袋页与动态袋详情共用测试 id 前缀 `real-bag-detail-<1440|375>`，同一 id 两次、截图按 id 命名互相覆盖（`13-38-39Z` 里 `real-bag-detail-1440.png` 实际是动态袋 42）；已用 `--only=pages` 复跑（`local/web-ui-implementation/out/run-real-2026-11-02T13-40-31-993Z/report.json` = 35 项 32 pass / 0 fail / 3 blocked 全为 `--only` 主动跳过标记，exitCode 3）留下静态袋 41 截图 `…/13-40-31-993Z/shots/real-bag-detail-1440.png`（172,807 B，1440×2258）；建议静态页 id 改为 `real-page-bag-detail-<vw>`。同库并发跑套件会互相污染合成数据，只能串行。
- 冻结与产物（本机打包，r3；部署结果见 2026.11.03 条目）：新源清单 `maintenance/registry/source-server-web-ui-20261102-r3.json`（file_count=258，tree_sha256=`95baea916fbe4c8504e9a3bc2ce1c18235cf53689373d323b32d914d1e1fe8de`，sha256=`2192a3545ebbe2ea3293072d1cc971a8deab1e524a4e39c20503d760888a7224`，已 `--activate`；旧 10-28、r1、r2 清单均未改写）；r3 源候选 `local/build/web-ui-20261102/candidates/server-web-ui-20261102-r3-source.zip`（bytes=13251571，sha256=`3800e2a210a1c0fdad562112b4682ed02d83ae466f678443bfafb1923a02d4f7`，entries=259 = 258 源文件 + `MANIFEST.json`，构建报告 `local/build/web-ui-20261102/candidates/build-summary-20261102-r3.json`）；r3 部署 bundle `local/build/web-ui-20261102/candidates/deploy-bundle-web-ui-20261102-r3.tar.gz`（bytes=91307，sha256=`8215a7958fe227452f19f3458a149509169cfd3cf26fadfbd6ecad82b6e8f02d`，entries=27，`FROZEN-20261102.sha256` 18 条 = 15 随包脚本 + 3 本地脚本（无空行），`bundle-meta.json` 的 `freeze_sha256`=`93b07b020fb76d0ce48075495737a1e08b34df081370ab966eddacfb40b416b8`、`shipped_script_count=15`，`params.env` 已指向 r3 的 zip/manifest 与两个 sha；**2026-11-03 更新**：部署期修复脚本缺陷后重打，最终实际部署包 bytes=**93,486** / sha256=`34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / entries=27 / `FROZEN` 18 / `bundle-meta` freeze=`f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`，本条前面列的 91307 为部署前中间包）；新登记 `maintenance/registry/artifact-server-web-ui-20261102-r3.json`（version=`lab_workflow19.0.2.0.0+lab_team_web19.0.1.2.0+server-ops2026.11.02.1`，`kind=source-only-local-candidate`，`production_deployed=false`，`supersedes` 指向 r2 登记）。**r2（tree `aad3eacd…`、ZIP 13,251,445 B、bundle 91,273 B）与 r1 已被 r3 取代，保留为历史，不得部署。**
- 其他实测（r3 收尾）：`python tools/repo_check.py` = **PASS / 52 checks / 0 errors / 1 既有 warning（`production-py312-rebuild`）**，证据 `local/web-ui-implementation/evidence/repo-check-20261102-r3.json`、exit 0；`git diff --check` = 0。沿用（未重跑、与 r3 无关）：`test_combobox.mjs` 20/20、`test_workflow_core.mjs` 19/19、bore 契约 `Ran 19 tests ... OK (skipped=7)`；Flutter 客户端 295 passed / 5 skipped、`flutter analyze` 0 error / 0 warning / 119 info、客户端清单 169 文件 tree `ee5adebd…` / sha `d703e507…`、版本仍 `1.1.3+6`（未构建/发布 APK）。
- 生产部署（2026-11-03 更新）：**已于 2026-11-03T003543Z 部署完成**（`DEPLOY_STATE=completed`、`DEPLOY_FACTS_PROVEN=43`、公网回归通过；artifact 登记 `production_deployed` 已改为 `true` 并新增 `production_deployment` 块），本条目 2026-11-02 时点写的「主机不可达 / 未部署」已失效。仍成立：隔离环境 WSL Python 3.10.12 + Odoo19 与生产 Python 3.12.15 不等价，生产 cp312 离线闭包仍缺（repo_check 的 `production-py312-rebuild` 警告）。

## 2026.11.02 战队管理站点统一 UI 收尾（r2 版本冻结 + 源候选 + 部署包；未提交/未推送/未部署；**r2 历史，已被 r3 取代**）

- 版本（`components.json` 已同步）：`lab_team_web 19.0.1.1.0 → 19.0.1.2.0`、`server-ops 2026.10.28.1 → 2026.11.02.1`；其余组件（`lab_workflow`/`lab_catalog`/`lab_inventory`/`lab_theme`/`lab_site`/client/eda）本轮不改，见 `maintenance/registry/components.json`。
- 源码变更（`lab_team_web`，分支 `codex/receipt-search-feedback`）：整站 1024px 断点（≥1024 固定侧栏 / ≤1023 抽屉）；`LC.combobox`（250ms 去抖、IME 组字不检索、请求序号 + 在途 ≤2 + 8s 显式超时与「重试检索」、方向键/Enter/Esc/Tab 与 aria 语义）；来料页关键词候选与多档案明确选择；建袋结果未知期锁定 `material-select`；旧入口 13 条 `/odoo/action-<xmlid>` 兼容路由（非 GET/HEAD 返回 405）与 `views/legacy_entry_menu.xml` 菜单可逆改指（卸载还原）；issues 页行内按钮统一 44px（`workflow_issue.css`/`workflow_inventory.css`）。
- Flutter 客户端（并行的客户端轮，已完成并冻结；版本仍 `1.1.3+6`）：收据/待打印入库页内联收据搜索建议——新增 `clients/app/lib/features/unified/widgets/catalog_suggest_search.dart`（818 行，格式化后：OverlayPortal + CompositedTransformFollower 浮层、防抖 `Duration(milliseconds: 250)`、每键 `_seq` 递增作废旧请求、IME 组合期（`_controller.value.composing.isValid`）不查询、loading/empty/error+retry、Up/Down/Enter/Escape/Tab、48dp 行高、TapRegion 外点关闭、不裁切）与测试 `clients/app/test/features/unified/catalog_suggest_search_test.dart`（739 行、20 个用例）；改 `clients/app/lib/features/unified/screens/receipt_screen.dart`（+66/-4）、`.../screens/pending_receipt_screen.dart`（+129/-16）、`.../providers/inventory_providers.dart`（+20/-1）、`.../test/features/unified/item_picker_test.dart`（1 行文案）。验证（`clients/app`，`--no-pub`、无 `pub get`）：`flutter test --no-pub --reporter compact` exit 0、`+295 ~5`（295 passed / 5 skipped，5 个 skip 为既有需真实 Odoo 账号的 live 用例），单跑新测试文件 20/20；`flutter analyze --no-pub` exit 1 但 0 error / 0 warning / 119 info（全为改动前既有 info，新文件 0 新增，证据 `local/web-ui-implementation/evidence/flutter-analyze-20261102.txt`）；两个新文件 `dart format --output=none --set-exit-if-changed` 无改动。客户端源码已冻结 `maintenance/registry/source-client-receipt-search-feedback-20261102.json`（file_count=169、tree_sha256=`ee5adebdaa0c3e81dfa616b8dc55243d6419790422b93b010f9126f3aaa70072`、清单 sha256=`d703e507cd04bbe6bad648a3bf263b79d6626bf34ae77bba45cae88d6d37952f`，已 `--activate`，旧 `source-client-android-install-fix-final-20261019.json` 未改写）；**未升版、未构建/发布 APK**；无 emulator/真机运行，receipt 页无专门提交锁 widget 测试（pending 页有）。
- 升级验证（隔离 WSL Odoo19 实例，在 r2 源码上重跑，真实退出码，**不是生产**）：`upgrade-only-test.sh`（`-u lab_team_web --test-enable --test-tags=/lab_team_web --stop-after-init`）→ RUN=`upgrade-keepdb-20261102T125331Z`、`ODOO_EXIT=0`，模块用例 `52 tests`、`0 failed, 0 error`，日志 `local/web-ui-implementation/evidence/upgrade-keepdb-20261102T125331Z.log`；升级后 DB 实测 `ir_module_module.latest_version('lab_team_web')=19.0.1.2.0`（state=installed）。
- 其他实测（同轮，真实退出码）：`test_combobox.mjs` 20/20、`test_workflow_core.mjs` 19/19、bore `test_legacy_action_gateway_contract.py` `Ran 19 tests ... OK (skipped=7)`（7 skip 为环境相关）、`python tools/repo_check.py` = PASS / 52 checks / 0 errors / 1 既有 warning（`production-py312-rebuild`，冻结时点；上一版记的「文档更新时点重跑为 51 checks / 1 error `frozen-source:client`」真实原因是并行客户端改动当时尚未冻结，不是回归——冻结客户端源码后按 `python tools/repo_check.py --output local/web-ui-implementation/evidence/repo-check-20261102-r2-flutter.json` 重跑 = PASS / 52 项 / 0 errors / 1 既有 warning）、`git diff --check` = 0。
- 冻结与产物（本机，未部署，r2）：新源清单 `maintenance/registry/source-server-web-ui-20261102-r2.json`（file_count=258，tree_sha256=`aad3eacd53b112943d2204b6cb9ba7e1f4feb1cee445dea3608b2a0fe254f765`，sha256=`9b29e0d2f4441ed61c2de4c0df48584dc8a56379737da9666b6004593592fd4d`，已 `--activate`；旧 `source-server-p3-web-20261028.json` 与 r1 `source-server-web-ui-20261102.json` 均未改写）；r2 源候选 `local/build/web-ui-20261102/candidates/server-web-ui-20261102-r2-source.zip`（bytes=13251445，sha256=`cb868d7645b48836666810c84d2571a2e353f69bf5269e028f1f84a147f9de62`，entries=259 = 258 源文件 + `MANIFEST.json`，构建报告 `local/build/web-ui-20261102/candidates/build-summary-20261102-r2.json`）；r2 部署 bundle `local/build/web-ui-20261102/candidates/deploy-bundle-web-ui-20261102-r2.tar.gz`（bytes=91273，sha256=`848082612140a6aa8710c4dc9505690fc6aaa9ca78e7fd80c6139ef138811f34`，entries=27，`FROZEN-20261102.sha256` 19 条 = 15 随包脚本 + 3 本地脚本 + 1 空行，`bundle-meta.json` 的 `freeze_sha256`=`93b07b020fb76d0ce48075495737a1e08b34df081370ab966eddacfb40b416b8`，`params.env` 已指向 r2 的 zip/manifest 与两个 sha）；artifact 登记 `maintenance/registry/artifact-server-web-ui-20261102-r2.json`（version=`lab_team_web19.0.1.2.0+server-ops2026.11.02.1`，`production_deployed=false`）。**r2 只比 r1 多一条 CSS 修复：`server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css:2198` 的 `body.lc-body .lc-panel:has(.lc-combobox-pop:not([hidden])) { overflow: visible; }`，修 375px 下拉向上展开被裁切；r1（tree `634d1893…` / sha `fe34ed95…`、ZIP 13251270 B、bundle 91154 B）已被 r2 取代，不得部署，仅作历史保留。**
- 文档：`local/web-ui-implementation/deploy-plan.md` 新增**第 8.5 步**（50-verify 之后执行 `remote/90-close.sh` 写 `DEPLOY_STATE`，含 incomplete 的唯一例外与不可逆性）与 `§1.1` 候选实测参数表；`docs/operations/CURRENT_STATE.md` 追加同日收尾段落；交接见 `maintenance/templates/HANDOFF.md` 与 `local/web-ui-implementation/handoff.md`。
- 真实浏览器证据（r2 源码上重跑）：`capture-receipt-dropdown.mjs` 48 断言 all pass / 0 fail（5 用例 keyword1440 / keyword375 / multi1440 / multi375 / bare-code1440，证据 `local/web-ui-implementation/out/receipt-dropdown-20261102/evidence.json`）；`run-real-ui.mjs` 54 项 51 pass / 0 fail / 3 blocked（report `local/web-ui-implementation/out/run-real-2026-11-02T12-50-26-676Z/report.json`，3 blocked 为 `real-page-bag-detail-deferred` 缺 `WEBUI_BAG_ID`〔已由动态袋用例覆盖〕、`real-receipt-multi-create-lock` 与 `real-receipt-legacy-precondition` 缺 `WEBUI_LEGACY_ARCHIVE_ID`，不猜）；r1 时期两轮存量证据（`run-real-2026-11-02T10-22-34-590Z` 55 项 54 pass/1 fail=两枚 36px 按钮；修 44px 后 `run-real-2026-11-02T11-08-17-482Z` 34 项 30 pass/0 fail/4 blocked）仅作历史。部署仍阻塞：生产主机 `192.168.31.105` 不可达（ping 100% 丢失、TCP 22/8069 不可连、同网段无 ARP 表项），本轮未接触生产、未 SSH、未部署；不构成"生产已验证"或"全平台通过"结论。

## 2026.10.28 P3 自有 Web 日常业务（源码候选：功能验证完成，未发布/未部署）

- 版本（`components.json` 已同步）：`lab_workflow 19.0.1.2.0 → 19.0.2.0.0`、`lab_team_web 19.0.1.0.5 → 19.0.1.1.0`、`server-ops 2026.10.27.3 → 2026.10.28.1`；`lab_catalog`/`lab_inventory`/`lab_theme`/`lab_site`/`client 1.1.3+6`/`eda 3.0.3` 不变。
- `lab_team_web`：13 个业务页面（`/team/lab/receipts`、`/team/scan`、`/team/lab/bags[/<id>]`、`/team/lab/labels`、`/team/lab/issues[/new]`、`/team/lab/history`、`/team/lab/locations`、`/team/lab/location-mappings`、`/team/lab/settings`、`/team/lab/materials`、`/team/account`）+ 公共外壳与 `window.LC` 运行时；写操作走 JSON-RPC + 前端 `request_key`，唯一表单 POST 为 PDF。
- `lab_workflow`：8 个 JSON-RPC 窄接口（袋列表/袋详情/库位改停用/类别映射三件/成员与角色）、新模型 `lab.location.mapping`、`POST /lab/labels/pdf`、`GET /lab/scan` 303 至 `/team/scan`；修复安全审查 S1 跨账号归还、S2 畸形入参、S3 `adopt_stock` 部分提交、S4 按 id 读取复核公司、S5 停用库位。
- 运维：公网 allowlist 模板逐端点新增 P3 页面与 POST（源码，**未部署**；`adopt_stock`/`legacy_stock`/通用 ORM 明确不放行）；新增 `verify-p3-write.sh`、`browser_flow_p3.py`、`test_p3_runner.py`、`test_p3_gateway_contract.py`。
- 验证（分项如实记，**不构成"P3 全部验证通过"**）：
  - **已通过**：隔离 ORM 业务 **82/82，0 fail 0 error**（**role wrapper 之后真实重测**：`backend-orm-final.log` + `backend-orm-final-evidence/`，同轮 HTTP 6 并发亦过）；真实 HttpCase **21/21**（`httpcase-r8.log`：total=21 failed=0 errors=0 `p3_class_ran=1`，RC=0）；API 断言 **54 pass / 0 fail / 1 blocked**（total 55，1 blocked 为 Origin 断言——本轮未提供 Origin URL，**不能改判 PASS**）；Nginx 配置契约 1.26.2 **34/34**、1.30.6 **34/34**；独立 process adapter 并发 **6/6**（`concurrency-standalone-r3.json`，负向自检 `detected=true`）；linux runner **17**；core **17/17**；XML **6/6**；JS 语法 **15/15**；路由表 **79** 条。
  - 真实浏览器主链 **31 步 28 pass / 0 fail / 3 blocked**（`runs/browser-20261028T065311Z/browser-p3.json`、`browser-r8.log`）：3 blocked 为 `p3-cross-user-denied`、`p3-receipt-same-key-conflict`、`p3-unknown-outcome-retry` 的 **DOM 场景未执行**，由 API 断言 / HttpCase / core 独立覆盖，**不得写成 DOM 通过**。真实 UI+服务端事实成立：两种 canonical key、建袋不增 quant、上架 +2、重复确认 quant 不变、领用 −2、部分归还 +1，role/materials/locations/mappings 管理页可用。
  - 有效性前提（不得省略）：原 `--test-enable` 进程内并发套件因 **Registry 锁 blocked**（Probe 直接证实 `Registry._lock` 由主线程持有），wrapper 整体 **exit 1**，**不得称该命令全绿、也不得称"原进程套件通过"**；6 条并发断言由独立 process adapter 复用执行并全过。
  - 历史失败（ORM R3/R4、HTTP R2、HttpCase 9 error、浏览器缺 `websockets`）为修复前记录，保留在 `local/build/p3-web-20261028/` 供追溯。
- 候选内产品修复：`receipts.js` 把 `lcsc:<C码>` 正确转成裸 `C…` 交付 `resolve`，`lab:<id>` 走既有 `catalogDetail` 适配以保住具体本地档案；`LABB:`/`LABL:`/SN/立创原厂码路径不变。
- 测试 trace 读取口径：只从**本轮新增的唯一 DOM 行 td** 读 `raw` trace；仅扫码时才补 `LABB:` 前缀，**不得要求表格文本里出现 QR 前缀**。
- 冻结 / 构建 / 登记（**已完成**）：
  - 源快照 `maintenance/registry/source-server-p3-web-20261028.json`：**250 源文件**，treeSHA `fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43`，manifestSHA `0bfc1e3f581d90109c3e8942ff85cd9880a22ceac950d3c6fd93c0e90389c164`；`active-sources.server` 已指向该快照，旧 manifest 与旧产物未覆盖。
  - 候选包 `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`：**13,186,981 B**，SHA256 `9070800b65b8fa3c751b5d4ac0dc5d94910a97e27128adbd0ff4370c4549e564`；250 个文件逐条 raw+normalized 校验 + **251 个归档条目重读**全部一致；构建环境 Windows 11 + Python 3.15 stdlib zip；**纯源码，无 runtime/数据库/凭据**；源码 ZIP **签名 N/A**。
  - artifact 登记 `maintenance/registry/artifact-server-p3-web-20261028.json`；构建摘要 `local/build/p3-web-20261028/build-summary*.json`。
  - 仓库检查 `repo-final-r1.json`：**52 项检查 PASS，exit 0**，唯一 warning 为 `production-py312-rebuild`。
- 测试口径修正：`test_04` 的 quantity 为**精确匹配实际成功请求**（可能是 10 或 11），**不得硬编码 10**；两管理员并发互撤后保留 1 名 manager，另一侧 `FORBIDDEN` 属合法权限撤销。
- 未关闭（不因本轮完成而消失）：手机流量不挂 VPN 实测、实体摄像头/扫码枪、实体纸张打印、真机；生产 Python 3.12 **不等价**隔离 3.10.12，完整离线恢复（cp312 wheelhouse + 一致 filestore 备份，P2 旧备份附件不完整且非一致快照）未闭合；**未做生产部署与公网开放**。
- [交接](maintenance/handoffs/2026-10-28-p3-web-workflows.md)｜[任务](maintenance/tasks/2026-10-28-p3-web-workflows.md)｜证据与候选包在 `local/build/p3-web-20261028/`（Git 排除）。

## 2026.10.27 正式team域名HTTPS验收

- 用户完成标准CNAME，实际Netlify Edge正常SNI/证书与22项检查通过；旧LAN200已通过remote_ip识别并排除。
- 区域节点直连超时、官方默认负载均衡单点可直连，记录线路差异；未改DNS或代理，待手机流量无VPN正式域名验收，不作全网稳定性承诺。[记录](maintenance/audit/netlify-formal-domain-acceptance-20261027.md)。

## 2026.10.27 用户侧登录通过，正式域名待绑定

- 用户确认Netlify真实账号登录和功能正常；自动端到端22/0。精确停止已完成使命的7882固定文本诊断服务，保留日志。
- 正式team域名使用阿里云外部DNS+CNAME接入，无需切Netlify DNS委派；仍待正式TLS/会话验收。[记录](maintenance/audit/netlify-frontend-acceptance-20261027.md)。

## 2026.10.27 Netlify实际前端验收

- 用户已更新现有测试项目；实际HTTPS前端22/0，静态资产内容一致、敏感路由与Origin拒绝、动态响应不缓存。
- 真实账号会话仍待用户登录/刷新/退出确认，然后进行team域名绑定与CNAME切换；不覆盖此前冻结源/产物。
- [验收证据](maintenance/audit/netlify-frontend-acceptance-20261027.md)。

## 2026.10.27 Netlify HTTPS回源网关与部署包

- 专用origin-team证书签发；新增IPv4 bore16444/回环TLS18445，明确回源Host与公开Origin、canonical管理Host，禁止共享缓存/验证器，保留白名单与原LAN vhost。
- 新renderer9/0、原8/0+契约21/0、真实本机79/0、合成15/0、最新正常SNI公网22/0，自动重连通过；原21/1 TLS重置记录保留。
- 运维2026.10.27.3，新[冻结源](maintenance/registry/source-server-netlify-https-origin-20261027.json)211文件；Netlify ZIP记录来源和SHA，等待用户更新已有项目，尚未宣称前台/真实账号最终通过。
- [审计](maintenance/audit/netlify-https-origin-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-netlify-https-origin.md)。

## 2026.10.27 Netlify实际回源通过与HTTPS准备

- 用户站点rad-taffy-56e1ce.netlify.app回源成功；Lead独立web_fetch/本机IPv4无代理均确认200与完整标记，响应no-store、fwd=miss。
- 为专用origin-team回源名启动独立DNS-01证书请求，等待用户添加A/TXT；保留现有team证书与DNS。正式业务回源/登录尚未验收。
- [审计与DNS待办](maintenance/audit/netlify-https-origin-20261027.md)。

## 2026.10.27 Netlify最小回源测试准备

- 提供无需构建、可拖拽部署的独立测试包，Netlify200 rewrite请求固定文本IPv4 bore探针；校验归档与脚本语法并实际取得中继标记。
- 尚未部署Netlify，等待用户上传并返回站点URL；暂不改DNS，不改原官网，不连接生产Odoo。诊断服务24小时到期。
- [审计与后续条件](maintenance/audit/netlify-bore-probe-20261027.md)。

## 2026.10.27 IPv4 bore独立网关部署

- 新增经过校验的独立白名单网关renderer与systemd模板，运维2026.10.27.2；生产仅新增回环18443网关与159.223.110.159:16443隧道，保留内网vhost。
- Nginx1.18 Cookie兼容、精确Origin/Host端口、敏感路径默认拒绝、共享认证POST限速；生产本机49/0、合成12/0、无SNI严格TLS公网19/0、自动重连通过。
- 正常浏览器SNI仍需DNS切换后验收，真实账号未测；Qoder委派未返回产物，未算独立验收。
- [审计](maintenance/audit/bore-public-ipv4-deploy-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-bore-public-ipv4-deploy.md)｜[冻结源](maintenance/registry/source-server-bore-public-ipv4-20261027.json)。

## 2026.10.27 bore IPv4/代理诊断纠正

- 真实公网合成服务经现有HTTP代理CONNECT/正向转发成功，域名与IPv4均HTTP200+精确响应；独立curl复核exit0。仅本机直连该中继超时，不能推出境外全部封锁。
- 撤销此前“HTTP代理不转TCP、bore必须放弃”的错误判断；本轮未改VPN/DNS/生产配置，测试隧道已清理。生产公网白名单入口仍未部署。
- [审计](maintenance/audit/bore-ipv4-proxy-recheck-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-bore-ipv4-proxy-recheck.md)。

## 2026.10.27 P2 模块生产上线

- `lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5` 已在生产 LcHardwareHouse 上线；服务 active、TLS 登录 200，库存与其它模块未变。
- 修复备份工具默认 `data_dir` 与生产实际不符导致**附件漏备**的缺陷：现同时解析配置、当前用户与 `odoo` 服务用户 home，库内有附件但归档为空时直接失败；已补备 139 个真实附件并新增 3 项回归测试。
- 通用 `upgrade_modules.sh` 硬编码三模块且不含 `lab_team_web`，本次改用专用最小发布流程，避免误升级或漏升级。
- 未改 DNS/Nginx/公网入口；`team.l-creation.club` 仍指向内网 `192.168.31.105`。公网需真实节点+标准443+隧道登记。
- 新快照 [source-server-production-p2-20261027.json](maintenance/registry/source-server-production-p2-20261027.json)（202 文件）；`repo_check` PASS 52/0。
- [审计](maintenance/audit/production-p2-deploy-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-production-p2-deploy.md)。

## 2026.10.27 P2 隔离验收证据加固

- P2 127/0/0/0，exit 0；浏览器28/0，P1 116/0，hook7/0；lab_team_web19.0.1.0.5、lab_catalog19.0.2.0.5候选未部署。
- 修复authority丢端口、原生退出语义、资产代理安全地址回退和隧道就绪检查；严格CSP/SSRF/TLS边界不变。
- 下载清单独立Ed25519验签、中文截图复核、同轮计数和源码稳定性通过。旧77/0完整验收口径撤销，旧快照和失败轮次保留。
- bore167项（WSL165通过2缺Node跳过，Windows补测2/0）；lab_team_web87项（86通过1 HttpCase跳过）；lab_catalog23/0。
- 新快照：[source-server-p2-evidence-hardened-20261027.json](maintenance/registry/source-server-p2-evidence-hardened-20261027.json)。生产仅内网只读，无部署/重启/DB查询，公网与真机未验收。
- [审计](maintenance/audit/bore-p2-evidence-hardening-20261027.md)｜[交接](maintenance/handoffs/2026-10-27-p2-evidence-hardening.md)。

## 2026.10.26 P2 最终

- lab_team_web 19.0.1.0.4：白名单重建 JSON-RPC 错误脱敏（全限定名兼容、业务消息过滤、未知错误通用+trace_id、端点 gating、uninstall_hook/restore）；退出/登录相对跳转；JS 退出 fetch+CSRF。
- 入口：CSP/XFO/Referrer same-origin、POST Origin 精确同源、@COOKIE_FLAGS@（P2 运行时 Nginx 1.30.6 proxy_cookie_flags，1.26.2 仅探测）。
- 验证：P2 77/0 BLOCKED=2 SKIP=0；P1 94/0；契约 12/0；模块单测 OK；headless Chrome 真实流程（登录/检索/详情/刷新/退出，console/CSP 无错误）通过；合成 update release 匿名 manifest 200 与下载/字节/sha256/角色/遍历断言通过。
- 冻结：source-server-bore-p2-final3-20261026.json（194 文件，tree 3ba4ac57…），repo_check 51/0。

## 2026.10.26 P2 隔离闭环修复

- lab_team_web 19.0.1.0.3：白名单重建式 JSON-RPC 错误脱敏（全限定名兼容、业务消息过滤、未知错误通用化 + trace_id）；幂等安装/可还原/uninstall_hook；端点级 gating。
- 入口模板：CSP/XFO/Referrer、POST Origin 精确同源、@COOKIE_FLAGS@；P2 运行时 Nginx 1.30.6 proxy_cookie_flags（1.26.2 仅探测，不冻结）。
- 结果：P2 61/0 BLOCKED=3 SKIP=1；P1 回归 94/0；契约 12/0；脱敏单测 8/0。asset 公开源与更新包 blocked。

## 2026.10.26 P2 真实 Odoo 只读验证

- 新增 `server/ubuntu22.04/bore/scripts/verify-real-odoo.sh`（环境变量驱动，无凭据），在隔离 Odoo 19 上经最终 P1 模板验证登录/会话/角色/资源/更新清单/拒绝路径/限速，**PASS=46 FAIL=0**。
- 入口模板补 CSP/nosniff/X-Frame-Options/Referrer-Policy；契约测试增至 10 项。
- 记录待决策缺口：会话 Cookie 仅 HttpOnly、JSON-RPC 错误含 traceback、生产未应用新头、web.base.url 仍 http。

## 2026.10.26 bore 公网入口 P1 本地隔离实现

- 新增 `server/ubuntu22.04/bore`：默认拒绝的入口 Nginx 模板（精确路径/方法白名单）、代理头覆盖、限流钩子、边缘 stream 模板、本地验证脚本与契约测试。
- 本地实测：真实 Nginx 1.18.0 + bore 0.5.3 + 合成上游，完整链路（边缘 Nginx stream → bore → TLS+PROXY 入口 → 上游）**94 断言通过、0 失败**；契约测试 9 项通过；失败路径测试 10 项通过（端口占用/WORK 复用）；运行时完整性 10 项通过（篡改归档拒绝且不解包）。
- 上游研究：bore（MIT）官方无 PROXY protocol，边缘必须由成熟 Nginx stream 生成；浏览器/客户端旧调用迁移、真实 Odoo 会话与公网节点仍未验证。
- 仅本地/隔离；未部署、未开公网、未改生产。

## 2026.10.26 bore公网入口与自有UI整合方案

- 基于当前源码形成仅Odoo登录的公网入口、HTTPS/可信来源IP/精确路由白名单和完整自有UI迁移方案；记录免费中转与标准443约束，复用成熟能力。
- 盘点旧WebClient/网站/扫码页面及客户端调用，先补入库/领用归还/标签等业务，再收敛普通用户入口；原生维护仅管理员内网可达，网站卸载另审依赖。仅文档，不表示已实施或获准清库/卸载。

## 2026.10.25 管理子域名HTTPS接入

- 用户自行完成LE生产签发，team Nginx启用443与80到HTTPS的308跳转，保留认证补修和旧vhost。正常TLS与页面/保护/资产/旧更新清单12项独立检查通过。
- manual证书到期2027-01-23，续期未自动化；HTTPS真实账号流程未测。离开内网后DSH桥接不可用，最终备份/操作审计待恢复取得，不计全部收尾完成。

## 2026.10.25 新域名冷登录会话补修

- 仅在team域名原生认证代理清除选库请求头，修复Odoo19首次认证后无法持久保存会话；其他路由仍自动选库。备份后校验并reload Nginx，业务源码、旧vhost和库存未改。
- 隔离4组场景13条断言通过；生产匿名入口、错误账号及旧更新清单复核通过。用户随后确认“可以了”，原登录无反应已恢复；刷新保留登录及退出未追加实测，HTTPS尚未启用。

## 2026.10.25 内网管理域名HTTP接入

- team.l-creation.club新增独立Nginx vhost并固定生产数据库；现有lab_team_web启用该management_host，根欢迎页、/login、/lab可直接访问，无需旧数据库选择页，旧站/API兼容保留。
- 按追加授权把服务器自身DNS从失效localhost改为路由器192.168.31.1，停用旧dnsmasq并取消自启；保留配置与回滚备份，IP/路由/其他网络服务未改。
- 客户端真实域名三组15项HTTP响应符合预期，CSS/JS内容缓存键一致；业务源码/库存基线未改。HTTPS未启用，LE账号/协议待用户答复；真实账号全流程、VPN与视觉未重测，manual续期未自动化。

## 2026.10.25 独立仓库 Web 第一批

- 新增 lab_team_web 19.0.1.0.0：自有欢迎、登录、检索和详情页面，Odoo 继续提供认证、权限和真实库存；保留旧后台与 API。
- 修正安全回跳、异常白屏和登录表单提交；手机采用紧凑信息行，CSS/JS 使用内容 hash 更新缓存。
- 候选验证：65 项逻辑通过、1 项跳过；11 项隔离 HTTP 通过；桌面/375px核心浏览器流程通过。175 文件来源冻结，生产发布另记审计；后续入库领用、DNS 和真机不计已完成。
- 本轮完整备份后仅新增 lab_team_web 并上线，服务active，新18文件匹配、旧133文件及库存基线不变，原页面/更新通道正常。多库首次会话需经原登录选库，管理Host/根别名未启用；生产真实账号全流程未重测。

## 2026.10.24 门户安装

- lab_portal19.0.1.0.0：独立战队首页、原生管理系统登录入口；修正原稿XML、资源路径和登录循环。
- 隔离安装及错误登录流程验证后完整备份上线，生产首页/13资源/认证跳转通过，原库存与更新通道不变。浏览器控制被URL安全检查中止，视觉验收未完成。后台主题可读性问题仍未修复。

## 2026.10.24 Odoo暗色主题上线

- lab_catalog19.0.2.0.4：暗色与荧光绿主题；修正改稿类名不匹配，保留器件卡片/工作流/手机布局；仅屏幕应用主题。
- 生产完整备份后升级，108文件匹配、服务active、真实认证后台与CSS200，库存/更新通道不变。视觉、手机与打印验收仍待完成。

## 2026.10.19 Android更新发布与安装入口修复

- Android1.1.3+6已发布stable seq2，实际旧版验签/版本判断、LAN清单200、认证完整包/hash、403与匿名303通过；实机安装仍待验证，旧安装入口失败需手动覆盖一次。

- 按用户明确请求发布Android1.1.2+5 stable（清单200、旧版验签/递增判断、认证完整包/hash及拒绝访问均验证），实际手机安装仍失败，未把发布当作实体验收。
- 1.1.3+6修复合法私有缓存路径别名被错误拒绝，仍校验真实目录包含、大小/hash及APK身份；显示权限/校验/安装器/取消等具体原生原因。真实JVM路径9项、Flutter275通过5跳过，分析0错误0警告。

## 2026.10.19 器件选择修复

- 按本轮明确授权上线lab_workflow19.0.1.2.0更新接口，三端manifest204，库存/袋计数不变；完整备份和权限验证完成，未发布stable包。

- 客户端1.1.2+5：修复采购入库选择器无限高度白屏；弹层内显示立创资料清单、服务端搜索及自定义新建入口，打开不自动弹键盘。校验提示去除Bad state技术前缀。
- 更新面板展示当前目标服务器，区分接口404、未发布204和连接/清单错误；新增实际打开弹层及本地HTTP回归。测试和三端候选见本轮修复交接。

## 2026.10.19 客户端更新器候选

- 客户端1.1.1+4：启动/前台恢复检查、重试、签名/版本/平台校验、同源登录下载和更新面板；非计费网络后台下载，确认后Android系统安装或桌面独立助手切换完整包，保留旧版。增加过期会话、请求保护及Windows短暂文件锁处理。
- lab_workflow19.0.1.2.0候选：匿名最小发布清单、需lab角色的完整包下载；签名发布工具和配套来源/依赖登记。三端候选已构建，尚未部署新服务端、发布stable或完成两版原生升级验收。

## 2026.10.19 服务端上线与部署修复

- lab_workflow 19.0.1.1.0已上线，三模块installed，服务active/HTTP200；前后库存和袋记录数量一致，权限与单QR标签检查通过。
- 修复升级工具将旧模块目录留在addons根导致Odoo19扫描失败的问题；旧源码改存配套备份、升级前校验扫描边界，108项运维故障测试通过。首次失败与重试、完整备份定位均保留在上线交接。

## 2026.10.19 原生候选包

- 基于冻结源重建 Windows、Android、Linux 1.1.0+3；完整桌面bundle及APK记录SHA256，Android与既有证书匹配，Linux依赖和执行权限通过。构建默认指向本地验收服务，未发布替换旧包；原生启动与实体扫码打印待测。
- 构建工具增加独立Gradle缓存选项，维护测试8项通过。用户另授权服务端子代理上线，其生产结果见独立上线交接和审计。

## 2026.10.19 两阶段入库开发候选

- 客户端源码 1.1.0+3、lab_workflow 源码 19.0.1.1.0：新增先建档制袋打印、再扫码选择库位确认实际入库两个循环；支持手工建档、独立袋码、补打、取消、打印选择恢复和安全重试。
- 默认袋标签调整为稳定身份和关键参数；同料号已有库存库位优先。新服务校验当前账号／公司和操作权限，实际入库沿用库存事务并防止重复提交。
- 按 Apple 风格简化分组、字段及动作，增加文字缩放、明暗主题、超时和隔离事务／HTTP 并发验收；进程内并发夹具限制单列。未构建发布新安装包，未部署生产。

## 2026.10.19 两阶段入库计划

- 新增两阶段入库与袋标签计划书：先建档制码打印，再扫码确认实际入库；明确标签字段、接口边界和验收标准。功能尚未实现，未变更组件版本或生产环境。

## 2026.10.19 维护归档基线

- 统一当前Flutter、Odoo、EDA、采集同步的权威源码与发布入口；旧版本独立保留。
- 新增组件/成品/源码/大文件来源登记、AGENTS协作规范、任务交接模板与维护检查。
- 保留离线依赖、历史数据及原WSL实际工具；Git排除大文件与私有签名。
- 原工作区未删除；生产仅做限定源码/服务与公开依赖元数据只读导出，没有部署、重启或业务写入。
- 当前功能版本不因归档改号；已知测试限制见CURRENT_STATE。
