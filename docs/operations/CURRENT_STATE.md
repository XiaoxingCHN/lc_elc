# 当前状态与已知限制

## 2026-11-21 EDA 插件 4.0.0：去掉本机桥接，改用 API 密钥（未部署）

**背景**：用户要求「只装插件，不装别的东西」。旧版带 89 MB 的 Node 桥接 + 配对码，必须先双击启动一个进程。

**根因（查官方文档确认）**：EDA 的 `sys_ClientUrl.request()` 的 `options` 只有 `headers`/`integrity`，**没有 `credentials`**；而 `Cookie` 是 Fetch 规范的禁止请求头。Cookie 会话在插件里物理上不可能。`Authorization` 不是禁止头，而 Odoo 19 原生支持 `auth='bearer'`。

**新增 `lab_eda` 模块**（`server/ubuntu22.04/odoo_addons/lab_eda`）：
- `lab.eda.token`：绑定到具体用户，只存 sha256，发放权锁在 `group_lab_manager`
- 插件端点 `/lab/api/eda/*`（`auth='none'` + bearer）
- 管理页端点 `/lab/api/eda/manage/*`（`auth='user'` + 会话）
- 现有 50 个 `auth='user'` 路由**一个没动**，网页端零影响

**管理页**：`/lab/settings` 新增「EDA 插件密钥」区块（选择成员 → 备注 → 有效期 → 发放 → 明文只显示一次 → 列表显示前缀/到期/最近使用/状态 → 吊销）。

**插件**：删除 `bridge/`（含 92 MB node.exe）、`relay.js`、`images.js`、配对码、Cookie 会话；`odoo.js` 改为 bearer；设置页只剩「服务器地址 + EDA 密钥」。包体积 **89 MB → 103 KB**。

**验证（真实 Odoo + 真实 HTTP）**：
- `lab_eda` 21 项 ORM 测试全绿；插件 119 单元 + 15 打包 = 134 项全绿
- 无 token→MISSING_TOKEN、错 token→INVALID_TOKEN、吊销后立即失效
- 操作员 `can_issue_for_others=false`、borrowers 只有自己；管理员可选他人
- **操作员出库 `actor_id` = token 绑定用户**；管理员代领 `actor_id=7/borrower_id=8` 分离正确
- 管理页 `/lab/settings` 200，EDA 区块表头 5 列、表单字段、结果区全部渲染；`data-workflow-config` 里三个端点映射正确
- 页面级闭环：发放 → 明文 → bearer 生效 → 吊销 → 立即失效

**过程中修掉的真 bug**：
1. `lab_catalog` 和 `lab_workflow` 各有一个**同名不同类**的 `LabApiError`，`api_route` 只认自己那个 → 越权返回 `INTERNAL_ERROR` 而非 `FORBIDDEN`。已加 `_map_business_error` + 自己的 `eda_endpoint` 装饰器。
2. `lab_web_list()` 用 `search([])` 会过滤 `active=False`，吊销后的密钥从管理页消失。已加 `with_context(active_test=False)`。
3. `FORBIDDEN_CODES` 分支丢掉了 `error.fields`，UI 无法告诉用户缺哪个权限组。

**未部署到生产**。生产仍是 `lab_catalog 19.0.2.0.19` / `lab_inventory 19.0.1.1.1`，没有 `lab_eda`。

**未验证**：EDA 宿主实机（无法在此环境启动 EDA）。

## 2026-11-21 域名更正：正式域名是 team.l-creation.club

**`lc.rm.com` 是已停用的旧域名。** 全仓库（插件源码、默认配置、文档）已改为 `https://team.l-creation.club`；历史审计记录（`maintenance/audit/`、`maintenance/handoffs/` 与 CHANGELOG 的历史条目）保持原样，那是当时的真实记录，不改写。

- nginx 只有 `team.l-creation.club` 一个业务 vhost（`/etc/nginx/sites-enabled/team-l-creation-club`），另有一个 `default-catchall` 把未匹配请求 404。
- 实测：`https://team.l-creation.club/` 200、`/web/health` 200、内网 `http://192.168.31.105:8069/web/health` 200。
- 插件默认上游：`src/main/config.js` `DEFAULT_SERVER_URL`、`bridge/server.mjs` `DEFAULT_UPSTREAM` 均已改为 `https://team.l-creation.club`。
- 测试里的主机名统一改为 `lab.example.test`（占位符，避免再写死真实域名）；两条断言默认值的用例改为新域名。

## 2026-11-21 EDA 插件 3.2.0 + 服务端等效件：已部署并验证

- **免登录（P1+P2）**：凭证全部搬到本机桥接侧，插件端一个密码都不碰。新增 `bridge/lab-credentials.dat`，内容是 Windows DPAPI 加密后的 JSON（cookie 与密码同一个文件——`session_id` 本身就是 bearer 凭证，只加密一个没有意义）。桥接新增 `POST /session/restore`：cookie 有效直接进，失效用保存的密码自动重登，都失败返回 `restored: 'none'` 让插件回落到登录表单。`/logout` 删除保存的密码。`--no-save-credentials` 供公用机器。Linux 桥接不存密码。
- **等效件（S5）**：新增 `/lab/api/catalog/equivalents`，一次请求处理整张 BOM。判定逻辑在 `lab_inventory/tools/equivalent_match.py`（纯逻辑、可离线测试）：容值/阻值不同或耐压/功率低于需求 = 硬冲突，**直接丢弃不展示**；参数不足退化为同封装同类别并标 `weak`。候选必须有可用库存。
- **版本**：`lab_catalog 19.0.2.0.18 → 19.0.2.0.19`、`lab_inventory 19.0.1.1.0 → 19.0.1.1.1`、EDA 插件 `3.1.1 → 3.2.0`。
- **部署**：`upgrade_modules.sh --code-dir` 走完整流程（备份 → 停服务 → 换代码 → `-u` → 健康检查 → 起服务）。退出码 0、0 条 ERROR、`/web/health` 200、`/web/login` 200。备份点 `/var/backups/lc-elc/20261120T162716Z-before-upgrade`。生产模块版本已确认 `lab_catalog 19.0.2.0.19` / `lab_inventory 19.0.1.1.1`。
- **生产实测（Odoo shell，真实 stock.quant）**：造一组临时同规格器件（10kΩ ±1%，同封装），接口返回 `basis=params`、1 条 `strong` 候选、可用量 42、库位 R11、一致项「阻值 10kΩ / 精度 ±1%」。验证数据已删除，残留计数全为 0。
- **生产真实数据无自然等效对**：现有 80 个有库存器件里没有两个同规格不同编号的，所以 S5 的验收场景在生产上**无法自然复现**——这是数据现状，不是功能缺陷。
- **实测**：`test_equivalent_match.py` 21 项（纯逻辑，含 3 个已修 bug 的回归）；插件单元 131 + 桥接凭证 7 + 打包 15 = 153 全绿；`repo_check` PASS 53。
- **未验证**：`test_catalog_equivalents.py`（ORM 测试）仍未在 Odoo 测试运行器上跑过——生产库不是测试靶场（AGENTS.md），隔离库需要改 `pg_hba.conf`，已试过并回滚。等效件的 ORM 路径改为在生产库上用 Odoo shell 直接验证（见上）。
- **EDA 插件**：包已构建并交付用户，尚未在真实 EDA 宿主中实机验证。
- 设计文档：[EDA 免登录与等效件](../../maintenance/tasks/2026-11-20-eda-persist-login-and-equivalents-design.md)

## 2026-11-19 客户端 1.3.5+22：作业页覆盖外壳；服务端已部署

- 作业页（入库/领料/归还/标签/历史）曾带着分区切换器显示：`context.push` 在 shell 分支内会推到该分支的导航器。7 条根级路由加 `parentNavigatorKey: rootNavigatorKey` 后总是覆盖外壳。同时删掉 `/catalog` 在 `unifiedRoutes` 里的重复定义（根级那份赢得匹配，器件库其实不在外壳里）。
- **服务端已部署**：`lab_workflow 19.0.2.0.3 → 19.0.2.0.4`、`lab_team_web` 同步换代码。备份 `/var/backups/lc-elc/20261119T135447Z-before-upgrade`。升级退出码 0、0 条 ERROR、服务 active、`/web/health` 200、公网 `/` 200。
- 存量数据：模板 #16 `GH1.25 端子 2P`（`LAB-000025`）原 `is_storable=False`，已确认无无批次库存后改为 `is_storable=True / tracking=lot`。
- 实测：`flutter test` **510 passed / 5 skipped**；`analyze` 0 error / 0 warning。
- **未验证**：Android 实机、真实打印与扫码。

## 2026-11-19 客户端 1.3.5+21：手机切换器布局 + 内网 https 手误

- 手机底部栏里分区切换器被撑成整屏胶囊（`Center` 在有限高度约束下扩张）。实测 412×915 屏幕上从 412×907 修到 412×52，加回归测试。
- 登录页拦下 `https://<内网IP>:8069`（该端口明文无证书），直接提示改成 `http://`。`18443` 与公网地址不受影响。
- 实测：`flutter test` **509 passed / 5 skipped**；`analyze` 0 error / 0 warning。
- **未验证**：服务端修复未部署、Android 实机、真实打印扫码；未提交/未推送。

## 2026-11-19 修「新建器件」不可入库；制袋贴标补完成按钮

- **服务端 bug**：`lab_pending_create` 的新建器件分支漏设 `is_storable`/`tracking`，物料建成不可库存，制袋码能出但扫码上架必被拒（截图里的「未开启库存管理（is_storable=False）」）。已补 `is_storable=True` + `tracking='lot'`，并在 `test_workflow_business.py` 加断言钉住「手工建档的物料必须能真正入库」。
- **客户端**：制袋贴标页补收尾区「第 1 步 · 制袋贴标」——打印按钮 + **「完成贴标，进入『扫码上架』」**。此前这一页结束在打印按钮上，没有完成动作也没有下一步入口。
- 实测：`flutter test` **504 passed / 5 skipped**；`analyze` 0 error / 0 warning；服务端 `py_compile` 通过。
- **未验证**：服务端 Odoo 测试本机无法运行（Windows 无 Odoo 运行时），需在服务器上跑；未部署；未提交/未推送。

## 2026-11-19 客户端 1.3.5+19：卡片对比度修复 + 库位标签版式

- 库存管理卡片曾整张铺荧光绿而文字用 `onSurface`，对比度 **1.2:1**（不可读）。改为中性玻璃面板 + 强调色图标；新增 `warehouse_contrast_test.dart` 用 WCAG 公式钉住 ≥4.5:1，并把错误组合本身也钉住。桌面切换器改为左侧紧凑胶囊。
- 库位标签：QR 11 mm @(1,1)，**库码在 QR 正下方**（6 pt，落在码列内），**名称右侧 17 pt**。名称取 `名称：` 行而非 `title`（服务端库位标签的 title 是库码）。器件袋标签不变。
- 实测：`flutter test` **504 passed / 5 skipped**；`analyze` 0 error / 0 warning；真实 Windows 截图确认可读。
- **未验证**：真实打印与扫码、Android 实机；未提交/未推送。

## 2026-11-19 客户端 1.3.4+18：登录后拆成四个分区

- 落点从器件库改为 **库存速览** `/stock`。四分区：库存速览 / 仓位速览（`/stock/locations`，含仓位内容页 `/stock/locations/:id`）/ 器件库（原样）/ 库存管理（`/stock/manage` 五入口）。
- 切换用 `GlassSegmentedControl`：≥900 顶部、窄屏底部、200% 文本回退下拉；`StatefulShellRoute.indexedStack`，各区保留自己的栈。
- 作业页仍在根级全屏 push，深链与返回栈不变；`/home`、`/products` 仍重定向到 `/catalog`。无会话的离线浏览不渲染切换器。
- 数据层增量：`locations(with_stats)`、新增 `bags()` 接 `/inventory/bags`（分页 `next_cursor`，`limit` ≤100）。服务端零改动。
- 实测：`flutter test --no-pub` **488 passed / 5 skipped**；`analyze` 0 error / 0 warning；`build_client.py --platform windows --test` 三步 exit 0；`repo_check` **PASS 53 项**。
- 产物 `clients/windows/releases/1.3.4+18/LC_ELC-Windows-1.3.4+18-x64.zip`（37,731,644 B，sha256 `6cd4ca0e…c2472317`），清单 `source-client-1.3.4-18-20261119.json`（218 文件）已激活。
- **未验证**：真实数据下的分区切换与仓位分页、打印仓位标签、Android 布局；未提交/未推送。任务单 [四分区导航](../../maintenance/tasks/2026-11-19-four-section-navigation.md)。

## 2026-11-19 客户端 1.3.3+17：有线接入的内网加速；标签排版先完整后字号

- 内网加速提示原先只按 WiFi SSID 匹配，**插网线的台式机没有 SSID，功能静默失效**（用户：「Windows 平台有时候我的内网是通过有线接入的」）。新增 `lib/services/lan_probe.dart`（`GET /web/health`，3 秒、无凭据、仅私有网段，`<500` 即可达）；判定改为「报告了 SSID 仍以名称为准；没有 SSID 则探测成功才提示」，覆盖「填过 WiFi 名但今天插网线」。
- 标签排版两处修正：① `wrappedBody()` 的 `omitted.clear()` 会连「超出四行上限的源行」一起清掉，第五个字段没打出来却报 `truncated=false`；现拆 `capOmitted`/`wrapOmitted`。② 适配改两遍，先找「放得下且不丢行」的最大字号，宁可小 0.4 pt 也不丢字段。
- 清理 `DrawLableBarCode` 绑定（条形码方案已放弃）。
- 实测：`flutter test --no-pub` **468 passed / 5 skipped**；`analyze` 0 error / 0 warning；`build_client.py --platform windows --test` 三步 exit 0；`repo_check` **PASS 53 项**。产物 `clients/windows/releases/1.3.3+17/LC_ELC-Windows-1.3.3+17-x64.zip`（37,666,952 B，sha256 `f09957ae…32580c`），清单 `source-client-1.3.3-17-20261119.json` 已激活。
- **未验证**：真实插拔网线、现网 `/web/health` 返回、真实打印与扫码、Android 蓝牙出纸、应用内更新；未提交/未推送。交接 [有线内网加速与标签适配](../../maintenance/handoffs/2026-11-19-wired-lan-and-label-fit.md)。

