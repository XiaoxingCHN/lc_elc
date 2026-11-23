# 变更日志

## 4.2.0

- **出库未决锁**：结果未知的出库（超时、断网、响应丢失）写入本机配置并在重开面板后恢复。重新读取、切换范围、仅刷新都不会清掉它，新的出库被阻止；只能「原样重试（同一请求号）」或以核对为前提「核对后放弃」。记录按服务器地址与登录用户隔离，不含密钥。
- **主按钮对比度**：新增 `--primary` / `--primary-hover` / `--on-primary` 成对令牌。深色 `#C9FF3F` 配 `#0A0D06`（16.64:1），浅色 `#3D7A00` 配 `#FFFFFF`（5.27:1），替换白字压蓝色渐变（深色最低 1.83:1）。
- **文案与导航**：连接入口统一为「连接设置」，删除与页签重复的头部按钮；未连接页与网络提示改为密钥连接的说法，不再提已移除的本机桥接与配对码。
- **BOM 表格**：「需求/可用/缺口」列不再逐字断行，表头不换行，窄窗口由表格容器横向滚动承担。
- **可读性与焦点**：信息性小字提升到 12 px；确认弹窗带 `aria-labelledby`，初始焦点落在第一个输入或「取消」，Tab/Shift+Tab 限制在弹窗内，Esc 关闭并把焦点还给触发控件。

## 4.1.4

- 原理图同编号器件保留已有的值和封装，支持带尺寸的贴片封装写法。
- 替代料按实验室 SN 展示，长位号在单元格内换行，查询结束后提示未匹配的行。
- 通过解包后的扩展在模拟 EDA 宿主中测试读取、请求、候选展开和勾选。

## 3.2.0

### 免登录（凭证存在桥接，不在插件）

以前每次重开 EDA 都要重新输密码，因为桥接的 Odoo `session_id` cookie 和插件的
`globalThis` 运行时**两处都是内存态**。现在：

- 桥接新增 `POST /session/restore`：先把上次的 cookie 灌回 jar 并探测
  `/web/session/get_session_info`；有效就直接登录，失效就用保存的密码自动重登，
  都失败返回 `restored: 'none'`，插件照常显示登录表单。
- 凭证落在 `bridge/lab-credentials.dat`，内容是 **Windows DPAPI 加密**后的 JSON
  （cookie 与密码同一个文件——`session_id` 本身就是 bearer 凭证）。
- 「注销」会**删除保存的密码**，下次必须手动输。
- `--no-save-credentials` 启动参数不读写任何凭证文件，供公用机器。
- 非 Windows（Linux 桥接）不存密码，退回手动登录。
- 插件端仍然一个密码都不碰：`sys_Storage` 只有明文键值，自加密等于没加密。

DPAPI 防的是「文件被拷到别的机器 / 别的账户读取」，**防不住以同一 Windows 账户
身份运行的其他程序**。这与浏览器保存密码同一水位。

### 等效件（S5 同型号不同编号）

BOM 缺料时，不再只是显示「缺料」了事——会列出实验室里规格相符、只是 C 编号/
品牌不同的器件，供操作员勾选替换。

- 服务端新增 `/lab/api/catalog/equivalents`，**一次请求处理整张 BOM**，共享一次
  库存快照（100 行不会触发 100 次 quant 查询）。
- 判定：容值/阻值不同，或耐压/功率**低于**需求 → 硬冲突，**直接丢弃不展示**
  （一个 25V 电容摆在 50V 需求旁边，即使标灰也迟早被误勾）。
- 参数不足时退化为「同封装 + 同类别」，标 `confidence: 'weak'` 并显式提示依据较弱。
- 候选必须有可用库存，没库存的不展示。
- **绝不自动替换**：默认出库只含 C 编号精确匹配的行；勾选后才进入分配，领用备注
  写明 `C14663 → C1525 替代`。
- 主表列定义与 C 编号精确匹配逻辑完全不变（S5 规则 1）。

### 版本

`package.json`、`extension.json`、`src/main/index.js`、`src/iframe/app.js` 的
VERSION 统一为 3.2.0。

## 3.1.0

### 定位调整：画图助手

插件只在画原理图/PCB 时提供价值：查这个器件有没有库存、有的话在哪个库位和袋、整张 BOM 一键出库。

### 移除

- **入库（receipt）、手动领用（issue）、归还（return）、袋/库位追溯（trace）四个页签与菜单。**
  这些能力在 Odoo 网页端和 Flutter 客户端已经完整存在，在 EDA 里重复实现等于维护三套
  写库存状态机，也是误报成功与重复领用的来源。
- 移除对应 `renderReceipt` / `renderReceiptSuccess` / `queryReceiptItem` /
  `buildReceiptPayload` / `submitReceipt`、`renderIssue` / `renderIssueSuccess` /
  `prefillIssueBag` / `resolveIssueBag` / `buildIssuePayload` / `submitIssue`、
  `renderReturn` / `renderReturnSuccess` / `loadReturnIssues` / `buildReturnPayload` /
  `submitReturn`、`renderTrace` / `resolveTrace`，以及 `state.receipt` / `state.issue` /
  `state.return` / `state.trace`。
- `extension.json` 删除 `openReceipt`、`openIssue`、`openReturn`、`openTrace` 菜单
  （含 PCB 菜单的 `openTrace`）；`src/main/index.js` 删除同名导出。

### 变更

- **「BOM 对比」改名「原理图库存」**：菜单标题、页签、页面标题同步；说明改为
  “选中器件后可直接查看库存与库位”。
- **默认范围改为「选中器件」**（原为「当前工程 BOM」），仍保留工程 BOM / 当前图页 /
  已加载图页三个选项。
- **对比结果新增「袋」列**：在「库位」之后显示该行袋追溯码，最多 3 个，超出显示
  `+N`；复制对比表（TSV）与导出 CSV 同步增加该列。
- 保留「器件库」「原理图库存」「连接/账户」「诊断」四个页签；「一键出库」仍在
  原理图库存页内，行为不变。
- 器件详情页移除「入库此器件」按钮与袋列表的「领用」按钮，改为提示到网页端/客户端办理。

### 版本

- `package.json`、`extension.json`、`src/iframe/app.js` 的 VERSION 统一为 3.1.0。

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
