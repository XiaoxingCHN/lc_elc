最新开发候选 **1.1.2+5** 修复器件选择白屏及更新状态；三端构建和来源核验通过，包/hash见[修复审计](../maintenance/audit/receipt-picker-fix-20261019.json)。生产更新接口已上线，尚未发布stable包。

# 三端客户端维护入口

唯一共享源码是[app](app/)（开发候选 1.1.1+4，已发布包仍为 1.0.1+2），Windows、Android、Linux不各复制一套lib。本轮新增更新器，三端完整包、来源/hash与真实升级未验收项见[更新器交接](../maintenance/handoffs/2026-10-19-client-updater.md)。每个平台的README负责环境和成品说明：

- [Windows](windows/README.md)：完整bundle/ZIP。
- [Android](android/README.md)：最终重签APK，必须保留匹配密钥。
- [Linux](linux/README.md)：完整bundle/tar.gz及199个运行DEB。

[开发与构建](../docs/development/CLIENT.md)说明工具链恢复和命令。发布先冻结完整源，不用旧根lab_inventory_client原型或10月14日handoff起步。

归档时核对66个原Dart/pubspec业务文件与既有构建快照一致；后续两阶段入库候选已修改源码，新manifest覆盖当前测试、平台runner、锁文件和配置。现成成品仍以registry/releases.json的hash为准，不能按mtime挑最新。
