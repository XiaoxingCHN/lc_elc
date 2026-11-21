# EDA3.1.0维护

## 源与运行时

src/main是EDA入口，src/iframe是业务面板，scripts/build.mjs负责构建eext/bundle，bridge/server.mjs是零npm第三方运行依赖的本机桥接。桥接不是Python/PyInstaller。

Windows runtime为bridge/runtime/node.exe v24.19.0（92825416字节），匹配NODE-LICENSE.txt。hash `3602f2bb1a10f2cbab4c36886218a33c1ab3db87290e73b033c46c77147d0237`。从已核对当前bundle提取bridge/runtime即可恢复同字节；_reference的24.13.0不是当前版本。Linux启动脚本需Linux Node≥20.5，Windows exe不能用于Linux。

构建依赖package-lock.json锁定esbuild0.25.10、jszip3.10.1及完整registry URL/integrity。当前node_modules已本地保留但Git排除；联网机器从本目录运行 `npm ci --cache ../../dependencies/npm-cache --no-audit --no-fund` 可获取。离线恢复必须先有完整npm缓存，不能把‘有node_modules’写成‘npm ci --offline通过’。本次新缓存准备遇到网络超时，CURRENT_STATE会保留实际结果。

## 测试与构建

```sh
npm ci --cache ../../dependencies/npm-cache --no-audit --no-fund
npm test
npm run test:package
npm run verify
```

build会清空本组件build/dist，属于生成物；当前release在独立releases目录，不能覆盖。构建前冻结source manifest，修改package.json与extension.json版本要一致。

既有日志105单测/13包测试通过；本次归档会从新路径重新执行可执行检查，具体本轮结果另记录。实际EDA宿主导入交互不因Node单测通过就算实机重测。

## 成品与权限边界

当前eext SHA `69665cbf3fac0732db7f6b01188014ac773dbc3d43e12062e8ffd039016998ef`，完整bundle SHA `5b48babfe8cb365c30588f79bb6e1c549769899ee95d75dabde4a6328cbf784b`。

桥接仅监听127.0.0.1，启动生成配对码，服务器会话保留桥接内部，不把cookie交给EDA。写库存前需要确认和服务端权限，不用插件UI隐藏替代后端鉴权。默认IP/DB仅为旧环境定位，迁服务器需同时维护bridge配置和集成验收。

### 登录凭证持久化（3.2.0 起）

插件端（`src/`）仍然**不存密码**：`sys_Storage` 只有明文键值，没有加密能力，自加密等于没加密，也违反「凭据使用 OS 安全存储」。

凭证由**本机桥接**持有，落在 `bridge/lab-credentials.dat`，内容为 Windows DPAPI 加密后的 JSON（`{version, upstream, db, login, password, cookies, uid, savedAt}`）。cookie 与密码放在同一个加密文件里，因为 Odoo 的 `session_id` 本身就是 bearer 凭证，只加密一个没有意义。

- DPAPI 绑定当前 Windows 账户：文件被拷到别的机器、或被别的账户打开都解不开。启动时解密失败要**明确报错**，不静默降级为「未登录」。
- **它防不住以同一 Windows 账户身份运行的其他程序。** 这与 Chrome/Edge 保存密码同一水位，UI 与文档都不许宣称「绝对安全」。
- 非 Windows 平台（Linux 桥接）不实现密码存储，`saveCredentials` 返回 `unsupported_platform`，退回手动登录。
- 桥接启动时探测 PowerShell 是否可用；不可用则禁用持久化并记 `credentials.unavailable`，其余功能不受影响。
- `--no-save-credentials`（或环境变量）启动时不读写任何凭证文件，供公用机器使用。
- **注销会删除保存的密码**（保留 upstream/db/login），这是「注销」应有的语义。
- 日志只记事件名与 `uid`/`db`/`restored`；绝不输出密码、cookie 值、`.dat` 内容或 DPAPI blob。

## 职责边界与其它端分工

插件定位是画图助手，不是第二个库存系统。保留：器件库（轻量查件）、原理图库存（选中器件/工程 BOM/图页的可用量、库位、袋码）、一键出库（原理图库存页内）、连接/账户、诊断。

入库（含制袋贴标）、单件领用、按原领用单归还、扫码追溯只在 Odoo 网页端和 Flutter 客户端实现；3.1.0 已从插件移除对应菜单、页签、渲染函数与 state。不要为了“顺手”把写库存状态机加回 iframe：三套状态机是本轮 H1/H2（误报成功、重复领用）的来源。桥接协议 `src/main/api.js` 仍保留 receipt/issue/returnStock 等封装，供其它用途与历史兼容，但 iframe 不再调用；新增 UI 若需要写库存，只能走已确认的一键出库路径并保持四态结果（SUCCESS/RECONFIRM/UNKNOWN/FAILED）。等效库存/替代件是另一项改动，不在本页签的职责内。

### 等效件（S5，3.2.0 起）

「原理图库存」页签的缺料行下会挂一个可展开的等效候选栏。规则：

- 主匹配永远是 C 编号；等效候选**单独一栏**，不混进主行。
- 硬冲突（容值/阻值不同、耐压或功率低于需求、工作电压区间覆盖不了需求）的候选由服务端**直接丢弃**，不下发、不可勾选。
- 「耐压」与「工作电压」是两条不同规则：前者是单值上限（越高越好），后者是区间（必须完整覆盖）。合并成一条会让 `2.0V~2.5V` 冒充 `1.71V~3.63V`。
- 参数不足时退化为「同封装 + 同类别」，标 `confidence: 'weak'`，UI 显式提示依据较弱。
- **绝不自动替换**：默认出库只含 C 编号精确匹配的行；勾选替代后才进入分配，并在领用备注写明 `C14663 → C1525 替代`。
- 判定逻辑在 `lab_inventory/tools/equivalent_match.py`（纯逻辑，可离线测试），检索在 `lab.catalog.item.equivalents()`。
