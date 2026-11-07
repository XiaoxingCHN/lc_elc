# 维护交接：2026-11-06 客户端 Liquid Glass 三端候选构建

## 结论

客户端 `1.2.0+7` 使用既有冻结源 `maintenance/registry/source-client-liquid-glass-20261106.json`（177 文件，tree `a19e0ddf2f7cdba420ae7605763c40926c3745d3ab5de60387c8aab7da1d0e4e`）。Windows 与 Linux 完整候选包已构建并静态核验；Android 因离线运行时依赖闭包不完整而 blocked，**没有 APK**。三者均非正式发布，未部署或连接生产。

任务及完整结果：`maintenance/tasks/2026-11-06-client-glass-candidates.md`。三个独立构建会话只操作本机隔离副本，权威客户端源码、锁文件和既有 releases 未改。

## 候选产物与主会话复核

| 平台 | 本机产物（Git 排除） | 字节数 | SHA256 | 状态 |
|---|---|---:|---|---|
| Windows x64 | `F:/lc_elc/local/build/windows-glass-1.2.0/candidate-20261106-r1/LC_ELC-Windows-1.2.0+7-x64.zip` | 19,156,583 | `ecd6f891f7bb333bae50cee13357a765918bad3bdfe031d4124517f263e9c806` | 完整 bundle，静态核验通过 |
| Linux x64 | `F:/lc_elc/local/build/linux-glass-1.2.0/20261106-candidate-a1/LC_ELC-Linux-1.2.0+7-glass-candidate-a1.tar.gz` | 16,509,178 | `c3e63587adf1bc17dd650d2da829945973008e2e5f907071edd498128a7660b5` | 完整 bundle，静态核验通过 |
| Android | 无 | — | — | blocked，无 APK |

主会话用 Python 标准库重读两份归档：SHA256、字节数与交付记录一致；Windows ZIP 29 个成员且 CRC 正常，Linux tar.gz 34 个成员且完整可读，均无绝对路径或 `..` 成员。

- Windows 包含 runner/update helper、Flutter/插件 DLL、Pdfium、assets 与匹配 CRT，版本 `1.2.0+7`；应用与更新助手未签名。原 stock 构建两次失败，最终私有生成目录的 CMake 适配成功，**不称原脚本全链通过**。
- Linux 包含应用、更新助手、资源、插件、Pdfium、libsecret 与许可证；构建环境 8 个 ELF `ldd` 无缺失。使用 WSL Ubuntu 22.04 原生 ext4、Flutter 3.47.7 / Dart 3.13.5，无 sudo/apt 安装。
- 各平台 Flutter 测试均为 319 passed / 5 skipped / 0 failed；跳过项是既有真实 Odoo 集成测试。Windows 执行了两次，不能重复累计成独立测试用例数。

## Android 阻塞与测试缺口

最终离线 Gradle 在 `:app:mergeReleaseNativeLibs` 退出 1：16 项运行时依赖无法离线解析，包含 Tink、部分 AndroidX、CameraX、ML Kit 与 Flutter 引擎组件。需要补齐带 AAR/JAR 和仓库元数据的完整离线闭包，或另行授权在线依赖恢复，再从新隔离目录重试。

独立 JVM 测试退出 1：`UpdatePackageFilesTest.java:31` 对 Windows 长路径别名的旧假设不成立；第一项断言已通过，后续 7 项未执行。APK 签名、版本与 ZIP 检查因无 APK 而未运行，不计 PASS。完整证据 `F:/lc_elc/local/build/android-glass-1.2.0/delivery.json`。

## 未验证与后续边界

- Windows/Linux 均未运行真实 GUI；未验证真实登录/库存业务、OS 安全存储或 SecretService、摄像头/扫码枪、实体打印、性能、读屏。Linux `ldd` 与 Windows 静态 DLL 检查不是目标设备兼容保证。
- 当前源内容与冻结清单一致；`clients/app/android/gradlew.bat` 的原始 CRLF 字节经 LF 规范化后匹配清单，属于行尾表示差异，不是内容漂移。
- 本轮没有 commit/push、发布登记、artifact 激活、部署、生产访问或凭据读取/输出；既有源清单与安装包保持不变。
- 若要把候选转为正式成品，需按发布规范另行登记产物、SHA256、构建环境与签名公证书，并完成对应设备验收；不能用本交接代替这些步骤。
