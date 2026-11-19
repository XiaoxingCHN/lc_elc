# 精臣 B1 Pro 打印适配方案（2026-11-19）

- Status: approved（用户确认机型 B1 Pro，先做 Windows，Android 去 x86）
- 目标：客户端直接驱动 B1 Pro 打印现有 40×20 mm 标签，不再依赖“A4 PDF + 系统打印”。

## 一、事实核对（来自 SDK 包与文档，非推测）

| 项 | Windows | Android |
|---|---|---|
| SDK | `CPP-4.0.6_release_20251114.zip` | `Android-4.1.1-20261117.zip`（AAR） |
| B1 Pro 支持 | 支持（`B1` 在支持列表；`api.txt:976`） | 支持（V4.1.1 更新记录明确“SDK支持 B1_Pro”） |
| 连接方式 | **仅 USB / Wi-Fi，无蓝牙**（C++ 文档全文 0 处“蓝牙”） | **蓝牙**（`connectBluetoothPrinter(address)`） |
| 驱动 | **Win10/11 不需要**；目录名即 `B3S_B31_B21_B1_B203_...（仅win7需安装）` | 无需驱动，需运行时权限 |
| 浓度 | 1–5，默认 3 | 1–5，默认 3 |
| 纸张类型 | 1 间隙纸 / 2 黑标纸 / 3 连续纸 / 4 过孔纸 / 5 透明纸 | 同 |
| 打印模式 | 1 热敏 / 2 热转印 | 同 |
| 架构 | 统一 x64（`Resources_x64`） | arm64-v8a + armeabi-v7a（无 x86_64） |

结论：**Windows 走 USB，Android 走蓝牙**；两端共用同一份标签内容（服务端 `include_content`）。

## 二、共用部分（已完成）

服务端 `/lab/api/labels/preview` 新增可选参数：

```json
{"include_content": true}
```

返回额外字段 `labels: [{kind, ref_id, payload, trace_code, title, lines[]}]`：

- `payload` = 唯一二维码内容（`LABB:追溯码` / `LABL:库位码`）；
- `title` = 标题行；`lines` = 正文逐行（如“追溯码：…”“名称：…”“型号：…”“封装：…”）；
- 与 PDF 同源（同一份 `build_contents`），两条打印路径不会漂移；
- 默认 `false`，旧客户端与契约不变。

## 三、40×20 mm 版式（两端共用同一套坐标）

```
0,0 ┌────────────────────────────────┐ 40mm
    │ ┌──────┐  标题 SN-0001          │
    │ │ QR   │  追溯码 TRC-2026-0001  │ 20mm
    │ │13×13 │  名称 0.1uF 0402 50V   │
    │ └──────┘  型号 CL05B104KO5NNNC  │
    └────────────────────────────────┘
     1.5  14.5  16 ────── 22.5mm ─────
```

| 元素 | 坐标/尺寸（mm） | 说明 |
|---|---|---|
| 画板 | 40 × 20，旋转 0 | `InitDrawingBoard` / `drawEmptyLabel` |
| 二维码 | x=1.5, y=3.5, 13×13 | `payload`，QR(31) |
| 标题 | x=16, y=1.8, 22.5×4.5 | 字号 2.4 mm ≈ 6.8 pt（≥6.5 红线） |
| 正文 | x=16, y=6.5, 22.5×12 | 每行 2.0 mm ≈ 5.7 pt（≥5.5 红线），最多 4 行 |
| 行数超限 | 缩到 3 行并返回 `truncated: true` | 不缩到不可读字号，不静默截断 |

依据：`label_render.py` 的 `MIN_BODY_FONT_PT=5.5`、`MIN_TITLE_FONT_PT=6.5`、`QR_MIN_MM=13`。

## 四、方案 A：Windows USB（先做）

### A1 资源打包
- `Resources_x64` 的 8 个 DLL → `clients/app/windows/runner/niimbot/`，CMake POST_BUILD 复制到 exe 同目录；
- 字体：`ZT001.ttf`（约 8 MB）随包；`simfang.ttf`（10 MB）不入库，运行时从 `%LOCALAPPDATA%\LC_ELC\fonts` 读，缺失时给明确中文提示；
- `niimbot/README.md` 记录来源 zip、sha256、升级方法；
- **不放 x86、不放 161 MB 整包**。

### A2 FFI 绑定（`lib/services/niimbot_printer.dart`）
按 `jcPrinterApi.h` 绑定 28 个导出函数中的 14 个：
`initSdk / unInitSdk / getAllPrinters / selectPrinter / disconnectPrinter / startJob_New / commitJob / endJob / isConnected / getPrintLastError / InitDrawingBoard / DrawLableText / DrawLableQrCode / FreeBuffer`。

要点：
- 字符串 UTF-8（`toNativeUtf8`），`getAllPrinters` 返回的指针用 `FreeBuffer` 释放（不是 `free`）；
- `StartJobParameter` 用 `Struct`（7×int32）；
- 非 Windows 或 DLL 缺失 → `available == false`，界面降级到系统打印。

