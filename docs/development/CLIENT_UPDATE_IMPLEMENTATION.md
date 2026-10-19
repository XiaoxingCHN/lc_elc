当前修复候选 **1.1.2+5** 及服务端上线状态见[最新交接](../../maintenance/handoffs/2026-10-19-receipt-picker-fix.md)。以下1.1.1+4记录是首次开发阶段的证据，不能代替当前状态。

# 更新器实现与验收：2026-10-19

客户端候选 **1.1.1+4**，lab_workflow候选 **19.0.1.2.0**。本轮仅开发、隔离验证和构建；生产仍19.0.1.1.0，未部署新接口、发布stable清单或推送本轮代码。

## 实际行为

- 冷启动后台检查；恢复前台可重查，服务器请求恢复成功触发重试；失败退避30秒/2分钟/5分钟/15分钟。只有一个任务，切换服务器/账号取消旧任务并丢弃迟到结果。不单独监听网卡事件，前台恢复、请求成功与退避探测覆盖重连。
- 清单探测独立匿名，不触发登录失效或延长十天有效期；下载使用原会话，仅当前同源、禁止重定向。非计费网络自动下载；计费或未知网络需确认下载。Android用ConnectivityManager、Windows用INetworkCostManager、Linux读NetworkManager Metered；失败按未知处理。
- Ed25519验签后读取安装决策，校验应用、平台/架构、递增build、最高已见发行序号、API范围、系统要求及512MiB大小上限。完整包流式下载并复验字节数/SHA256；支持取消、整包重试及已完成缓存复验复用，未做断点续传。缓存按服务器/数据库隔离，不写凭据。
- 登录页/仓库有“关于与更新”，可查看说明、检查/下载/取消/确认安装，后台下载有状态入口。安装前只允许仓库/登录页且无活跃请求；确认后暂停新服务器操作，禁止在表单/打印过程中强行安装。
- Android验证真实APK包名、versionCode、现有签名证书，调用PackageInstaller处理系统确认、安装来源授权与取消；不先卸载旧应用。
- 桌面独立Dart AOT助手先复验签名、包、路径和安装标记，准备成功才允许应用退出。完整bundle解压到旁边的新目录；拒绝越界、链接/特殊文件/重复路径/Windows特殊名称，限制条目数和展开总量；仅在有效标记的可写安装根切换，原安装路径保持稳定。第一帧回报nonce及实际build后才标成功；失败恢复旧入口，保留旧目录，不提权、不递归删除用户数据。

## HTTP契约与布局

普通HTTP，与库存JSON-RPC分开，均无库存写操作：

| 路径 | 授权/结果 |
|---|---|
| GET /lab/client/updates/manifest?platform=windows&arch=x64&channel=stable | 匿名、无会话保存；200签名信封，204未发布，404非法或损坏 |
| GET /lab/client/updates/assets/{release_id}/{filename} | 已登录且有lab角色；200完整流/长度/ETag，无角色403，未知/不完整404；未登录由Odoo拒绝或转登录，客户端不跟随 |

windows/linux/android，x64/arm64/universal，首版只有stable；Android使用universal APK。根目录取**Odoo运行时实际data_dir**下的lab-client-updates；布局为 `{platform}/{arch}/stable.json` 和 `releases/{release_id}/{filename,manifest.json}`。只能读取登记文件。匿名数据只含应用发行信息，无账号、库存、真实配置或GitHub认证。

信封 `{key_id,payload,signature}` 的payload是原始UTF8 JSON的base64，Ed25519签这些字节，避免跨语言重排。载荷包含schema=1、app_id、release_id、filename、version、build_number、release_sequence、channel、platform、arch、package_type、size、sha256、api_min/api_max、requirements及notes。系统要求使用android_sdk、windows_build、glibc（主版本*1000+次版本）；未知要求不安装。发布工具另要求source_manifest及其SHA256、source_tree_sha256、source_commit，全部受签名覆盖。

## 构建与发布

tools/build_client.py在桌面构建后调用tools/prepare_client_update.py，编译匹配宿主的助手并生成client-install.json；自定义CMake配方也必须执行准备步骤。完整zip/tar.gz均以bundle为顶层，Linux保留执行权限；不能仅分发exe或遗漏助手。目标机无需Python/Dart。旧版需先人工安装一次完整更新器包。

tools/client_release.py是离线发布工具，依赖tools/requirements-client-release.txt，只装开发者环境，不给Odoo加签名依赖。它要求来源元数据、持有发布锁，拒绝覆盖及序号/build倒退；包和不可变清单完成后原子切换指针。正式平台验收后，管理员才可将公有清单/包复制到服务器；工具本身不联网或自动上线。

公钥和锁定依赖见[登记](../../maintenance/registry/client-update-dependencies-20261019.json)。私钥只在Git排除的local/private/signing保管，不进入客户端、服务器或Git。换钥须由受信任客户端发行加入新公钥，不能信任未验证清单提供的钥匙。现有HTTP环境仍必须验签，不能只信任同一HTTP响应给出的hash。HTTPS变更另走运维流程。

本轮包是candidate，默认localhost验收地址/数据库，登录页可选择实际服务器。Android保留既有debug证书以维持安装身份，Windows/Linux未做OS代码签名；不能跳过原生升级验收直接提升stable。

## 证据与限制

[审计](../../maintenance/audit/client-updater-20261019.json)记录最终来源、包/hash、证书及日志。新增22项更新/界面测试已包含在全量264通过、5跳过中；维护10通过、1符号链接权限跳过；Odoo隔离55项中54通过、1既有跳过，6个真实HTTP并发通过。分析无error/warning，info单列。真实Flutter更新面板已渲染检查，320/1280宽度、明暗和200%文字通过；不是原生安装截图。

尚未真实Android安装确认/取消、两版Windows/Linux GUI升级及回退、真实网络费用策略、物理扫码打印和断电恢复。现有桌面测试验证目录切换/回退，不能替代原生GUI验收。断电可能留下prepared事务及保留目录，需核对路径和安装标记后人工恢复；首版不声称自动恢复断电。库存写入仅在隔离库测试，本轮未访问生产。