## 2026-11-19 客户端 1.3.3+11：精臣 B1 Pro 热敏标签直打（Windows USB / Android 蓝牙）

- 三端：Windows `1.3.3+11`（USB 直打，随包 8 个 x64 DLL + ZT001.ttf）、Android `1.3.3+11`（蓝牙直打，仅 arm64-v8a / armeabi-v7a，102.6 MB）、Linux 仍 `1.3.2+10`（无精臣 Linux SDK）。
- 服务端 `lab_labels_preview` 增加可选 `include_content`（默认 false）：返回每张标签的 `title`/`lines`/`payload`，与 PDF 同源，供直打使用。
- 版式 40×20：QR 13×13 + 标题 6.49 pt + 正文 5.50 pt × 3 行；第 4 行省略并返回 `truncated`。
- 构建：两平台三步 exit 0，`flutter test` 各 456 passed / 5 skipped，`analyze` 0 error，`repo_check` PASS 53 项。
- **未验证**：真实 USB/蓝牙打印、权限弹窗、实体扫码、DPAPI、应用内更新；未提交/未推送。

## 2026-11-19 Android 精臣 B1 Pro 蓝牙直打（源码 + 构建通过；未实机出纸）

- **范围**：Flutter Android 客户端新增蓝牙直打（40×20 mm：一个二维码 + 标题 + 文字行），走服务端已就绪的 `/lab/api/labels/preview` 可选 `include_content: true`。服务端、Windows/Linux 打印路径未改；客户端 `pubspec` 版本未升（仍 `1.3.2+10`）。
- **SDK**：精臣 Android SDK 4.1.1（`4.1.1-release.aar` + **必需**的 `image-1.9.5.aar`）复制到 `clients/app/android/app/libs/`，来源 `F:\lc_elc\Android-4.1.1-20261117.zip`，SHA256 记录在同目录 README；未引入 LPAPI（B1 Pro 不需要）。V4.1.1 更新记录明确“SDK 支持 B1_Pro”。
- **实现**：`NiimbotPrinterBridge.kt`（`lab/printer` MethodChannel + `lab/printer/scan` EventChannel，扫描/连接子线程/打印缓存回调）；`lib/services/niimbot_android_printer.dart` 复用 Windows 侧的 `planThermalLabel` 几何计划；标签页在 Android 上显示搜索→列表→连接→打印区域，非 Android 或 SDK 不可用时隐藏；失败一律给具体中文原因，只有真实完成打印才显示成功。
- **权限**：Android 12+ `BLUETOOTH_SCAN`(neverForLocation)+`BLUETOOTH_CONNECT`，6–11 `ACCESS_FINE_LOCATION`，`BLUETOOTH`/`BLUETOOTH_ADMIN` 限 `maxSdkVersion=30`；运行时请求在 `MainActivity`。
- **混淆**：新增 `android/app/proguard-rules.pro`（文档 1.3 节规则），否则 Flutter release 的 R8 会破坏 SDK 反射/native 回调。
- **证据**：`flutter analyze` 0 error（119 条既有风格 info）；`flutter test --no-pub` **456 通过 / 5 跳过 / 0 失败**；`build_client.py --platform android --test` 三步 exit 0，APK 134,929,251 B sha256 `e31c4845…a50908`（内含两个 ABI 的 `libminilzo.so`/`libniimbot_canvas_image.so`/`libskia.so` 与 `assets/font/ZT001.ttf`）。`repo_check.py` 的 3 项 `frozen-source` 失败来自本工作树既有未提交改动，非本轮引入。
- **未做/边界**：真机蓝牙配对、实际出纸、开盖/缺纸/断线错误提示、Android 6–11 与 12+ 权限弹窗均 **未验证**；APK 只在 `local/build/`，未复制到 `clients/android/releases`、未登记快照、未发布、未提交。交接 [Android 精臣蓝牙直打](../../maintenance/handoffs/2026-11-19-android-niimbot-bluetooth.md)。

## 2026-11-18 Linux 客户端 1.3.2+10 构建（WSL；未实机验收）

- 三端补齐：Linux `1.3.2+10` 已在 WSL Ubuntu 22.04 用归档工具链构建，三步 exit 0，`flutter test` **340 passed / 5 skipped**；产物 `clients/linux/releases/1.3.2+10/LC_ELC-Linux-1.3.2+10.tar.gz`，16,503,485 B，sha256 `4f20594c…f78e5a`，bundle 内 `client-install.json` = 1.3.2 / build 10 / linux。
- 未附 `deps/` 离线 DEB，运行时依赖系统 GTK3/libsecret/cups；真实登录、打印、扫码、SecretService、桌面实机与签名发布清单仍未验证；未推送。

## 2026-11-14 旧工作区审核与退役（F:\lc_elc_workspace 已删除；补档 2,870 文件；`repo_check` exit 0）

- **结论**：旧工作区 `F:\lc_elc_workspace`（原 178,156 文件 / 49,676,894,303 B）经审核补档后于 **2026-11-14** 删除，目录已不存在；合并早在 2026-10-19 完成（commit `3b3c3af`、tag `archive-2026.10.19`、`original_files_deleted: 0`）。本轮未改源码、未提交/推送、未接触生产。
- **审核**：138,294 个已迁移目标中 138,107 个仍在；缺失 187 个全为 `dependencies/sdk/windows/flutter/.pub-preload-cache/*.tar.gz`；820 个抽查哈希中 51 个因迁移后源码演进不同，旧修订已补档。`lcscmigration/components.sqlite3` 与 `data/catalog/checkpoint-20261015/components.sqlite3` 全量 SHA256 一致（`ac536621032c6028b708847b4ee0d74669008c9dfd2dee480991dfa11ad60823`，各 3,547,037,696 B）。
- **补档**：2,870 文件 / 1,402,575,621 B 进入 Git 排除目录 `local/archive/workspace-candidates`（570）、`local/archive/eda/workspace-intermediates`（30）、`local/archive/evidence/analysis-workspace-20261014`（2,219）、`local/archive/source-import-before-format`（新增 51）。
- **记录路径**：逐文件来源与哈希 `local/manifests/workspace-retirement-20261114.json`；退役说明 `workspace-retirement-20261114.md`；复核 `merge-recheck-20261114.{json,log}`；删除日志 `workspace-purge-20261114.log`。
- **空间与检查**：删除 176,743 文件 / 46.243 GB（`robocopy /MIR /XJ`，0 失败），F: 可用 64.1 GB → 109 GB；`python tools/repo_check.py` exit 0。未归档：可重建缓存/运行时状态、`output\` 接线图、`.workbuddy` 会话状态。

## 2026-11-10 修复制袋贴标“选择器件无反应”，客户端 1.3.2+10（Windows / Android；未上更新通道）

- **版本**：`clients/app 1.3.1+9 → 1.3.2+10`（`pubspec.yaml`、`components.json` 一致）；服务端未动，生产仍 `lab_catalog 19.0.2.0.17` / `lab_team_web 19.0.1.2.7` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2`。
- **为什么**：用户实测“选择器件无反应”——输入 `STM32F401CCU` 提交仍提示“请选择器件”。三个静默路径：选中走 `_run()`，`_busy` 时直接 return；档案读取完成前不改界面，失败还丢弃选中；面板被外部点击关闭后再次点输入框不重新搜索。另修选中后改词不清除旧选中（详情把 `lcsc:C…` 换成 `lab:…` 时键比对失效）。
- **修复**：选中当帧提交并显示“已选中，正在读取内部档案…”，读取中禁止建袋；失败保留选中并说明原因；按“是否来自建议”清除选中；输入框 `onTap` 重开面板/重搜，回写标签不再当查询。
- **测试**：定向测试 28 passed（新增 6 条回归）；全量 `flutter test` **340 passed / 5 skipped**；`flutter analyze` **0 error / 0 warning / 119 info**。
- **产物**：Windows `clients/windows/releases/1.3.2+10/LC_ELC-Windows-1.3.2+10-x64.zip`（18,391,710 B，sha256 `35695044…92ba0`，19 文件，exe `d9d5be41…1764`，Authenticode 未签名，冒烟 RUNNING→STOPPED）；Android `clients/android/releases/1.3.2+10/LC_ELC-Android-1.3.2+10.apk`（74,876,669 B，sha256 `ae6df079…c493`，1.3.2 / code 10 / minSdk 24，证书 SHA-256 `8b4c2409…9ff43` 与已登记 keystore 一致）。
- **构建**：Windows 三步 exit 0（68.9s），Android 三步 exit 0（Gradle 175.6s）。Windows 构建需 `PDFIUM_LOCAL_ARCHIVE=<repo>/dependencies/windows/pdfium-win-x64-5200.tgz` 与本工作区 `local/pub-cache-windows`（带补丁的 printing 插件）；`--pub-cache` 必须传绝对路径。
- **清单/登记**：active `source-client-1.3.2-10-20261110.json`（180 文件，tree `d7aca661…cfdb`）；`artifact-client-windows-1.3.2-10-20261110.json`、`artifact-client-android-1.3.2-10-20261110.json`；交接 [客户端 1.3.2+10 选择修复](../../maintenance/handoffs/2026-11-10-client-1.3.2-selection-fix.md)。
- **未做/边界**：签名发布清单缺真实 `source_commit`（源码仍在工作区）；客户端更新通道未发布（生产写入需授权）；真实登录后的搜索/档案读取、实机安装与升级、打印、扫码、DPAPI、应用内更新未验证；未提交/推送。

## 2026-11-10 Flutter 客户端 1.3.1+9 打包发布（Windows / Android；未上更新通道）

- **版本**：客户端保持 `1.3.1+9`（`pubspec.yaml`、`components.json` 一致）；服务端未动，生产仍 `lab_catalog 19.0.2.0.17` / `lab_team_web 19.0.1.2.7` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2`。
- **为什么**：此前只有源码与 11-08 的 `local/build` 候选，`clients/windows/releases` 仍停 1.0.1、`clients/android/releases` 仍停 1.1.3+6；器件库按需抓取面板、详情页「刷新资料」等改动没有可安装包。
- **产物**：Windows `clients/windows/releases/1.3.1+9/LC_ELC-Windows-1.3.1+9-x64.zip`（18,386,856 B，sha256 `c0b2e2f0…88df73`，19 文件，exe `0e9a9bd8…`，Authenticode 未签名）；Android `clients/android/releases/1.3.1+9/LC_ELC-Android-1.3.1+9.apk`（74,876,669 B，sha256 `87c0f8cd…e34594`，1.3.1 / code 9 / minSdk 24，证书 SHA-256 `8b4c2409…9ff43` 与已登记 keystore 一致）。
- **构建/测试**：两平台 `build_client.py` 三步 exit 0；`flutter test` 各 334 passed / 5 skipped；Gradle 602.1s；Windows 冒烟 RUNNING→STOPPED；包内 AOT 含“立即从立创商城抓取/刷新资料/选这个”。`repo_check.py` exit 0。
- **默认地址**：包内 `LAB_ODOO_URL=http://192.168.31.105:8069`、`LAB_ODOO_DB=LcHardwareHouse`，新装走内网直连；登录页可改。
- **清单/登记**：active `source-client-1.3.1-9-20261110.json`（180 文件，tree `c8057727…bd2160`）；`artifact-client-windows-1.3.1-9-20261110.json`、`artifact-client-android-1.3.1-9-20261110.json`；交接 [客户端 1.3.1+9 发布](../../maintenance/handoffs/2026-11-10-client-1.3.1-release.md)。
- **未做/边界**：签名发布清单缺真实 `source_commit`（源码仍在工作区）；客户端更新通道未发布（生产写入需授权）；真实登录/打印/扫码/DPAPI/实机安装未验证；未提交/推送。

## 2026-11-09 器件详情链路修复（已部署：19.0.2.0.17 / 19.0.1.2.7）

- **根因**：立创中文详情页 `item.szlcsc.com` 现在返回阿里云 WAF 的 JS 验证页，旧代码把"中文页不可用"当成整条抓取失败，官方 SMT 接口已给出的名称/型号/品牌/封装/库存/价格/参数被一起丢弃；网页入库建的"立创物料 Cxxx（待补全）"占位档案又不会回填，详情页只显示本地档案、没有任何参数。
- **行为（现在）**：中文页被风控拦截且官方通道有数据时，按官方事实入库（分类按官方 `componentType` 名称匹配，匹配不到退回 wmsc 一级分类），请求置 `done` 并注明"中文详情页被立创风控拦截"；没有官方数据时仍按可重试错误处理。入库后自动回填该 C 编号下的占位档案（名称/型号/品牌/封装/文档/规格，只填空字段）。搜索与详情按"绑定表 ∪ 档案自身 C 码"取档案，没有 binding 行的网页入库档案也能看到库存/袋/流水。详情页对只有本地档案的编号显示"资料还没有抓取"的说明。
- **前端修正**：候选与旧空态不再同屏（`renderCandidates`、`startFetch` 都会收起下拉）；查询比较与服务端同口径（`normQuery`：去空白 + NFKC + 大写），`STM32 G437` 这类输入也能触发自动接续；建袋锁定时点候选只提示、不改输入、不抓取；`done` 但无 `item_key` 时不拿旧输入去解析。
- **生产实测（2026-11-09 22:12–22:28 CST）**：`C503071` 由官方兜底收录为 `STM32F407IGH6 / ST / UFBGA-201 / 13 条参数 / 单片机(MCU/MPU/SOC)`，`detail('lcsc:C503071')` 返回参数与档案 #10；占位档案名称已回填。四次部署 `-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_catalog|19.0.2.0.17`、`lab_team_web|19.0.1.2.7`；服务 active、`/web/login` 带库头 200、日志 0 错误。备份 `20261109T141243Z / 142322Z / 142603Z / 142847Z`（filestore sha256 `4ac71554…`、`7dfc749b…`、`85cd4dea…`、`da583eee…`）。
- **测试**：`test_p3_ui_consistency.py` 27/27、`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_lcsc_remote.py` 25/25、`test_lcsc_openapi.py` 23/23、Node 23/23 与 19/19、`repo_check.py`/`generate_routes.py --check`/`git diff --check` 均 exit 0；新增的两条 Odoo ORM 用例需数据库，本机未跑，已用生产 `odoo shell` 复核等价结果。
- **清单**：active `source-server-web-fetch-entry-20261109-r9.json`（274 文件，tree `4144e419…c9b6`）；`…-r6/r7/r8.json` 与更早清单保留。
- **仍未验证/边界**：不破解立创验证码，中文分类细分与文档等待 WAF 自行解除；官方兜底路径未做浏览器手测；`C503071` 的 PDF 文档暂缺；请求 17（`STM32F103C8T6` → `C8734`）是修复前失败记录，未自动重跑。
## 2026-11-09 采购入库无感接续检索 + 器件详情入口（已部署：19.0.1.2.4 / 19.0.2.0.15）

