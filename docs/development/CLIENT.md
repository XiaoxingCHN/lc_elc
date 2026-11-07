# 客户端开发与环境恢复

## 改哪里

lib/features/unified是统一器件展示、详情和收/领/还/标签；lib/services/lab_api_client.dart是业务API；odoo_client.dart是登录和HTTP会话；login_memory_store.dart/secret_backend.dart是安全登录；providers/auth_provider.dart负责状态；routes负责返回/离线访问边界。修改共享源码同时考虑三端行为。

## 玻璃设计系统

1.2.0 源码候选以深色玻璃和荧光绿为默认外观，只改视觉层，保留业务路由、文案、协议和交互语义。`lib/ui/glass/` 是统一实现，`lib/widgets/lab_ui.dart` 保留 `LabTheme`、`LabAppBar`、`LabGlassSurface` 等兼容入口。

- `GlassTokens` 管理深浅色板、圆角、模糊强度与动效；裸 `ThemeData` 按 brightness 回退。
- 只有 `GlassSurface` 创建 `BackdropFilter`。AppBar、抽屉、搜索建议和对话框等浮层使用真实模糊；`GlassPanel` 和滚动卡片默认无模糊，不逐项创建滤镜。
- 主操作沿用 Material `FilledButton` 的统一主题，不为换肤机械替换业务按钮。高亮 accent 背景必须配 `onAccent` 文字；高对比度提高不透明度并关闭模糊，减少动态效果时关闭按压缩放。
- 错误、警告、成功与通知使用 `StatusBanner`，保留图标和文字，不只靠颜色区分。标签 A4 预览及 PDF 保持白底黑字。
- 320/1280 宽、深/浅主题、200% 文本由 widget 测试覆盖；PNG 离屏渲染不等于真机性能、读屏、触控或实体打印验收。

这是 Flutter 对 Liquid Glass 的近似实现：没有原生材质的真实折射、边缘弯折和自适应光照。零新增 pub 依赖，不改变 `--enforce-lockfile --offline` 的依赖闭包。

## 器件库按需抓取

搜索零结果且服务端在 `fetch_suggestion` 中明确给出精确 C 码/完整 MPN 时，目录页的 `EmptyView` 显示“立即从立创商城抓取”。抓取是异步的：`CatalogNotifier.startFetch()` 调用 `/lab/api/catalog/fetch` 入队，随后每秒轮询 `/lab/api/catalog/fetch_status`（最多 60 次），`done` 后自动 `refresh()`；换查询或销毁 notifier 时取消轮询。

- 只有精确 C 码/MPN 会得到建议；名称、品牌、短关键词不发请求，也不由客户端自行判断。
- `candidates` 是终态：必须由用户点选某一条（带 `catalog_code` 重新提交），不能自动取第一条。
- 失败、非电子、待复核、未找到都显示服务端中文原因，状态卡同时带图标与文字，不只靠颜色。
- 抓取只影响器件资料与供应商库存，不创建本地档案、不改实验室库存；离线模式下不出现该按钮。
- 客户端测试 `test/features/unified/catalog_fetch_test.dart` 用 `FakeLabApi` 覆盖建议、轮询、候选、限流失败、清空与终态集合；不访问网络。

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
