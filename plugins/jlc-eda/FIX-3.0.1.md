# 3.0.1 修复记录：插件界面打不开

日期：2026-10-18
适用版本：lab-inventory-odoo 3.0.0 → 3.0.1（UUID 不变，扩展管理器按同一扩展升级）

## 1. 现象

在真实嘉立创 EDA 专业版 3.2.149 中启用扩展后，点「库存联动」下的任意菜单（器件库与库存、BOM 对比、入库、领用、归还、追溯、连接与账户、诊断日志）都没有面板弹出，等于插件界面打不开。

## 2. 根因

EDA 扩展宿主（`resources/app/assets/pro-api/0.2.53.aee2f57a/api.js` 的 `og()`）这样执行扩展入口：

```js
// pro-api api.js —— 实际宿主代码（节选）
function ag(e) {
  e = `with (sandbox) {/**/ ${e} /**/}`;
  const t = Object.getPrototypeOf(async () => {}).constructor; // Function
  const i = t('sandbox', e);                                  // new Function('sandbox', code)
  ...
}

async function og(e, t) { // e = 已编译的入口函数, t = 扩展 UUID
  let n = {
    document: void 0, window: void 0, self: void 0, location: void 0,
    navigator: void 0, localStorage: void 0, sessionStorage: void 0,
    postMessage: void 0, fetch: () => Promise.reject(...), alert: () => {},
    eda: new tg(t || bl()),          // ← 扩展 API 只以 `eda` 绑定注入
    EDMT_...: ..., ESYS_...: ...     // enum
  };
  ...
  window.top._EXTAPI_SCRIPT_SPACES_[t] ||= i ? s : r;
  await e(window.top._EXTAPI_SCRIPT_SPACES_[t]);   // with(sandbox) 执行入口
}
```

结论：

1. 入口 bundle 在 `with (sandbox)` 里执行，扩展 API 是 **裸 `eda` 绑定**；宿主没有设置 `window.eda` / `globalThis.eda`。全量检索 EDA 3.2.149 的 `resources/app/assets`，没有任何 `window.eda =` 赋值。
2. iframe 面板是另一回事：宿主 `SYS_IFrame.openIFrame` 实现里显式把 `eda` 与 `E***` enum 赋给 iframe 的 `contentWindow`（`for (I of keys) S.contentWindow[I] = window._EXTAPI_SCRIPT_SPACES_[uuid][I]`），所以面板 iframe 里 `window.eda` 存在。
3. 旧版 v2.0.1（真机可用）在入口里用的是裸 `eda`（例如 `eda.sys_ClientUrl.request(...)`），其 iframe 页面用 `typeof eda !== 'undefined' || window.parent.eda`。

3.0.0 的入口却统一写成 `globalThis.eda`（`src/main/eda.js` 的 `getEda()/toast()`、`index.js` 的 `detectSdk()`、`panel.js` 的 `openOdooAction()/installBridge()`、`transport.js` 的兜底）。真实宿主里它是 `undefined`，于是：

```text
menuAction(showInventoryPanel)
  → openTab() → ensureRuntime() → resetRuntime() → getEda()
  → throw ApiError(EDA_CONTEXT, '未检测到 EDA 扩展 API…')
  → menu.failed → toast('器件库与库存打开失败：…')
  → installBridge/openPanel 从未执行，openIFrame 从未调用 → 界面打不开
```

### 为什么 3.0.0 的自动化测试没发现

`review/browser-smoke.mjs` 仿真的父层直接执行 `window.eda = eda`（第 379 行；另有 `globalThis.eda = {...}`），而真实宿主不这么做。因此 61/62 项 UI 检查全部建立在错误前提上；3.0.0 的 93 项单元测试也只覆盖注入参数，不覆盖宿主执行方式。

### 复现证据（3.0.0 构建产物，按宿主方式执行）

用 `new Function('sandbox', 'with (sandbox) { <dist/index.js> }')` + 只注入裸 `eda`、不设 `globalThis.eda`：

```text
[lab-inventory-v3] WARN config.load_failed { message: '未检测到 EDA 扩展 API，请在嘉立创 EDA 专业版中运行本插件。' }
[lab-inventory-v3] ERROR menu.failed { name: '器件库与库存', code: 'EDA_CONTEXT', message: '未检测到 EDA 扩展 API…' }
openIFrameCalls: 0
```

与真机现象一致。

## 3. 修复

新增 `src/main/eda.js#resolveEda()`：**优先使用宿主注入的裸 `eda` 绑定**，`globalThis.eda` 只作为单元测试/独立浏览器的兜底。