### A3 打印流程
```
initSdk(fontDir)
→ getAllPrinters()           // JSON: {打印机名: 端口}
→ selectPrinter(name, port)
→ startJob_New({paperType:1, density:3, printMode:1, colorType:0,
                qualityType:0, printCount:N, printCopies:1})
→ 每张：InitDrawingBoard(40,20,0,'ZT001.ttf',0,0)
        DrawLableQrCode(1.5,3.5,13,13,payload,31,0)
        DrawLableText(16,1.8,22.5,4.5,title,'ZT001.ttf',2.4,0,0,0,2,0,0.6,{})
        DrawLableText(16,6.5,22.5,12,lines.join('\n'),'ZT001.ttf',2.0,0,0,0,2,0,0.5,{})
        commitJob()
→ endJob()
```
失败读 `getPrintLastError()`，22 种码转中文（缺纸 2 / 开盖 1 / 电量低 3 / 温度高 7 / 超时 22 / 断开 23 …）。

### A4 界面
「标签打印」页：Windows 且 `available` 时显示「精臣直打」按钮（与「系统打印」并列）；打印机未连接时按钮置灰并显示原因；**只有 `endJob()` 成功且无错误码才显示成功**。

## 五、方案 B：Android 蓝牙（第二步）

### B1 集成
- `4.1.1-release.aar` + `image-1.9.5.aar` 放 `android/app/libs/`，`build.gradle.kts` 加 `implementation(fileTree("libs"))`；
- ABI 已限定 `arm64-v8a + armeabi-v7a`（已改）；
- 权限（SDK 文档要求）：
  - Android 12+：`BLUETOOTH_SCAN`（`neverForLocation`）、`BLUETOOTH_CONNECT`
  - Android 6–11：`ACCESS_FINE_LOCATION`
  - 兼容旧版：`BLUETOOTH`、`BLUETOOTH_ADMIN`（`maxSdkVersion=30`）
- 运行时申请 + 引导开蓝牙与 GPS（文档明确“搜索前需蓝牙开启、GPS 开启”）。

### B2 Kotlin 桥接（`MainActivity.kt` 新增 channel `lab/printer`）
| 方法 | 对应 SDK |
|---|---|
| `scan()` | `api.scanBluetoothPrinter(ScanCallback)` → 回调 `onScan(PrinterDevice{deviceName, deviceAddress})` |
| `stopScan()` | `api.stopScanPrinter()` |
| `connect(address)` | `api.connectBluetoothPrinter(address)`（**同步耗时，放子线程**，返回 int） |
| `isConnected()` | `api.isConnection()` |
| `print(labels, spec)` | 见 B3 |
| `paperInfo()` | `api.getPaperInfo()` |

初始化：`JCPrintApi.getInstance(callback)` → `initSdk(applicationContext)` → `initDefaultImageLibrarySettings("","")`。

### B3 打印流程
```
setTotalPrintQuantity(页数 × 份数)
startPrintJob(density=3, paperType=1, printMode=1, PrintCallback)
  └ onBuffer(index) 回调中：drawEmptyLabel(40,20,0,"")
        drawLabelQrCode(1.5,3.5,13,13,payload,31,0)
        drawLabelText(...) × 2
        → generateLabelJson() → commitData([json], [printerInfo])
endPrintJob()
```
（SDK 要求数据在 `onBuffer` 回调里提交，不能在 `startPrintJob` 之后直接 commit。）

### B4 界面
「标签打印」页：Android 显示「蓝牙打印机」区域 —— 搜索 → 列表（名称 + MAC）→ 连接 → 显示「已连接：B1 Pro」→ 打印。错误按 `errorCode/errorInfo` 转中文。

## 六、测试矩阵

| 层 | 可自动化 | 必须真机 |
|---|---|---|
| 服务端 `include_content` | ✅ 已加 2 条 ORM 测试（内容结构、默认不返回） | — |
| 40×20 布局计算 | ✅ 纯函数测试（坐标、字号、截断） | — |
| 错误码中文映射 | ✅ 纯函数测试 | — |
| FFI 绑定正确性 | ⚠️ 只能验证“DLL 缺失时降级” | ✅ 插 B1 Pro 打印 |
| Android 桥接 | ⚠️ 可 mock MethodChannel | ✅ 蓝牙配对 + 打印 |
| 标签内容一致性 | ✅ 同一 `LabelContent` 生成 PDF 与直打输入 | ✅ 肉眼比对纸质标签 |

## 七、实施顺序与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| 1 | Windows FFI + 40×20 + 界面（进行中） | 插 USB 打出一张 40×20 袋标签，二维码可扫，中文清晰 |
| 2 | Android AAR + 桥接 + 权限 | 手机搜到 B1 Pro、连接、打出同样内容 |
| 3 | 批量（1–100 张）与错误场景 | 缺纸/开盖/断连给出正确中文提示，不误报成功 |
| 4 | 网页端（可选，暂缓） | 需用户额外装精臣打印服务，收益低 |

## 八、风险与回退

| 风险 | 处理 |
|---|---|
| 字体缺失导致中文变方块 | 启动自检，缺字体时明确提示并禁用直打，回退系统打印 |
| DLL 加载失败（杀软/缺 VC 运行库） | 捕获异常 → 降级到 PDF 打印，不崩溃 |
| 蓝牙权限被拒/未开 GPS | 分步引导，不显示“搜索中”假状态 |
| 打印中途失败 | 记录已打印张数，提示“第 N 张失败”，可重打剩余 |
| 与 PDF 版式漂移 | 两端都从同一 `LabelContent` 取数，坐标常量单点定义 |

回退：直打完全独立于现有 PDF 路径，删除按钮即恢复原状；服务端 `include_content` 默认关闭。
