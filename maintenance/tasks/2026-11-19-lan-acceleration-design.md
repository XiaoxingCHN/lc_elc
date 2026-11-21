# 任务：默认公网登录 + 内网加速（设计约束）

- Status: in_progress（Dart 实现与单测完成；Windows/Android 原生构建 blocked，见交接）
- 用户批准：2026-11-18 全部批准（C1–C8）
- 相关：`maintenance/tasks/2026-11-18-audit-remediation.md`

## 已确认的现状事实（评审子代理，带文件证据）

| 编号 | 事实 | 证据 |
|---|---|---|
| B1 | **任何一次成功登录都会把 baseUrl 明文写入 SharedPreferences**，与“记住登录”开关无关；`rememberLogin=false` 只删除密码，不删除账号 | `clients/app/lib/providers/auth_provider.dart:604-619`；`lib/services/login_memory_store.dart:188-197, 334-343`；测试 `test/providers/auth_provider_test.dart:112-137` |
| B2 | 内网账号会成为 `lastUsedAccount`，重启后 bootstrap 预填内网地址；有新鲜密码时还会自动登录内网 | `login_memory_store.dart:366-382, 271-276`；`auth_provider.dart:293-306, 359-364` |
| B3 | 资产缓存 sidecar 与 pin 列表会写含完整 URL（内网 IP）的明文；scope 目录名是未加盐截断哈希 | `asset_cache.dart:172-173, 352-369, 605-614`；`session_scope.dart:69-73` |
| B4 | 没有原子 `switchServer`：`login()` 在认证前就改 `state.baseUrl`，失败时保留旧 uid；`logout()` 会删密码并 `autoLoginBlocked` | `auth_provider.dart:570-596, 402-432`；`auth_gateway.dart:19-35` |
| B5 | Android 明文 HTTP 白名单只允许 `192.168.31.105` | `lib/services/odoo_client.dart` 明文检查 |
| B6 | 构建默认仍烘焙内网 URL/DB（`build_client.py` 与 `--dart-define`） | `tools/build_client.py` |

## 因此的设计修正（相对原提案）

1. **新增 session-only 登录路径**（必做，否则“不落盘”不成立）：
   - `LoginMemoryStore` 增加 `rememberAccount(..., persistent: false)` 或 `ephemeral` 标记；
   - ephemeral 账号：不写 `lc_elc.login.accounts.v1`、不 `markSuccessfulLogin`、不 `savePassword`、不参与 `lastUsedAccount`；
   - 进程内只保留 `_activeScope` 与必要的内存态；
   - 退出/切换/关闭窗口时清除内存中的内网地址与 SSID。
2. **bootstrap 不得预填内网地址**：ephemeral 账号不进入 `_accounts`；若历史版本已写入含内网 baseUrl 的条目，启动时清理（需要用户确认，因为会丢“记住的账号”）。
3. **资产缓存**：ephemeral 会话使用内存-only 缓存（`persistBusinessData=false`），pin 不写 SharedPreferences；或至少 sidecar/pin 只存 `item_key` 与相对路径。
4. **切换语义**：新增 `switchServer`：先 drain/取消在途请求（generation token 过滤旧 401），认证成功后再原子提交 baseUrl/database；失败保持原会话。
5. **默认公网**：`build_client.py` 默认 `--server https://team.l-creation.club`；`OdooConfig.defaultBaseUrl` 保持 build-time define（由构建传入），登录页在无记录时预填公网。
6. **Android 明文白名单**：保留 `192.168.31.105`，并允许用户在设置里填写的内网地址（需要运行时允许清单，仅 HTTP 内网地址；不放开任意 HTTP）。

## 验收

- 单元测试：ephemeral 登录后 raw prefs 不含该 baseUrl；重启后不预填、不自动登录内网；切换失败保持原会话；资产缓存不写盘。
- Widget/集成：设置页填写 → 测试连接 → 切换 → 重新登录 → 切回公网。
- 三端 WiFi：Android 权限拒绝/位置关闭；Windows 有线/无线；Linux 无 nmcli。
- 真机与桌面手测：WiFi 切换、弱网、切回公网。
