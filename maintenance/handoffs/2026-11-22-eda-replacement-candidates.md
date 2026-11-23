# 交接：EDA 4.1.4 BOM 替代料

## 用户目标与边界

原理图和工程 BOM 中有 C 编号的缺料、未收录器件可以查实验室库存，按 SN 选择替代料。精确库存与候选分开显示，只有手动选择才带入出库预览。连接器按实际型号查找。

## 源码与版本

- 基线 `433004398837cdb2d78191b38cdddf0ee3abf6fc`。
- 插件源清单 [4.1.4](../registry/source-eda-4.1.4-20261122.json)。服务端候选源清单 [lab_catalog 19.0.2.0.24](../registry/source-server-lab-catalog-19.0.2.0.24-20261122.json)。
- 4.1.3 的安装包用截图中的 `C5137636` 重现缺封装。测试模拟首个位号缺封装、其他位号用 `C0603_L1.6-W0.8`，没有采集用户的实时 EDA 请求。
- 4.1.4 保留原理图值与封装，兼容 `100 nF`，使用 SN 显示和记录替代料。服务端候选先筛实时正可用量，再比规格或型号。

## 验证

- Windows 11、Node 24.13.0、npm 11.6.2，`npm run test:all` 通过 144 个单元测试及 17 个打包测试，`npm run verify` 通过。
- `node scripts/verify-bom-equivalents.mjs <.eext>` 使用 Edge、Playwright 和隔离 EDA/Odoo 响应，验证读取 61 个位号、发出 `100nF / 0603`、展开并勾选 SN、未匹配提示、缺料阻止提交、预览和模拟按袋出库。确认请求包含袋 313、数量 61、模拟本人领用人及 SN 备注。
- Python 3.15.0，`test_param_search.py` 8 项、`test_equivalent_match.py` 21 项通过。新增服务端匹配分支用模拟库存记录运行，排除缺库存、封装和数值不符及原编号。Odoo ORM 用例已添加，当前机器缺少 Odoo 运行环境，未执行。

## 成品与未验证项

- 成品目录 `plugins/jlc-eda/releases/4.1.4/`，安装文件 `lab-inventory-odoo_v4.1.4.eext`。同目录的 `release-manifest.json` 记录冻结源、构建环境和哈希。
- 生产 `lab_catalog` 未升级。真实 EDA 工程连接生产 Odoo 后的候选与领用流程尚未验收。
- 4.1.3 成品保存在原版本目录。如需切回，可导入原版 `.eext`。
