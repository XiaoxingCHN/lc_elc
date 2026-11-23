# 当前发布入口

**发布状态**（2026-11-23）。Windows、Android、Linux 的本机包和正式应用内 stable 均为 `1.4.0+26`。正式域名三份签名清单已验证。 EDA `4.2.0` 为手动导入包。桌面手动包直接包含程序文件，应用内通道包包含 `bundle/` 顶层。两种包的哈希独立登记。通道验证见[更新通道交接](../maintenance/handoffs/2026-11-23-client-stable-release.md)。

> 2026-11-23：三端客户端升到 `1.4.0+26`，EDA 升到 `4.2.0`（均在主仓成品目录，客户端已上线 stable，EDA 手动导入）：仓位速览按真实层级展开/折叠、搜索保留祖先、写操作按 `can_manage_locations` 授权、新增「更改上级」且超时复用同一请求号、创建结果未知不自动重试；EDA 出库结果未知后保留原请求并阻止新出库、主按钮改为成对配色（深色 16.64:1）、连接入口统一「连接设置」、BOM 数量列不再逐字换行、弹窗限制并恢复焦点。三端 `flutter test` 526 通过 / 5 跳过，EDA 144 单测 + 18 打包测试通过。

> 2026-11-19：Windows / Android 升到 `1.3.5+25`：登录后拆成四个分区（库存速览 / 仓位速览 / 器件库 / 库存管理）、库位标签改为「库码在下、名称放大」、修卡片对比度、制袋贴标补完成按钮、修手机切换器撑满整屏、拦下内网 https 手误、作业页覆盖外壳、内网地址可记住登录、详情页库位显示修复、入库先扫库位再连扫袋码。服务端 `lab_workflow` 升到 `19.0.2.0.4`（新建器件补 `is_storable`/`tracking`），**已部署到 lc-nas（2026-11-19 13:54 UTC）**。Linux 无精臣 SDK，仍为 `1.3.2+10`。

> 2026-11-18：Windows/Android 客户端 `1.3.2+10` 已并入主仓；Linux 端 `1.3.2+10` 已在 WSL Ubuntu 22.04 构建（未附 `deps/` 离线 DEB，运行时需系统 GTK/libsecret/cups）。旧版成品保留不覆盖。

| 组件 | 版本 | 本机成品目录 | 源码 |
|---|---|---|---|
| Windows客户端 | 1.4.0+26（库位树 + 精臣 B1 Pro USB 直打） | ../clients/windows/releases/1.4.0+26/ | ../clients/app/ |
| Android客户端 | 1.4.0+26（库位树 + 精臣 B1 Pro 蓝牙直打，仅 ARM） | ../clients/android/releases/1.4.0+26/ | ../clients/app/ |
| Linux客户端 | 1.4.0+26（库位树；无精臣 Linux SDK） | ../clients/linux/releases/1.4.0+26/ | ../clients/app/ |
| 嘉立创EDA专业版 | 4.2.0（画图助手） | ../plugins/jlc-eda/releases/4.2.0/ | ../plugins/jlc-eda/ |
| Odoo 历史归档修复包 | 2026-10-18 | ../server/releases/2026-10-18/ | ../server/ubuntu22.04/odoo_addons/ |

本机三端 `1.4.0+26` 的文件和校验值见 [Windows](../maintenance/registry/artifact-windows-1.4.0+26.json)、[Android](../maintenance/registry/artifact-android-1.4.0+26.json) 和 [Linux](../maintenance/registry/artifact-linux-1.4.0+26.json) 的成品登记。EDA 见[构建交接](../maintenance/handoffs/2026-11-23-client-eda-alignment.md)。[GitHub 客户端 Release](https://github.com/XiaoxingCHN/lc_elc/releases/tag/client-v1.4.0%2B26) 提供 Linux x64 手动包。现有 Windows 和 Android 通过登录后的应用内 stable 分发。历史归档成品仍以旧清单及其校验值为准。

发布物由Git排除，请按dependencies/README和离线载荷流程获取。不要只取Windows exe或Linux ELF，应保留完整同目录资源。

历史 Android 安装修复及验收边界见 [1.1.3+6 交接](../maintenance/handoffs/2026-10-19-android-install-fix.md)。

1.1.3+6安装入口修复已发布seq2；实体手机升级仍需验证，旧入口失败先手动覆盖一次，不先卸载。