```js
export function resolveEda() {
  try {
    if (typeof eda !== 'undefined' && eda) return eda;   // 宿主 with(sandbox) 注入
  } catch (_) { /* 不在宿主作用域 */ }
  try {
    if (typeof globalThis !== 'undefined' && globalThis.eda) return globalThis.eda; // 测试兜底
  } catch (_) {}
  return null;
}
```

所有原来读 `globalThis.eda` 的位置改为 `resolveEda()`：

| 文件 | 位置 |
| --- | --- |
| `src/main/eda.js` | `getEda()`、`toast()` |
| `src/main/index.js` | `detectSdk()` |
| `src/main/panel.js` | `openOdooAction()`、`installBridge()` 兜底 |
| `src/main/transport.js` | `createSdkTransport()` 兜底 |

## 4. 回归测试（新增）

`src/tests/package/entry-host.test.js` 按真实宿主方式执行构建后的 `dist/index.js`：

- `new Function('sandbox', 'with (sandbox) { <bundle> ... }')`；
- sandbox 把 `document/window/self/location/navigator/localStorage/sessionStorage/postMessage` 置为 `undefined`，`fetch` 置为拒绝；
- 只注入裸 `eda`，并删除 `globalThis.eda`；
- 断言：6 个菜单各自恰好调用 1 次 `openIFrame('/iframe/app.html', …, 'labOdooV3Panel')`、无错误 toast、私有 MessageBus 注册 `lab.odoo.v3.rpc`；
- 断言：写入 `lab_odoo_v3_panel_payload` 的 nonce 可被桥接接受，`app.init` 返回 `ok:true`、版本一致、`sdk.available/iframe/messageBus` 均为 true；错误 nonce 被拒绝。

## 5. 验证结果

| 验证 | 结果 |
| --- | --- |
| `npm test` | 93 pass / 0 fail |
| `npm run test:package`（构建 + 包测试 + 新增回归） | 13 pass / 0 fail |
| `npm run verify` | PACKAGE VERIFY OK |
| 宿主模拟（Node，with(sandbox)） | `openIFrame` 1 次、无 toast、`app.init` ok、版本 3.0.1 |
| 浏览器模拟（Edge 无头，页面内 `with(sandbox)` 执行入口、真实 iframe、注入 `eda` 到 contentWindow） | 面板打开并渲染：标题、v3.0.1、状态栏、8 个页签、登录门禁；无脚本错误。截图 `release-20261018-fix/screenshots/panel-opened-3.0.1.png` |

浏览器模拟脚本与 `review/browser-smoke.mjs` 的区别：不再给父层设 `window.eda`，入口只在 `with(sandbox)` 里拿到裸 `eda`，iframe 才通过宿主的注入方式拿 `window.eda`，与真实宿主一致；同时删除父层 `__LAB_ODOO_V3_BRIDGE__`，强制面板走私有 MessageBus（真机跨 realm 下的实际路径）。

## 6. 交付物

- `release-20261018-fix/lab-inventory-odoo_v3.0.1.eext`
  - 93,705 字节；SHA-256 `a7631ddeeac6258700a7b582c7c80a3ee2b60409ba10914b88772d419006da33`
- `release-20261018-fix/lab-inventory-odoo_v3.0.1-bundle.zip`
  - 92,959,589 字节；SHA-256 `cbab5dc34b539bc1197f1354117b985914f9525be79fd6ecdca509196b401345`
- `release-20261018-fix/release-manifest.json`、`SHA256.txt`、`修复说明.md`、`screenshots/panel-opened-3.0.1.png`

## 7. 仍需真机确认

本地已按宿主实现方式做等价验证，但仍需在真实 EDA 中导入 3.0.1 确认：

1. 扩展管理器导入 `lab-inventory-odoo_v3.0.1.eext`（同 UUID，按升级）；启用并开启「外部交互」。
2. 点「库存联动 → 器件库与库存」，面板应立即弹出并显示登录门禁。
3. 若仍失败：打开「诊断」页签导出诊断日志（菜单本身不需要登录即可打开面板）。

## 8. 附：宿主关键代码定位

- 扩展入口执行：`resources/app/assets/pro-api/0.2.53.aee2f57a/api.js` 的 `ag()` / `og()`（`with (sandbox)`、`window: void 0`、`eda: new tg(...)`）。
- 菜单回调：同文件 `Sa()` 在 bundle 末尾追加 `if (typeof <fn> === 'function') … else if (edaEsbuildExportName…) …`。
- iframe 打开与 `eda` 注入：`resources/app/assets/pro-ui/3.2.149.43637efe/js/ui.js` 的 `UL.openIFrame` / `iframeDialog`（`S.contentWindow[I] = window._EXTAPI_SCRIPT_SPACES_[uuid][I]`）。
- iframe 文件解析：`UL.getHtmlData` / `getFileData`（`uuid|iframe/app.html`，`xcr()` 去掉前导 `/`）。
