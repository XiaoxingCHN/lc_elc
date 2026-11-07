# 任务：客户端 Liquid Glass 三端候选包构建

- Status: done（Windows/Linux 候选完成静态核验；Android 构建 blocked，无 APK）

- 目标/用户场景：由三个独立会话分别构建客户端 `1.2.0+7` 的 Windows、Android、Linux 本机候选包；保持业务与冻结源不变，不发布或部署。
- 当前问题及复现方法：Liquid Glass 源码与测试已完成，但此前没有对应安装包。Android 的离线 Gradle/Maven 运行时依赖不完整。
- 验收标准：实际构建源与 `source-client-liquid-glass-20261106.json` 一致；记录环境、命令、退出码、测试和未验证项；候选包为完整 bundle，独立复核 SHA256 与归档完整性；不把静态检查称为真机验收或正式发布。
- 允许修改目录/接口：Git 排除的本机 `local/build/` 隔离构建目录与证据；本任务和交接文档。权威 `clients/app`、锁文件、既有 releases、发布登记与生产均不修改。
- 业务不变量/依赖：使用现有冻结客户端及已登记离线载荷；不连接或写入生产，不读取/输出签名私钥，不降级依赖，不新增源清单或改写旧清单。
- 负责人/协作者及分工：主会话冻结源、验收与交付；`windows-glass-build`、`android-glass-build`、`linux-glass-build` 分别执行隔离构建，互不修改源码。
- 分支/起始commit/源码manifest：分支 `feat/receipt-param-search`，源清单 `maintenance/registry/source-client-liquid-glass-20261106.json`，177 文件，tree SHA256 `a19e0ddf2f7cdba420ae7605763c40926c3745d3ab5de60387c8aab7da1d0e4e`，清单 SHA256 `930b53e17d189a0b5ab1fb1a507aa74ce7d2be7c57d1cad91892f07486c6b11c`。
- 环境与凭据获取方式（只写位置，绝不写值）：Windows 使用本机 Flutter 3.47.7 / Dart 3.13.5 与原生编译器；Linux 使用现有 WSL Ubuntu 22.04 原生 ext4 隔离构建环境；Android 使用已登记 SDK/JDK、私有 Gradle 缓存与 stock 构建脚本管理的既有签名材料位置，不读取密钥内容。现有默认 Odoo URL/数据库仅为既有环境配置，不是测试靶场；本轮未连接它。
- 实施步骤：校验冻结源和载荷 → 隔离副本中运行测试及 release 构建 → 生成完整候选 bundle → 核验版本、运行库、归档、哈希 → 主会话独立重读并汇总。

## 实际结果与交付（2026-11-06）

### Windows：候选完成，静态核验通过

- 产物：`F:/lc_elc/local/build/windows-glass-1.2.0/candidate-20261106-r1/LC_ELC-Windows-1.2.0+7-x64.zip`
- 19,156,583 字节；SHA256 `ecd6f891f7bb333bae50cee13357a765918bad3bdfe031d4124517f263e9c806`。
- 29 个归档成员，完整 runner/update helper、Flutter/插件 DLL、Pdfium、assets 与编译器匹配的 CRT；exe 版本 `1.2.0+7`，PE 为 x64。主会话重算 SHA256 一致、ZIP CRC 无错误、成员路径安全。
- 两次 Flutter 测试各 319 passed / 5 skipped / 0 failed，exit 0。5 个跳过为既有真实 Odoo 集成测试。
- 原 `build_client.py --test` 两次在原生编译退出 1，原因分别为长路径和插件头文件解析；最终仅对隔离生成目录做短路径、锁定插件实体化及 runner include 适配后，直接 CMake INSTALL exit 0。不是原构建脚本全链通过。
- 应用、更新助手及插件未签名；不是正式发布包。GUI、真实登录/业务、OS 安全存储、摄像头/扫码枪、实体打印、JVM 功能和干净 Windows 环境未验证。

### Linux：候选完成，静态核验通过

- 产物：`F:/lc_elc/local/build/linux-glass-1.2.0/20261106-candidate-a1/LC_ELC-Linux-1.2.0+7-glass-candidate-a1.tar.gz`
- 16,509,178 字节；SHA256 `c3e63587adf1bc17dd650d2da829945973008e2e5f907071edd498128a7660b5`。
- 34 个 tar 成员，22 个 bundle 文件，包含应用、更新助手、Flutter 资源、插件、Pdfium、libsecret 和许可证；版本 `1.2.0+7`。主会话重算 SHA256 一致、tar 可完整读取、成员路径安全。
- 离线 pub、Flutter 测试与 Linux release build 均 exit 0；319 passed / 5 skipped / 0 failed。8 个 ELF 在构建环境的 `ldd` 检查无缺失。
- GUI、真实登录/业务、SecretService 往返、摄像头/扫码、实体打印、性能与读屏未验证；未签名/公证。

### Android：blocked，未生成 APK

- 冻结源 177/177 匹配；Flutter 测试 319 passed / 5 skipped / 0 failed。原生 ABI 编译完成。
- 最终离线 Gradle `:app:mergeReleaseNativeLibs` exit 1，16 项运行时依赖无法离线解析，涉及 Tink、AndroidX、CameraX、ML Kit 和部分 Flutter 引擎组件；缺少 AAR/JAR 或完整元数据，不能记为 APK 通过。
- 独立 JVM 测试 exit 1：第一项断言通过后，`UpdatePackageFilesTest.java:31` 的旧 Windows 长路径别名假设失败，后续 7 项未执行；不是 Android 实机结果。
- 未运行 APK 的 apksigner/aapt/ZIP 完整性检查，未生成 APK 哈希。首次构建触发 SDK Platform 35 安装，后续 `sdkmanager` 网络探测失败；未改依赖锁或降级版本。
- 交付记录：`F:/lc_elc/local/build/android-glass-1.2.0/delivery.json`。后续须补齐并核验完整离线 Gradle/Maven 运行时闭包，或另行授权在线恢复，再新建隔离构建。

## 源一致性与边界

- 三个会话均报告实际构建源 177 文件 raw/LF 规范化哈希与清单匹配；主会话复核当前权威源内容未漂移。`android/gradlew.bat` 工作树原始字节是 CRLF，LF 规范化哈希匹配冻结清单；不是源内容改动。
- 未提交、推送、发布、部署、连接生产或改写既有成品；未生成发布 artifact 登记，未激活新源快照。
- 原始命令、失败日志、环境与更细核验在各候选目录的 `delivery.json`、`verification.json` 和日志中。本任务不把构建 exit 0 等同业务通过，不把历史测试等同真机验证。
- 主会话收尾：`git diff --check` exit 0，仅 CRLF 提示；`python tools/repo_check.py` exit 1，51 项通过，唯一错误为既有的 `frozen-source:server` 九个服务端文件晚于 active r2，16 条离线载荷警告。未执行 `--verify-payloads`，不计为通过；本轮没有服务端改动。
