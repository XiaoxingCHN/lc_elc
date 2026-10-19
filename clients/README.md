# 三端客户端维护入口

唯一共享源码是[app](app/)（1.0.1+2），Windows、Android、Linux不各复制一套lib。每个平台的README负责环境和成品说明：

- [Windows](windows/README.md)：完整bundle/ZIP。
- [Android](android/README.md)：最终重签APK，必须保留匹配密钥。
- [Linux](linux/README.md)：完整bundle/tar.gz及199个运行DEB。

[开发与构建](../docs/development/CLIENT.md)说明工具链恢复和命令。发布先冻结完整源，不用旧根lab_inventory_client原型或10月14日handoff起步。

本次核对66个原Dart/pubspec业务文件与既有构建快照一致，后续完整源码manifest还覆盖测试、平台runner、锁文件和配置。当前成品以registry/releases.json的hash为准，不能按mtime挑最新。