- **行为**：采购入库的料号下拉仍先查本地库；本地零结果且服务端给出 `fetch_suggestion` 时，输入静默 800ms 后**自动**接续立创——关键词只列候选（选定某个 C 码后才抓资料），精确 C 码/完整 MPN 直接抓取。同一关键词本页只自动打一次，输入一变取消，抓取中/建袋锁定不触发；原空态按钮保留为显式重试。
- **详情入口**：选中物料后卡片显示「查看器件详情（参数 / 文档 / 档案与流水）」，新标签页打开 `/lab/items/<item_key>`（如 `/lab/items/lcsc:C54110218`）。
- **版本/部署**：`lab_team_web 19.0.1.2.4`、`lab_catalog 19.0.2.0.15`（`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2` 未变），**已于 2026-11-09 14:21 CST 部署生产**（19.0.1.2.4 修正：抓取未结束时改词不再丢掉自动接续，旧结果不覆盖已改输入；备份 `/var/backups/lc-elc/20261109T062109Z-before-upgrade`，归档 sha256 `898baf77…34aa9a`） → `-u lab_team_web` 退出码 0、0 条 ERROR/CRITICAL/Traceback；DB `lab_team_web|19.0.1.2.4|installed`；服务 active、`/web/login` 带库头 200、Odoo 返回的 `receipts.js`（86,734 B）已含补排与旧结果保护、视图 arch 含详情入口；重启后日志 0 错误。
- **抓取慢的根因（19.0.2.0.15，17:21 CST 部署）**：`wmsc.lcsc.com` 的 AAAA（CloudFront）在本机不可达，`urllib` 逐条尝试 IPv6 使单次搜索耗时 120 秒，同步抓取必然超预算转后台、cron 也被拖住。已改为只解析 IPv4（`_IPv4HTTPSConnection`）并在读响应时逐块核对预算；生产实测搜索 0.55s / 详情 0.48s / 中文页 0.36s。部署后原先排队的 `STM32F427IIH6` 由 cron 在 14 秒内完成，`lab_catalog_item` 已收录 `C503072`（13 条参数，`fetched_at 2026-11-09 09:23:49Z`）；此前每 120 秒被 Odoo 杀掉的 cron worker 超时不再出现。部署备份 `/var/backups/lc-elc/20261109T092100Z-before-upgrade`（归档 sha256 `6bc3cf32…c701c`），`-u lab_catalog` 退出码 0、0 错误；DB `lab_catalog|19.0.2.0.15|installed`。
- **测试**：`test_p3_ui_consistency.py` 21/21（新增 6 条）、`test_lcsc_remote.py` 25/25（新增 IPv4 断言）、`test_p3_web_contract.py` 28/28、`test_entry_contract.py` 11/11、`test_combobox.mjs` 23/23、`test_workflow_core.mjs` 19/19、`node --check` OK、`repo_check.py`/`generate_routes.py --check`/`git diff --check` 均 exit 0。
- **清单**：active server 清单 `source-server-web-fetch-entry-20261109-r5.json`（274 文件，tree `18007fa1…14b48`，清单 sha256 `460ff5ae…f5e4`）；`…-r4.json`、`…-r3.json`、`…-r2.json` 与更早清单保留。
- **未验证/风险**：手机端自动接续的真实手感、`not_found`/失败态、限流（5 个进行中 / 每小时 20 次）与"锁被占用退回 cron"均未实测；自动关键词查询会提高立创接口调用量，需观察命中质量与频次。

## 2026-11-09 网页端采购入库按需抓取入口（已部署：19.0.2.0.14 / 19.0.1.2.2）

- **行为**：网页端「采购入库」料号输入零结果时，服务端给出 `fetch_suggestion` 才显示按钮——C 号/完整 MPN 是「立即从立创商城抓取」，≥5 字符含字母的关键词是「到立创商城查候选」。点击后同步抓取（15 秒服务端预算），未完成则前端每 1.5 秒轮询 `fetch_status`（最多 60 秒）；抓到后输入收敛为 `lcsc:Cxxxx` 并走既有解析；关键词只列候选，选定某个 C 码后才抓完整资料。不写库存、不自动建袋。
- **版本**：`lab_catalog 19.0.2.0.14`、`lab_team_web 19.0.1.2.2`（`components.json` 已同步）；**已于 2026-11-09 00:27 CST 部署到生产**（备份 → 停服务 → 换两模块代码 → `-u` 退出码 0、0 条 ERROR/CRITICAL/Traceback → 起服务；DB 复核 `lab_catalog|19.0.2.0.14|installed`、`lab_team_web|19.0.1.2.2|installed`；`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2` 未变；`odoo.service` active、`/web/login` 带库头 200、10 分钟日志 0 错误；备份 `/var/backups/lc-elc/20261108T162707Z-before-upgrade`，归档 sha256 `35d17e9e…9ce4d`）。部署脚本新增 `--modules` 参数（原来只认三个业务模块，`lab_team_web` 无法随批部署）。
- **变化点**：关键词候选门槛 6 → 5 字符（仍要求含字母），用户截图里的 `tlv77` 因此可以走候选；`common.py` 登记 `catalogFetch`/`catalogFetchStatus`，并把 `lc_version` 修正为 `19.0.1.2.2`（原来显示 `19.0.1.1.0`，与 manifest 不符）。
- **测试**：`test_lcsc_remote.py` 24/24、`test_lcsc_openapi.py` 23/23、`test_p3_web_contract.py` 28/28、`test_p3_ui_consistency.py` 15/15、`test_entry_contract.py` 11/11、`test_combobox.mjs` 23/23、`test_workflow_core.mjs` 19/19、`node --check receipts.js` OK。
- **清单/检查**：active server 清单切到 `source-server-web-fetch-entry-20261109.json`（274 文件，tree `a3ee3678…a899472`，清单 sha256 `b204f65c…39cbbeb`），本轮早先的 `…-20261108.json` 与 `…-r2.json` 原样保留；`repo_check.py` exit 0、`generate_routes.py --check` exit 0、`git diff --check` 0。
- **公网入口修复**：首次实测时抓取返回 `INTERNAL_ERROR`，原因是公网网关 allowlist 未登记 `catalog/fetch`、`catalog/fetch_status`（Netlify→bore 网关直接 404，请求未到 Odoo）。已新建并切换到网关 release `p3-web-20261109T010500Z`（旧 release 原样复制 + 两条 location，`nginx -t` 通过、`nginx -T` 确认、reload；回滚点 `rollback/project-include.before`，原 include sha `34289f26…08ef` → 新 `7e9566d6…2371`）。公网两个端点现均 200 并到达 Odoo。仓库模板与契约测试同步补齐。旧的直连公网网关 release `20261027-a2` 未改。
- **官方接口边界**：C 码走官方 SMT 通道；官方关键词搜索接口对当前账号返回"接口权限不足"，关键词候选仍走 LCSC 网页搜索（只读），选定 C 码后才走官方 SMT。
- **清单/检查**：active server 清单已切到 `source-server-web-fetch-entry-20261109-r2.json`（274 文件，tree `6946414f…3cb4c2`，清单 sha256 `fb459a5f…3469f9`），`…20261109.json` 与更早清单保留；`repo_check.py` exit 0、`generate_routes.py --check` exit 0、`git diff --check` 0。
- **浏览器实测**：2026-11-09 01:0x CST 用户在手机端重试 `tlv77`，抓取/候选入口已正常。仍未验证限流、"锁被占用退回 cron"、`not_found`/失败态的真实呈现；未提交/推送。

## 2026-11-08 接入立创官方 OpenAPI（19.0.2.0.13 已部署；凭据已注入 systemd）

- **行为**：按 C 编号抓取资料时先查官方 SMT 通道 `/smtOpenApi/smtComponent/selectComponentInfoByCodes`，用官方返回的名称/型号/品牌/封装/库存/阶梯价/中文参数（`paramTextAll`）覆盖页面解析结果；分类与文档仍由中文页解析给出。未配置 `LCSC_OPENAPI_*` 环境变量或官方接口报错时静默回退页面解析，行为与 `19.0.2.0.12` 相同。官方接口只读，**不写本地库存**。
- **版本**：`lab_catalog 19.0.2.0.13`（`components.json` 已同步），客户端 `1.3.1+9`；**`19.0.2.0.13` 已于 2026-11-08 09:16Z 部署到生产**——`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108c/modules`，备份 → 停服务 → 换三模块代码 → `-u` 退出码 0、输出 0 条 ERROR/CRITICAL/Traceback；`ir_module_module` 复核 `lab_catalog|19.0.2.0.13|installed`（`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2` 同批）；部署目录与暂存副本源码哈希一致（排 `__pycache__` 后均 `132338bc…7f6ae3`）；`odoo.service` active、`/web/login` 带库头 200、`Modules loaded` 09:18:00Z、09:16Z 起 0 条 ERROR/CRITICAL/Traceback、cron 25 正常；备份 `/var/backups/lc-elc/20261108T091631Z-before-upgrade/`（归档 sha256 `087c2fe7…ff79fe`）。
- **实测**：本机只读探针 `--probe C17414` → `PROBE_OK`（名称/型号/封装/库存 49,946,661/首档价 0.0202/中文参数 7 条）；签名已与官方文档示例对拍一致。凭据在 `local/private/`（Git 排除）。
- **生产凭据（2026-11-08 09:26–09:29Z 已注入）**：`/etc/lc-elc/openapi.env`（`root:odoo 0640`，4 个键）+ `/etc/systemd/system/odoo.service.d/10-lc-elc-openapi.conf`（`EnvironmentFile=-/etc/lc-elc/openapi.env`），`daemon-reload` + `restart odoo` 退出码 0。复核 `EnvironmentFiles` 已加载、odoo 主进程环境四个变量齐备（只记长度 24/18/32/32，不记值）、重启后 `odoo.service` active、`/web/login` 带库头 **200**、09:27Z 起日志 **0 条 ERROR/CRITICAL/Traceback**。服务器侧用同一 env 跑签名探针：`--probe C17414` → `CHANNEL smt`，`stock=49,948,000`、`price=0.0202`、`params=7`，`rc=0`。临时传输文件已清理。
- **测试**：`test_lcsc_openapi.py` **23/23**、`test_lcsc_remote.py` **24/24**；**Odoo 运行时用例未跑**（本机无 Odoo/PG）。
- **清单/检查**：active server 清单切到 `source-server-lcsc-openapi-20261108.json`（274 文件，tree `740bc540…56e903e`，清单 sha256 `f1754c79…a4121e0`），旧清单未改写；`repo_check.py` **exit 0 / PASS / 52 项 / 0 错误**（16 条既有 payload 警告照旧）；`generate_routes.py --check` exit 0（94 条）。
- **Odoo 运行时实测（2026-11-08 13:0xZ，生产库，只读 + `rollback`）**：在 `odoo shell` 里构造 `Environment` 后调 `_official_item('C17414')` → `OFFICIAL_OK True`，`stock=49,941,126`、`price=0.0202`、`params=7`、`tiers=6`、`source=openapi_smt`；同一探针不加载 `LCSC_OPENAPI_*` 时返回 `False`（静默回退），行为符合设计。探针用 `set -a; . /etc/lc-elc/openapi.env` 加载与服务单元同一份文件；未写库，日志无新增错误。
- **未做**：未通过网页端/客户端做一次真实抓取入库（只直接调了模型方法）；Odoo ORM/HttpCase 用例未跑；客户端 Windows 候选包在 `local/build/windows-1.3.1/candidate-20261108-r1/`（未进发布目录）；未提交/推送。
- **交接**：[官方接口与 Windows 构建](../../maintenance/handoffs/2026-11-08-windows-1.3.1-and-openapi.md)｜[任务单](../../maintenance/tasks/2026-11-08-lcsc-openapi-integration.md)。

## 2026-11-08 立创资料改为纯按需抓取（19.0.2.0.12 已部署；客户端包待构建）

