# 离线依赖：来历、实际路径与获取方法

本目录保留已有离线载荷，Git只保留恢复工具/说明，完整机器可用副本由本地文件承载。逐类登记见maintenance/registry/payloads.json，精确来源到目标映射和全量hash在local/manifests/migration-files.json。缺文件时先运行：

```sh
python tools/fetch_payload.py --list
python tools/fetch_payload.py --id flutter-windows
python tools/fetch_payload.py --id flutter-windows --download
python tools/fetch_payload.py --id flutter-windows --verify
```

只有登记为pinned HTTPS单文件的项目能用--download；生成缓存、数据库和自制发布物按登记命令恢复，工具不会偷偷执行apt、构建或连接服务器。

## 1. Flutter、Android、Windows

- sdk/flutter_windows_3.47.7-stable.zip、flutter_linux_3.47.7-stable.tar.xz：来自Google Flutter官方归档，元数据sdk/flutter-*-release.json给出原URL/hash；registry也保留可直接下载URL。参见[官方archive](https://docs.flutter.dev/install/archive)。
- Windows展开工具链sdk/windows/flutter；Linux sdk/linux/flutter。不要删SDK上游.git元数据，否则Flutter自检可能失败；它不是本项目Git历史。
- Android包在android/和android/downloads：Google commandline tools16111833、platform36、build-tools36.0.0、NDK28.2.13676358；各JSON含URL和SHA。JDK是AWS Corretto17.0.20.12.1，jdk17-download.json保存精确地址。Google SDK获取入口为[Android Studio工具下载](https://developer.android.com/studio)。
- 恢复到新目录：`powershell -File dependencies/restore_client_tools.ps1 -TargetRoot <新工具目录> -AndroidProject clients/app -Verify`。脚本处理cmdline-tools/latest、build-tools内部android-16目录和JDK层级；默认不修改全局PATH。随后给build_client.py传--flutter、--android-sdk和--jdk。
- pub-cache-windows/linux来自pubspec.lock解析：在联网恢复机设置新的PUB_CACHE后从clients/app运行flutter pub get --enforce-lockfile，离线重放用保留缓存加--offline。原生Pdfium不由pubget保证齐全。
- gradle-cache来自Gradle9.3.1 wrapper与Maven解析；wrapperURL在clients/app/android/gradle/wrapper/gradle-wrapper.properties。联网构建填充独立GRADLE_USER_HOME，再保留以供离线；代理gradle.properties不分发。
- VC运行库windows/VC_redist.x64.exe有精确URL/hash；C++编译工具MSVC **未在旧离线包提供**。官方[VS安装步骤](https://learn.microsoft.com/en-us/cpp/build/vscpp-step-0-installation?view=msvc-170)选择C++桌面开发、v143和Windows SDK。原D:/VS2026便携布局不是跨机安装方法。

## 2. Ubuntu/Odoo/采集器

server/out保存544 DEB、Odoo固定提交源码、60 Odoo wheel及5 crawler wheel；MANIFEST.json、SHA256SUMS、constraints-odoo.txt和constraints-crawler.txt保留原验收版本。Odoo提交ab96189527544254a751adbfaafca6563ceb3f96，来源https://github.com/odoo/odoo.git。

联网Ubuntu22.04准备机执行（指定新的输出，不能覆盖已保存out）：

```sh
cd dependencies/server
OUT_DIR=<新输出目录> WORK_DIR=<私有工作目录> ODOO_REV=ab96189527544254a751adbfaafca6563ceb3f96 bash run_all.sh
# 分步为01_download_apt_closure.sh、02_fetch_odoo.sh、03*_wheelhouse.sh
cd <新输出目录>
sha256sum -c SHA256SUMS
```

04_build_manifest.sh生成清单，05_offline_verify.sh为离线验证入口。APT使用Ubuntu Jammy archive/security及apt_packages.list；脚本不是逐DEB版本锁，未来旧包可能不在镜像，因此**不能凭有脚本就删除原包**。重建字节不同必须作为新依赖版本登记。

全新安装闭包为cp310。生产cp312条码wheel在server/out/extras-barcode/python312：rl-renderPM4.0.3，URL和hash由registry可直接恢复；来自官方PyPI JSON，不能混进cp310安装。生产完整cp312依赖闭包尚未整体离线验收。

## 3. Linux客户端和EDA

Linux运行DEB在linux-runtime/out/debs和当前Linux1.0.1成品内（199个），包清单与verify_deb_closure.py保留。编译用clang/cmake/ninja/pkg-config、GTK/libsecret/CUPS开发包与运行时不同；在Ubuntu22.04联网开发机用apt安装平台README列出的明确包。原WSL私有环境路径不等于已迁出的完整工具链，具体导出状态见CURRENT_STATE。

EDA Windows Node24.19.0在plugins/jlc-eda/bridge/runtime。可从已核对3.0.3 bundle提取bridge/runtime恢复同字节，并带NODE-LICENSE.txt；官方版本目录https://nodejs.org/dist/v24.19.0/，获取前核对发布checksum。Linux需独立Linux Node，参见[官方Node下载](https://nodejs.org/en/download)，Windows exe不能用。

EDA构建用npm package-lock完整URL/integrity。联网在plugins/jlc-eda运行npm ci --cache ../../dependencies/npm-cache；离线必须先验证缓存重放。归档时若网络超时，仍保留现成node_modules但不会虚称npm ci --offline已通过。

## 4. 自制产物、数据库和历史

当前三端安装包、EDA bundle和Odoo修复ZIP都是本工程构建产物，来源是权威源码与原构建证据，不是某个可公开下载软件包。精确旧二进制只能从当前成品目录或可信离线备份取回；未来新构建按RELEASE.md产生新版本，未承诺逐字节复现。

SQLite是自行采集产物，来源/快照命令见data/README。生产备份仍在服务器，不在本地。历史聊天、构建缓存和私有签名不批量上传GitHub。

## 5. 搬到另一台机器

先克隆Git，再从当前机器导出载荷（不含local/private和历史聊天）：

```sh
python tools/offline_bundle.py export --file <备份盘>/lc-elc-payloads.tar
# 同时保存工具生成的 .tar.sha256
python tools/offline_bundle.py import --file <备份盘>/lc-elc-payloads.tar
python tools/repo_check.py --verify-payloads
```

导入拒绝路径穿越、符号链接和覆盖冲突。签名私钥另行受控备份；Git与普通载荷没有它。没有这份匹配key就不能保持Android现有安装的覆盖升级身份。

第三方许可证随依赖保留，不因为归档而删除。不要将依赖中的SDK .git或node_modules误加入本项目Git。

## 本次补齐的实际WSL工具载荷

`dependencies/wsl-build-tools/wsl-build-tools-20261019.tar.gz`已从现有WSL只读导出，4436412077字节，SHA256 `7d9c152d1a58dd04e319b173459f40bce13cb38d47dc06a34657b8e5aea475b1`。包括原Linux Android JDK/SDK/Flutter和缓存、Linux sysroot/Pdfium/适配bin，具体源路径见registry/wsl-toolchain.json。用`python tools/fetch_payload.py --id wsl-build-tools --verify`核验，然后在新私有WSL目录解包并按CLIENT.md传入路径。该文件可随普通离线payload导出，排除了签名私钥和代理配置。
