# 维护交接：Windows 客户端精臣（NIIMBOT）标签打印机直打

- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 未提交、未发布、未接触生产；服务端 `include_content` 已存在，本轮只改客户端。
- 客户端源码版本仍是 `clients/app/pubspec.yaml` 的 `1.3.2+10`（未升版本）。

## 用户目标与已确认边界

在 Windows 客户端用 `dart:ffi` 调精臣 PC C++ SDK 4.0.6（x64）的 `jcPrinterApi.dll`，
把 `/lab/api/labels/preview?include_content=true` 返回的结构化标签内容直接打到
40×20 mm 间隙纸热敏标签：左侧 13×13 mm 唯一二维码（`LABB:`/`LABL:`），右侧标题 +
最多 3 行正文。失败必须中文提示且不得显示成功；非 Windows / 缺 DLL 时隐藏按钮并保留
PDF/系统打印。不改 Android/Linux 打印路径，不改服务端行为。

## 已完成工作与实际证据

### 新增文件

- `clients/app/lib/services/niimbot_printer.dart` — `dart:ffi` 绑定与整批打印流程
  （`initSdk`/`unInitSdk`/`getAllPrinters`/`selectPrinter`/`disconnectPrinter`/
  `startJob_New`/`commitJob`/`endJob`/`isConnected`/`getPrintLastError`/
  `InitDrawingBoard`/`DrawLableText`/`DrawLableQrCode`/`FreeBuffer`），
  `StartJobParameter` 7×int32 结构体，`getAllPrinters()` 结果用 `FreeBuffer` 释放，
  45 个错误码中文映射，`Isolate.run` 后台执行。
- `clients/app/lib/services/niimbot_layout.dart` — 纯 Dart 排版计算（可单测）。
- `clients/app/test/services/niimbot_layout_test.dart`（17 项）。
- `clients/app/test/services/niimbot_printer_test.dart`（16 项）。
- `clients/app/test/features/unified/labels_direct_print_ui_test.dart`（2 项）。
- `clients/app/windows/niimbot/README.md` — 来源、逐文件 SHA256、升级/恢复方法。
- `clients/app/windows/niimbot/runtime/.gitignore` — 运行时载荷不入库（只跟踪本文件）。
- `tools/restore_niimbot_runtime.py` — 从登记 zip 只解 x64 运行必需文件并校验 SHA256。

### 修改文件

- `clients/app/lib/features/unified/models/labels.dart` — 新增 `LabelContent`；
  `LabelPdfResult.contents/hasContents`，`fromJson` 读取可选 `labels` 数组。
- `clients/app/lib/services/lab_api_client.dart` — `previewLabels(spec, {includeContent=false})`；
  默认请求体不变（不带 `include_content`），直打时才传 `true`。
- `clients/app/lib/features/unified/providers/label_providers.dart` — `niimbotAvailableProvider`、
  `niimbotLabelPrinterProvider`、`LabelDesignerState.printingDirect`、`printDirect()`。
- `clients/app/lib/features/unified/screens/labels_screen.dart` — PDF 按钮下方并列
  「精臣打印机直打」（仅在 `niimbotAvailableProvider` 为真时渲染）。
- `clients/app/lib/features/unified/widgets/label_preview.dart` — PDF 全屏预览对话框内
  新增直打按钮（与「系统打印」并列）。
- `clients/app/pubspec.yaml` / `pubspec.lock` — 显式依赖 `ffi: ^2.2.0`（原为传递依赖）。
- `clients/app/windows/runner/CMakeLists.txt` — `install()` 把 `windows/niimbot/runtime/`
  的 DLL/`icudtl.dat` 复制到 exe 旁、`font/` 复制到 `exe/font/`；目录缺失时构建成功并警告。
- `maintenance/registry/payloads.json` — 新增 `niimbot-cpp-sdk-windows`（external，zip SHA256）。

### 资源打包结论