- **行为**：整库搜索、入库/待入库建议面板、器件详情页三个入口都能对精确 C 码/完整 MPN 当场抓取（服务端 15 秒预算；锁被占用或超预算退回每分钟 cron，前端继续轮询）。详情页「刷新资料」只刷新当前这一条（`refresh: true` + 单个 `catalog_code`），没有列表级/全库刷新。**规范化后大于 5 个字符且含字母的关键词**只做候选检索：只调用一次立创搜索接口，候选带 `name`/`mpn`/`brand`/`package`/`catalog_code`，不打开中文详情页、不写库；人选定后才抓取。≤5 字符关键词、纯数字仍不发请求。
- **版本**：源码为 `lab_catalog 19.0.2.0.12`、客户端 `1.3.1+9`（`components.json` 已同步）；**`19.0.2.0.12` 已于 2026-11-08 04:37Z 部署到生产**（备份 → 停服务 → 换代码 → `-u` 退出码 0、输出 0 条 ERROR/CRITICAL/Traceback → 起服务；部署后三模块树哈希与暂存副本一致，`lab_catalog/__manifest__.py` = `19.0.2.0.12`，04:38:52Z `Modules loaded`，`/web/login` 带 DB 头 200，04:37Z 起时间戳行 0 条 ERROR/CRITICAL/Traceback，两个 `lcsc-*.timer` 仍 `disabled`/`inactive`；备份 `/var/backups/lc-elc/20261108T043724Z-before-upgrade/`，`db.dump` 119,023,251 B / `a6ad4c1b…4b55c3`，`filestore.tar.gz` 12,819,190 B / `08670f20…4e0ea3`）。上一版 `lab_catalog 19.0.2.0.11` 的部署记录（2026-11-08 01:00 本地）仍在下面保留：`19.0.2.0.11` 已于 2026-11-08 01:00（本地）部署到生产：`upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261108/modules`，`-u` 完成、`odoo.service` active、55 模块加载、`/web/login` 带 DB 头 200、17:00Z 起日志 0 条 ERROR/CRITICAL/Traceback；三个模块的树哈希与暂存副本一致。备份 `/var/backups/lc-elc/20261107T170002Z-before-upgrade/`（`db.dump` 119,011,646 B / `2654a241…cb4ca5`，`filestore.tar.gz` 12,819,190 B / `ae429c94…f9f414`）。
- **夜间批量已停用（2026-11-08 01:00 本地）**：`lcsc-crawler.timer` / `lcsc-crawler-stop.timer` 现均 `disabled`/`inactive`，`lcsc-crawler.service` 与 `lcsc-catalog-import.service` 均 inactive；unit 与采集器源码保留，手工全量重建仍可用。停用前已核实它们长期空转（`cn_queue` 无 pending 行，2 秒退出、0 条抓取、库行数不变）。
- **测试**：`test_lcsc_remote.py` **24/24**（含关键词门槛、候选名称与非电子过滤）；真实候选检索已试（`TLV9001`/`STM32F103` 各 10 条，带名称与封装，未打开详情页）；新增 Odoo 用例 `test_catalog_fetch_inline.py` 已注册但**未运行**（本机无 Odoo/PG）；`flutter test --no-pub` **334 passed / 5 skipped / 0 failed**；`flutter analyze` **0 error / 0 warning / 120 info（exit 1）**。
- **清单/检查**：active 清单已切到 `source-server-keyword-candidates-20261108.json`（272 文件，tree `21a6800c…31c8e`）与 `source-client-keyword-candidates-20261108.json`（180 文件，tree `c8057727…bd2160`），上一版 `source-*-on-demand-fetch-20261108.json` 原样保留；`repo_check.py` **exit 0 / PASS / 0 错误**，16 条既有 payload 警告照旧；`git diff --check` exit 0。旧清单未改写，指针回指即可回滚。
- **未做/阻塞**：未构建客户端 `1.3.1+9` 包（现网客户端尚无关键词候选界面）；真实网络端到端手测（两个搜索入口 ≤20 秒、关键词候选、详情页只改目标行 `fetched_at`、锁占用退回队列）；DB 侧 `ir_module_module.latest_version` 未查；Odoo ORM 用例未运行；未提交/推送。首次部署尝试因暂存 ops 目录缺 `lc_archive.py` 在备份步骤中止（未停服务、未换代码），补齐后重试成功。
- **交接**：[按需抓取交接](../../maintenance/handoffs/2026-11-08-on-demand-only-fetch.md)｜[任务单](../../maintenance/tasks/2026-11-08-on-demand-only-fetch.md)。

## 2026-11-07 按需抓取源码已冻结（repo_check 归零）

- **active 清单**：server → `maintenance/registry/source-server-catalog-fetch-20261106.json`（271 文件，tree `10c3aa4a…4cf7757f`，清单 sha256 `fd087000…dce555f0`）；client → `source-client-catalog-fetch-20261106.json`（178 文件，tree `a2d5d42c…6add70abeb`，清单 sha256 `dd872ded…8dbaedf250`）。旧 `source-server-param-search-20261104-r2.json` 与 `source-client-liquid-glass-20261106.json` 未改写，指针回指即可回滚。
- **检查**：`python tools/repo_check.py` **exit 0 / result=PASS / 52 项通过 / 0 错误**（冻结前 exit 1：`frozen-source:client` 4 文件、`frozen-source:server` 13 文件）；16 条既有离线载荷警告仍在，`--verify-payloads` 未执行，不记作全仓零告警。`generate_routes.py --check` exit 0、`git diff --check` exit 0。
- **边界**：清单只记录源码哈希，不代表可安装产物；客户端未构建包，生产未再变更（仍为 2026-11-06 部署的 `lab_catalog 19.0.2.0.10` 等四模块）。未推送。
- **任务单**：[冻结源码清单](../../maintenance/tasks/2026-11-07-freeze-catalog-fetch-sources.md)。

## 2026-11-06 器件库按需抓取已部署生产（cron 已运行；DB 行已核对）

- **版本与范围**：生产 `/opt/odoo/custom-addons` 现为 `lab_catalog 19.0.2.0.10`、`lab_inventory 19.0.1.1.0`、`lab_workflow 19.0.2.0.2`；本次 `-u` 覆盖这三个模块，`lab_team_web 19.0.1.2.1` 未参与。客户端源码仍 `1.2.0+7`，未构建/发布安装包。
- **部署执行**：`server/ubuntu22.04/upgrade_modules.sh --code-dir /home/hbut/lc-deploy-20261106/modules`，2026-11-06T14:29–14:31Z；步骤 4 `-u lab_inventory,lab_catalog,lab_workflow` **退出码 0、ERROR/CRITICAL/Traceback 行数 0**。
- **备份/回滚**：`/var/backups/lc-elc/20261106T142949Z-before-upgrade/`——`db.dump` **118,970,696 B** / `40863d500fffc8f36013cd99da8625d3ed988799826f6633cc178f41d3ba0d66`；`filestore.tar.gz` **12,819,190 B** / `5b9e5d42a03d339dcbab225ad3e1da09913b4b853dcded117fcb29614a3f5fc0`；`MANIFEST.json` 17,246 B、`odoo.log.tail`；旧三模块源码在 `module-source-before-upgrade/`。
- **健康检查**：脚本步骤 5 把 `/web/login` 的 **303**（→ `/web/database/selector`）判为失败，与 2026-11-04 相同的既有脚本缺陷，不是服务故障；独立复核：`X-Odoo-Database: LcHardwareHouse` 时 `/web/login` **200**、`odoo.service` **active/enabled**、Odoo 于 14:31:36Z 打印 `Modules loaded`（55 模块）。
- **运行证据（免 sudo 可复核）**：`/var/log/odoo/odoo.log` 自 2026-11-06 14:30Z 至 2026-11-07 13:11Z **0 条 ERROR/CRITICAL/Traceback**；`ir.cron` 任务「器件库：处理在线补抓队列」（id 25，`data/lab_catalog_cron.xml` 声明每 1 分钟、`model._cron_process_queue(limit=2)`）自 **2026-11-06 14:31:16Z** 起持续运行，至 2026-11-07 13:11:47Z 共 **1356 次启动、0 次失败**，每次 `fully done (#loop 1; done 0; remaining 0)`（队列当前为空）。这同时说明新模型已加载、`lab_catalog_fetch_request` 表可用、cron 已入库。
- **DB 行核对（2026-11-07T13:17:07Z，只读脚本 `verify_deploy.sh`，root 下以 `runuser -u odoo psql` 查询）**：四模块均 `installed`——`lab_catalog|19.0.2.0.10`、`lab_inventory|19.0.1.1.0`、`lab_workflow|19.0.2.0.2`、`lab_team_web|19.0.1.2.1`；`to_regclass('lab_catalog_fetch_request')` 存在，7 个索引含部分唯一索引 `lab_catalog_fetch_active_uniq`（谓词 `state IN ('queued','resolving','fetching')`）与 `lab_catalog_fetch_state_idx`；`ir_model_data` 的 `lab_catalog.ir_cron_lab_catalog_fetch` → `res_id=25`，与日志中每 62 秒运行的 job 25 一致。输出文件 `/home/hbut/lc-deploy-20261106/verify-20261107T131707Z.txt`。
- **数据未受影响（2026-11-07T13:32:04Z 补查，`verify2-20261107T133203Z.txt`）**：`lab_catalog_item` **695,217** 行（与 2026-11-04 部署时一致）、`lab_catalog_param` **4,110,477** 行、`lab_catalog_fetch_request` **0** 行（队列空）；`ir_cron` 表 25 号行存在，列清单证实 Odoo 19 用 `ir_actions_server_id` 而非 `model_id`（第一步脚本在此中断的原因）。HTTP/服务/日志段已由独立命令复核（见上条），不依赖该脚本。
- **未做**：真实网络端到端（C32445874 / TLV77333PDBVR / TLV77733PDBVR 抓取与中文入库）、Flutter widget 测试、客户端包构建、source manifest 冻结。
- **交接**：[按需抓取实施记录](../../maintenance/handoffs/2026-11-06-catalog-on-demand-fetch.md)。

## 2026-11-06 器件库按需抓取源码候选（【已部署】见上一节；源清单未冻结）

