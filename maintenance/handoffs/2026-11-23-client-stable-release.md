# 三端应用内更新 1.4.0+26 正式发布

## 版本与范围

经用户授权，Windows `x64`、Android `universal`、Linux `x64` 的 `stable` 已由 `1.3.5+25` 切换到 **`1.4.0+26`**，build 和 sequence 均为 26。发布仅写入生产更新存储；Odoo 服务持续运行。Git 来源为 `d98c73acf42d1219364599e03b6ee70f2d6c14ae`，对应[冻结清单](../registry/source-client-1.4.0-26-20261123.json)。EDA 扩展仍走独立发行路径。

## 公网核查与成品

| 平台 | Release ID | 通道包大小 | SHA-256 |
| --- | --- | ---: | --- |
| Windows x64 | `windows-1.4.0-build26-20261123` | 37,747,522 B | `f8e5f19b03faa8702a8478794521fd3d6779492c20669885952118a8b8d3d5d8` |
| Android universal | `android-1.4.0-build26-20261123` | 108,074,988 B | `b543e7fb6395311b937d844d4edd75413bd4f65dd32ea28b7ae225197647cad0` |
| Linux x64 | `linux-1.4.0-build26-20261123` | 16,984,249 B | `03e631dbe1889fd701cd157dddcb8f416a3025cb762447e6bc9aa2e4732c6bf3` |

- 正式域名的三份清单均返回 HTTP 200，逐份验证 Ed25519 签名、版本、序号、大小、SHA-256 及源码提交。下载路径在匿名请求下均返回 303 到登录页。
- 以生产 Odoo 进程身份从真实 `ReleaseStore` 打开并完整读取三份文件，大小和 SHA-256 与签名清单一致。
- Windows 与 Linux 的通道包含 `bundle/` 顶层。发布前验证了现有更新器解包以及 build 26 的首帧就绪标记。Android 核对了包名、构建号、ABI 和既有证书。个人设备的登录后下载、Android 覆盖安装及从旧版到新版的完整升级回退没有复测。 [候选准备证据](2026-11-23-client-stable-staging.md)

## 回滚

上线之前备份了 build 25 的三份指针，具体位置见生产受控备份台账。三份备份逐项核对 SHA-256，旧不可变发行目录仍保留。撤回时按目标平台原子恢复对应 stable 指针。已安装 build 26 或已记录更高序号的设备可能拒绝旧版，需要另发更高 build 的修正版。

GitHub Releases 是手动下载入口，本次发布未向 GitHub 上传附件。
