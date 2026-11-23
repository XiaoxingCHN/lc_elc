# 三端客户端维护入口

唯一共享源码在 [clients/app](app/)。Windows、Android、Linux 的本机包和正式应用内 stable 均为 `1.4.0+26`。正式域名三份签名清单已验证。 三个本机构建均已登记哈希和冻结源。

- [Windows](windows/README.md) 使用完整 x64 ZIP。
- [Android](android/README.md) 使用匹配既有证书的 ARM APK。
- [Linux](linux/README.md) 使用含主程序、更新助手和运行资源的 x64 tar.gz。

「仓位速览」在 `1.4.0+26` 支持多级库位树、搜索和管理员更改上级。当前入口、设备验收和生产发布边界分别见[开发与构建](../docs/development/CLIENT.md)、[构建交接](../maintenance/handoffs/2026-11-23-client-eda-alignment.md)和[更新通道交接](../maintenance/handoffs/2026-11-23-client-stable-release.md)。
