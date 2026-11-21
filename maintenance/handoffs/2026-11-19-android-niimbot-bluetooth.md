# 维护交接：2026-11-19 Android 精臣 B1 Pro 蓝牙直打

## 用户目标与已确认边界

- 给 Flutter **Android** 客户端增加精臣 B1 Pro **蓝牙直打**（40×20 mm 标签：
  一个二维码 + 标题 + 文字行），复用服务端已就绪的
  `/lab/api/labels/preview?include_content=true`。
- 不改服务端；不改 Windows/Linux 打印路径；不提交 git。
- 本轮用户授权范围：仓库源码修改、Flutter 测试、Android release APK 构建。
  **没有**授权发布、注册 release、重启服务或写生产。

## 当前权威源码、分支和版本

- 工作树：`F:\lc_elc\.claude\worktrees\read-tomc-memory-56e7a2`
  （分支 `feat/receipt-param-search`，未提交）。
- 客户端源码：`clients/app`（`pubspec` 版本未改动，仍 `1.3.2+10`）。
- Android SDK 来源：`F:\lc_elc\Android-4.1.1-20261117.zip`
  （SHA256 `655e1ff5b085e86ca440859d2dbb2a0d2632d72f2fd3ba583d78d5b88d57da8c`），
  只取 `SDK接入包/4.1.1-release.aar` 与 `SDK接入包/image-1.9.5.aar`。

## 已完成工作与实际证据

### 新增/修改文件

Android：

- `clients/app/android/app/libs/4.1.1-release.aar`（791,385 B，
  SHA256 `a23ac708acbc2a66f13367edaf53245476fa185209ee2e51b73a988a388c88e4`）
- `clients/app/android/app/libs/image-1.9.5.aar`（28,663,052 B，
  SHA256 `7e7b055bb6a72a26a77de9af46ac86d099bcec105860d1b5c9852dd307fa61cc`）
- `clients/app/android/app/libs/README.md`（来源、版本、SHA256、为何 image AAR 必需）
- `clients/app/android/app/build.gradle.kts`：新增 `dependencies { implementation(fileTree(...)) }`
- `clients/app/android/app/proguard-rules.pro`（新增；文档 1.3 节混淆规则。
  Flutter release 默认 `isMinifyEnabled = true`，不加这些规则 SDK 会被 R8 破坏）
- `clients/app/android/app/src/main/AndroidManifest.xml`：四组蓝牙权限
- `clients/app/android/app/src/main/kotlin/.../NiimbotPrinterBridge.kt`（新增，SDK 桥接）
- `clients/app/android/app/src/main/kotlin/.../MainActivity.kt`：
  `lab/printer` MethodChannel + `lab/printer/scan` EventChannel + 运行时权限回调

Dart：

- `clients/app/lib/services/niimbot_android_printer.dart`（新增；MethodChannel 封装、
  几何计划、中文错误映射）
- `clients/app/lib/features/unified/models/labels.dart`：`LabelContent.toJson/toString`
- `clients/app/lib/features/unified/providers/label_providers.dart`：新增
  `niimbotAndroidPrinterProvider` / `AndroidPrinterState` / `AndroidPrinterController` /
  `androidPrinterProvider`
- `clients/app/lib/features/unified/screens/labels_screen.dart`：Android 上显示
  「蓝牙打印机（精臣 B1 Pro）」卡片（搜索 → 列表 → 连接 → 打印），非 Android 或
  SDK 不可用时整块隐藏

测试：

- `clients/app/test/services/niimbot_android_printer_test.dart`（19 项）
- `clients/app/test/features/unified/android_printer_provider_test.dart`（9 项）
- `clients/app/test/features/unified/android_printer_ui_test.dart`（3 项）

### 文档核对结论（以 doc4 V4.1.1 为准，与任务说明的差异）

1. `scanBluetoothPrinter(int, ScanCallback)` / `stopScanPrinter(int)` 的 int 参数
   文档正文未写明；字节码显示它是**搜索秒数**（SDK 内部 `postDelayed(..., n*1000)`
   后取消 discovery 并回调 `onFinish`），`stopScanPrinter` 的 0=蓝牙、1=WIFI、
   其他=两者都取消。实现取 12 秒、`stopScanPrinter(0)`。
2. `isConnection()` 返回 **0 表示已连接**，非 0 表示未连接（文档 8.3 注释与字节码
   一致）。实现按 `== 0` 判断。
3. `drawEmptyLabel` 有 4 参 `String font`（已废弃）与 `List<String>` 两个重载；
   使用 `List<String>`（`emptyList()`）版本，`font` 留空 = 默认字体。
4. `drawLabelText` 第 11 个参数是 `lineModel`，选 **6**（宽高固定、内容超出时自动
   缩小），而非任务示例里的 `2`：2 是“宽度固定、高度自适应”，会让 4 行文字溢出
   20 mm 标签。
5. `drawLabelQrCode(..., 31, 0)` 与 `commitData` 的 `printerInfoList` JSON 结构
   （`printerImageProcessingInfo` / `printQuantity` / `printMultiple` 以字符串序列化）
   与文档 8.4.1.2 一致；任务说明中的示例参数顺序正确。
