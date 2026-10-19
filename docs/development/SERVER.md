# Odoo开发与测试

## 组件职责

server/ubuntu22.04/odoo_addons内lab_inventory扩展product/stock；lab_catalog管理商品/参数/分类/统一搜索/网页仓库；lab_workflow提供带权限与幂等的扫码入库、领用、原单归还、袋和标签。不要从客户端或导入器直接写stock.quant来绕过业务方法。

修改manifest、ACL、XML、assets必须同步版本和升级验证。Odoo19的res.groups.privilege与native roles widget是当前角色结构，不能套用旧版res.users生成字段。

## 本地测试

新建隔离Odoo/PostgreSQL测试库，绝不能把默认生产库用于自动测试。模块测试从lab_workflow/tests和tox.ini入口查起；纯Python标签/追溯逻辑可在离线工具环境验证，真实ORM测试必须在Odoo内运行。tools/pdf_selfcheck.py验证PDF逻辑，check_barcode_rendering.py验证实际ReportLab位图backend。

```sh
python3 server/ubuntu22.04/tools/check_barcode_rendering.py
# 真实模块测试示意，必须给测试配置和隔离DB：
<测试venv>/bin/python3 <odoo源>/odoo-bin -c <测试配置> -d <隔离库> --test-enable -i lab_workflow --stop-after-init --no-http
```

无Odoo环境时可以语法/纯逻辑检查，但不能冒称ORM、并发和HTTP业务全通过。现有26权限/7组件/9浏览器测试是20261018生产修复证据，归档另作来源核对。

## 依赖

全新Ubuntu22.04安装器使用Python3.10、ReportLab3.6.8和PostgreSQL14离线依赖；现有生产为Python3.12.15、ReportLab4.1.0、Pillow10.2.0、rl-renderPM4.0.3。ABI不同，wheel不能混用。cp312完整生产venv离线闭包尚未作为完整包验收，维护时遵循CURRENT_STATE。

依赖准备器在dependencies/server，按目录相对找crawler requirements；指定新WORK_DIR/OUT_DIR运行，不覆盖已验收out。APT当前镜像不能保证历史DEB永远可下载，应保留原包、Packages、constraints和SHA256SUMS。

## 运维故障夹具回归

`lc_ops_tests.py`只对临时fixture/stub运行，不访问真实PostgreSQL或systemd。本次在WSL root（仅临时文件归属检查所需）运行100检查全通过；非root先跑的10个权限前置失败保留日志，未算通过。维护者应在隔离WSL/测试环境审阅后以正确身份执行，不能把它当作真实生产恢复演练。
