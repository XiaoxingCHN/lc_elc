# 当前系统架构

## 数据流与责任

```text
Windows / Android / Linux（共享Flutter源） ───HTTP会话───┐
Odoo浏览器仓库 / 网站门户 ────────────────────────────┤
嘉立创EDA专业版插件 ──本机127.0.0.1 Node桥接───────────┤
                                                      ▼
Odoo19：lab_catalog + lab_inventory + lab_workflow
  │ 权限由服务器会话/用户组决定；业务写入走统一库存作业方法
  ▼
PostgreSQL：资料库、物料、库存、袋/批次追溯、领用/归还

立创中文站 → 采集器 → SQLite供应商资料快照
                        │ 独立导入服务（不是直接修改库存数量）
                        └──→ lab_catalog商品/参数/分类
```

Flutter只缓存公开资料和安全登录状态，没有第二套权威库存数据库。供应商库存是商城信息，实验室库存来自stock.quant/stock.move。UI显示隐藏不构成权限控制，所有业务仍要服务端鉴权。

## 组件边界与维护源

| 组件 | 唯一源码 | 责任 |
|---|---|---|
| Flutter客户端 | clients/app | 三端共享业务、登录、统一搜索、扫码、标签预览、公开缓存 |
| lab_catalog | server/ubuntu22.04/odoo_addons/lab_catalog | 资料导入、分类/参数筛选、统一列表与网页仓库、缓存资产 |
| lab_inventory | 同级lab_inventory | product/stock扩展、SN和库位、库存字段与映射 |
| lab_workflow | 同级lab_workflow | 入库/领用/原单归还、袋追溯、幂等、QR/A4标签、三档业务角色 |
| EDA插件 | plugins/jlc-eda/src | EDA业务入口和iframe，调用本机桥接 |
| Node桥接 | plugins/jlc-eda/bridge/server.mjs | 127.0.0.1配对，代持Odoo会话，Linux宿主Node/Windows随包Node |
| 采集器 | server/ubuntu22.04/crawler | 中文采集、去重、断点、过滤与一致性快照 |
| 导入器 | server/ubuntu22.04/odoo_addons/lab_catalog/tools/import_catalog.py | SQLite到供应商资料模型，保留实验室库存语义 |
| 服务编排 | services/lcsc/systemd-production | 每日03:30启动/05:30停止；成功结束后OnSuccess触发导入 |

保留crawler在server的内部相对布局，是为了安装脚本和依赖准备脚本能复用同一源，不在services再复制第二份可编辑源码。services只负责编排和运维入口。

## 主数据与标识

- 供应商器件用立创编号去重，绑定后的实验室物料与资料合并成一张卡片。
- 多库位/批次数量在一张卡汇总，详情展开；有本地库存优先。
- 器件SN是主档标识，袋/批次有追溯码，库位有库码。
- 器件标签只有一个追溯二维码；SN、库位、参数可作文字。库位标签单独用库码。
- 领用绑定系统账号、项目说明和原领料行；归还只回补允许归还的原领用数量，不能随意制造库存。
- 库存事务要使用业务API、幂等键和服务端权限，不从客户端直接更新stock.quant。

## 环境分离

已知生产192.168.31.105:8069、数据库LcHardwareHouse、内网域名lc.rm.com仅供定位，真实账号密码与odoo.conf不在仓库。维护者应为本地/测试环境使用独立配置，不把生产作为自动测试默认目标。

server/ubuntu22.04/systemd是旧离线安装模板；services/lcsc/systemd-production是归档时只读导出的实际服务定义。二者用途不同，不可混称同一环境。全新Ubuntu22.04包为cp310；生产已存在cp312，见CURRENT_STATE。