6. `startPrintJob(int density, int paperType, int printMode, PrintCallback)` 是
   4 参重载（还有 5 参带 quality 的重载），使用 4 参。
7. `endPrintJob()` 必须在 `onProgress` 到最后一页最后一份后调用；异常/取消路径不调用
   （文档 2.3 注意事项）。实现照此处理。
9. `getMultiple()`（文档 5.2 “打印倍率查询”）在连接后返回打印机分辨率的
   毫米→像素倍率；桥接在打印前用它覆盖 Dart 侧按机型推断的 11.81/8.0，
   仅在 SDK 返回非正数时才回退到机型值。
8. 错误码表（1–31、34、50–53、58–63）来自 doc4 2.3.1 的 `onError(errorCode,
   printState)`，复用 Windows 侧已有的 `niimbotErrorMessage`。

### image AAR 结论

**必需，不能省。** `4.1.1-release.aar` 的 `JCPrintApi` 每个绘图方法
（`drawEmptyLabel` / `drawLabelText` / `drawLabelQrCode` / `generateLabelJson` …）
都是对 `com.niimbot.canvas.image.NBCanvasImageApiSzwy` 的 native 转发；该类与
`libniimbot_canvas_image.so`、`libskia.so`、`assets/font/ZT001.ttf` 只在
`image-1.9.5.aar`。文档 1.1.2.2 只把 `LPAPI` 标为 B50/B11/T6/T7/T8 可选，没有把
image AAR 标为可选。代价：APK 从约 75 MB 增至 128.7 MB（两个 ABI 的 .so + 字体）。

### 测试与构建证据（真实执行）

- `flutter analyze --no-pub lib test`：**0 error**；119 条 info/warning，全部是
  仓库既有风格提示（新文件本身没有 error/warning）。
- `flutter test --no-pub`（全量）：**456 通过，5 跳过，0 失败**。
- `python -I tools/build_client.py --platform android --flutter … --test`：多轮
  构建（逐步加入 `getMultiple()` 覆盖倍率、连接前停搜等修正），每轮三步退出码均为
  `pub get 0 / flutter test 0 / build apk 0`。
- 最终 APK：`local/build/client-android-20261119T122258221176/source/build/app/outputs/flutter-apk/app-release.apk`
  （134,929,251 B，128.7 MB，Gradle 141.7s），SHA256
  `e31c484539a9b7f50c6ea6b207841b599d1e0591fa7722b2176d8b3c80a50908`；
  该源码快照与最终源码一致（含 `getMultiple()`、连接前停搜、manifest 注释修正）。
  已核对 APK 内含 `lib/{arm64-v8a,armeabi-v7a}/libminilzo.so`、
  `libniimbot_canvas_image.so`、`libskia.so`、`libc++_shared.so`、
  `assets/font/ZT001.ttf`；`classes.dex` 内保留
  `com/gengcon/www/jcprintersdk/JCPrintApi`、`com/niimbot/canvas/image/NBCanvasImageApiSzwy`
  与通道名 `lab/printer`、`lab/printer/scan`。
- 合并后的 manifest 含 `BLUETOOTH`/`BLUETOOTH_ADMIN`（maxSdkVersion=30）、
  `BLUETOOTH_CONNECT`、`BLUETOOTH_SCAN`（neverForLocation）、`ACCESS_FINE_LOCATION`。
- `python -I tools/repo_check.py`：50 项通过、3 项 `frozen-source:*` 失败、16 条
  warning。3 项失败均来自本工作树已有的未提交改动（client/server/eda 与
  `active-sources.json` 冻结清单不一致），不是本轮引入；本轮未注册新快照，按要求
  不覆盖旧 manifest。

## 剩余工作与阻塞

**BLOCKED（无法在无真机环境验证，未声称通过）**：

1. 真机蓝牙配对、B1 Pro 实际连接（`connectBluetoothPrinter` 返回 0 且
   `isConnection()==0`）。
2. 实际出纸与版面观感（二维码可扫、中文清晰、4 行是否溢出、浓度是否合适）。
3. 打印中错误回调（开盖/缺纸/断连/超时）在真机上的触发与中文提示。
4. Android 6–11 与 12+ 两套运行时权限弹窗的真机表现。

可执行的下一步：装 APK 到真机 → 系统蓝牙配对 B1 Pro → 标签页搜索/连接/打印 →
记录返回码与出纸结果。若失败，日志标签 `LabPrinter`（`adb logcat -s LabPrinter`）。

## 依赖和产物

- 厂商 SDK 二进制在 `clients/app/android/app/libs/`（README 记录来源与 SHA256）。
  本目录未登记到 `maintenance/registry/payloads.json`；如需冻结源清单，须按
  `tools/release.py snapshot` 流程另行登记。
- 签名密钥只写私有位置：`F:\lc_elc\local\private\signing\windows-debug.keystore`
  （未复制进仓库）。

## 生产状态和回滚

- 未碰生产：没有部署、重启、升级、导入或发布。APK 只在 `local/build/` 工作目录，
  未复制到 `clients/android/releases`，也未更新 `active-sources.json`。
- 回滚：删除本轮新增文件并还原 5 个被改动的 Android/Dart 文件即可（均未提交）。
