# 维护交接：2026-10-19 客户端更新接口已上线

## 用户目标与已确认边界

用户明确授权“现在上线更新接口”：先完整备份，再升级 lab_workflow 并必要重启。仅操作既有项目；不发布stable包，不安装客户端、不改网络/其他服务/爬虫、不写生产测试库存。认证经既有 getpass 桥接在内存持有，未保存密码或会话。

## 当前权威源码、分支和版本

源码 server/ubuntu22.04，分支 codex/two-stage-receipt-plan，未提交/推送。冻结源 maintenance/registry/source-server-updater-20261019.json，130文件，源树 SHA256 `446e7ada847f86c15572f808c3175723e6e533dea845a0c0fd9e63f6b3ec841e`。生产仅 lab_workflow 从19.0.1.1.0升级至 **19.0.1.2.0**；lab_catalog19.0.2.0.3、lab_inventory19.0.1.0.0未替换/升级，三个均installed。

## 已完成工作与实际证据

机器记录 maintenance/audit/update-endpoint-deploy-20261019.json，任务 maintenance/tasks/2026-10-19-update-endpoint-deploy.md。

- 完整源与130个包成员逐项核验；生产107个addons文件匹配冻结源。初次验证器错误地对二进制做LF归一化而报错，修正为清单规定的仅UTF8文本归一化后通过，生产源码未因此改变。
- 真实data_dir仍为 /opt/odoo/.local/share/Odoo；停服务后备份完整数据库和134个附件，源字节36,468,636。备份实物/hash、每个附件内容hash、pg_restore --list均通过。旧源码归档和旧模块目录均保留在addons扫描根之外。
- 仅-u lab_workflow，exit0；服务active，升级日志ERROR/CRITICAL/Traceback均0；升级后80行运行日志同类计数均0。
- 生产本机及开发机LAN实际请求：登录200；android/universal、windows/x64、linux/x64 manifest均204；未发布stable时属于正常无更新。非法arch404；匿名下载303跳登录。未发布任何stable清单/安装包。
- 升级前后 bag1、quant2、move1、operation1、catalog695217、location16、pending0、trace1、quantity/reserved总量0均相同。
- 真实5账号在只读事务并回滚中调用同一更新控制器权限守卫：2个有权账号进入资源查找返回404、2个无权账号403、1个公共账号403。未生成认证HTTP cookie，不冒称完成实际包传输。

## 剩余工作与阻塞

更新接口已上线且LAN可达，无认证阻塞。客户端修复由主代理交付；更新包实体安装、两版本原生升级/回退未验收，因此本轮不发布stable。之后经客户端验收并授权发布签名stable清单，才能实测认证包下载。完整恢复演练、离机备份未执行。

## 依赖和产物

无新增生产依赖。本地部署候选 local/build/update-endpoint-deploy-20261019/server-updater-19.0.1.2.0-candidate.tar.gz：11,535,892字节，SHA256 `287b9fc67a64713c2ed3aa4ce0ac5a444ede29480351d79df98e33e3ae75b902`。远端stage /opt/odoo/deployments/update-endpoint-20261019-a1 保留受控配置、备份/升级日志及脱敏deployment-facts.json；不导出私有日志/配置到Git。

## 生产状态和回滚

本轮完整配套备份 `/var/backups/lc-elc/20261019T131258Z-before-update-endpoint`：

- db.dump：110,511,511字节，SHA256 `4da86809f9ff5b16e4d7a21b5f4323a010ad36510d30dfc07c431010c026a9ab`。
- filestore.tar.gz：12,183,441字节，SHA256 `aab5c4a00bf6123a57da1ebb76f9d06033a709e18ab365a8a9fb99eb396b23da`。
- 旧lab_workflow：备份根下 module-source-before-upgrade/lab_workflow。
- 三模块旧源码另归档stage/old-source.tar.gz：11,700,288字节，SHA256 `38e8306dfc708d709750be1a8a3feba7a773c3df0673e347aeea2c91dbc3bf67`。

如需回滚，先备当前业务并核验绝对目标/包含关系、上述DB与真实filestore配对。停服务，把现模块保留至addons外，从旧模块目录恢复；odoo_restore.py先--list/--dry-run，确认恢复授权后恢复配套备份，传入真实data_dir的受控配置，启动并只读核验。不得对旧模块-u；数据库恢复会回退本轮备份后的写入。此次未恢复、未离机复制。
