# 变更日志

## 3.0.3

### 修复

- 真机 BOM 对比报 `EDA 消息总线调用失败：undefined`：`getBomFile` 是 @beta 接口，
  在原理图编辑器里调用 `pcb_ManufactureData.getBomFile` 可能一直不返回，导致桥接
  30 秒超时（宿主超时的 rejection 值是 `undefined`，于是显示成 `undefined`）。
  现在：
  - 按当前编辑器优先使用 **`eda.sch_ManufactureData.getBomFile`**（原理图 BOM 导出），
    再试 `eda.pcb_ManufactureData.getBomFile`；
  - 每次导出调用都被 `withTimeout()` 限时 7 秒，超时/失败立即回退到原理图读取，
    绝不再让面板整体卡死；
  - 失败原因写进页签警告，页脚显示实际来源（`sch` / `pcb` / 原理图）。
- 桥接错误信息改为带方法名与超时秒数（例如
  `EDA 消息总线调用失败（eda.bom）：宿主在 45 秒内没有响应…`），并新增 `TIMEOUT`
  错误码提示，不再出现 `undefined`。
- 新增 `src/tests/unit/bom-scan.test.js`：覆盖导出接口优先顺序、挂起导出限时回退、
  无接口时的显式报错。

## 3.0.2

### 新增

- **当前工程 BOM 对比**：改用 EDA 制造数据接口
  `pcb_ManufactureData.getBomFile(name, 'csv')` 导出整份工程 BOM（覆盖全部图页，
  不依赖图页是否已加载），解析 CSV（位号/数量/立创编号/名称/型号/封装）后按 C 编号
  归并，再逐行对比 Odoo 实时可用库存；导出不可用时自动回退原理图读取。
  BOM 页签默认范围改为「当前工程 BOM」，并显示数据来源。
- **一键出库**：BOM 对比结果页新增「一键出库」。按领用人 + 项目，把每个型号的需求量
  按袋 FIFO 分配到具体 `bag_id`（先预览分配计划，库存不足则一行都不扣），确认后调用
  真实 `/lab/api/inventory/issue` 生成领用单，幂等 `request_key` 防止重复扣减。
- 新增共享逻辑 `parseBomCsv`、`allocateBags`（`src/shared/bom.js`）与桥接方法
  `eda.bom`、`inventory.outbound`（支持 `dry_run` 预演）。
- **Apple 液态玻璃视觉**：多层渐变网格背景、半透明毛玻璃面板/页签/表格/弹窗、
  胶囊按钮与分段控件、深色玻璃模式、`prefers-reduced-motion` 适配。

### 修复

- 登录会话在切换菜单后失效：宿主每次点击菜单都会重新执行整份 bundle，模块级状态被
  清空。现在把运行时（配置、会话客户端、配对码、桥接）挂在
  `globalThis.__LAB_ODOO_V3_RUNTIME__`，登录在多个菜单之间保持，密码/会话 Cookie
  仍然不写入 `sys_Storage`。

## 3.0.1

### 修复

- 修复真机点击「库存联动」菜单后面板打不开：EDA 宿主把扩展入口包在
  `new Function('sandbox', 'with (sandbox) { ... }')` 里执行，扩展 API 只以
  `eda` 这个注入绑定存在；3.0.0 读取的是 `globalThis.eda`（真实宿主不设置），
  因此每次菜单调用都在 `getEda()` 处抛「未检测到 EDA 扩展 API」，`openIFrame`
  从未被调用。现在统一通过 `resolveEda()` 优先使用注入绑定，`globalThis.eda`
  仅作为测试/独立环境的兜底。
- 同步修正 `transport.js`、`panel.js`、`index.js` 的 API 解析；`detectSdk()`
  在真实宿主里也能正确报告 SDK 能力。
- 新增回归测试 `src/tests/package/entry-host.test.js`：按宿主的方式
  （`with (sandbox)`、屏蔽 `window/document`、不设 `globalThis.eda`）执行构建产物，
  断言菜单能打开面板且私有 MessageBus 桥接可用。

## 3.0.0

### 重写

- 从旧 FastAPI/Bearer 协议迁移到 Odoo 19 JSON-RPC 会话协议。
- 移除旧版硬编码 `admin/admin123` 登录和旧 `lab_inventory_token`。
- 身份改为契约规定的 `lcsc:C123` / `lab:42`，不再使用 `LAB-` 内部码。
- 源码重组为 `src/main`、`src/iframe`、`src/shared`、`src/tests`、`src/scripts`。
- 保留 extension UUID `1329a87d576b4b8cbb8592b1c1012b8b`，版本升为 3.0.0。

### 新增

- 默认改为「EDA → 本机 relay → Odoo」；relay 用原生 node:http/https 管理 CookieJar，解决真实 Cookie 与跨域。
- 本机 relay 只绑定 127.0.0.1:49621，随机配对码仅内存，固定上游 `http://lc.rm.com` / `LcHardwareHouse`，接口 allowlist、无开放代理/重定向、请求/响应限制。
- 直接 Odoo 模式保留为高级选项；登录后强制探测 `session_id`，不伪造登录状态，不再尝试设置 Cookie 头。
- 统一器件库检索、分页、分类、详情、参数、图片、实时库存、库位、袋/批次、未归还记录。
- BOM 只读数量对比（选中器件 / 当前图页 / 已加载图页）。
- 袋码/库位码/SN/C 编号/立创原厂袋二维码解析。
- 按袋入库、按系统账号 + 项目领用、按原 `issue_line_id` 归还。
- 确认弹窗、请求号幂等、网络超时用同一请求号重试、`replayed` 标识。
- iframe 优先使用官方私有 `SYS_MessageBus.rpcService/rpcCall`，nonce 校验；同源父桥保留。
- 删除 sys_Storage RPC 队列，密码/配对码/登录不落盘；sys_Storage 只传初始化 nonce 和非敏感配置。
- 外部商城图片转换为 Odoo `/lab/api/asset?url=`，经 relay 带会话取回；兼容 catalog detail 的许多2one袋/领用形状。
- `/web/session/destroy` 无 result 的现网返回已兼容。
- 诊断日志脱敏、SDK 能力面板、错误码中文提示。
- 真实 Node 测试、确定性 ZIP 打包、包内容校验。

### 已知限制

- EDA `getAll('part', true)` 只覆盖已加载图页；未打开图页不计入 BOM。
- 直接 Odoo 模式仍依赖 EDA 客户端保留 Cookie，生产推荐本机 relay。
- 未安装真实 EDA、未执行生产库存写操作。
- 标签 PDF/二维码仍由 Odoo 现有功能生成，插件不生成前端二维码。
