# 立创采集与Odoo资料同步服务

## 唯一源码与生产事实

采集Python源码唯一入口是server/ubuntu22.04/crawler，保留它在现有部署布局以兼容安装器和依赖准备器，不在这里再复制第二套可编辑源码。Odoo导入器为server/ubuntu22.04/odoo_addons/lab_catalog/tools/import_catalog.py。

systemd-production是归档时从192.168.31.105只读导出的完整实际定义（含drop-in），服务器时区Asia/Shanghai；没有重启/改变服务，也没有读取/etc/odoo.conf或环境凭据。

- lcsc-crawler.timer：每日03:30启动，enabled。
- lcsc-crawler-stop.timer：每日05:30停止，enabled；停止service仅在采集服务active时运行。
- lcsc-crawler.service：16 workers、delay0.1、status interval5秒、no-export、Restart=no，CPUQuota50%、内存限制1G。service本身disabled是正常的timer启动方式，不代表timer失效。
- lcsc-crawler.service.d/odoo-import.conf：`OnSuccess=lcsc-catalog-import.service`。
- lcsc-catalog-import.service：使用Odoo venv运行import_catalog.py，读取SQLite与分类，更新供应商资料，`--verify`；不是直接更新实验室库存。
- odoo.service：现有实例启动定义，单独保留以便理解环境，不要在归档后批量覆盖线上unit。

这些是配置已核对，不是归档时实际等待一个夜间窗口并重跑业务的验收。失败采集不会凭配置就叫成功导入。绝不要为‘验证’自动启动爬虫。

## 实际服务器路径

`/opt/lcsc-crawler/app`源码；`/opt/lcsc-crawler/.venv`依赖；`/var/lib/lcsc-crawler/components.sqlite3`数据；同目录categories_cn.json；日志journal；Odoo源/opt/odoo/custom-addons。Windows盘路径不是Linux部署路径。

## 维护与恢复方法

依赖为requests==2.34.2及其锁定传递wheel，在dependencies/server/out/wheelhouse-crawler。用私有venv和--no-index安装，不改宿主全局Python。安装工具server/ubuntu22.04/install_crawler.sh或install_offline.sh --crawler，但生产已有实例时不得无必要重装或覆盖数据库。

读取状态可用 `systemctl status lcsc-crawler.timer lcsc-crawler-stop.timer lcsc-catalog-import.service` 和 `journalctl -u lcsc-crawler.service -u lcsc-catalog-import.service`（管理员在已授权范围执行）。真实配置更改前备份unit/drop-in并核对时区、路径、权限，变更后systemd-analyze verify、daemon-reload及是否启用需要独立授权，不随归档自动执行。

数据快照必须先按授权暂停采集，使用snapshot_catalog.py SQLite backup创建新目的文件，携同分类文件，再verify_checkpoint；普通复制活跃SQLite可能不一致。恢复旧662768资料快照会落后于当前生产，详见data/README。

旧Windows64线程runner与Codex路径/任务名哈希绑定，已放local/archive/windows-tools，默认不注册不启动；不能同时跑两个指向同一库的采集器。
