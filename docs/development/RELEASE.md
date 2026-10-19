# 构建、发布与追溯

## 现成包与新构建

现成当前客户端在clients/<platform>/releases/1.0.1，EDA在plugins/jlc-eda/releases/3.0.3，服务器模块修复包在server/releases/2026-10-18。它们是不可变导入的既有发布物，具体SHA256见registry/releases.json。

新构建从权威源开始，写到local/build时间戳目录，不修改成品目录。当前build_client.py是仓库归档后新维护入口，本次验证其dry-run和基础测试，未宣称由该新入口重建三端并完成全部实机验收；历史实测配方保留在local/archive/evidence/ui-repair-20261018。

```sh
python tools/build_client.py --platform android --dry-run
python tools/build_client.py --platform android --test
python tools/release.py snapshot --component client --output maintenance/registry/source-client-<版本>.json
python tools/release.py artifact --file clients/android/releases/<新版本>/<文件.apk> --source-manifest maintenance/registry/source-client-<版本>.json --version <新版本> --output maintenance/registry/artifact-android-<新版本>.json
```

先更新版本号，确保平台runner和lock受控；构建前冻结，构建后确认源未改变。artifact工具只登记哈希，不替代验收，初始状态为pending。

## 发布必备

- 源commit与完整source manifest；依赖锁/Flutter/Dart、JDK/NDK或Odoo/Python ABI。
- 构建命令、环境与exitcode；测试实际数量、跳过/限制；Windows/Linux完整bundle而非孤立exe/ELF。
- Android最终APK的公开证书指纹，确认与现有发布签名相同。私钥不进Git。
- 文件大小、SHA256、安装/升级步骤、服务端兼容范围及回滚点。
- 更新CHANGELOG、CURRENT_STATE和registry；新版本用新目录，禁止覆盖老包。

## 服务器归档包

只将当前源码重新打包不能叫‘全新环境已验收’。本次旧Ubuntu离线整包属于20261015历史，今天最新代码由修复包及权威源承载。若制作新完整部署包，保持server/ubuntu22.04与dependencies/server/out相对结构，并附cp310/cp312差异和实际验收状态。

生产升级按SERVER.md：备份 → 审核模块和目标 → 维护窗口 → 运维升级脚本 → 健康与业务验证 → 写变更记录。恢复会覆盖后续业务，必须先保存当前数据并明确数据库/filestore配套。不要把一次性40模块卸载脚本变成通用安装步骤。

## 当前源码与历史冻结的区别

maintenance/registry/active-sources.json指向当前代码的完整manifest；老manifest和已发布包保持不可变。正常功能修改后，不要改写旧baseline来凑检查：在测试并确认要冻结时创建新的源快照，例如 `python tools/release.py snapshot --component client --output maintenance/registry/source-client-task-<日期>.json --activate`。--activate只切换当前源码指针，不替旧安装包改变来源，也不代表已发布/已验收。未切换之前checker会指出代码相对当前快照的差异，这是需要补齐交接的明确状态。
