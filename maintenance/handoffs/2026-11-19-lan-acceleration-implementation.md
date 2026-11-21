# 维护交接：默认公网登录 + 内网加速（内存态，不落盘）

- 任务单：`maintenance/tasks/2026-11-19-lan-acceleration-design.md`
- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 未提交、未发布；未接触生产。

## 用户目标与已确认边界

默认使用公网 `https://team.l-creation.club`（HTTPS）登录；在可信局域网内可临时切到内网地址加速。
内网会话只存在于内存：不写账号列表、不写密码、不成为 lastUsedAccount、不写离线缓存与 pin。
切换失败必须保持原会话；旧 401 不得踢掉新会话。Android 明文 HTTP 只允许配置过的内网地址。

## 当前权威源码

- `clients/app`（三端共享 Flutter 源码）。
- 设计事实 B1–B6 与修正见任务单；本实现逐条对应。

## 已完成工作与实际证据

改动文件：

- `lib/config/odoo_config.dart`：公网默认 `publicBaseUrl/publicDatabase`、`fallbackBaseUrl/fallbackDatabase`；
  `buildLanBaseUrl`（LAB_LAN_URL）、进程内 `setRuntimeLanBaseUrl`；`isPrivateNetworkHost` /
  `permittedCleartextHosts` / `isPermittedBaseUrl` / `ensureCleartextAllowed`（HTTP 白名单）。
- `lib/services/auth_gateway.dart`：新增 `sessionGeneration`、`authenticateAt`（原子切换）、
  `probe`（不改会话的测试连接）、`cancelInFlightRequests` 默认实现。
- `lib/services/odoo_client.dart`：`configure` 走明文白名单；generation 计数；
  `authenticateAt` 用临时客户端认证成功后才提交 uid/cookie；`probe` 用临时客户端；
  请求携带 generation（`_sessionGenerationKey`），`_notifySessionInvalid` 忽略旧会话的 401；
  `cancelInFlightRequests` 取消在途请求。
- `lib/services/login_memory_store.dart`：`rememberAccount(..., persistent: false)` 不写盘、不入列表。
- `lib/providers/auth_provider.dart`：`login(ephemeral:)`、`switchServer`、`switchToPublic`、
  `testConnection`；`AuthState.ephemeral/switching`；`_activeGeneration` 守卫；
  logout / sessionInvalid 清理内存态与 SSID；`_failureDetail`。
- `lib/services/lan_acceleration.dart`（新）：`ssidMatches`、`shouldOfferLanAcceleration`（纯函数）、
  `LanAccelerationState/Notifier`（内存态，含 dismissed hint）。
- `lib/providers/lan_acceleration_provider.dart`（新）：`lanSettingsProvider`，登出时清空。
- `lib/screens/lan_acceleration_sheet.dart`（新）：设置 UI（地址、SSID、用户名/密码、测试连接、
  切换到内网、切回公网、两条强制说明文案）。
- `lib/widgets/lan_acceleration_hint.dart`（新）：前台恢复 / ≥60s 读 SSID，匹配且为公网会话时提示；
  不自动切换、不自动登录；detached 时清理内存。
- `lib/main.dart`、`lib/screens/login_screen.dart`、`lib/screens/home_screen.dart`、
  `lib/features/unified/screens/unified_catalog_screen.dart`：入口、默认预填、内网地址即会话级登录。
- `lib/features/unified/models/session_scope.dart`：`ephemeral` 进入 scope 身份与 `canPersistBusinessData`。
- `lib/features/unified/services/asset_cache.dart`：`memoryOnly`（不读盘、不写文件/sidecar/pin/详情）。
- `lib/features/unified/providers/unified_providers.dart`：`memoryOnly: scope.ephemeral`。
- `lib/services/wifi_ssid.dart`：`platformOverride`（仅测试用）以覆盖 Android 分支。
- `android/.../MainActivity.kt` + `AndroidManifest.xml`：`lab/wifi_ssid`（currentSsid/requestPermission、
  PERMISSION_DENIED/LOCATION_OFF）、ACCESS_FINE_LOCATION、ACCESS_WIFI_STATE。
- `windows/runner/flutter_window.cpp` + `windows/runner/CMakeLists.txt`：同 channel（WLAN API），链接 wlanapi.lib。
- `tools/build_client.py`：`--server` 默认 `https://team.l-creation.club`。
- 测试：`test/services/lan_acceleration_test.dart`、`test/services/wifi_ssid_test.dart`、
  `test/services/odoo_switch_test.dart`、`test/features/unified/ephemeral_cache_test.dart`；
  `test/providers/auth_provider_test.dart`、`test/support/login_test_support.dart` 扩充。

本轮实测：

- `flutter test --no-pub test/providers test/services test/features/unified`
  → passed 337 / failed 0 / skipped 5（exit 0）。其中 skipped 5 是既有的需要真实服务器的集成用例。
- `flutter test --no-pub`（全量）→ 385 passed / 0 failed / 5 skipped（exit 0）。
- `flutter analyze --no-pub lib test` → 0 error / 0 warning，119 条 info 均为既有风格提示。
- `python tools/repo_check.py` → FAIL：仅 `frozen-source:client/server/eda` 三项，因本轮改动与工作树中
  其他既有改动未登记快照；`python-syntax` 已修复并通过。

## 剩余工作与阻塞

- **blocked**：Windows 原生 `flutter build windows` 未执行——本机未找到 MSVC/CMake 工具链；
  `flutter_window.cpp` 的 WLAN 代码未做本机编译验证。
- **blocked**：Android 原生构建未执行——工作树内 `dependencies/android/{sdk,java}` 不存在；
  `MainActivity.kt` 的权限流程未做本机编译验证。
- 未做真机手测：Android 权限拒绝/位置关闭、Windows 有线/无线、Linux 无 nmcli、弱网切换与切回公网。
- 未运行 `tools/build_client.py` 实构建；仅 `--dry-run` 验证默认 server 为公网。
- 发布登记（`tools/release.py snapshot`）未做，等用户确认版本与三端验收后执行。

## 依赖和产物

本轮未新增依赖、未生成发布产物。既有构建依赖见 `dependencies/README.md`。

## 生产状态和回滚

未接触生产（未 SSH、未部署、未改库）。回滚即丢弃本工作树改动；`clients/app` 之外的登记表未改动。
