# 精臣（NIIMBOT）标签打印机直打运行时

本目录是 Windows 客户端「精臣打印机直打」功能的**运行时载荷说明**。真正的
DLL/字体不入库（仓库 Git 边界拒绝 `*.dll` 和二进制大文件），构建机用恢复脚本
从登记的 SDK 接入包解出到 `runtime/`，`windows/runner/CMakeLists.txt` 的
`install()` 再复制到 `lab_inventory_client.exe` 同目录。

## 来源

| 项 | 值 |
| --- | --- |
| 接入包 | `CPP-4.0.6_release_20251114.zip`（161,570,781 字节） |
| 包内路径 | `CPP-4.0.6_release_20251114/接入包/Resources_x64/` |
| SHA256（zip） | `dbe9c4d0bbb256f4eb9fe2ce4e961f1353a4ea45833c3f41f61c52995b70793f` |
| 版本 | PC 端 C++ SDK 4.0.6（2025-11-14 发布，新增批量打印流程与错误码更新） |
| 本机原始位置 | `F:\lc_elc\CPP-4.0.6_release_20251114.zip`（Git 排除，见 `local/`） |

只取 x64 运行必需文件；**不要**把整包或 `Resources_x86/` 放进仓库：

| 文件 | 字节 | SHA256 | 去向 |
| --- | --- | --- | --- |
| `jcPrinterApi.dll` | 859,136 | `bc9acc1c6dd1baf4bbe91a9d19d9e12b1cf0179bd89564700d54454d46ab111e` | exe 同目录 |
| `jcPrinterSdk.dll` | 5,187,584 | `64998e07eac481ed4e38f8822ddc44d97428ddde2042df8658e6f38f6c638dc9` | exe 同目录 |
| `USBPrintDll.dll` | 244,224 | `a0af1af673f9274399b23a0e5ea81583e3bb141c0bcf107c3017cecff8ed6b66` | exe 同目录 |
| `BYNetPortAPI.dll` | 2,816,512 | `41d66667fd3f014084f1c70e5b10263ca04a7a43212a21821027057bd04d9b64` | exe 同目录 |
| `NBCanvasImageSzwy.dll` | 47,104 | `7ebd602c04ee654bdfb7c9d65a4018b2ad975dadfb5ab41d86b686abe0680c73` | exe 同目录 |
| `SimpleLogModule.dll` | 199,168 | `e3ad9ffa39c3faa2de2d213c1f122662db33da5568b96494f46d13c63cd2b395` | exe 同目录 |
| `SNBCSDKForBarcodePrinter.dll` | 990,720 | `b626d747c830ddb442521d70e2ec2d45534a848146e80dfe728264b4aa86458f` | exe 同目录 |
| `netal_windows.dll` | 8,957,440 | `b2475e74cfe42a2a1560fbdb14de4476b16154bc8114c627c8a30abb9f5a4df5` | exe 同目录 |
| `icudtl.dat` | 10,185,008 | `846942a316b4e38fdbd4de3ad83e4faae78a8bced50f4720acdbdab6ee7c4b8e` | exe 同目录 |
| `font/ZT001.ttf` | 8,261,128 | `297b088424be212207df2ce8b98e335468b782aa6b96832af0b8b773d711e2b1` | `exe/font/` |
| `font/language.json` | 10,656 | `70a854b27e078c9db783eacbcf98dd43f72572e60331ffe0bf591e1824020a19` | `exe/font/` |

合计约 38.7 MB。`icudtl.dat` 是 `netal_windows.dll`（文字排版引擎）需要的
Unicode 数据，缺失会导致绘制文字失败，所以一并携带。

### 没有入库的字体

`simfang.ttf`（10.6 MB）和 `arialbi.ttf`（0.7 MB）**不随包**：当前排版只用
`ZT001.ttf`，而且 ZT001 已包含全部常用汉字（实测 20,902 个 CJK 码位，
「追溯码名称型号封装数量库位器件参数」均有字形）。如果将来需要别的字体，
在 `initSdk` 的字体目录里放同名 ttf 即可，无需改代码。

## 恢复方法

在仓库根目录执行（需要本机存在上面那个 zip）：

```sh
python tools/restore_niimbot_runtime.py
python tools/restore_niimbot_runtime.py --zip <另一路径>/CPP-4.0.6_release_20251114.zip
python tools/restore_niimbot_runtime.py --verify-only   # 只校验已有文件
```

脚本只解 x64 的上述文件到 `clients/app/windows/niimbot/runtime/`，逐文件校验
SHA256，不覆盖 hash 不符的文件（会报错），也不会执行接入包里的任何程序。

随后正常 `flutter build windows --release`：CMake 会把 DLL 复制到 exe 旁、
字体复制到 `exe/font/`。如果 `runtime/` 不存在，构建仍然成功，只是客户端隐藏
「精臣打印机直打」按钮并继续提供 PDF/系统打印。

## 升级方法

1. 拿到新的精臣接入包，核对官方来源；
2. 用新包覆盖 `CPP-4.0.6_release_20251114.zip` 的同名登记（新版本应作为新
   payload 登记，不改写旧记录）；
3. 更新本 README 的来源表与 SHA256；
4. `python tools/restore_niimbot_runtime.py --zip <新包>`；
5. 按 `lib/services/niimbot_printer.dart` 顶部注释核对导出函数与错误码表是否
   变化（4.0.6 新增了 32/34/35/50–63 等错误码，已在 `kNiimbotErrorMessages`）；
6. 真机验收：USB 连接、缺纸、开盖三种情形各打印一次。

## 客户端代码

- `lib/services/niimbot_printer.dart` — `dart:ffi` 绑定与整批打印流程；
- `lib/services/niimbot_layout.dart` — 40×20 mm 排版计算（纯 Dart，可测）；
- `lib/features/unified/providers/label_providers.dart` — `printDirect()`；
- `lib/features/unified/screens/labels_screen.dart` — 「精臣打印机直打」按钮。

## 注意

- DLL 家族是 **x64 only**，客户端 Windows 构建必须是 x64；
- 当前配置按用户尺寸 40×20 mm、间隙纸（`printLabelType: 1`）、浓度 3、
  热敏、单色、高速；换纸型需改 `startJob` 参数；
- 直打只读 `/lab/api/labels/preview`（`include_content: true`），不改库存；
- 打印机未连接/缺纸/开盖等错误会以中文显示，**不会**显示成功。