- 入库：8 个 x64 DLL + `icudtl.dat` + `font/ZT001.ttf` + `font/language.json`（合计约
  38.7 MB）**不入 Git**（仓库边界拒绝 `*.dll` 与二进制大文件），由
  `python tools/restore_niimbot_runtime.py` 从 `CPP-4.0.6_release_20251114.zip`
  （SHA256 `dbe9c4d0…793f`）解出；README 记录逐文件 SHA256。
- 字体：只带 `ZT001.ttf`（实测含 20,902 个 CJK 码位，「追溯码名称型号封装数量库位器件参数」
  均有字形），`simfang.ttf`（10.6 MB）与 `arialbi.ttf` 未带；缺字时在 `initSdk` 字体目录
  放同名 ttf 即可，无需改代码。
- `icudtl.dat`（`netal_windows.dll` 文字排版依赖）必须与 exe 同目录，已一并处理。
- 本机已用 `tools/restore_niimbot_runtime.py --verify-only` 与 `--zip` 两种模式验证 PASS。

### 测试命令与真实结果（本轮，2026-11-19）

```
cd clients/app
flutter pub get --offline                 # exit 0（ffi 变为 direct main）
flutter analyze --no-pub lib test          # 119 issues（全部为 info，均为既有代码；本轮文件无新增）
flutter test --no-pub                      # +425 ~5: All tests passed!（exit 0）
```

新增/相关用例：`niimbot_layout_test.dart` 17、`niimbot_printer_test.dart` 16、
`labels_direct_print_ui_test.dart` 2、`labels_test.dart` 新增 3、`lab_api_client_test.dart`
新增 1，全部通过。`~5` 是既有 `odoo_client_test.dart` 在无凭据时的 skip，不是本轮引入。

CMake 安装规则用独立最小工程实测：`cmake --install` 正确复制
`bundle/jcPrinterApi.dll` 与 `bundle/font/ZT001.ttf`；缺 `runtime/` 时只输出警告。

`python tools/repo_check.py`：PASS 之外仍 FAIL 于 `frozen-source:client/server/eda`
（本轮与并行会话的改动尚未重新冻结快照，属于预期）；payload 登记本身无新增错误。

## 剩余工作与阻塞

- **BLOCKED：真机打印**。需要 USB 连接的精臣打印机（当前用户尺寸 40×20 mm 间隙纸），
  验收正常打印、缺纸、开盖三种情形；本轮环境无打印机，未执行。
- **BLOCKED：真实 DLL 加载与 FFI 调用**。自动化测试主机非 Windows/无打印机；
  `NiimbotPrinter.open()` 与 `_runJob()` 未在真实 DLL 上跑过。
- **BLOCKED：`flutter build windows --release`**。本机失败于既有 `printing` 插件下载
  pdfium（网络），与本改动无关；需在可联网或已缓存 pdfium 的机器上完成整包构建并确认
  exe 旁出现 DLL 与 `font/`。
- 若更换纸型/浓度，需要改 `startJob` 默认参数（当前：间隙纸 1、浓度 3、热敏 1、单色 0、
  高速 1）。
- 客户端版本号与 CHANGELOG/CURRENT_STATE 未更新：本轮未发布，按发布流程在冻结源码时处理。

## 依赖和产物

- registry ID `niimbot-cpp-sdk-windows`（external）。恢复：
  `python tools/restore_niimbot_runtime.py --zip <path>/CPP-4.0.6_release_20251114.zip`；
  只校验：`--verify-only`。
- 原始 zip 在本机 `F:\lc_elc\CPP-4.0.6_release_20251114.zip`（Git 排除）。
- 无凭据、无签名密钥、无真实 odoo.conf 进入本改动。

## 生产状态和回滚

未接触生产、未重启/升级任何服务、未写库存。回滚：删除本轮新增文件并还原上述修改文件
即可；`windows/niimbot/runtime/` 是 Git 排除的本机载荷，可直接删除。
