# 维护交接：有线接入的内网加速 + 标签排版「先完整后字号」

- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 未提交、未发布；未接触生产。

## 用户目标

1. **「Windows 平台有时候我的内网是通过有线接入的」** —— 内网加速提示原先只按 WiFi SSID
   匹配，插网线的台式机永远没有 SSID，功能在最该用的机器上静默失效。
2. 顺手收掉热敏标签排版里两处「宁可丢字段也要用最大字号」的行为，以及条形码试验的残留。

## 已完成工作

### 1. 有线接入（`lib/services/lan_probe.dart` 新增）

- `LanReachabilityProbe.reachable(baseUrl)`：对配置的内网地址发一次 `GET /web/health`，
  3 秒上限，**不带任何凭据**，`statusCode < 500` 即视为可达（404/重定向也证明有服务在听）。
  只探测私有网段地址（`OdooConfig.isPrivateNetworkHost`），公网地址直接返回 false。
- `shouldOfferLanAcceleration` 的判定改为：
  - 平台**报告了 SSID** → 仍以 WiFi 名称为准（咖啡馆里地址碰巧可达不算实验室内网）；
  - 平台**没有 SSID**（有线，或读不到）→ 只有探测成功才提示。
    这一条同时覆盖「操作员填过 WiFi 名，但今天插了网线」的情况。
- `LanAccelerationState` 新增 `lanReachable` / `dismissedWired`；`configure()` 会清掉旧探测结果
  （换地址后旧答案无效）；`dismissHint(null)` 记的是有线忽略标志，不写空 SSID。
- 提示条文案分两种：有 SSID 时「已连接 X，可切换内网加速」；无 SSID 时
  「内网服务器可直连，可切换内网加速」（图标也换 `Icons.lan`）。
- 设置页在无 SSID 时显示探测结果；WiFi 名称输入框的说明补上「有线接入请留空」。
- 未配置 WiFi 名称时**不申请定位权限**：有线用户不该为了一个提示被弹权限框。
- 设置页在 Android 上补一条说明：`network_security_config.xml` 只放行了
  `192.168.31.105` 的明文 HTTP，应用层白名单接受任意私有地址、系统层不接受 ——
  两者不一致正是「切换失败」最难解释的一种。

### 2. 标签排版（`lib/services/niimbot_layout.dart`）

- **修了一个真 bug**：`wrappedBody()` 每次尝试都 `omitted.clear()`，把「超出四行上限的源行」
  也一起清掉了 —— 结果第五个字段（封装）没打出来，`truncated` 却报 false，界面告诉操作员
  「打全了」。现在拆成 `capOmitted`（一次性）与 `wrapOmitted`（每次重算）两个列表。
- **字号让位于完整性**：适配改成两遍。第一遍找「既放得下、又一行不丢」的最大字号；找不到
  才退到第二遍「放得下就行的最大字号」并如实上报丢掉了什么。此前 7.4 pt 下长描述要折三行
  （超两行上限被丢），而 7.0 pt 下两行就够 —— 旧代码宁可丢字段也要 7.4 pt。
- 删掉 `DrawLableBarCode` 的 FFI 绑定与 `drawBarCode()`（条形码方案已按用户「算了还是恢复原来吧」
  放弃，保留未使用的符号查找只会在 DLL 变动时白白多一个失败点），代码里留了说明。

## 实测

- `flutter test --no-pub` → **468 passed / 5 skipped / 0 failed**。
- 构建（本机真实执行）：`tools/build_client.py --platform windows --test`
  pub get / flutter test / flutter build 三步 **exit 0 / 0 / 0**
  （需显式传 `--flutter`、`--pub-cache` 与 `PDFIUM_LOCAL_ARCHIVE`，见下）。
  新增用例：有线分支（探测 true/false/null、有名字但今天插网线、探测结果随地址失效、
  有线忽略标志）、探测拒绝公网地址、长描述「缩字号而不丢字段」。
- `flutter analyze --no-pub lib test` → 0 error / 0 warning（119 条既有风格 info）。
- 版本升到 `1.3.3+17`（`pubspec.yaml` 与 `components.json` 一致）。
- **产物**：`clients/windows/releases/1.3.3+17/LC_ELC-Windows-1.3.3+17-x64.zip`，
  37,666,952 B，sha256 `f09957ae…32580c`，30 文件，exe sha256 `a22c5871…c0fa96`，`NotSigned`；
  `client-install.json` = 1.3.3 / build 17 / windows；冒烟进程 RUNNING → STOPPED。
- **登记**：`source-client-1.3.3-17-20261119.json`（206 文件，tree `0322ce1d…182d`，已 `--activate`）；
  `artifact-client-windows-1.3.3-17-20261119.json`。`repo_check.py` **PASS 53 项 / 0 errors**。

## 构建环境（本机复现要点）

本工作树里没有 `dependencies/sdk`、`dependencies/pub-cache-windows`（`.gitignore` 排除，只有主仓
`F:\lc_elc` 下有），所以 `build_client.py` 的默认路径会报 `Flutter missing`。三条都要显式给：

```
PDFIUM_LOCAL_ARCHIVE=F:/lc_elc/dependencies/windows/pdfium-win-x64-5200.tgz \
python tools/build_client.py --platform windows --test --work-root C:/lcw \
  --flutter   F:/lc_elc/dependencies/sdk/windows/flutter/bin/flutter.bat \
  --pub-cache F:/lc_elc/dependencies/pub-cache-windows
```

少了 `PDFIUM_LOCAL_ARCHIVE` 会去 GitHub 下载 pdfium 并失败（本网络到不了）。
`dependencies/pub-cache-windows` 里的 `printing-5.15.1` 已打过本地归档补丁，不要换成
`local/pub-cache-windows`（那一份没有补丁）。

## 未验证

- 真实有线/无线切换下的提示出现时机（需在实验室机器上插拔网线）。
- `GET /web/health` 在现网 Odoo 19 上的实际返回（未连生产验证；<500 的判定对 404 也成立）。
- 真实打印观感、扫码、Android 蓝牙出纸、应用内更新。
- 未 commit / 未 push。
