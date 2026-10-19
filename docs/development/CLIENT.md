# 客户端开发与环境恢复

## 改哪里

lib/features/unified是统一器件展示、详情和收/领/还/标签；lib/services/lab_api_client.dart是业务API；odoo_client.dart是登录和HTTP会话；login_memory_store.dart/secret_backend.dart是安全登录；providers/auth_provider.dart负责状态；routes负责返回/离线访问边界。修改共享源码同时考虑三端行为。

## 依赖与路径

默认离线Flutter在dependencies/sdk/<windows或linux>/flutter；缓存dependencies/pub-cache-<host>。源码锁文件pubspec.lock提交Git。Windows/Android恢复入口 `powershell -File dependencies/restore_client_tools.ps1 -TargetRoot <新工具目录> -AndroidProject clients/app -Verify`；已知原包布局在dependencies/README。

恢复脚本产生的Flutter可用 `--flutter <工具目录>/flutter`，JDK/Android分别用--jdk和--android-sdk传给build_client.py。脚本只改子进程环境，不全局改PATH。`--online`允许pubget联网；默认offline和enforce-lockfile，失败应查日志而不是抹掉锁重新解析。

Linux在开发机按平台README安装原生构建依赖，恢复sdk/flutter_linux_3.47.7-stable.tar.xz及pubcache。独立LinuxNode不是Android/Flutter的依赖，但EDA桥接需要，别混为客户端必须项。

## 隔离构建与验收

build_client.py以脚本自身推导仓库根，复制源码到local/build/client-<平台>-<时间>/source，写独立日志和results.json；最多2个原生并行job。不会覆盖已发布文件。仅适配普通可用本机工具链，portable VS及旧WSL私有sysroot需要对应环境适配，历史配方可参考但不能盲跑旧绝对路径。

先dry-run核对计划，再实际--test。客户端测试必须记录非零数量；实体打印/扫码和OS安全存储按平台区分，没有执行就记未验证。Android必须核对最终APK公开证书，匹配local/private受控key；不允许自动生成新签名。

当前业务源的66文件与各平台原构建副本一致；完整源树由归档新manifest另冻，非66文件包含项不要冒称原构建证据已覆盖。归档本轮不全量重编译三端，具体当前状态见CURRENT_STATE。

## 原实际WSL工具已归档

原Android的Linux JDK/SDK/Flutter/pubcache/Gradle wrapper及模块缓存、Linux sysroot/Pdfium和私有适配bin已只读导出为dependencies/wsl-build-tools/wsl-build-tools-20261019.tar.gz（约4.4GB），SHA和成员原路径在maintenance/registry/wsl-toolchain.json。签名、代理gradle.properties、运行锁/日志不包含。可在WSL新私有目录解包，用明确路径传给构建入口；历史adapter中可能残留原绝对路径，应先按新解包根调整，不能冒称解包即实机验收通过。
