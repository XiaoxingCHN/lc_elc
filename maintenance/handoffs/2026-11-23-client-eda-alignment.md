# 交接：客户端库位树与 EDA 对齐

## 目标与边界

针对[审查报告](../audit/2026-11-23-client-eda-alignment.md)实施核心改动并补充自动化。各项完成度以审查矩阵和下面的验收记录为准。生产发布准备见[更新通道交接](2026-11-23-client-stable-staging.md)。

## 版本与源码

- 客户端 `1.4.0+26`，源清单 [source-client-1.4.0-26-20261123.json](../registry/source-client-1.4.0-26-20261123.json)。
- EDA `4.2.0`，源清单 [source-eda-4.2.0-20261123.json](../registry/source-eda-4.2.0-20261123.json)。
- 服务端未改动，生产仍是 `lab_team_web 19.0.1.3.1` / `lab_workflow 19.0.2.0.5` / `lab_catalog 19.0.2.0.23`。

## 完成了什么

客户端（三端共用源码）：

- `LabApiClient.locationsTree()` 请求 `with_tree`，解析 `locations` 与视图祖先；`LabStockLocation` 增加 `parentId / hierarchyKnown / isView`。
- 仓位速览改为多级树：默认展开到区级，分支可折叠，搜索显示命中节点及祖先；统计只算真实内部库位。
- 写操作（新建库位、更改上级）只在服务端确认 `can_manage_locations` 后出现；新建可选上级；移动冻结请求号，超时后「原样重试」，创建结果未知只提示核对、不自动重试。

EDA：

- 结果未知的出库写入 `lab_eda_pending_outbound`（按服务器 + 用户隔离，不含密钥），重扫/切范围/重开面板都不清除，新出库被禁用，只能同键重试或核对后放弃。
- 主按钮改用 `--primary/--on-primary` 成对令牌：深色 16.64:1、浅色 5.27:1。
- 连接入口统一「连接设置」，删除头部重复按钮，去掉桥接/配对码措辞。
- BOM 数值列不再逐字换行；信息性小字 12px；确认弹窗限制并恢复焦点。

## 实际验证

- `flutter analyze --no-pub`：0 error / 0 warning（既有 info 提示未变）。
- `flutter test --no-pub`：526 通过、5 跳过；新增 `location_tree_test.dart` 11 项。
- `npm run test:all`（EDA）：144 单元 + 18 打包测试通过。
- `verify-bom-equivalents.mjs` 对实际 `.eext` 断言：读取 61 位号、候选、缺料阻止、模拟出库、未决锁跨重扫、同键重试、弹窗焦点、主按钮对比度 ≥4.5:1。
- `python tools/repo_check.py`：PASS 53，0 错误。
- 成品：`plugins/jlc-eda/releases/4.2.0/`，`.eext` 99277 B / `f3e56d98…`，bundle 104102 B / `ed4540dd…`。

## 三端构建与登记

| 平台 | 成品 | 大小 | SHA-256 前缀 | 验证 |
| --- | --- | --- | --- | --- |
| Windows | `clients/windows/releases/1.4.0+26/LC_ELC-Windows-1.4.0+26-x64.zip` | 37,748,130 B | `7817d572f9ae64a0` | pub get / test(526) / build 均 exit 0；zip 顶层即 bundle，含 exe、更新助手与 `client-install.json` |
| Android | `clients/android/releases/1.4.0+26/LC_ELC-Android-1.4.0+26.apk` | 108,074,988 B | `b543e7fb6395311b` | 同上；arm64+arm；证书 SHA-256 与 1.3.2+10 相同 |
| Linux | `clients/linux/releases/1.4.0+26/LC_ELC-Linux-1.4.0+26.tar.gz` | 16,618,723 B | `e4842e57fab27b89` | 同上；bundle 顶层且保留可执行位 |

构建脚本：`tools/build_client.py`（Windows 需 `PDFIUM_LOCAL_ARCHIVE`、`--work-root C:/lcw`；Android 需显式 `--flutter/--android-sdk/--jdk/--gradle-cache/--signing-key`；Linux 在 WSL 内并设 `PKG_CONFIG_PATH` 指向解包的 libsecret 前缀）。打包与登记：`tools/package_client_release.py`。登记文件 `maintenance/registry/artifact-{windows,android,linux}-1.4.0+26.json`。

## 未完成

1. 真实嘉立创 EDA 宿主安装 `4.2.0` 并跑 EDA-T01…T07。
2. Windows 和 Linux 已从重新打包的通道归档启动至首帧。完整覆盖升级、回退、Android 真机覆盖安装和 SecretService 记住登录待验收。
3. 客户端连接生产 Odoo 的真实库位树（客户端未连生产）。
4. 三端应用内 stable 已上线 `1.4.0+26`，来源提交 `d98c73a`。完整设备升级验收待完成。[正式发布交接](2026-11-23-client-stable-release.md)。
5. FL-06 的改名/停用未移植到 Flutter；EDA-06 的最小控件尺寸未加断言。
