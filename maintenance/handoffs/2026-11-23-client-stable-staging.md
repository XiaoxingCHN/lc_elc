# 三端 1.4.0+26 应用内更新准备

> **候选准备历史**。后续三端 stable 已切换到 `1.4.0+26`，见[正式发布记录](2026-11-23-client-stable-release.md)。

## 准备阶段的正式状态

已通过正式域名读取并校验三份 Ed25519 清单。Windows `x64`、Android `universal`、Linux `x64` 的 stable 都是 `1.3.5+25`，build 和 sequence 均为 25。当前正式指针没有切换。

用户已明确授权发布三端更新通道，并批准仅在 Git 本地提交客户端。客户端源码与冻结清单在提交 `d98c73acf42d1219364599e03b6ee70f2d6c14ae`，本次提交包括 7 个客户端文件和 1 个冻结清单。冻结源中两份已登记的安卓 AAR 通过哈希核对，沿用离线载荷管理。签名器公钥已与客户端登记及线上清单核对。

## 已完成的发布准备

- 工作区、Windows、Android、Linux 三份构建副本分别与[冻结源清单](../registry/source-client-1.4.0-26-20261123.json)逐项比较，均为 **222/222 文件相符**。旧安装包维持原登记和哈希。
- 本机桌面直装包的布局不能直接送入应用内更新器。更新器要求所有成员位于 `bundle/`，并拒绝含 `.` 的成员。本轮另行生成通道包，Windows 与 Linux 的应用程序和更新助手都保留在归档中，Linux 保留可执行位。
- Windows ZIP 和 Linux tar.gz 已使用客户端 `extractBundle()` 和 `installationIdentity()` 解包校验。两端从准确的通道归档解包后都启动至首帧，发出 build 26 的 ready 标记。Linux 使用 WSLg，未测试登录或 SecretService。
- Android 延用本机成品 APK。核对包名 `com.example.lab_inventory_client`、版本 `1.4.0`、构建号 26、最低 API 24 及 `arm64-v8a`/`armeabi-v7a`。该 APK 的签名与登记的旧 Android 包一致。ADB 当前无设备，覆盖安装与用户确认流程待验收。
- 尚未执行从旧版实际切换和回滚、生产认证下载或客户端业务验收。启动冒烟不能替代这些检查。

| 通道 | 候选文件 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| Windows x64 | `LC_ELC-Windows-1.4.0+26-x64.zip` | 37,747,522 | `f8e5f19b03faa8702a8478794521fd3d6779492c20669885952118a8b8d3d5d8` |
| Android universal | `LC_ELC-Android-1.4.0+26.apk` | 108,074,988 | `b543e7fb6395311b937d844d4edd75413bd4f65dd32ea28b7ae225197647cad0` |
| Linux x64 | `LC_ELC-Linux-1.4.0+26.tar.gz` | 16,984,249 | `03e631dbe1889fd701cd157dddcb8f416a3025cb762447e6bc9aa2e4732c6bf3` |

两个桌面包与三份提交来源元数据位于 `local/build/client-update-1.4.0+26/`。同目录 `signed-staging/` 内的三份清单已由现有 Ed25519 身份签名，并用已登记公钥独立验证，包大小和 SHA-256 一起核对通过。Android 原包在主仓 `clients/android/releases/1.4.0+26/`。哈希按文件区分，勿把手动安装包的桌面哈希写入通道清单。

## 发布顺序与回滚

1. 已提交并核对客户端冻结源。按正式发布约定完成隔离升级验收，记录 Android 真机覆盖安装和桌面完整更新、回滚。
2. 已在本地签名并验证三个候选。实际发布前再检查 stable 的 build 与 sequence。生产仅接收签名后的清单和包。备份当时的三个 stable 指针，准备不可变发行目录，分别核对包大小、SHA-256、权限和完整性，再原子切换各平台指针。
3. 公网重新读取三份清单，验证签名、平台、build 和 sequence。以已授权库存账号下载完整包，复验大小和 SHA-256。匿名资源下载应被拒绝。设备侧覆盖安装、登录和库存操作按平台另记。
4. 若要撤回，恢复对应旧指针，保留已登记的发行目录。已看到较高序号或已安装较高 build 的客户端可能不会自动降级，必要时提供更高 build 的修正版。