- **版本与边界**：`lab_catalog 19.0.2.0.9 → 19.0.2.0.10`（`components.json` 已同步）；客户端源码变更但版本仍为 `1.2.0+7`。**本节其余内容是 2026-11-06 部署前的时点记录**：其中「未升级模块、未注册 `ir.cron`、未建表、未部署、未提交」均已被后续动作改变（部署见上一节，改动已提交为 `e563da0`）；source manifest 仍未冻结。
- **服务端**：`lab_catalog/tools/lcsc_remote.py` 用固定域名（`wmsc.lcsc.com`、`item.szlcsc.com`）完成 C 码/精确 MPN 取数，中文字段全部来自中文详情页；`lab.catalog.fetch.request` 状态机 + 部分唯一索引去重 + advisory lock 串行的每分钟 cron（2 条）；`/lab/api/catalog/search` 空结果返回 `fetch_suggestion`，新增 `/lab/api/catalog/fetch`、`/fetch_status`；只写 `lab.catalog.item/param` 与供应商库存，不写产品/quant/move。
- **客户端**：空结果页“立即从立创商城抓取”，1 秒轮询最多 60 次，成功自动刷新；多候选必须人工选择；失败显示中文原因可重试；换查询取消轮询。
- **实际验证**：`flutter test --no-pub` exit 0，**326 passed / 5 skipped / 0 failed**（基线 319/5）；`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 120 info**；`test_lcsc_remote.py` 15/15。`python tools/repo_check.py` exit 1，50 项通过，错误为本轮未冻结的 `frozen-source:client`（4 文件）与 `frozen-source:server`（13 文件），16 条 payload 警告为既有缺口；`generate_routes.py` 重新生成 `routes.json`（94 条）后 `--check` exit 0，`git diff --check` exit 0。
- **未验证**：Odoo/PostgreSQL 测试库 ORM 用例、真实网络端到端（三个目标料号）、Flutter widget 测试、真实生产环境。
- **交接**：[按需抓取实施记录](../../maintenance/handoffs/2026-11-06-catalog-on-demand-fetch.md)。

## 2026-11-06 Flutter Liquid Glass 源码候选（未发布/未部署）

- **版本与边界**：客户端 `1.1.3+6 → 1.2.0+7`，`pubspec.yaml` 与 `components.json` 已同步；默认深色玻璃 + 荧光绿。保留路由、文案、登录记忆、参数搜索、待入库服务端筛选与库存语义；零新增 pub 依赖。未构建、签名或发布安装包，未生产部署、未推送。
- **设计系统**：`lib/ui/glass/` 提供 tokens/surface/chrome/controls/theme；`lab_ui.dart` 保持兼容。只有 `GlassSurface` 创建 `BackdropFilter`，真实模糊限于 chrome/抽屉/建议/浮层，内容卡片与 `GlassPanel` 默认无模糊。修复 prominent 的 accent/onAccent 配对、默认面板过度模糊、更新宿主接入回归。Material 主操作通过统一主题呈现，不机械替换全部按钮。
- **业务屏**：登录、器件库、详情、收/领/还、标签、离线与两阶段入库接入视觉层；`StatusBanner` 统一图标+文字状态。待入库服务端 query/state、去抖与慢响应序号保护不变；A4 预览白底黑字。Flutter 材质是近似实现，不声称具备原生真实折射。
- **实际验证**：Flutter 3.47.7 / Dart 3.13.5，`flutter analyze --no-pub lib test` exit 1，**0 error / 0 warning / 118 info**；`flutter test --no-pub --reporter compact` exit 0，**319 passed / 5 skipped / 0 failed**。6 张深色离屏 PNG（登录、1280 器件库、详情、入库准备/扫码、A4）已逐张检查，无溢出；320/1280 × 深/浅 × 200% 文本与 prominent/高对比度/减少动效由 widget 测试覆盖。
- **冻结**：`maintenance/registry/source-client-liquid-glass-20261106.json`（177 文件，tree `a19e0ddf2f7cdba420ae7605763c40926c3745d3ab5de60387c8aab7da1d0e4e`，清单 SHA256 `930b53e17d189a0b5ab1fb1a507aa74ce7d2be7c57d1cad91892f07486c6b11c`），已 `--activate`，旧清单未改写。
- **仓库检查**：`generate_routes.py --check` exit 0（92 条既有路由），`git diff --check` exit 0。`python tools/repo_check.py` exit 1，51 项通过，**唯一错误 `frozen-source:server`**：9 个已登记服务端文件（catalog `19.0.2.0.9`、workflow `19.0.2.0.2` 相关工作区源码）晚于 active r2；客户端冻结通过。16 条离线载荷警告为既有缺口，`--verify-payloads` 未执行。该服务端差异不属于本轮 UI，不能记作已冻结/已部署。
- **未验证**：三端真机、profile 滚动性能、真实触控、读屏、摄像头/扫码枪、OS 安全存储、实体打印；PNG 为离屏证据，不代表这些项目通过。
- **交接**：[Flutter Liquid Glass](../../maintenance/handoffs/2026-11-06-client-liquid-glass.md)。

## 2026-11-04 入库参数关键词搜索（已部署；真实浏览器验收待做）

- **性质**：分支 `feat/receipt-param-search`（从 `main` `c808065` 切出）上的源码候选；**未提交、未推送**。生产已于 **2026-11-04T12:59–13:09Z** 从 r3 升级到本候选。
- **版本（生产已 installed）**：`lab_inventory 19.0.1.1.0`、`lab_catalog 19.0.2.0.6`、`lab_workflow 19.0.2.0.1`、`lab_team_web 19.0.1.2.1`；`components.json` 已同步，client/eda/theme/site 不变。
- **已实现**：共享参数选取/归一化（含 `10Ω = 10R`、`4.7Ω = 4R7`、`0.1Ω = R1`、`4k7`、`1k5`、`100nF = 0.1uF`）；`product.template.lab_search_specs` 与迁移回填；`lab.catalog.item.search_params`、参数行增量重算、导入器写入与独立回填脚本；检索空白分词 AND（身份字段 + 参数文本），保留本地有货优先排序；`/lab/api/catalog/search` 响应新增 `param_index_ready`；待入库队列 query/state/total；Web 队列筛选、"共 N 条"、combobox "查看全部结果"、索引未就绪提示。
- **生产部署**：四模块 `-u lab_inventory,lab_catalog,lab_workflow,lab_team_web` 退出码 0、0 条 ERROR/CRITICAL/Traceback；`odoo.service active`；`/web/login` 返回 303 → `/web/database/selector`（带 cookie 跟随后最终 200 登录页，不是故障）；`lab_team_web` 静态 JS 200（75,312 B）且含 `pendingTotal`/`viewAllLabel`。参数回填 **695,217/695,217**，`lab_catalog.param_index_state=ready`；回填日志 0 条 Traceback/ERROR/CRITICAL。
- **备份/回滚**：`/opt/odoo/backups/20261104T125944Z-before-upgrade/`（`db.dump` 110,948,317 B / `2c8bd939…810794`；`filestore.tar.gz` 12,819,190 B / `c180ca54…c929f`）；旧四模块源码在同目录 `module-source-before-upgrade/`，回滚工具在 `deploy-tools/`。升级/回填日志 `param-search-upgrade-20261104T125944Z.log`、`param-search-backfill-20261104T130525Z.log`。
- **测试（真实执行）**：纯归一化 8/8、combobox 21/21、workflow_core 19/19、`py_compile` OK、`git diff --check` 0；生产升级与回填日志如上。**未执行**：Odoo ORM/HttpCase（本工作区无可用 Odoo/PostgreSQL 测试实例）、真实浏览器 `10R`/`4R7`/`R1`/`100nF`/`0.1uF` 搜索、待入库队列筛选、Flutter。新增 ORM 与队列用例已写入但未运行，不能记作通过。
- **冻结与检查**：新建并激活 `maintenance/registry/source-server-param-search-20261104-r2.json`（264 文件，tree_sha256 `503e278221851fa129351bae12e95b6da5a8eeb5192d4e8ab2e5907c270ab378`，清单 sha256 `485c93c2ca3d1543bf8bb8838acb538f24c0a6f23ae4b68418cd4c8f3410b86a`）；r1 与旧 r3 清单未改写。`repo_check` = 51 项通过 / exit 1，唯一错误为既有 `frozen-source:client`（`clients/app/t.obj` 缺失），16 条 payload 警告为既有离线载荷缺口；`generate_routes.py --check` = 0。
- **未做/风险**：目录导入、真实业务写、Flutter 回归未做；短 token（如 `1%`）误命中未在真实库评估；本地档案仅 2 条占位记录，`lab_specifications` 搜索不能宣称生产覆盖。标准 `server/ubuntu22.04/upgrade_modules.sh` 仍只升级三模块，且把 `/web/login` 的 303 判为失败；本次用四模块副本 + `finish_remote.sh` 完成，后续应修脚本以免重复手工收尾。

## 2026-11-03 P3 Web 生产部署完成（r3 → 生产 LcHardwareHouse；公网回归通过）

- **结论**：r3 冻结候选已于 **2026-11-03 00:16–00:36Z** 部署到生产 `192.168.31.105`（DB `LcHardwareHouse`），
  `DEPLOY_STATE=completed`（`DEPLOY_COMPLETED_UTC=20261103T003543Z`、`DEPLOY_FACTS_PROVEN=43`），odoo.service active、
  HTTP `/web/login` 200；公网 `team.l-creation.club` 回归全项通过。**此前各节的「未部署 / 生产主机不可达」均为部署前时点结论。**
- **版本生效**：`lab_team_web 19.0.1.1.0 → 19.0.1.2.0`（`-u lab_team_web`，`UPGRADE_EXIT=0`、错误行 0）；
  `lab_workflow 19.0.2.0.0`、`lab_catalog 19.0.2.0.5`、`lab_inventory 19.0.1.0.0` 未变；`lab_site` 仅权限归一（内容 = 冻结）、
  `lab_theme` 仅由 `deploy-theme.sh` 换成冻结版。生产运行面：Odoo19、`/opt/odoo/venv/bin/python3`（Python 3.12.15）、
  `/etc/odoo.conf`、`/opt/odoo/custom-addons`、data_dir `/opt/odoo/.local/share/Odoo`、base 19.0.1.3、已装 55 模块、nginx 1.18.0。
- **一致备份（停服态）** `/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`：`db.dump` 110,944,415 B /
  `40c76d0679d2a7915ba5857d5009c291c18f17fdf239803a484246228993ba19`；`filestore.tar.gz` 12,819,190 B /
  `305b841f50f0b3417b120a3ff0b52e61800d533f3a2337418f3114a2d85abfda`（611 条目）；`MANIFEST.json`、`odoo.log.tail`；
  `store_fname` distinct 139 / tar 成员 140 / 缺失 0；`service_was_active=false`。
  源码回滚快照 `/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`。
- **菜单**：before 234 行（其中 lab_* 21 行，sha `3eb392d0…`）→ after `removed=0 / added=1 / changed=12 / match=1`；
  新增 `lab_team_web.menu_legacy_label_wizard`（id 382，parent `lab_workflow.menu_lab_config`，action `lab_workflow.action_lab_label_open`）；
  12 条仅 action 变（旧入口改指）；菜单树稳定 sha `bafa905fc5f5fdb65fe3ea72af42647e78300b685d5323b9764db26e9ec64b8c`。
- **网关**：release `/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z`；`/etc/nginx/conf.d/lc-bore-netlify.conf` 现 include 该 release 的
  `gateway.conf`，include sha `34289f2612c9adb460c787c6765f72525bd1db5359eff515164cbb1ab42508ef`（切换前 `bb3164e5…`，
  回滚点同目录 `rollback/project-include.before`）；allowlist pages 24 / apis 5 / legacy 13；未动 `lc-bore-public.conf`、DNS、Docker、其他服务。
- **50-verify**：**PASS，129 项检查 / 0 失败**（`/var/tmp/lc-deploy/verify-20261103T003528Z.json` + `verify-facts-…env`）；
  三模块逐文件与冻结清单逐字节相等（`lab_site 19` / `lab_team_web 58` / `lab_theme 6` 文件）；13 条 legacy action GET/HEAD 全过、POST 全拒；
  `/web/login`、`/database`、`/jsonrpc`、ORM 404；`workflow_core.js` sha `6942f733fddaf4b3183a0251ad5d2ac99913d4c339921ca48dc59b7346cc0936`。
- **90-close**：`DEPLOY_STATE=completed`、`DEPLOY_COMPLETED_UTC=20261103T003543Z`、`DEPLOY_FACTS_PROVEN=43`；run env
  `/var/tmp/lc-deploy/run-20261103T001600Z.env`（sha `20f5b3fe34c2ed6c1c3f35a6141368a729a4e3baf4532ccdafe5dfb7905ec008`）、
  close log `/var/tmp/lc-deploy/close-20261103T003543Z.log`。
- **公网回归**（`team.l-creation.club` 经 Netlify→bore→网关）：`/ 200`、`/login 200`、`/team/login 200`、`/team/lab/receipts 303`、
  `/team/scan 303`、`/lab/bags 303`、`/odoo/action-lab_workflow.action_lab_scan_console 303`、`/odoo/action-lab_inventory.action_lab_mapping 303`、
  `/web/login 404`、`GET /lab/api/inventory/bags 403`、`POST /team/lab/receipts 403`、`POST /lab/api/catalog/search 415`、
  `workflow_core.js` sha 一致、`pages/receipts.js 200`、`workflow_receipt.css 200`。
- **最终部署包** `deploy-bundle-web-ui-20261102-r3.tar.gz`：**93,486 B** / `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / 27 条目 /
  FROZEN 18 条 / shipped 15 / `bundle-meta` freeze `f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`；
  部署前中间包 91,307 B/`8215a795…`、91,586 B/`e453db43…`、92,857 B/`085945a2…` **均非最终**。
- **部署期修复的脚本缺陷（已修）**：`05-bootstrap.sh`（tar 选项顺序 / mawk 转义斜杠正则 / members.txt 误判顶层，
  sha `f2d46931a5ddf15d430f63c469f78476345a22aa20be367526301e70b6755fde`）、`00-preflight.sh`（网关 include 闸门改声明式，
  `c48bbfddb5070f35e7724761b7a865ed3e0ab7a32d2abb1385b88577bd8ef99a`）、`lib.sh`（`http_login_code` 多路径 + `X-Odoo-Database`，
  `d5da44ed05aa46fab3e90bf53fe2215bbc490c1bbff315b63445db261817ba98`）、`40-gateway.py`（reload 优雅切换竞态加有界 settle，
  `487283ee6ee844a0ca81af66f57cda70fcc1a74579bb506be2096125cb231e7b`）、`50-verify.py`（`ir_ui_menu.action` Char vs res_id int、
  origin 探针补 DB 头、公网 5xx 有界重试，`14d4c1e084691486c5b231028848a553b948f269aae802c5238ee55a64997f0d`）；
  `FROZEN-20261102.sha256` 已同步，`check-scripts` `SYNTAX_ERRORS=0`、`USED_BUT_MISSING none`。
- **证据**：`local/web-ui-implementation/evidence/production/p3-deploy-evidence-20261103.tar.gz`（21,344 B /
  `53433008c3bb6ae48da899105e64d2fd6e814b24a47d5b2617a3fe9cdc8069b5` / 20 条目，Git 排除）。
- **凭据**：`local/private/web-ui-20261102.dpapi` 部署后已删除（`BLOB_DELETED`），本机不再存生产口令。
- **仍未做**：未 commit/push（分支 `codex/receipt-search-feedback` 仍在工作区）；未建/发布客户端包（客户端 `1.1.3+6` 不变）；
  未做真实业务写入；未动 DNS/Docker/其他服务；未执行回滚（回滚点已备）；未读 CI。

## 2026-11-02 自有 Web 统一 UI（历史时点：本机实施轮，早于冻结；当前冻结口径见下一节 r3）与生产状态只读核对

- **本轮性质（历史）**：本机实施 + 隔离实例验证，分支 `codex/receipt-search-feedback`（基线 `b3bcbf244e44939c6d481e3f97f11579cdf9ee99`）。
  **未提交、未推送、当时未冻结、未连生产**（同日随后重新冻结为 r2、继而 r3，见下一节）；下文 10-28 节的「未部署生产」只描述那一轮，不能当作 2026-11-02 的生产结论。
- **已落地（有隔离实测证据）**：整站骨架 1024px 断点（≥1024 固定侧栏 / ≤1023 抽屉）、`LC.combobox`
  （250ms 去抖、IME 组字不检索、请求序号 + 在途 ≤2 + 8s 显式超时 + 「重试检索」、方向键/Enter/Esc/Tab 与 aria 语义）、
  来料页关键词候选与多档案明确选择、建袋结果未知期锁定 `material-select`、旧入口 13 条 `/odoo/action-<xmlid>`
  兼容路由（非 GET/HEAD 返回 405，不重放写操作）、菜单可逆改指（卸载还原、保留用户自定义）。
  证据：模块用例 52/52、真实 Chrome 15/15、14 个路由 × 桌面/375 共 28 张截图、
  `node .../tests/test_combobox.mjs` 20/20、`tests/test_workflow_core.mjs` 17/17、bore 契约 19 项 OK。
- **生产状态（截至 2026-11-01 只读预检，见 `local/web-ui-implementation/deploy-preflight.md`，Git 排除）**：
  磁盘 addons 的 20/20 静态资源 hash 与冻结登记 `maintenance/registry/source-server-p3-web-20261028.json` 一致；
  **DB 内模块版本 / 表 / 库存未核实**（psql 报 `FATAL: role "hbut" does not exist`、Peer authentication failed，缺提权）；
  公网 `/web/login`、`/team/lab/receipts`、`/team/scan`、`/lab/api/catalog/search`、`/web/static/*` 为 nginx 404（146B 体），
  而内网同样路径分别 200/303/303/405/200。→ 因此**不以“已部署/未部署”定性**，DB 与公网入口仍待核实。
- **回滚风险（旧备份不合格）**：2026-10-27 P2 的 `filestore.tar.gz` 只有 59B 空包，真实 139 个附件在事后单独补包且未进
  `MANIFEST.artifacts`；`odoo_restore.py` 只解 `filestore.tar.gz` 且不做 `store_fname` 交叉校验 → 旧备份不是一致回滚点，
  正式部署前必须重新做停机一致备份（DB dump + filestore 同刻、校验清单与还原清单）。
- **仍未验证**：13 个业务页的逐页交互验收、异常权限下的 403/登录表现、Flutter 端适配、生产 DB 与公网入口、
  CSP 在真实网关链路上的行为（直连隔离服务没有项目网关 CSP，不能据此声称生产合规）。
## 2026-11-02 收尾：r3 版本冻结 / 源候选 / 部署包（r2、r1 已被 r3 取代；本节为部署前时点，**2026-11-03 已部署，见上一节**）

- **版本已定版**并同步 `maintenance/registry/components.json`：`lab_team_web 19.0.1.1.0 → 19.0.1.2.0`、
  `server-ops 2026.10.28.1 → 2026.11.02.1`；`lab_workflow`/`lab_catalog`/`lab_inventory`/`lab_theme`/`lab_site` 源码版本未动。
  `lab_workflow` 为 `19.0.2.0.0`（`server/ubuntu22.04/odoo_addons/lab_workflow/__manifest__.py:4`，与
  `maintenance/registry/components.json` 及生产 DB 记录一致；早先「磁盘 19.0.2.0.5 / 三处不一致」是误记，已更正）。
- **r2 相对 r1 的唯一源码变化（历史；r2 已被 r3 取代）**：`server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css:2198` 新增
  `body.lc-body .lc-panel:has(.lc-combobox-pop:not([hidden])) { overflow: visible; }`，修掉 375px 窄屏下下拉向上展开被
  `.lc-panel { overflow: hidden }` 裁切、点击落不到选项的真实缺陷。r1 冻结于该修复之前，**已被 r2 取代，不得部署**
  （r1 数字仅作历史：manifest `634d1893…`/`fe34ed95…`、ZIP 13,251,270 B、bundle 91,154 B）。
