# 精臣 (NIIMBOT) Android SDK 二进制

本目录只放**不可变**的厂商 SDK 文件，由 `android/app/build.gradle.kts` 的
`fileTree(dir = "libs", include = ["*.jar", "*.aar"])` 引入。不要在这里改文件，
升级时整包替换并同步下面的 SHA256。

## 来源

| 项目 | 值 |
|---|---|
| 来源压缩包 | `F:\lc_elc\Android-4.1.1-20261117.zip`（本机 `local/` 材料，Git 排除） |
| 包内路径 | `Android-4.1.1-20261117/SDK接入包/` |
| 版本 | Android 端 SDK 4.1.1（更新记录 2026-06-08：**SDK支持 B1_Pro**） |
| 机型 | 精臣 B1 Pro（300 dpi，热敏） |
| 接口文档 | `Android端SDK 接口说明文档 V4.1.1.pdf`（包内 `SDK接口文档/`），已解出文本 `local/incoming/niimbot-android/doc4.txt` |
| 接入包说明 | `Android端 SDK接入包使用说明.pdf`（包内根目录） |
| 蓝牙注意事项 | `注意事项/Android 打印机蓝牙相关注意事项-案例编号0001.pdf`（`doc3.txt`） |
| 排版说明 | `排版相关/Android SDK-内容排版.pdf`（`doc2.txt`） |

## 文件

| 文件 | 大小 | SHA256 |
|---|---|---|
| `4.1.1-release.aar` | 791,385 | `a23ac708acbc2a66f13367edaf53245476fa185209ee2e51b73a988a388c88e4` |
| `image-1.9.5.aar` | 28,663,052 | `7e7b055bb6a72a26a77de9af46ac86d099bcec105860d1b5c9852dd307fa61cc` |

来源压缩包：`Android-4.1.1-20261117.zip` SHA256
`655e1ff5b085e86ca440859d2dbb2a0d2632d72f2fd3ba583d78d5b88d57da8c`。

## 为什么是这两个

- `4.1.1-release.aar`：`com.gengcon.www.jcprintersdk.JCPrintApi`（SDK 主入口）
  与 `jni/{arm64-v8a,armeabi-v7a}/libminilzo.so`。
- `image-1.9.5.aar`：**必需，不可省**。`JCPrintApi` 的每一个绘图方法
  （`drawEmptyLabel` / `drawLabelText` / `drawLabelQrCode` / `drawLabelBarCode` /
  `generateLabelJson` …）都是对 `com.niimbot.canvas.image.NBCanvasImageApiSzwy`
  的 native 转发，该类与 `libniimbot_canvas_image.so`、`libskia.so`、
  `assets/font/ZT001.ttf`（默认中文字体）只在 image AAR 里。去掉它 APK 能编译，
  但一调用绘图就会 `NoClassDefFoundError` / `UnsatisfiedLinkError`。
  代价是 APK 增加约 56 MB（两个 ABI 各一份 .so 与字体）。
- **未引入** `LPAPI-2019-11-20-R.jar`：文档第 1.1.2.2 节注明只有
  B50/B50W/B11/T6/T7/T8 系列需要它；B1 Pro 不需要，也不引入以避免
  `com.dothantech` 类缺失警告。

## 许可

厂商 SDK 二进制，随厂商接入包分发；本目录的 README 只记录来源与校验值，
不改变厂商的许可条款。`assets/font/ZT001.ttf` 是 SDK 默认字体，按接入包说明
仅用于调用 SDK 字体接口。
