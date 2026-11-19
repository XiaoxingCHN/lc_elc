# 当前发布入口

> 2026-11-19：Windows / Android 升到 `1.3.5+22`：登录后拆成四个分区（库存速览 / 仓位速览 / 器件库 / 库存管理）、库位标签改为「库码在下、名称放大」、修卡片对比度、制袋贴标补完成按钮、修手机切换器撑满整屏、拦下内网 https 手误、作业页覆盖外壳。服务端 `lab_workflow` 升到 `19.0.2.0.4`（新建器件补 `is_storable`/`tracking`），**已部署到 lc-nas（2026-11-19 13:54 UTC）**。Linux 无精臣 SDK，仍为 `1.3.2+10`。

> 2026-11-18：Windows/Android 客户端 `1.3.2+10` 已并入主仓；Linux 端 `1.3.2+10` 已在 WSL Ubuntu 22.04 构建（未附 `deps/` 离线 DEB，运行时需系统 GTK/libsecret/cups）。旧版成品保留不覆盖。

| 组件 | 版本 | 本机成品目录 | 源码 |
|---|---|---|---|
| Windows客户端 | 1.3.5+22（四分区 + 精臣 B1 Pro USB 直打） | ../clients/windows/releases/1.3.5+22/ | ../clients/app/ |
| Android客户端 | 1.3.5+22（四分区 + 精臣 B1 Pro 蓝牙直打，仅 ARM） | ../clients/android/releases/1.3.5+22/ | ../clients/app/ |
| Linux客户端 | 1.3.2+10（1.3.3 起未构建；无精臣 Linux SDK） | ../clients/linux/releases/1.3.2+10/ | ../clients/app/ |
| 嘉立创EDA专业版 | 3.1.0（画图助手） | ../plugins/jlc-eda/releases/3.1.0/ | ../plugins/jlc-eda/ |
| Odoo模块当前修复包 | 2026-10-18 | ../server/releases/2026-10-18/ | ../server/ubuntu22.04/odoo_addons/ |

实际文件名、大小、SHA256、来源和已知验收限制见maintenance/registry/releases.json。旧版全部在local/archive/packages和local/archive/eda，不能用于覆盖当前服务器或客户端。

发布物由Git排除，请按dependencies/README和离线载荷流程获取。不要只取Windows exe或Linux ELF，应保留完整同目录资源。

Android stable发布与手机安装状态分开记录：build5已完成签名/HTTP下载核验，手机反馈安装入口仍失败，1.1.3+6修复见最新交接。

1.1.3+6安装入口修复已发布seq2；实体手机升级仍需验证，旧入口失败先手动覆盖一次，不先卸载。