- **r3 相对 r2 的源码变化（共 2 处，只改 `team.css`；r3 为当前候选）**：① 在 `body.lc-body` 令牌块内
  （`server/ubuntu22.04/odoo_addons/lab_team_web/static/src/css/team.css:38-41`，`--lc-ease` 之后、`display:flex` 之前）
  新增 `color-scheme: dark`，使原生滚动条 / select / input 按深色 UA 渲染；② `team.css:2181` 的 `.lc-combobox-pop`
  由 `max-width: min(540px, calc(100vw - 28px))` 改为 `min(780px, calc(100vw - 28px))`，桌面 1440 时候选弹层与
  770px 输入框同左同宽，窄屏仍受视口约束（注释补句在 `team.css:2166`）。其余 CSS 属性、JS、XML、Python 均未改；
  manifest 差异仅这一个文件，258 个源文件数量不变（无增删）。
- **已知遗留 B / C 已修复（实测值）**：B（深色主题缺 `color-scheme`，原生控件按浅色 UA 渲染）：5 个下拉用例
  `colorScheme` 实测均为 `dark`（修复前 `normal`），原生滚动条 / select / input 跟随深色；C（1440 下拉偏窄）：
  1440 视口实测 `input=770px`、`pop=770px`（gap 0，修复前 540px），375 视口 `input=pop=277px` 且
  `document.scrollWidth=375` 无横向溢出（窄屏仍受视口约束）。
- **升级验证（r3 源码上重跑，隔离实例，真实退出码）**：`local/web-ui-implementation/browser/upgrade-only-test.sh`
  → RUN=`upgrade-keepdb-20261102T134429Z`，`ODOO_EXIT=0`，`/lab_team_web` 用例 **52 tests，FAIL: / ERROR: 计数 0**，日志
  `local/web-ui-implementation/evidence/upgrade-keepdb-20261102T134429Z.log`（r2 轮的 RUN=`upgrade-keepdb-20261102T125331Z` 仅作历史）；DB 实测
  `lab_team_web=19.0.1.2.0`（state=installed），`lab_workflow` 记录仍为 `19.0.2.0.0`、`lab_catalog 19.0.2.0.5` 不变。
- **同轮重跑（更正上一节数字；r3 轮沿用，未重跑，与 r3 的 CSS 改动无关）**：`tests/test_combobox.mjs` 20/20；`tests/test_workflow_core.mjs` **19/19**
  （上一节写 17/17 是同日更早一轮）；bore 契约 `Ran 19 tests ... OK (skipped=7)`（7 skip 为环境相关）。
- **冻结与产物（r3，本机，未部署）**：源清单
  [source-server-web-ui-20261102-r3.json](../../maintenance/registry/source-server-web-ui-20261102-r3.json)
  **258 文件**，treeSHA `95baea916fbe4c8504e9a3bc2ce1c18235cf53689373d323b32d914d1e1fe8de`，
  manifestSHA `2192a3545ebbe2ea3293072d1cc971a8deab1e524a4e39c20503d760888a7224`，已 `--activate`
  （`active-sources.server` 指向 r3；`source-server-p3-web-20261028.json`、r1 `source-server-web-ui-20261102.json`
  与 r2 `source-server-web-ui-20261102-r2.json` 未改写）；
  候选包 `local/build/web-ui-20261102/candidates/server-web-ui-20261102-r3-source.zip`
  （**13,251,571 B**，SHA256 `3800e2a210a1c0fdad562112b4682ed02d83ae466f678443bfafb1923a02d4f7`，
  259 条目 = 258 源文件 + `MANIFEST.json`，构建报告 `local/build/web-ui-20261102/candidates/build-summary-20261102-r3.json`）；部署包
  `local/build/web-ui-20261102/candidates/deploy-bundle-web-ui-20261102-r3.tar.gz`（部署前中间包 **91,307 B**，
  SHA256 `8215a7958fe227452f19f3458a149509169cfd3cf26fadfbd6ecad82b6e8f02d`，27 条目；
  **2026-11-03 更新**：部署期修复 5 个脚本缺陷后重打，最终实际部署包为 **93,486 B** /
  `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` / 27 条目 / `FROZEN-20261102.sha256` 18 条 /
  `bundle-meta.json` 的 `freeze_sha256` = `f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`、`shipped_script_count=15`；
  91,586 B / `e453db43…`、92,857 B / `085945a2…` 同为部署前中间包，均非最终；`params.env` 已指向 r3 的 zip/manifest 与两个 sha）；登记
  [artifact-server-web-ui-20261102-r3.json](../../maintenance/registry/artifact-server-web-ui-20261102-r3.json)
  （新文件，`kind=source-only-local-candidate`；**`production_deployed` 已于 2026-11-03 部署后改为 true**，并新增 `production_deployment` 块与 `validation_results.production_post_verify` / `public_regression`；`supersedes` 指向 r2 登记）。
  r2 的数字仅作历史（ZIP 13,251,445 B / `cb868d76…`、bundle 91,273 B / `84808261…`、FROZEN 19 条 = 15 + 3 + 1 空行）；
  r2 的清单、两个包与 artifact 登记均保持未改写。
- **真实浏览器证据（均在 r3 源码上重跑）**：下拉截图 `node local/web-ui-implementation/browser/capture-receipt-dropdown.mjs`
  = **53 断言 all pass / 0 fail**（`evidence.json` 记 total 53 / pass 53 / fail 0 / failedIds `[]`，证据
  `local/web-ui-implementation/out/receipt-dropdown-20261102/evidence.json`；补充截图
  `.../receipt-dropdown-20261102/width-fix-1440.png`（118,206 B，1440×900）、`width-fix-375.png`（67,712 B，375×812）
  与度量原始数据 `width-fix-measure.json`，headless Chrome 156.0.8078.74）；全站真实套件
  `node local/web-ui-implementation/run-real-ui.mjs` = **55 项 55 pass / 0 fail / 0 blocked**（`exitCode 0`，
  `writeGate` 全 true），report `local/web-ui-implementation/out/run-real-2026-11-02T13-38-39-691Z/report.json`；
  r2 时 3 项 blocked 已消失：静态袋详情按 1440/375 真跑出 2 条（`/team/lab/bags/41`，lab.bag id=41，
  trace `TRC00000045`，company=1；httpStatus 200、errCount 0、horizontalOverflow false、smallTargetCount 0），
  `real-receipt-multi-create-lock`（archiveId=13，product.template 13，C990000001，tracking=none，无批次库存 12.00；
  createPosts=1、payloadTemplate=13、payloadMatch true、trace `TRC00000046`）与 `real-receipt-legacy-precondition`
  （code=`PRECONDITION_FAILED`、fieldsItemKey=`legacy_untracked_stock`、库存 12→12 未变、hasBag false、界面提示可见）
  一并通过。（r2 轮为 48 断言、54 项 51P/0F/3B，仅作历史。）
- **套件证据缺陷（工具问题，非产品缺陷；已补证据，未改工具源码）**：真实浏览器套件在给了 `WEBUI_BAG_ID` 后，
  静态袋页与交互节动态袋详情共用测试 id 前缀 `real-bag-detail-<1440|375>`，同一 id 出现两次且截图按 id 命名
  互相覆盖，`13-38-39Z` 目录里 `real-bag-detail-1440.png` 实际是动态袋 42；已用 `--only=pages` 复跑
  （`local/web-ui-implementation/out/run-real-2026-11-02T13-40-31-993Z/report.json` = 35 项 32 pass / 0 fail / 3 blocked，
  3 个 blocked 全为 `--only` 主动跳过 interactions/drawer/manager 的标记，`exitCode 3`）留下静态袋 41 截图
  `shots/real-bag-detail-1440.png`（172,807 B，1440×2258）。建议后续把静态页 id 改成 `real-page-bag-detail-<vw>`。
  另注：同库并发跑套件会互相污染合成数据，只能串行执行。
- **仓库检查（r3）**：`python tools/repo_check.py` = PASS / 52 项 / **errors 0** / 1 条既有 warning
  （`production-py312-rebuild`），证据 `local/web-ui-implementation/evidence/repo-check-20261102-r3.json`；`git diff --check` = 0（r1 时期修掉 `team.css` 文件尾多空行，随后 r2 又新增 CSS 规则并重新冻结）。
  本文档上一版曾记「更新时点（2026-11-02 21 时前后）重跑 repo_check = FAIL / 51 项 / 1 error `frozen-source:client`
  （`clients/app/lib/features/unified/` 下 `inventory_providers.dart`、`pending_receipt_screen.dart`、`receipt_screen.dart`
  与冻结源不一致）」——那次 FAIL 的真实原因是**客户端改动（收据/待打印入库页内联搜索建议）当时尚未冻结**，不是仓库回归；
  冻结客户端源码后重跑 `python tools/repo_check.py --output local/web-ui-implementation/evidence/repo-check-20261102-r2-flutter.json`
  = **PASS / 52 项 / 0 errors / 1 既有 warning（`production-py312-rebuild`）**，故当前可宣称 PASS。
- **Flutter 客户端：收据/待打印入库页内联搜索建议已完成并冻结（并行的客户端轮，验收通过）**：
  - 新增 `clients/app/lib/features/unified/widgets/catalog_suggest_search.dart`（818 行，格式化后）：OverlayPortal +
    CompositedTransformFollower 的内联建议浮层；防抖 `Duration(milliseconds: 250)`；每键 `_seq` 递增使旧请求作废；
    IME 组合期（`_controller.value.composing.isValid`）不查询；状态 loading/empty/error+retry；Up/Down/Enter/Escape/Tab 键操作；
    48dp 行高；TapRegion 外点关闭；不裁切。
  - 新增测试 `clients/app/test/features/unified/catalog_suggest_search_test.dart`（739 行，20 个用例）。
  - 改 `clients/app/lib/features/unified/screens/receipt_screen.dart`（+66/-4）：扫码行下加内联建议字段；档案加载中显示
    「正在读取本地档案…」并禁用提交（`archivesLoading = itemKey 非空且 materials 空且 detail.isLoading`）；选中走
    `ReceiptController.setItem`；再次键入时 `_releaseSuggestion` 撤销上一次由建议提交的卡（仅当当前 `itemKey` 仍等于该卡时才清）。
  - 改 `clients/app/lib/features/unified/screens/pending_receipt_screen.dart`（+129/-16）：用建议字段替换原「选择元器件」ListTile，
    保留「从器件库选择」「资料库没有？新建器件」两个入口；已选卡用带「清除选择」按钮的 ListTile 展示；同一 C 多档案时显示
    「此编号对应多个本地档案，请先选择本次制袋的档案。」并禁用「生成袋码并加入待打印」；`_selectionSeq` 令牌防止在途档案查询
    复活已撤销的选择。
  - 改 `clients/app/lib/features/unified/providers/inventory_providers.dart`（+20/-1）：`ReceiptController.setItem` 在切换到不同卡时
    清 `resolved`/`materials`/`templateId`/`sn`（`copyWith` 用 `_unset` 哨兵，传 `null` 真能清空），同一张卡重选保留已选档案。
  - 改 `clients/app/test/features/unified/item_picker_test.dart`（1 行）：点击目标文案「选择元器件」→「从器件库选择」。
  - 实现决策：复用既有 `LabApiClient.search(CatalogQuery)`/`detail()`，无新接口；同 C 分组在客户端按规范化的 C 码合并，本地变体排主位，
    只有供应商独有组才显示供应商库存，绝不把供应商库存当本地库存；`lab:`/`lcsc:`/`LABB:`/`LABL:` 等内部前缀由 `catalogSuggestTerm` 剥掉，
    `LABB`/`LABL` 不作为文本上送；扫码与手工建档路径未改。
  - 验证（工作目录 `F:/lc_elc/clients/app`，`PUB_CACHE=F:/lc_elc/dependencies/pub-cache-windows`、`FLUTTER_SUPPRESS_ANALYTICS=true`、
    `F:/lc_elc/dependencies/sdk/windows/flutter/bin/flutter.bat`，均 `--no-pub`、无 `pub get`）：`flutter test --no-pub --reporter compact`
    = exit 0，`+295 ~5`（295 passed / 5 skipped；5 个 skip 是既有需要真实 Odoo 账号的 live 集成用例，本轮同样跳过），Lead 已自行复跑
    确认同一结果；单跑新测试文件 = exit 0，20/20；`flutter analyze --no-pub` = **exit 1，但 0 error / 0 warning / 119 info**（全部为改动前
    既有 info：deprecated `DropdownButtonFormField.value`、curly braces、1 个多余 import；新文件 0 新增），输出存
    `local/web-ui-implementation/evidence/flutter-analyze-20261102.txt`；`dart format --output=none --set-exit-if-changed` 两个新文件 = exit 0、
    无改动；三个既有文件故意没跑新 SDK 格式化（会把 ~435 行无关行重排，仓库本就不是该格式化基线）。
  - 客户端源码冻结（Lead 执行，EXIT=0）：`python tools/release.py snapshot --component client --output maintenance/registry/source-client-receipt-search-feedback-20261102.json --activate`
    → `file_count=169`、`tree_sha256=ee5adebdaa0c3e81dfa616b8dc55243d6419790422b93b010f9126f3aaa70072`、清单 sha256
    `d703e507cd04bbe6bad648a3bf263b79d6626bf34ae77bba45cae88d6d37952f`；`active-sources.client` 已指向它，旧
    `source-client-android-install-fix-final-20261019.json` 未改写。
  - 版本与边界：客户端 `pubspec` 仍 `1.1.3+6`（本轮未升版、未构建签名 APK、未发布；Android stable 仍 `1.1.3+6`）；
    **没有 emulator/真机运行**，UI 证据只有 widget 测试与静态分析；receipt 页没有专门的提交锁 widget 测试（pending 页有），不声称已测。
  - 遗留：`git stash@{0}`（format-churn-revert，仅含三个文件被新格式化器重排的副本）因安全策略不允许删除，保留未动。
- **文档**：`local/web-ui-implementation/deploy-plan.md` 增 `§1.1`（本轮候选实测参数）与**第 8.5 步**
  （50-verify 之后执行 `remote/90-close.sh` 写 `DEPLOY_STATE`）；`CHANGELOG.md` 增 2026-11-02 条目；
  交接见 [2026-11-02 实施交接](../../maintenance/handoffs/2026-11-02-web-ui-unification-implementation.md)。
