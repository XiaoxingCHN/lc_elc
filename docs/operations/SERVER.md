# 服务器安装、升级、备份与回滚

当前已知环境192.168.31.105:8069、数据库LcHardwareHouse、代码/opt/odoo、配置/etc/odoo.conf、数据/var/lib/odoo；本仓库只保存非敏感定位，不保存真实配置或账号密码。不要因读取此文自动连生产。

## 操作入口

- 全新Ubuntu22.04：server/ubuntu22.04/install_offline.sh；`--fresh-odoo <dependencies/server/out绝对路径>`。脚本会拒绝覆盖已有实例。只有明确全新目标和管理员输入密码时运行。
- 现有实例升级：同目录upgrade_modules.sh；先看其参数帮助，备份后安装候选代码并验证日志/HTTP/模块状态。
- 成套备份：odoo_backup.py（数据库+filestore+源码指纹）。
- 恢复计划：odoo_restore.py --list及--dry-run；实际恢复会覆盖指定目标库，需要明确数据库/filestore配对和维护窗口。
- 资料导入：import_catalog_config.py及lab_catalog/tools/import_catalog.py，只更新供应商主资料，不改变实验室库存。
- 条码backend：tools/check_barcode_rendering.py；cp312增量修复用tools/fix_barcode_rendering.sh及dependencies/server/out/extras-barcode/python312。

这些脚本不要拆散。完整参数以当前脚本--help为准；不在本归档任务重复执行安装、40模块卸载或全量导入。

## 标准升级步骤

1. 在测试环境按候选源和目标ABI验证。冻结模块版本、hash、API兼容、依赖差异和回滚方案。
2. 核对授权范围、目标主机/DB、可用空间和业务维护窗口；执行完整备份并核对文件实物与校验值。
3. 仅升级本项目的指定模块。Odoo重启/升级日志既要检查退出码，也要检查ERROR/CRITICAL；不能只凭exit0。
4. 检查服务active/HTTP200、三模块installed、用户权限、统一搜索、库存原单关系、条码PDF等真实操作范围。测试写入需明确授权，优先隔离库。
5. 更新部署记录和release manifest。失败按备份恢复，先另备当前数据；恢复会回退备份之后所有业务写入。

## 当前备份定位

20261018完整备份：`/opt/odoo/backups/module-cleanup-production-20261018T153740Z`，DB dump SHA256 `1bd86e42ca5c2055f856203d88718a0314cc14ca0f89a9e7d6efc8e784a9f310`。

这是服务器上的实物定位，**没有因归档自动下载到本机**。需要离机备份时由管理员在受控渠道复制数据库dump+filestore+源码备份，核对清单，并存入Git之外的备份库。不能仅保留一串路径便称已离机保护。

## 安装与生产ABI差异

原离线新装路径cp310，现有生产cp312。仅cp312条码wheel增量已保留；当前没有声称完整复建生产venv的离线验收。若需重建cp312，先用服务器venv的pip list/freeze（只保存公开包版本、不导出凭据）生成锁，在联网同ABI Ubuntu准备机执行pip download/wheel构建完整闭包，再隔离验证；不能把cp310 wheelhouse直接灌入cp312。

## 权限/应用维护

库存依赖stock/product/mrp，网站与登录也有传递依赖。禁止按‘销售/会计/制造’字样盲删模块。已卸载40/保留52的具体清单是一次性历史变更，不应新服务器默认复用。

普通用户权限页只显示网站和实验室库存，隐藏组保留原值；技术完整权限在开发者模式。用户列表不是角色直接编辑入口，需打开账号详情→访问权限。
