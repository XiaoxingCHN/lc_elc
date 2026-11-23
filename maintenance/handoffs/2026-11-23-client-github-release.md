# 客户端 1.4.0+26 GitHub 公开发行

## 发行状态

客户端公开 Release 已创建，标签 `client-v1.4.0+26` 指向真实构建来源 `d98c73acf42d1219364599e03b6ee70f2d6c14ae`。源码通过标签可查，没有推送开发分支。 [公开 Release](https://github.com/XiaoxingCHN/lc_elc/releases/tag/client-v1.4.0%2B26)

| 附件 | 用途 | 验证 |
| --- | --- | --- |
| `LC_ELC-Linux-1.4.0+26.tar.gz` | Linux x64 手动安装包 | 无需登录下载成功，16,618,723 字节，SHA-256 `e4842e57fab27b890dcb221842cbbe8f5a1d9d42eaa49220e4b404cfd4ac2d26`，与本机成品登记一致 |
| `SHA256SUMS.txt` | Linux `sha256sum -c` 校验文件 | 使用 LF 换行格式，以公开下载的内容核对哈希 |

Linux 包中有桌面程序、更新助手、完整运行资源和 Flutter 许可证通知。包内没有精臣打印 SDK。Linux `1.4.0+26` 的编译、归档结构与 WSLg 首帧有记录，设备完整升级和实体打印待验收。

## Windows、Android 和 EDA

现有 Windows 和 Android 成品包含精臣运行时及字体。接入资料未确认公开再分发权，Android 接入说明还明确列出附带字体的授权限制。这两个原始成品继续通过库存账号登录后的应用内 stable 分发。对外发行时可另建去掉精臣依赖的公开版，或在取得附件公开再分发确认后使用原包。EDA 扩展按独立版本发布。

GitHub 手动安装包与生产应用内通道分别登记。正式 stable 三端仍是 `1.4.0+26`，Linux 手动归档的 SHA-256 与 `bundle/` 布局的通道归档不同。 [生产更新交接](2026-11-23-client-stable-release.md)