- **有效性边界（2026-11-03 更新）**：**已部署**——r3 于 2026-11-03 00:16–00:36Z 部署到生产 `192.168.31.105`（DB `LcHardwareHouse`），
  `lab_team_web 19.0.1.2.0` 生效、网关切到 r3 allowlist、50-verify 129 项 0 失败、90-close `completed`（`20261103T003543Z`）、公网回归全项通过；
  备份与回滚点见上一节。此前记录的「未部署 / 生产主机不可达」是 2026-11-02 时点结论，已失效。
  仍未做：commit/push（分支仍在工作区）、客户端包（`1.1.3+6` 不变）、真实业务写、DNS/Docker 变更、回滚演练、CI。
  仍未复核：13 个业务页逐页真实点击交互、异常权限下的 403/登录呈现、Flutter 端对其余业务页的适配（收据/待打印两页见本节上一条）、真实网关链路上的 CSP。
  浏览器证据是**隔离实例**结果（全站套件 55 项 55 pass / 0 fail / 0 blocked；`--only=pages` 复跑为 35 项 32 pass / 0 fail / 3 条主动跳过标记），**不得写成生产已验收**。

## 2026-10-28 P3 自有 Web 日常业务：候选已冻结 / 构建 / 登记（**未部署生产**）

- **版本（已定版）**：`lab_workflow 19.0.2.0.0`、`lab_team_web 19.0.1.1.0`、`server-ops 2026.10.28.1`
  （`maintenance/registry/components.json` 已同步）。`lab_catalog 19.0.2.0.5`、`lab_inventory 19.0.1.0.0`、
  `lab_theme 19.0.1.0.2`、`lab_site 19.0.1.0.0`、`client 1.1.3+6`、`eda 3.0.3` **均不变**。
- **生产仍是 P2**：`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5`、`lab_workflow 19.0.1.2.0`；
  本轮**没有部署、没有 `-u`、没有重启、没有改 DNS/公网、没有读写生产库**。
- **范围**：`lab_team_web` 新增 13 个业务页面（两阶段入库、扫码、袋与追溯、标签、领用/归还、
  流水、库位、类别映射、管理、档案、账号），`lab_workflow` 新增 8 个 JSON-RPC 窄接口 + 新模型
  `lab.location.mapping` + `POST /lab/labels/pdf` + `GET /lab/scan` 303 到 `/team/scan`，
  并修复安全审查 S1（跨账号归还）/S2（畸形入参）/S3（`adopt_stock` 部分提交）/S4/S5。
- **已通过（有证据、可复核）**：
  - 隔离 ORM 业务 **82/82，0 fail 0 error**（**role wrapper 之后真实重测**：`backend-orm-final.log` + `backend-orm-final-evidence/`，同轮 HTTP 6 并发亦过）
  - 真实 HttpCase **21/21**，`failed=0 errors=0 p3_class_ran=1`，RC=0（`httpcase-r8.log`）
  - API 断言 **54 pass / 0 fail / 1 blocked**（total **55**；1 blocked 为 Origin 断言，本轮未提供 Origin URL，**不得改判 PASS**）（`runs/run.KOJbZY/verify-summary.json`）
  - Nginx 配置契约 1.26.2 **34/34**、1.30.6 **34/34**（`real-nginx-r2-results.json`；源码层，**未部署**）
  - 进程内并发独立 adapter **6/6**，负向自检 `detected=true`，exit 0（`concurrency-standalone-r3.json`；`test_enable:false`、`registry_cursor_patched:false`）
  - linux runner **17**（`runner-linux-r2.log` OK）、core **17/17**、XML **6/6**、JS 语法 **15/15**、路由表 **79** 条 `--check`
- **浏览器主链（R8）**：**31 步 28 pass / 0 fail / 3 blocked**，`unreached=0`
  （`runs/browser-20261028T065311Z/browser-p3.json`、`browser-r8.log`）。3 blocked 是
  `p3-cross-user-denied`、`p3-receipt-same-key-conflict`、`p3-unknown-outcome-retry` 的
  **DOM 场景未执行**；这三项由 API 断言 / HttpCase / core 独立覆盖，**不得写成 DOM 通过**。
  同轮真实 UI+服务端事实通过：两种 canonical key（`lcsc:`→裸 `C…`、`lab:` 走 `catalogDetail` 保具体档案）、
  建袋不增 quant、上架 +2、重复确认 quant 不变、领用 −2、部分归还 +1，role/materials/locations/mappings 管理页可用。
- **有效性前提（写报告不得省略）**：原 `--test-enable` 进程内并发套件因 **Registry 锁 blocked**
  （Probe 直接证实 `Registry._lock` 由主线程持有），wrapper 整体 **exit 1**，
  **不得称该命令全绿、也不得称"原进程套件通过"**；6 条并发断言由独立 process adapter 复用执行并全过。
- **测试口径**：`test_04` 的 quantity 为**精确匹配实际成功请求**（并发成功方可能是 10 或 11），
  **不得硬编码 10**；两管理员并发互撤后保留 1 名 manager，另一侧 `FORBIDDEN` 属合法权限撤销。
- **冻结 / 构建 / 登记（本轮完成）**：源快照
  [source-server-p3-web-20261028.json](../../maintenance/registry/source-server-p3-web-20261028.json)
  **250 文件**，treeSHA `fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43`，
  manifestSHA `0bfc1e3f581d90109c3e8942ff85cd9880a22ceac950d3c6fd93c0e90389c164`；
  `active-sources.server` 已指向该快照，**旧 manifest 与旧产物未覆盖**。
  候选包 `local/build/p3-web-20261028/candidates/server-p3-web-20261028-source.zip`
  （13,186,981 B，SHA256 `9070800b65b8fa3c751b5d4ac0dc5d94910a97e27128adbd0ff4370c4549e564`，
  250 文件逐条 raw+normalized 校验、251 归档条目重读一致；构建环境 Windows 11 + Python 3.15 stdlib zip；
  **纯源码、无 runtime/数据库/凭据**；源码 ZIP **签名 N/A**）；登记
  [artifact-server-p3-web-20261028.json](../../maintenance/registry/artifact-server-p3-web-20261028.json)；
  构建摘要在同目录 `build-summary*.json`。
- **仓库检查**：`repo-final-r1.json` **52 项 PASS，exit 0**，唯一 warning 为 `production-py312-rebuild`；
  旧 active 源 hash 漂移已随冻结消除，已无 credential-scan 失败。
- **公网未开放**：`bore/nginx/bore-public-allowlist.conf.template` 已逐端点列出 P3 页面与写接口
  （源码，**未部署**）；`validation-plan.md` §9 的 G1–G9 未逐项宣称通过。精确门槛在 Nginx 层
  （源码已过 1.26.2 与 1.30.6 各 34/34）；Netlify 侧是 `/*` → `httpsOrigin/:splat 200!` 通配透传、
  `_headers` 亦为 `/*` 全局、无 functions，**不需要为 P3 逐路径增补**；公网联调与部署仍未做。
  合成测试库/证据已保留，Lead 自建项目 PG 已按租约精确停止，**无活跃测试服务**。
- **仍未关闭（不因本轮分项通过而消失）**：手机流量不挂 VPN 的正式域名实测、实体摄像头/扫码枪与
  实体纸张打印、真机安装升级；生产 **Python 3.12 与隔离 runtime 3.10.12 不等价**，生产 cp312
  wheelhouse 缺失、"完整离线恢复"未闭合；**一致 filestore 备份**未取得（P2 备份首份
  `filestore.tar.gz` 仅 59 字节空归档，139 个附件在独立 supplement 且与 `db.dump` 非同一时刻，
  `odoo_restore.py` 只解 `filestore.tar.gz`）。
- 详见 [交接](../../maintenance/handoffs/2026-10-28-p3-web-workflows.md) 与 [任务](../../maintenance/tasks/2026-10-28-p3-web-workflows.md)；
  发布预检计划与全部证据在本机 `local/build/p3-web-20261028/`（Git 排除，克隆后不存在）。

以下为此前时点记录，按各自日期理解。

2026-10-27正式team域名CNAME与可信HTTPS已确认，实际Netlify Edge22项通过；现有代理路径工作，本机系统解析仍到LAN，区域Netlify IPv4直连有超时，官方默认负载均衡75.2.60.5直连固定标记两次通过。**尚待用户手机流量无VPN在正式域名打开/登录确认**，不能承诺全网稳定；未因诊断改DNS/代理。见[正式验收](../../maintenance/audit/netlify-formal-domain-acceptance-20261027.md)。以下为此前时点。

2026-10-27用户已确认Netlify真实登录成功、功能正常；自动前端22/0。当前待team绑定/CNAME：用户进入的是可选Netlify DNS向导，继续阿里云外部DNS，只将team A改为CNAME rad-taffy-56e1ce.netlify.app，保留origin-team A及根站点。正式域名证书/会话仍未验收。旧7882诊断服务精确停止并保留日志。见[验收](../../maintenance/audit/netlify-frontend-acceptance-20261027.md)。以下为此前时点。

2026-10-27 Netlify实际前台验收：用户已更新rad-taffy-56e1ce项目并见登录页；Lead对实际站点22/0（IPv4 HTTPS、无显式HTTP代理）：页面、JS/CSS权威源码hash、敏感路径/Origin拦截、private/no-store与无缓存命中均通过。**真实账号登录/刷新保持/退出未确认，team自定义域名仍待切换**；本轮无生产写入或DNS变更。见[验收](../../maintenance/audit/netlify-frontend-acceptance-20261027.md)。

2026-10-27 HTTPS回源已部署：origin-team证书签发，IPv4 bore16444→回环TLS网关18445，lc-bore-netlify.service已启用并通过自动重连。真实本机79/0、合成15/0、最新公网正常SNI22/0；首次公网21/1因单次TLS重置，失败证据保留。新Netlify ZIP待用户更新现有rad-taffy-56e1ce项目，**Netlify端HTTPS业务代理/真实账号尚未验收**。team A当前159.223.110.159，最终前端通过后改CNAME。运维2026.10.27.3；[审计](../../maintenance/audit/netlify-https-origin-20261027.md)｜[交接](../../maintenance/handoffs/2026-10-27-netlify-https-origin.md)。下方为此前时点。

2026-10-27 Netlify回源实测通过：用户站点rad-taffy-56e1ce.netlify.app经Netlify到bore7882取得完整诊断标记，Lead独立web_fetch与Windows IPv4不使用代理均200，响应no-store、fwd=miss。已启动独立origin-team.l-creation.club的DNS-01证书申请，等待用户新增回源A和TXT，team暂不切换。现有证书/业务网关未改；正式HTTPS回源和真实登录尚未通过，详见[本轮审计](../../maintenance/audit/netlify-https-origin-20261027.md)。

2026-10-27 Netlify评估：用户希望隐藏端口并能在国内直连。已准备独立拖拽测试包和无生产数据的IPv4 bore诊断服务，等待用户上传新Netlify项目后复核实际回源。现有根站点单次本机IPv4直连200约0.92秒，不能视为全国稳定性证明。**暂缓此前team DNS直接切到bore的步骤**；Netlify正式域名/回源证书/登录会话尚未实现。详见[测试审计](../../maintenance/audit/netlify-bore-probe-20261027.md)。

2026-10-27公网网关部署：独立IPv4回环TLS网关18443已加载，lc-bore-public.service enabled/active，公共中继159.223.110.159:16443，自动重连端口保持验证通过。真实本机网关49/0、合成Cookie/头/限速12/0、无SNI但严格校验TLS链与域名的公网19/0；正常浏览器SNI尚超时，真实账号未测。**当前等待用户将阿里云team A记录改为159.223.110.159，之后继续正常SNI与浏览器验收**；URL须含:16443。运维版本2026.10.27.2，新[源快照](../../maintenance/registry/source-server-bore-public-ipv4-20261027.json)；[审计](../../maintenance/audit/bore-public-ipv4-deploy-20261027.md)。内网业务vhost未改写，DNS/VPN/库存未改。下方为此前时点。

2026-10-27 晚间网络复核：**bore 公网经现有 VPN/HTTP 代理可用**。NAS 到真实 IPv4 中继建链，Windows 通过 7897 的 CONNECT/正向代理，使用域名/IPv4 四种组合均获得 HTTP200 与精确合成内容（2.1～2.3秒）；本机直连两种组合超时。撤销“境外全部封锁、代理不支持TCP、必须放弃bore”的结论。合成隧道已停止，生产TLS登录200，未改VPN/DNS/路由或生产入口。**正式Odoo公网白名单入口尚未部署**。详见[复核审计](../../maintenance/audit/bore-ipv4-proxy-recheck-20261027.md)。

2026-10-27 P2 模块已上生产：`lab_team_web 19.0.1.0.5`、`lab_catalog 19.0.2.0.5` 在 LcHardwareHouse 生效，odoo/nginx active、TLS 登录 200，库存 2 行与其它模块未变。本轮同时修复备份工具默认 data_dir 造成的附件漏备（已补备 139 文件、加回归测试）。新快照[source-server-production-p2-20261027.json](../../maintenance/registry/source-server-production-p2-20261027.json)；[审计](../../maintenance/audit/production-p2-deploy-20261027.md)。**公网仍未开通**：team.l-creation.club 仍解析到内网 192.168.31.105，无 AAAA，需真实公网节点+标准443+隧道登记；DNS/Nginx 本轮未改。

2026-10-26 P2 隔离闭环：真实 Odoo 19 经最终 P1 模板验证登录/Cookie/刷新/退出/角色/Origin/错误响应/限速/更新清单，**P2 77/0 BLOCKED=2 SKIP=0**；P1 回归 94/0；契约 12/0。修复：gated JSON-RPC 错误白名单脱敏（lab_team_web 19.0.1.0.4）、Nginx 1.30.6 proxy_cookie_flags、CSP/Origin、相对跳转、headless Chrome 真实流程。生产未应用；asset 公开源 blocked。

2026-10-26 P2 真实 Odoo 只读验证：隔离 Odoo 19 经最终 P1 入口模板完成冷登录/Cookie/刷新/会话接口/目录/详情/静态/asset/退出失效、错误认证与非法 DB、next 边界、四角色边界、安全响应头、跨来源、匿名更新清单、敏感路径默认拒绝、两来源限速，**PASS=46 FAIL=0**；生产仅只读核对。发现待决策：Odoo 会话 Cookie 仅 HttpOnly（缺 Secure/SameSite）、原生 JSON-RPC 错误含 traceback、生产入口缺 CSP（模板已补待应用）、web.base.url 仍 http。未做公网/真实密码/P3。见[审计](../../maintenance/audit/bore-p2-real-odoo-readonly-20261026.md)。

