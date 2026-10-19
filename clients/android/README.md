当前已发布1.1.3+6 stable，包在releases/1.1.3+6/LC_ELC-Android-1.1.3+6.apk，来源/签名/测试与旧入口失败后的手动覆盖说明见[交接](../../maintenance/handoffs/2026-10-19-android-install-fix.md)。以下为历史发布背景。

最新：1.1.2+5已发布Android stable，完整包/签名/HTTP下载核验通过，见[发布交接](../../maintenance/handoffs/2026-10-19-android-stable.md)。用户已允许未知来源但旧安装入口失败，当前1.1.3+6安装修复见[交接](../../maintenance/handoffs/2026-10-19-android-install-fix.md)。以下1.0.1描述保留原发布背景。

# Android客户端

当前成品releases/1.0.1/LC_ELC-Android-1.0.1.apk（1.0.1+2，73690852字节）。这是最终重签版本，不能替换为_analysis的中间APK。源码../app；applicationId仍是com.example.lab_inventory_client。

## 签名延续（归档时已实际核实）

最终公开证书SHA256：`8b4c2409604fcd6fdd65dc5344afca7bffb81f07df2c77c210bcef1a78a9ff43`。

匹配密钥本机保存在local/private/signing/windows-debug.keystore，不入Git、不放普通离线载荷。来源与公开匹配结果见maintenance/registry/android-signing.json。WSL/home/xiaoxingchn/.android/debug.keystore的证书为640b…a5ff，是另一个密钥，不能用于同签名更新。

当前release仍使用debug signingConfig（已有内网部署约定）。改包名或迁正式签名是单独迁移任务；不能在普通修复中自动生成新密钥，否则现有安装不能覆盖升级。

## 构建

Flutter3.47.7/Dart3.13.5、JDK17.0.20.12.1、Android platform36/buildtools36.0.0、NDK28.2.13676358、Gradle9.3.1，源和恢复方法见dependencies/README。

`python tools/build_client.py --platform android --dry-run`；恢复后实际构建可加--test、--android-sdk、--jdk和--flutter明确覆盖路径。脚本将匹配key不透明复制到本次隔离Android用户目录，不打印其内容；结束后由维护者按私有材料规范保管构建目录。

真实10月18构建使用WSL私有SDK，原配方保留在local/archive/evidence/ui-repair-20261018/build-android.sh。新通用入口本次仅检查计划，不能冒称已同环境重建。最终产物发布前必须apksigner verify --print-certs、核对版本/证书/来源并在设备或约定范围验收。按用户此前选择，当前版未上模拟器；不能写‘模拟器通过’。