2026-10-26 bore P1 本地隔离入口：在 server/ubuntu22.04/bore 新增默认拒绝的入口 Nginx 模板（按真实控制器/JS 端点）、代理头覆盖、登录端点限速钩子、边缘 stream 模板与本地验证脚本；用真实 Nginx 1.18.0 + bore 0.5.3 + 合成上游验证「公开边缘 Nginx(stream，不接受客户端 PROXY) → bore 隧道 → TLS+PROXY 入口 → 上游」完整链路：94 项断言通过、9 项契约测试通过；失败路径 10 项断言通过（端口占用/WORK 复用不影响已有服务、无子进程残留）；运行时完整性 10 项通过（篡改归档拒绝且不解包）。PROXY 来源 IP、伪造 XFF/Forwarded 与伪造 PROXY 拒绝、默认拒绝、路径绕过、限速与断链失败关闭均本地实测；真实公网节点/标准 443/真实 Odoo 会话/自动续期/生产部署仍未验证，不构成公网开放授权。见[审计](../../maintenance/audit/bore-p1-local-isolated-entry-20261026.md)。

2026-10-26 方案状态：用户明确要求bore公网访问只使用Odoo登录，不新增身份门禁，并希望整合旧页面为自有UI。已完成[完整方案](../requirements/PUBLIC_ACCESS_AND_UNIFIED_UI_PLAN.md)：本地38个路由装饰器/44个路径模式，识别EDA旧后台链接、Flutter通用ORM兼容调用、自有Web写业务尚未接入，以及bore来源IP与Odoo冷却的配合风险。方案待确认，未派发DSH、未连生产、未部署bore/切DNS/卸载或清库；不代表公网安全验收通过。

2026-10-25 HTTPS更新：team.l-creation.club已启用受信任TLS及HTTP308跳转，Codex离开内网前独立12项通过（信任/SAN/HTTPS页面/保护/跳转/资产/旧更新清单）。证书有效期至2027-01-23 21:22:47（Asia/Shanghai），手动DNS续期未自动化。用户自行完成LE注册/协议/签发；HTTPS真实账号、刷新和退出未测。用户离开内网后本机DSH桥接拒绝连接，最终备份定位与操作退出码未取得，后续恢复同一任务核验，不重复部署。见[最新交接](../../maintenance/handoffs/2026-10-25-team-https-current.md)。以下为此前阶段记录。

2026-10-25 登录补修：team域名Nginx仅在原生认证端点清除X-Odoo-Database，避免Odoo19冷会话进入stateless模式、认证成功却不能保存Cookie；配置校验和reload成功，Odoo未重启。隔离4组场景13条断言通过；生产匿名入口、随机不存在账号失败响应、旧更新清单哈希复核通过。用户随后回复“可以了”，确认原登录无反应已恢复，按用户复验记录；Codex未独立操作真实账号，刷新保留登录、退出和跨端流程未追加实测。HTTPS仍未启用。见[本次交接](../../maintenance/handoffs/2026-10-25-team-login-cold-session.md)。

2026-10-25 域名迁移准备：用户已在阿里云添加 `team.l-creation.club → 192.168.31.105`，内网/VPN访问。按本轮追加授权，服务器resolv.conf仅改用路由器192.168.31.1，旧dnsmasq已disabled且无进程，备份和正常系统解析/TLS验证通过，IP/默认路由及Odoo/Nginx保持正常。此为手工指定路由器DNS，未实现NetworkManager/DHCP自动DNS管理。新域名HTTP入口已接通：`http://team.l-creation.club/`，Nginx固定生产库，management_host仅命中新域名；根欢迎页、/login、匿名/lab保护已从客户端真实域名独立复核。旧vhost和root_aliases=0保留，Odoo与Nginx主进程均未重启。LE生产账号/协议尚未获同意，HTTPS和自动续期未启用，VPN跨网/真实账号全流程/生产视觉未测。见[DNS审计](../../maintenance/audit/team-domain-dns-repair-20261025.md)。

2026-10-25：**lab_team_web 19.0.1.0.0 已安装生产**。新增独立欢迎、登录、仓库检索和详情；18 个新模块文件与冻结源一致，旧五模块133文件、库存计数与合计保持不变，服务 active。欢迎/登录/匿名保护、静态资源和原入口已做生产HTTP检查；真实账号完整流程、生产大目录和真机未重测。65项逻辑通过+1跳过、11项隔离HTTP通过属于同源候选证据。见[生产审计](../../maintenance/audit/team-web-production-20261025.md)与[发布核验](../../maintenance/audit/team-web-publish-codex-review.md)。

旧IP/lc.rm.com多库入口仍需原登录选库方式，/team兼容路径保留；新管理Host已启用且fresh会话可直接使用根路径。root_aliases=0继续保证旧Host的/login与/lab行为不变；入库/领用新页面尚未接入。


2026-10-24：lab_portal 已废弃并从源码移除（生产 uninstalled），**不再是当前能力**；最新方案为 lab_team_web 候选。

2026-10-24：**lab_catalog19.0.2.0.4 暗色主题已上线**。仅更新主题与资产配置，服务active、认证后台/主题CSS200、库存计数和更新通道不变；视觉及手机验收尚未完成。备份与验证见[主题交接](../../maintenance/handoffs/2026-10-24-dark-theme-deploy.md)。

**最新Android stable为1.1.3+6（release_sequence2）**，已从冻结166文件构建并核验包签名/内容/来源，LAN清单200及认证完整包/hash通过，Windows/Linux仍204。修正私有缓存合法别名误拒，显示具体安装错误；275 Flutter通过5跳过、9项真实JVM路径检查通过。用户旧安装入口已失败，本次需手动覆盖修复APK一次，不先卸载；手机是否完全解决仍待实测。旧build5及渠道指针备份保留，服务不重启、库存不写入，见[最终安装修复交接](../../maintenance/handoffs/2026-10-19-android-install-fix.md)。

以下为此前发布/诊断时点：

最新：Android1.1.2+5已按用户明确要求发布到stable，旧1.1.1+4验签/版本判断、LAN清单200和真实认证完整下载/哈希/403/匿名303检查通过。用户手机反馈未知来源已允许但旧安装入口仍失败；当前开发修复1.1.3+6，原生路径9项、Flutter275通过5跳过、分析无错误警告。手机唯一根因尚无原生日志，不把路径测试当作实体安装通过。后续见[安装修复交接](../../maintenance/handoffs/2026-10-19-android-install-fix.md)和[build5发布交接](../../maintenance/handoffs/2026-10-19-android-stable.md)。

以下为此前交接时点：

当前客户端开发候选 **1.1.2+5** 修复器件选择白屏、补齐弹层自定义入口、明确更新接口状态；测试/构建与未验收项见[修复交接](../../maintenance/handoffs/2026-10-19-receipt-picker-fix.md)。生产 **lab_workflow19.0.1.2.0已上线**，服务active、登录200，Android/Windows/Linux manifest均204。bag1/quant2/move1/operation1/catalog695217/location16/pending0/trace1及数量/预留总量0前后一致；完整备份核验和权限证据见[部署交接](../../maintenance/handoffs/2026-10-19-update-endpoint-deploy.md)。本轮未发布stable包。以下1.1.1+4段落为上一开发时点。

归档基线：2026-10-19。当前说明优先于local/archive中的旧README。计数是相应证据的时点快照，不是永久业务要求。

最新开发候选为客户端 **1.1.1+4**、lab_workflow **19.0.1.2.0**，实现启动/恢复检查、签名清单、同源后台下载、更新面板、Android系统安装与桌面独立更新助手；完整包和测试证据见[更新器交接](../../maintenance/handoffs/2026-10-19-client-updater.md)。当前active-sources指向更新器候选源；生产仍为下述19.0.1.1.0，未新部署或发布stable。真实设备安装、原生GUI升级/回退和物理打印未验收，不能用编译或目录夹具代替。

2026-10-19 已完成[两阶段入库实现与验收](../development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md)：客户端 **1.1.0+3** 三端原生候选包已重建，尚未发布；Android签名匹配，Windows进程冒烟及Linux动态依赖检查通过，三端界面、安全存储和实体扫码打印仍待验收，见[原生交接](../../maintenance/handoffs/2026-10-19-native-candidates.md)。**lab_workflow 19.0.1.1.0 已上线**，服务active、HTTP200，权限与单QR标签PDF检查通过。升级前后bag1、quant2、move1、operation1、catalog695217、location16及数量/预留总量0一致，pending0、trace1，历史袋码无缺漏；未写入生产测试库存。详见[上线交接](../../maintenance/handoffs/2026-10-19-server-deploy.md)及[审计](../../maintenance/audit/server-deploy-20261019.json)。

本轮完整回滚备份 `/var/backups/lc-elc/20261019T073840Z-before-upgrade` 与部署目录 `/opt/odoo/deployments/two-stage-20261019-a1/old-source.tar.gz` 配对；数据库和154个附件的实物/hash已核验，未离机备份或完整恢复演练。首次升级因工具把旧模块保留在addons根而失败，移出后重试成功；工具已修复并通过108项故障测试，最终服务端源清单为 `source-server-two-stage-receipt-opsfix-20261019.json`，104个业务文件与原候选一致，额外3个运维修复文件已同步。active-sources 指向最终源；所有历史manifest和发布包来源保持不变。

## 归档发布版本和权威源

以下版本与逐文件核对事实均为归档时点，不代表当前候选源仍与旧安装包字节一致。

| 组件 | 当前版本 | 维护源/成品 |
|---|---|---|
| Flutter Windows/Android/Linux | 1.0.1+2 | clients/app / clients/<platform>/releases/1.0.1 |
| lab_inventory | 19.0.1.0.0 | server/ubuntu22.04/odoo_addons/lab_inventory |
| lab_catalog | 19.0.2.0.3 | 同级lab_catalog |
| lab_workflow | 19.0.1.0.2 | 同级lab_workflow；20261018精简与权限修复包 |
| EDA专业版插件 | 3.0.3 | plugins/jlc-eda；Node桥接同目录bridge |
| 中文采集/资料导入编排 | 20261019服务器只读快照 | services/lcsc/systemd-production；采集源码server/ubuntu22.04/crawler |

具体来源及SHA在maintenance/registry。当前客户端66个Dart/pubspec业务文件已与原构建冻结和三端构建副本核对；Odoo102文件在初始导入时与最新修复ZIP相同；随后新副本仅规范化客户端两行空白和网页XML末尾多余空行，原始文件另存且变换hash/patch已登记（import-transformations.json），业务逻辑不变。干净Git克隆测试另发现Flutter模板忽略了Gradle启动文件，现已显式跟踪jar/gradlew；生成registrar与IDE状态转存历史，当前完整源指针按修正后的新manifest登记。完整源树本次另建立baseline manifest，UTF8文本指纹按LF归一化，另保留导入原字节hash，兼容Windows/Linux Git换行。

## 已知生产事实（来自20261018验收，归档仅只读复核必要元数据）

- Odoo192.168.31.105:8069，DB LcHardwareHouse；三个模块installed、服务active、HTTP200。
- 器件695217、参数4110477、分类2791；卸载40个无关模块、保留52个业务模块及依赖。
- 网站6页内容hash、保留模块账号权限一致。系统记录6账号含模板/非活动，普通列表3个。
- 当前没有实验室库存/bag/领料数据；POS自带默认产品随卸载移除，未删除真实库存。
- 权限26项事务回滚测试、7组件测试、9浏览器项通过，条码PNG/PDF生成成功；物理打印机未测。
- 归档只读导出确认每日03:30开始/05:30结束（Asia/Shanghai），OnSuccess触发Odoo资料导入；未在本轮重新跑采集/导入。
- 生产备份在服务器/opt/odoo/backups/module-cleanup-production-20261018T153740Z，未下载完整生产数据库到本地。

## 本轮归档实际验证

- 所选来源到目标逐文件复制核对SHA256；完整记录local/manifests/migration-files.json（已完成；旧progress仅为故障续传记录，最终以迁移摘要和完成报告为准）。
- EDA在新路径105/105单测、13/13包测试、build与verify均exit0，重建eext/bundle与旧发布物hash相同；没有冒称真实EDA宿主再导入验收。
- 服务端纯逻辑26项运行、1跳过，exit0；不是Odoo ORM生产重测。
- 现有运维故障夹具100项检查在新路径/WSL root通过，不访问真实PostgreSQL或systemd；初次非root前置失败已记录。
- 新维护工具8项通过：源码冻结/换行、机密扫描、离线导入覆盖/越界保护、构建dry plan。
- 最终安卓APK公开证书8b4c…ff43，已与原Windows离线密钥匹配；WSL默认key640b…a5ff不是最终发布身份。公证书明文登记、私钥Git排除。
- 原WSL工具已只读导出4.4GB（JDK/SDK/Flutter/cache及Linux适配），路径/成员/hash见registry/wsl-toolchain.json。没有搬迁或修改原WSL SDK。

最终源码/Git边界检查通过；空目录克隆的源码检查、8项维护测试、路由一致性与构建dry-run四项均通过。具体结果见maintenance/audit及归档完成报告，不能仅以本段静态说明当成功证据。

## 仍需知道的边界

1. 三端当前包是导入的既有1.0.1成品，不是从本次未来Git commit全量重编译的新包。Android按用户约定未模拟器测试；Linux1.0.1未重新完整做SecretService/CUPS/实体打印。原客户端测试233通过、5跳过，保留其来源。
2. 新通用build_client入口本次检查dry-run与工具测试，不保证便携VS或旧WSL私有adapter解包后无需调整即可编译。标准VS与Linux开发依赖有明确获取步骤。
3. 旧Ubuntu离线整包是20261015快照，不含今天最新全部修复，保留为历史。全新cp310闭包与生产cp312 ABI不同；已导出生产70个公开包版本锁，但完整cp312 wheelhouse还需同ABI准备机生成和隔离验收。
4. 新npm缓存联网准备曾180秒超时，不能标为npm ci --offline已通过；当前node_modules和lock已保存，新路径EDA构建已通过。按依赖指南可联网重新填缓存。
5. 原有部分器件图片资源404仍存在，未借归档修复；没有全量手册离线镜像。
6. GitHub远端尚未创建/推送；CI流程已准备但未云端运行。离线大文件仍在本机，离开本机前需导出可信载荷及单独私钥备份。
7. 历史原始聊天/补丁/候选源码保留在旧目录或local归档，不自动进入Git，不应盲执行。旧计划/计数不代表当前状态。
