import { createBridge, readPanelPayload } from './bridge-client.js';
import { parseItemKey, normalizeCatalogCode } from '../shared/codes.js';
import {
  createDraft,
  withPayload,
  beginSubmit,
  markSuccess,
  markFailure,
  defaultKeyFactory,
} from '../shared/idempotency.js';
import { groupBom, compareLine, summarize, bomTsv, BOM_STATUS } from '../shared/bom.js';
import {
  bagAvailableQuantity,
  bagLocationName,
  bagLotName,
  issueBagName,
  issueBorrowerName,
  locationSummary,
} from '../shared/detail.js';

const VERSION = '3.0.3';

const TABS = [
  { id: 'inventory', label: '器件库' },
  { id: 'bom', label: 'BOM 对比' },
  { id: 'receipt', label: '入库' },
  { id: 'issue', label: '领用' },
  { id: 'return', label: '归还' },
  { id: 'trace', label: '追溯' },
  { id: 'settings', label: '连接/账户' },
  { id: 'diagnostics', label: '诊断' },
];

const ERROR_HINTS = {
  SESSION_REQUIRED: '请先到「连接/账户」登录 Odoo。',
  SESSION_EXPIRED: '会话已失效，请重新登录；插件不会保存密码。',
  SESSION_COOKIE_UNAVAILABLE:
    '直接连接没有保持登录会话。请改用默认的「本机桥接」，或联系管理员确认客户端设置。',
  INVALID_CREDENTIALS: '请检查数据库名、登录名和密码；若账号启用两步验证，请先在 Odoo 网页端处理。',
  NETWORK_OR_CORS:
    '无法连接。使用本机桥接时请确认桥接窗口仍打开；直接连接时请检查 Odoo 地址和网络。',
  FORBIDDEN: '当前账号缺少 lab 权限组（user/operator/manager），请联系库存管理员。',
  AMBIGUOUS_MATERIAL: '同一 C 编号有多个实验室档案，请明确选择 SN；插件不会自动取第一个。',
  CONFLICT: '请求号已用于不同内容。请确认当前表单后重新提交（插件会生成新请求号）。',
  TIMEOUT_AMBIGUOUS: '请求超时，服务器可能已处理。写操作请使用同一请求号重试，服务端会按幂等键返回原结果。',
  EXTERNAL_INTERACTION_DISABLED: '请在 EDA 扩展管理器中启用本扩展的「外部交互」权限。',
  RELAY_AUTH: '配对码不正确或已变化，请重新复制本机桥接窗口中的配对码。',
  RELAY_UNAVAILABLE: '本机桥接未启动或已关闭。请双击压缩包里的「start-windows.cmd」并保持窗口打开。',
  NOT_FOUND: '服务器没有找到该对象，请刷新后重试。',
  VALIDATION_ERROR: '请按提示修正输入。',
  HTTP: '服务器返回了异常状态，请查看诊断日志。',
  PARSE: '服务器响应不是预期 JSON，请检查地址、数据库和反向代理。',
  UNEXPECTED_ENVELOPE: '接口返回结构异常，请把诊断日志交给管理员。',
  BRIDGE: '面板与扩展主模块通信失败，请从 EDA 菜单重新打开面板。',
  TIMEOUT:
    '扩展主模块在限定时间内没有返回。常见原因：EDA 正在等待某个对话框、当前编辑器不支持该操作，或读取工程 BOM 超时。请重新点击一次；BOM 页签会自动改用原理图读取。',
  EDA_CONTEXT: '当前 EDA 环境不支持该操作，请在原理图编辑器中重试。',
};

const state = {
  bridge: null,
  payload: null,
  init: null,
  tab: 'inventory',
  session: { active: false, uid: null, sessionMode: 'none' },
  sessionError: null,
  bootstrap: null,
  bootstrapError: null,
  bootstrapLoading: false,
  inventory: {
    initialized: false,
    loading: false,
    query: '',
    stockOnly: false,
    categoryId: '',
    cursor: null,
    items: [],
    total: 0,
    next: null,
    error: null,
    categories: [],
    detail: null,
    detailError: null,
    detailLoading: false,
  },
  bom: {
    scope: 'project',
    loading: false,
    refreshing: false,
    scan: null,
    warnings: [],
    rows: [],
    summary: null,
    unmapped: [],
    error: null,
    outbound: { computing: false, submitting: false, plan: null, shortage: null, error: null, result: null },
  },
  receipt: {
    itemKey: '',
    detail: null,
    detailError: null,
    detailLoading: false,
    locationId: '',
    quantity: '1',
    supplierQr: '',
    note: '',
    templateId: '',
    draft: null,
    submitting: false,
    success: null,
    error: null,
  },
  issue: {
    borrowerId: '',
    project: '',
    bagRaw: '',
    bagInfo: null,
    bagError: null,
    loadingBag: false,
    lines: [],
    note: '',
    draft: null,
    submitting: false,
    success: null,
    error: null,
  },
  return: {
    issues: [],
    query: '',
    cursor: null,
    next: null,
    loading: false,
    selected: null,
    quantity: '',
    note: '',
    draft: null,
    submitting: false,
    success: null,
    error: null,
  },
  trace: { raw: '', loading: false, result: null, error: null },
  settings: {
    mode: 'relay',
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: '',
    hasPairingToken: false,
    serverUrl: '',
    db: '',
    login: '',
    password: '',
    busy: false,
    message: null,
    error: null,
  },
  diagnostics: { loading: false, data: null, error: null },
};

const dom = {
  version: document.getElementById('version'),
  statusLine: document.getElementById('status-line'),
  tabs: document.getElementById('tabs'),
  banner: document.getElementById('banner'),
  view: document.getElementById('view'),
  toasts: document.getElementById('toasts'),
  modalRoot: document.getElementById('modal-root'),
  btnSettings: document.getElementById('btn-settings'),
  btnDiagnostics: document.getElementById('btn-diagnostics'),
};

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'value' && 'value' in node) node.value = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === undefined || child === null || child === false) continue;
    if (Array.isArray(child)) append(node, child);
    else if (child instanceof Node) node.appendChild(child);
    else node.appendChild(document.createTextNode(String(child)));
  }
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function fmtQty(value) {
  if (value === null || value === undefined || value === '') return '未知';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number - Math.round(number)) < 1e-9) return String(Math.round(number));
  return String(Math.round(number * 1000) / 1000);
}

function fmtDate(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').slice(0, 19);
}

function shortKey(key) {
  if (!key) return '';
  return key.length <= 14 ? key : key.slice(0, 8) + '…' + key.slice(-4);
}

function codeOf(item) {
  return (item && (item.catalog_code || (item.item_key || '').replace(/^lcsc:/, ''))) || '';
}

function copyText(text, okMessage = '已复制') {
  const value = String(text ?? '');
  const done = () => toast(okMessage, 'ok');
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    navigator.clipboard.writeText(value).then(done).catch(() => fallbackCopy(value, done));
  } else {
    fallbackCopy(value, done);
  }
}

function fallbackCopy(value, done) {
  const area = el('textarea', { style: 'position:fixed;left:-9999px;top:0' }, value);
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand('copy');
    done();
  } catch (_) {
    toast('复制失败，请手动选择文本。', 'error');
  } finally {
    document.body.removeChild(area);
  }
}

function toast(message, kind = 'info', ms = 4200) {
  const item = el('div', { class: 'toast ' + (kind === 'error' ? 'error' : kind === 'warn' ? 'warn' : kind === 'ok' ? 'ok' : '') }, message);
  dom.toasts.appendChild(item);
  setTimeout(() => {
    if (item.parentNode) item.parentNode.removeChild(item);
  }, ms);
}

function showBanner(message, kind = 'info') {
  dom.banner.hidden = false;
  dom.banner.className = 'banner ' + kind;
  dom.banner.textContent = String(message);
}

function hideBanner() {
  dom.banner.hidden = true;
  dom.banner.textContent = '';
}

function hintFor(error) {
  return (error && ERROR_HINTS[error.code]) || (error && error.action === 'relogin' ? ERROR_HINTS.SESSION_EXPIRED : '');
}

function errorBox(error, options = {}) {
  const box = el('div', { class: 'error-box' });
  append(box, [
    el('div', { class: 'code' }, (error && error.code) || 'UNKNOWN'),
    el('div', { class: 'msg' }, (error && error.message) || String(error || '未知错误')),
  ]);
  const hint = hintFor(error);
  if (hint) box.appendChild(el('div', { class: 'hint' }, hint));
  if (error && error.fields && Object.keys(error.fields).length) {
    box.appendChild(el('details', {}, [el('summary', {}, '错误字段'), el('pre', {}, JSON.stringify(error.fields, null, 2))]));
  }
  if (options.retry) {
    box.appendChild(
      el('div', { class: 'row', style: 'margin-top:8px' }, [
        el('button', { class: 'btn', type: 'button', onclick: options.retry }, options.retryLabel || '重试'),
      ]),
    );
  }
  return box;
}

function confirmModal(title, content, confirmText = '确认提交') {
  return new Promise((resolve) => {
    const mask = el('div', { class: 'modal-mask' });
    const close = (value) => {
      if (mask.parentNode) mask.parentNode.removeChild(mask);
      document.removeEventListener('keydown', onKey);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') close(false);
    };
    const confirm = el('button', { class: 'btn primary', type: 'button' }, confirmText);
    confirm.addEventListener('click', () => close(true));
    const cancel = el('button', { class: 'btn', type: 'button' }, '取消');
    cancel.addEventListener('click', () => close(false));
    const modal = el('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' }, [
      el('h3', {}, title),
      el('div', { class: 'modal-body' }, content),
      el('div', { class: 'modal-actions' }, [cancel, confirm]),
    ]);
    mask.appendChild(modal);
    dom.modalRoot.appendChild(mask);
    document.addEventListener('keydown', onKey);
    confirm.focus();
  });
}

function section(title, children) {
  return el('section', { class: 'panel' }, [el('h2', {}, title)].concat(children));
}

function table(headers, rows, options = {}) {
  const head = el('tr', {}, headers.map((header) => el('th', { class: header.num ? 'num' : '' }, typeof header === 'object' ? (header.label ?? '') : header)));
  const body = rows.map((row) =>
    el('tr', {}, row.map((cell, index) => el('td', { class: headers[index] && headers[index].num ? 'num' : '' }, cell))),
  );
  return el('div', { class: 'table-wrap ' + (options.class || '') }, el('table', {}, [el('thead', {}, head), el('tbody', {}, body)]));
}

function field(labelText, input, hint) {
  return el('label', {}, [el('span', {}, labelText), input, hint ? el('span', { class: 'muted' }, hint) : null]);
}

function nav(tab) {
  state.tab = tab;
  render();
}

function isActive() {
  return Boolean(state.session && state.session.active);
}

function loginGate(what) {
  return el('div', { class: 'panel' }, [
    el('h2', {}, '需要登录 Odoo'),
    state.sessionError ? errorBox(state.sessionError) : null,
    el('p', {}, '要使用' + what + '，请先在「连接/账户」中登录。插件只在当前 EDA 会话内保持登录，不保存密码。'),
    el('button', { class: 'btn primary', type: 'button', onclick: () => nav('settings') }, '去登录'),
  ]);
}

async function call(method, params = {}, timeoutMs) {
  if (!state.bridge) throw Object.assign(new Error('桥接未初始化。'), { code: 'BRIDGE' });
  try {
    return await state.bridge.call(method, params, timeoutMs);
  } catch (error) {
    if (error && error.code === 'SESSION_EXPIRED') {
      state.sessionError = error;
      state.session = Object.assign({}, state.session, { active: false, sessionMode: 'none' });
    }
    throw error;
  }
}

function renderTabs() {
  clear(dom.tabs);
  for (const tab of TABS) {
    dom.tabs.appendChild(
      el(
        'button',
        {
          class: 'tab' + (state.tab === tab.id ? ' active' : ''),
          type: 'button',
          role: 'tab',
          'aria-selected': state.tab === tab.id ? 'true' : 'false',
          onclick: () => nav(tab.id),
        },
        tab.label,
      ),
    );
  }
}

function renderStatus() {
  const sdk = (state.init && state.init.sdk) || {};
  const parts = [];
  const connection = (state.init && state.init.connection) || { mode: 'relay', relayUrl: 'http://127.0.0.1:49621' };
  parts.push(connection.mode === 'relay' ? '本机桥接 ' + connection.relayUrl : '直接连接 ' + (state.init && state.init.config ? state.init.config.serverUrl : '未配置'));
  if (connection.mode === 'direct' && state.init && state.init.config && state.init.config.db) parts.push('数据库 ' + state.init.config.db);
  if (isActive()) {
    parts.push('用户 ' + (state.session.name || state.session.username || 'uid ' + state.session.uid));
    parts.push(state.session.sessionMode === 'relay' ? '桥接会话' : '直接会话');
  } else {
    parts.push('未登录');
  }
  if (sdk.clientUrl === false) parts.push('警告：网络接口不可用');
  dom.statusLine.textContent = parts.join(' · ');
}

async function refreshSession() {
  try {
    state.session = await call('session.status');
  } catch (error) {
    state.session = { active: false, uid: null, sessionMode: 'none' };
  }
  renderStatus();
}

async function loadBootstrap() {
  if (!isActive() || state.bootstrapLoading) return;
  state.bootstrapLoading = true;
  try {
    const data = await call('inventory.bootstrap');
    state.bootstrap = data;
    state.bootstrapError = null;
    const borrowers = Array.isArray(data.borrowers) ? data.borrowers : [];
    if (!state.issue.borrowerId) {
      const self = borrowers.find((borrower) => borrower.is_self);
      if (self) state.issue.borrowerId = String(self.id);
      else if (borrowers.length === 1) state.issue.borrowerId = String(borrowers[0].id);
    }
    if (!state.receipt.locationId && Array.isArray(data.locations) && data.locations.length) {
      state.receipt.locationId = String(data.locations[0].id);
    }
  } catch (error) {
    state.bootstrapError = error;
  } finally {
    state.bootstrapLoading = false;
    if (['receipt', 'issue', 'return', 'settings'].includes(state.tab)) render();
  }
}

function ensureBootstrap() {
  if (!isActive() || state.bootstrap || state.bootstrapLoading) return;
  void loadBootstrap();
}

function render() {
  hideBanner();
  clear(dom.view);
  renderTabs();
  renderStatus();
  switch (state.tab) {
    case 'inventory':
      renderInventory();
      break;
    case 'bom':
      renderBom();
      break;
    case 'receipt':
      renderReceipt();
      break;
    case 'issue':
      renderIssue();
      break;
    case 'return':
      renderReturn();
      break;
    case 'trace':
      renderTrace();
      break;
    case 'settings':
      renderSettings();
      break;
    case 'diagnostics':
      renderDiagnostics();
      break;
    default:
      state.tab = 'inventory';
      renderInventory();
  }
  ensureBootstrap();
}

function fatal(message) {
  clear(dom.view);
  dom.statusLine.textContent = '初始化失败';
  dom.view.appendChild(
    el('div', { class: 'panel' }, [
      el('h2', {}, '无法打开库存面板'),
      el('p', {}, message),
      el('p', { class: 'muted' }, '请关闭本窗口，从 EDA 顶部菜单「库存联动」重新打开。'),
    ]),
  );
}

async function init() {
  dom.version.textContent = 'v' + VERSION;
  const payload = readPanelPayload();
  state.payload = payload;
  if (!payload) {
    fatal('未读取到面板初始化数据（sys_Storage 不可用或数据被清除）。');
    return;
  }
  if (payload.tab && TABS.some((tab) => tab.id === payload.tab)) state.tab = payload.tab;
  try {
    state.bridge = createBridge(payload);
  } catch (error) {
    fatal((error && error.message) || '桥接初始化失败。');
    return;
  }
  dom.statusLine.textContent = '已连接（' + state.bridge.mode + '），正在读取配置…';
  try {
    state.init = await call('app.init', {}, 8000);
  } catch (error) {
    fatal((error && error.message) || '读取扩展状态失败。');
    return;
  }
  state.session = state.init.session || { active: false, uid: null, sessionMode: 'none' };
  const config = state.init.config || {};
  const connection = state.init.connection || {};
  state.settings.mode = connection.mode === 'direct' ? 'direct' : 'relay';
  state.settings.relayUrl = connection.relayUrl || 'http://127.0.0.1:49621';
  state.settings.hasPairingToken = Boolean(connection.hasPairingToken);
  state.settings.serverUrl = config.serverUrl || 'http://lc.rm.com';
  state.settings.db = config.db || 'LcHardwareHouse';
  state.settings.login = config.login || '';
  render();
  if (isActive()) {
    await refreshSession();
    void loadBootstrap();
  }
  window.addEventListener('beforeunload', () => {
    if (state.bridge) state.bridge.close();
  });
}

dom.btnSettings.addEventListener('click', () => nav('settings'));
dom.btnDiagnostics.addEventListener('click', () => nav('diagnostics'));

init().catch((error) => fatal((error && error.message) || String(error)));

/* ------------------------------------------------------------------ */
/* Inventory                                                           */
/* ------------------------------------------------------------------ */

function renderInventory() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('器件库与库存'));
    return;
  }
  const inv = state.inventory;

  const searchInput = el('input', {
    type: 'search',
    placeholder: '搜索 C 编号 / 型号 / 名称 / 品牌',
    value: inv.query,
    'aria-label': '搜索器件',
  });
  searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      inv.query = searchInput.value.trim();
      void searchInventory(true);
    }
  });

  const categorySelect = el('select', { 'aria-label': '分类' }, [
    el('option', { value: '' }, '全部分类'),
    ...inv.categories.map((category) =>
      el('option', { value: String(category.id), selected: String(inv.categoryId) === String(category.id) }, category.name || String(category.id)),
    ),
  ]);
  categorySelect.addEventListener('change', () => {
    inv.categoryId = categorySelect.value;
    void searchInventory(true);
  });

  const stockOnly = el('input', { type: 'checkbox', checked: inv.stockOnly });
  stockOnly.addEventListener('change', () => {
    inv.stockOnly = stockOnly.checked;
    void searchInventory(true);
  });

  const searchPanel = el('section', { class: 'panel' }, [
    el('div', { class: 'row' }, [
      el('div', { class: 'grow' }, searchInput),
      el('label', { class: 'check' }, [stockOnly, el('span', {}, '仅看有库存')]),
      categorySelect,
      el('button', {
        class: 'btn primary',
        type: 'button',
        disabled: inv.loading,
        onclick: () => {
          inv.query = searchInput.value.trim();
          void searchInventory(true);
        },
      }, inv.loading ? '查询中…' : '查询'),
    ]),
    el('p', { class: 'muted', style: 'margin-top:8px' }, '库存数量实时从服务器读取；无权限、会话失效、网络错误会显示错误，不会当作 0 库存。'),
  ]);
  dom.view.appendChild(searchPanel);

  if (inv.error) {
    dom.view.appendChild(errorBox(inv.error, { retry: () => searchInventory(true) }));
  }

  if (inv.detailLoading) {
    dom.view.appendChild(el('div', { class: 'panel muted' }, '正在读取器件详情与袋/库位追溯…'));
  } else if (inv.detailError) {
    dom.view.appendChild(el('section', { class: 'panel' }, [el('h2', {}, '器件详情'), errorBox(inv.detailError)]));
  } else if (inv.detail) {
    dom.view.appendChild(renderInventoryDetail(inv.detail));
  }

  const resultPanel = el('section', { class: 'panel' }, [
    el('div', { class: 'row', style: 'justify-content:space-between' }, [
      el('h2', { style: 'margin:0' }, inv.initialized ? '查询结果（' + fmtQty(inv.total) + '）' : '正在加载器件库…'),
      el('span', { class: 'muted' }, inv.items.length ? '已显示 ' + inv.items.length + ' 条' : ''),
    ]),
  ]);

  if (!inv.initialized && inv.loading) {
    resultPanel.appendChild(el('div', { class: 'empty' }, '正在读取器件库…'));
  } else if (inv.initialized && inv.items.length === 0 && !inv.loading) {
    resultPanel.appendChild(el('div', { class: 'empty' }, '没有匹配的器件。可更换关键词，或取消「仅看有库存」。'));
  } else {
    const list = el('div', { class: 'card-list', style: 'margin-top:10px' });
    for (const item of inv.items) list.appendChild(inventoryCard(item));
    resultPanel.appendChild(list);
    if (inv.next) {
      resultPanel.appendChild(
        el('div', { class: 'row', style: 'margin-top:12px;justify-content:center' }, [
          el('button', {
            class: 'btn',
            type: 'button',
            disabled: inv.loading,
            onclick: () => searchInventory(false),
          }, inv.loading ? '加载中…' : '加载更多'),
        ]),
      );
    }
  }
  dom.view.appendChild(resultPanel);

  if (!inv.initialized && !inv.loading && !inv.error) void initializeInventory();
}

function inventoryCard(item) {
  const code = codeOf(item);
  const title = el('div', { class: 'card-title' }, (code ? code + ' · ' : '') + (item.name || item.mpn || '未命名器件'));
  const sub = el('div', { class: 'card-sub' }, [item.mpn || '', item.brand || '', item.package || ''].filter(Boolean).join(' · ') || '无型号/品牌信息');
  const qty = Number(item.lab_quantity) || 0;
  const available = Number(item.lab_available_quantity) || 0;
  const card = el(
    'div',
    {
      class: 'card',
      role: 'button',
      tabindex: '0',
      onclick: () => openInventoryDetail(item.item_key),
      onkeydown: (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openInventoryDetail(item.item_key);
        }
      },
    },
    [
      title,
      sub,
      el('div', { class: 'card-foot' }, [
        el('div', {}, [
          el('span', { class: 'qty ' + (qty > 0 ? '' : 'zero') }, fmtQty(qty)),
          el('span', { class: 'muted' }, ' 在库 / ' + fmtQty(available) + ' 可用'),
        ]),
        el('div', { class: 'chips' }, [
          item.has_stock ? el('span', { class: 'chip ok' }, '有库存') : el('span', { class: 'chip' }, '无库存'),
          item.image_url ? el('span', { class: 'chip' }, '有图') : null,
          item.param_count ? el('span', { class: 'chip' }, fmtQty(item.param_count) + ' 参数') : null,
        ]),
      ]),
    ],
  );
  return card;
}

async function initializeInventory() {
  const inv = state.inventory;
  inv.loading = true;
  render();
  try {
    const categories = await call('catalog.categories');
    inv.categories = Array.isArray(categories.categories)
      ? categories.categories.filter((category) => category.parent_id === null || category.level <= 1).slice(0, 300)
      : [];
  } catch (error) {
    inv.categories = [];
  }
  inv.initialized = true;
  inv.loading = false;
  await searchInventory(true);
}

async function searchInventory(reset) {
  const inv = state.inventory;
  if (inv.loading) return;
  inv.loading = true;
  inv.error = null;
  if (reset) {
    inv.cursor = null;
    inv.items = [];
    inv.next = null;
    inv.total = 0;
    inv.detail = null;
    inv.detailError = null;
  }
  render();
  try {
    const data = await call('catalog.search', {
      query: inv.query,
      category_id: inv.categoryId ? Number(inv.categoryId) : null,
      stock_only: inv.stockOnly,
      limit: 30,
      cursor: inv.cursor,
    });
    const items = Array.isArray(data.items) ? data.items : [];
    inv.items = reset ? items : inv.items.concat(items);
    inv.total = Number(data.total) || 0;
    inv.next = data.next_cursor || null;
    inv.cursor = data.next_cursor || null;
  } catch (error) {
    inv.error = error;
    if (reset) inv.items = [];
  } finally {
    inv.loading = false;
    inv.initialized = true;
    render();
  }
}

async function openInventoryDetail(itemKey) {
  const inv = state.inventory;
  if (!itemKey) return;
  inv.detailLoading = true;
  inv.detailError = null;
  inv.detail = null;
  render();
  try {
    const detail = await call('catalog.detail', { item_key: itemKey });
    inv.detail = detail;
  } catch (error) {
    inv.detailError = error;
  } finally {
    inv.detailLoading = false;
    render();
  }
}

function renderInventoryDetail(detail) {
  const item = detail.item || {};
  const code = codeOf(item);
  const imageBox = el('div', { class: 'image-box' }, item.image_url ? '图片加载中…' : '无图片');
  if (item.image_url) void loadDetailImage(item.image_url, item.item_key, imageBox);

  const meta = el('div', { class: 'meta' }, [
    el('h2', {}, (code ? code + ' · ' : '') + (item.name || '未命名器件')),
    el('div', { class: 'chips' }, [
      item.has_stock ? el('span', { class: 'chip ok' }, '有库存') : el('span', { class: 'chip' }, '无库存'),
      item.local_only ? el('span', { class: 'chip warn' }, '仅本地档案') : null,
      detail.lab_templates && detail.lab_templates.length > 1
        ? el('span', { class: 'chip warn' }, detail.lab_templates.length + ' 个本地档案，禁止自动选第一个')
        : null,
      item.param_count ? el('span', { class: 'chip' }, fmtQty(item.param_count) + ' 参数') : null,
    ]),
    el('dl', { class: 'kv', style: 'margin-top:10px' }, [
      el('dt', {}, '型号'), el('dd', {}, item.mpn || '—'),
      el('dt', {}, '品牌 / 封装'), el('dd', {}, [item.brand, item.package].filter(Boolean).join(' / ') || '—'),
      el('dt', {}, '分类'), el('dd', {}, item.category_path || item.category_name || '—'),
      el('dt', {}, 'item_key'), el('dd', { class: 'mono' }, item.item_key || '—'),
      el('dt', {}, '资料库库存'), el('dd', {}, item.catalog_stock === null || item.catalog_stock === undefined ? '—' : fmtQty(item.catalog_stock)),
    ]),
    el('div', { class: 'row', style: 'margin-top:10px' }, [
      el('button', {
        class: 'btn primary',
        type: 'button',
        onclick: () => {
          state.receipt.itemKey = item.item_key || ('lcsc:' + code);
          state.receipt.detail = detail;
          state.receipt.detailError = null;
          state.receipt.templateId = '';
          nav('receipt');
        },
      }, '入库此器件'),
      el('button', { class: 'btn', type: 'button', onclick: () => copyText(code, '已复制 C 编号') }, '复制 C 编号'),
    ]),
  ]);

  const panel = el('section', { class: 'panel' }, [el('div', { class: 'detail-head' }, [imageBox, meta])]);

  const locations = Array.isArray(detail.locations) ? detail.locations : [];
  const bags = Array.isArray(detail.bags) ? detail.bags : [];
  const issues = Array.isArray(detail.issues) ? detail.issues : [];
  const history = Array.isArray(detail.history) ? detail.history : [];
  const params = Array.isArray(item.parameters) ? item.parameters : Array.isArray(detail.parameters) ? detail.parameters : [];

  panel.appendChild(
    el('div', { class: 'grid-3', style: 'margin-top:12px' }, [
      stat('实时在库', fmtQty(item.lab_quantity)),
      stat('实时可用', fmtQty(item.lab_available_quantity)),
      stat('本地档案', fmtQty((detail.lab_templates || []).length)),
    ]),
  );

  if (params.length) {
    panel.appendChild(el('h3', {}, '参数'));
    panel.appendChild(table([{ label: '参数' }, { label: '值' }], params.map((param) => [param.name || param.code || '—', param.value || ''])));
  }

  if (locations.length) {
    panel.appendChild(el('h3', {}, '实时库位汇总'));
    panel.appendChild(
      table(
        [{ label: '库位' }, { label: '在库', num: true }, { label: '可用', num: true }],
        locations.map((location) => [
          location.location || location.path || '—',
          fmtQty(location.quantity),
          location.available_quantity === null || location.available_quantity === undefined
            ? '—'
            : fmtQty(location.available_quantity),
        ]),
      ),
    );
  }

  if (bags.length) {
    panel.appendChild(el('h3', {}, '袋 / 批次追溯'));
    panel.appendChild(
      table(
        [{ label: '追溯码' }, { label: '在库', num: true }, { label: '可用', num: true }, { label: '未归还', num: true }, { label: '库位' }, { label: '批次/收货' }, { label: '' }],
        bags.map((bag) => [
          el('span', { class: 'mono' }, bag.trace_code || '—'),
          fmtQty(bag.quantity),
          bagAvailableQuantity(bag) === null ? '—' : fmtQty(bagAvailableQuantity(bag)),
          fmtQty(bag.outstanding_quantity),
          bagLocationName(bag),
          [bagLotName(bag), fmtDate(bag.receipt_date)].filter(Boolean).join(' / ') || '—',
          el('button', { class: 'btn small', type: 'button', onclick: () => prefillIssueBag(bag) }, '领用'),
        ]),
      ),
    );
  }

  if (issues.length) {
    panel.appendChild(el('h3', {}, '未归还原领用单'));
    panel.appendChild(
      table(
        [{ label: '领用单 ID' }, { label: '袋' }, { label: '领用', num: true }, { label: '已还', num: true }, { label: '未还', num: true }, { label: '领用人' }, { label: '项目' }],
        issues.map((issue) => [
          String(issue.id || issue.issue_line_id || '—'),
          issueBagName(issue),
          fmtQty(issue.quantity),
          fmtQty(issue.returned_quantity),
          fmtQty(issue.outstanding_quantity),
          issueBorrowerName(issue),
          issue.project || '—',
        ]),
      ),
    );
    panel.appendChild(el('p', { class: 'muted' }, '归还必须按原领用明细（issue_line_id），不能按器件总量归还。'));
  }

  if (history.length) {
    panel.appendChild(el('h3', {}, '最近作业流水'));
    panel.appendChild(
      table(
        [{ label: '时间' }, { label: '袋 ID' }, { label: '作业 ID' }, { label: '数量', num: true }],
        history.slice(0, 50).map((row) => [fmtDate(row.create_date), String(row.bag_id || '—'), String(row.operation_id || '—'), fmtQty(row.quantity)]),
      ),
    );
  }

  if (item.datasheet_url || item.source_url) {
    panel.appendChild(
      el('p', { class: 'muted', style: 'margin-top:10px' }, '资料链接：' + [item.datasheet_url ? '数据手册' : '', item.source_url ? '来源页' : ''].filter(Boolean).join(' / ') + '（请在 Odoo 资料库中打开，插件不代理外部链接）'),
    );
  }

  return panel;
}

function stat(label, value) {
  return el('div', { class: 'stat' }, [el('div', { class: 'label' }, label), el('div', { class: 'value' }, value)]);
}

async function loadDetailImage(url, itemKey, box) {
  try {
    const image = await call('catalog.image', { url });
    if (!state.inventory.detail || state.inventory.detail.item.item_key !== itemKey) return;
    clear(box);
    if (image && image.supported && image.dataUrl) {
      box.appendChild(el('img', { src: image.dataUrl, alt: '器件图片' }));
    } else {
      box.textContent = (image && image.reason) || '无图片';
    }
  } catch (error) {
    if (!state.inventory.detail || state.inventory.detail.item.item_key !== itemKey) return;
    clear(box);
    box.textContent = '图片加载失败：' + ((error && error.code) || 'ERROR');
  }
}

/* ------------------------------------------------------------------ */
/* Read-only BOM comparison                                            */
/* ------------------------------------------------------------------ */

const BOM_STATUS_LABEL = {
  ok: '充足',
  short: '缺料',
  unknown: '库存未知',
  not_in_catalog: '资料库无此器件',
  no_code: '无 C 编号',
};

function bomStatusChip(status) {
  const cls = status === BOM_STATUS.OK ? 'ok' : status === BOM_STATUS.SHORT ? 'danger' : status === BOM_STATUS.UNKNOWN ? 'warn' : '';
  return el('span', { class: 'chip ' + cls }, BOM_STATUS_LABEL[status] || status);
}

function renderBom() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('BOM 对比'));
    return;
  }
  const bom = state.bom;

  const scope = bom.scope;
  const radios = el('div', { class: 'chips' }, [
    scopeRadio('project', '当前工程 BOM', scope),
    scopeRadio('selected', '选中器件', scope),
    scopeRadio('page', '当前图页', scope),
    scopeRadio('loaded', '已加载图页', scope),
  ]);

  dom.view.appendChild(
    el('section', { class: 'panel' }, [
      el('h2', {}, 'BOM 对比云端库存'),
      el('p', { class: 'muted' }, '按立创 C 编号归并器件，只读取 EDA 与 Odoo，不会修改原理图、BOM 或库存。数量按 1 块板计算。'),
      el('div', { class: 'row', style: 'justify-content:space-between;margin-top:10px' }, [
        radios,
        el('div', { class: 'row' }, [
          el('button', { class: 'btn', type: 'button', disabled: bom.loading, onclick: () => refreshBomStock() }, bom.refreshing ? '刷新中…' : '仅刷新库存'),
          el('button', { class: 'btn primary', type: 'button', disabled: bom.loading, onclick: () => runBom() }, bom.loading ? '读取中…' : '读取并对比'),
          el(
            'button',
            {
              class: 'btn primary',
              type: 'button',
              disabled: bom.loading || bom.outbound.computing || bom.outbound.submitting || !(bom.rows || []).length,
              onclick: () => openBomOutbound(),
            },
            bom.outbound.computing ? '分配中…' : '一键出库',
          ),
        ]),
      ]),
      scope === 'project'
        ? el('p', { class: 'notice', style: 'margin-top:10px' }, '当前工程 BOM 由 EDA 制造数据导出（pcb_ManufactureData.getBomFile），覆盖全部图页，不依赖图页是否已加载。若导出不可用会自动改用已加载图页。')
        : el('p', { class: 'notice warn', style: 'margin-top:10px' }, '注意：原理图范围只返回已加载图页中的器件；需要完整 BOM 请用「当前工程 BOM」。'),
    ]),
  );

  if (bom.error) dom.view.appendChild(errorBox(bom.error, { retry: () => runBom() }));

  if (bom.loading) {
    dom.view.appendChild(el('div', { class: 'panel muted' }, '正在读取原理图器件并查询 Odoo 实时库存…'));
    return;
  }

  if (!bom.scan) {
    dom.view.appendChild(el('div', { class: 'empty' }, '选择范围后点击「读取并对比」。'));
    return;
  }

  for (const warning of bom.warnings || []) {
    dom.view.appendChild(el('div', { class: 'notice warn', style: 'margin-top:10px' }, warning));
  }

  if (bom.summary) {
    dom.view.appendChild(
      el('section', { class: 'panel' }, [
        el('div', { class: 'grid-3' }, [
          stat('BOM 行数', fmtQty(bom.summary.lineCount)),
          stat('需求总数', fmtQty(bom.summary.need)),
          stat('缺口总数', fmtQty(bom.summary.gap)),
          stat('缺料行', fmtQty(bom.summary.shortLines)),
          stat('库存未知行', fmtQty(bom.summary.unknownLines)),
          stat('资料库无器件', fmtQty(bom.summary.notInCatalogLines)),
        ]),
      ]),
    );
  }

  if (bom.outbound.error) dom.view.appendChild(errorBox(bom.outbound.error));
  if ((bom.outbound.shortage || []).length) {
    dom.view.appendChild(
      section('一键出库：库存不足，未扣减任何库存', [
        table(
          [{ label: 'C 编号' }, { label: '需求', num: true }, { label: '可用', num: true }, { label: '缺口', num: true }, { label: '原因' }],
          bom.outbound.shortage.map((entry) => [
            el('span', { class: 'mono' }, String(entry.item_key || '').replace('lcsc:', '')),
            fmtQty(entry.need),
            entry.available === null || entry.available === undefined ? '未知' : fmtQty(entry.available),
            entry.shortfall === undefined ? '—' : fmtQty(entry.shortfall),
            entry.reason || '库存不足',
          ]),
        ),
      ]),
    );
  }
  if (bom.outbound.result) {
    dom.view.appendChild(
      el('div', { class: 'notice ok', style: 'margin-top:10px' }, '一键出库成功：' + ((bom.outbound.result.plan || []).length) + ' 个型号，按袋扣减完成。可在「领用」页签查看领用单。'),
    );
  }

  const rows = bom.rows || [];
  if (rows.length) {
    const tableRows = rows.map((row) => [
      bomStatusChip(row.status),
      el('span', { class: 'mono' }, row.code),
      row.name || '—',
      (row.designators || []).join(','),
      fmtQty(row.need),
      row.available === null ? '未知' : fmtQty(row.available),
      row.gap === null ? '未知' : fmtQty(row.gap),
      (row.locations || [])
        .map((location) => locationSummary(location))
        .join(' ') || '—',
    ]);
    dom.view.appendChild(
      section('对比结果', [
        table(
          [
            { label: '状态' },
            { label: 'C 编号' },
            { label: '名称' },
            { label: '位号' },
            { label: '需求', num: true },
            { label: '可用', num: true },
            { label: '缺口', num: true },
            { label: '库位' },
          ],
          tableRows,
        ),
        el('div', { class: 'row', style: 'margin-top:10px' }, [
          el('button', { class: 'btn', type: 'button', onclick: () => copyText(bomTsv(rows), '已复制对比表') }, '复制对比表'),
          el('button', { class: 'btn', type: 'button', onclick: () => exportBomCsv(rows) }, '导出 CSV'),
        ]),
      ]),
    );
  }

  if (bom.unmapped && bom.unmapped.length) {
    dom.view.appendChild(
      section('缺少有效 C 编号的器件（未并入库存）', [
        table(
          [{ label: '位号' }, { label: '名称' }, { label: '型号' }, { label: '原因' }],
          bom.unmapped.map((component) => [
            component.designator || '—',
            component.name || '—',
            component.mpn || '—',
            '没有有效的立创 C 编号，禁止猜测或合并',
          ]),
        ),
      ]),
    );
  }

  const excluded = Array.isArray(bom.scan.components) ? bom.scan.components.filter((component) => component.addIntoBom === false).length : 0;
  const unknownFlag = Array.isArray(bom.scan.components) ? bom.scan.components.filter((component) => component.addIntoBom === null).length : 0;
  const sourceLabel =
    bom.scan.source === 'bom'
      ? '工程 BOM 导出' + (bom.scan.provider ? '（' + String(bom.scan.provider).replace('_ManufactureData', '') + '）' : '')
      : bom.scan.source === 'schematic'
        ? '原理图读取（工程 BOM 导出不可用）'
        : bom.scan.scope === 'selected'
          ? '选中器件'
          : bom.scan.scope === 'page'
            ? '当前图页'
            : '已加载图页';
  dom.view.appendChild(
    el('p', { class: 'footer-note' }, [
      '来源：' + sourceLabel +
        '，器件 ' + fmtQty((bom.scan.totals && (bom.scan.totals.components || bom.scan.totals.lines)) || 0) +
        (excluded ? '，未加入 BOM ' + excluded : '') +
        (unknownFlag ? '，BOM 标志未知 ' + unknownFlag : '') +
        (bom.scannedAt ? '，时间 ' + fmtDate(bom.scannedAt) : ''),
    ]),
  );
}

/* ------------------------------------------------------------------ */
/* One-click outbound (BOM -> bag allocation -> real issue)            */
/* ------------------------------------------------------------------ */

function bomOutboundSourceLines(rows) {
  return (rows || [])
    .filter((row) => row && row.code)
    .map((row) => ({ item_key: 'lcsc:' + row.code, quantity: Number(row.need) || 0 }));
}

async function openBomOutbound() {
  const out = state.bom.outbound;
  out.computing = true;
  out.error = null;
  out.shortage = null;
  out.plan = null;
  out.result = null;
  out.sourceLines = bomOutboundSourceLines(state.bom.rows);
  render();
  try {
    const response = await call('inventory.outbound', { lines: out.sourceLines, dry_run: true });
    out.plan = (response && response.plan) || [];
    if (response && response.ok === false) out.shortage = response.shortage || [];
  } catch (error) {
    out.error = error;
  }
  out.computing = false;
  render();
  if (!out.error && !(out.shortage || []).length && (out.plan || []).length) await confirmBomOutbound();
}

async function confirmBomOutbound() {
  const out = state.bom.outbound;
  const bootstrap = state.bootstrap || {};
  const borrowers = Array.isArray(bootstrap.borrowers) ? bootstrap.borrowers : [];
  if (!borrowers.length) {
    toast('没有可用的领用人，请先刷新连接或确认权限。', 'error');
    return;
  }
  let borrowerId = String(state.issue.borrowerId || (borrowers[0] && borrowers[0].id) || '');
  let project = state.issue.project || '';
  const borrowerSelect = el(
    'select',
    { class: 'grow' },
    borrowers.map((borrower) =>
      el(
        'option',
        { value: String(borrower.id), selected: String(borrower.id) === borrowerId },
        (borrower.name || borrower.login || String(borrower.id)) + (borrower.is_self ? '（本人）' : ''),
      ),
    ),
  );
  borrowerSelect.addEventListener('change', () => {
    borrowerId = borrowerSelect.value;
  });
  const projectInput = el('input', { type: 'text', value: project, placeholder: '例如：2026 春季电源板' });
  projectInput.addEventListener('input', () => {
    project = projectInput.value;
  });
  const planRows = (out.plan || []).map((entry) => [
    el('span', { class: 'mono' }, String(entry.item_key).replace('lcsc:', '')),
    entry.name || '—',
    fmtQty(entry.need),
    entry.available === null ? '未知' : fmtQty(entry.available),
    (entry.bags || []).map((bag) => '袋#' + bag.bag_id + '×' + fmtQty(bag.quantity)).join(' '),
  ]);
  const content = el('div', {}, [
    el('div', { class: 'grid-2' }, [field('领用人', borrowerSelect, '必须是已建立的系统账号'), field('项目/用途', projectInput, '会写入领用单')]),
    table(
      [
        { label: 'C 编号' },
        { label: '名称' },
        { label: '需求', num: true },
        { label: '可用', num: true },
        { label: '按袋分配' },
      ],
      planRows,
    ),
    el('p', { class: 'muted' }, '确认后立即按袋扣减云端库存并生成领用单，不可撤销；归还需走「归还」。'),
  ]);
  const ok = await confirmModal('一键出库（' + (out.plan || []).length + ' 个型号）', content, '确认出库');
  if (!ok) return;
  if (!project.trim()) {
    toast('请填写项目/用途。', 'error');
    return;
  }
  state.issue.project = project.trim();
  out.submitting = true;
  out.error = null;
  render();
  try {
    const response = await call('inventory.outbound', {
      lines: out.sourceLines,
      dry_run: false,
      request_key: defaultKeyFactory(),
      borrower_id: Number(borrowerId),
      project: project.trim(),
      note: 'BOM 一键出库',
    });
    out.result = response;
    toast('已出库 ' + ((response && response.plan) || []).length + ' 个型号', 'ok');
    out.submitting = false;
    await runBom();
    state.bom.outbound.result = response;
    render();
  } catch (error) {
    out.submitting = false;
    out.error = error;
    render();
    toast(String(error.message || error), 'error', 6000);
  }
}

function scopeRadio(value, label, current) {
  const input = el('input', { type: 'radio', name: 'bom-scope', value, checked: current === value });
  input.addEventListener('change', () => {
    if (input.checked) {
      state.bom.scope = value;
      state.bom.scan = null;
      state.bom.rows = [];
      state.bom.summary = null;
      state.bom.unmapped = [];
      state.bom.warnings = [];
      state.bom.grouped = null;
      state.bom.outbound = { computing: false, submitting: false, plan: null, shortage: null, error: null, result: null };
      render();
    }
  });
  return el('label', { class: 'check', style: 'padding-bottom:0' }, [input, el('span', {}, label)]);
}

async function fetchDetailMap(codes) {
  const result = new Map();
  let index = 0;
  const workers = Array.from({ length: Math.min(4, codes.length) }, async () => {
    while (index < codes.length) {
      const current = index;
      index += 1;
      const code = codes[current];
      try {
        result.set(code, { detail: await call('catalog.detail', { item_key: 'lcsc:' + code }) });
      } catch (error) {
        result.set(code, { error });
      }
    }
  });
  await Promise.all(workers);
  return result;
}

async function runBom() {
  const bom = state.bom;
  bom.loading = true;
  bom.error = null;
  render();
  try {
    const scan = bom.scope === 'project' ? await call('eda.bom', {}, 45000) : await call('eda.scan', { scope: bom.scope });
    let lines = Array.isArray(scan.lines) ? scan.lines : null;
    let unmapped = Array.isArray(scan.unmapped) ? scan.unmapped : [];
    if (!lines) {
      const grouped = groupBom(scan.components || []);
      lines = grouped.lines;
      unmapped = grouped.unmapped;
    }
    const details = await fetchDetailMap(lines.map((line) => line.code));
    bom.scan = scan;
    bom.warnings = scan.warnings || [];
    bom.unmapped = unmapped;
    bom.grouped = { lines, unmapped };
    bom.rows = lines.map((line) => {
      const entry = details.get(line.code);
      return compareLine(line, entry && entry.detail, entry && entry.error);
    });
    bom.summary = summarize(bom.rows);
    bom.scannedAt = scan.scannedAt;
    bom.outbound = { computing: false, submitting: false, plan: null, shortage: null, error: null, result: null };
  } catch (error) {
    bom.error = error;
  } finally {
    bom.loading = false;
    render();
  }
}

async function refreshBomStock() {
  const bom = state.bom;
  if (!bom.grouped || !bom.grouped.lines.length) {
    await runBom();
    return;
  }
  bom.refreshing = true;
  bom.error = null;
  render();
  try {
    const details = await fetchDetailMap(bom.grouped.lines.map((line) => line.code));
    bom.rows = bom.grouped.lines.map((line) => {
      const entry = details.get(line.code);
      return compareLine(line, entry && entry.detail, entry && entry.error);
    });
    bom.summary = summarize(bom.rows);
  } catch (error) {
    bom.error = error;
  } finally {
    bom.refreshing = false;
    render();
  }
}

function csvCell(value) {
  const text = String(value ?? '');
  return '"' + text.replace(/"/g, '""') + '"';
}

function exportBomCsv(rows) {
  const header = ['状态', 'C 编号', '名称', '型号', '位号', '需求', '可用', '缺口', '库位'];
  const lines = rows.map((row) => [
    BOM_STATUS_LABEL[row.status] || row.status,
    row.code,
    row.name,
    row.mpn,
    (row.designators || []).join(','),
    row.need,
    row.available === null ? '未知' : row.available,
    row.gap === null ? '未知' : row.gap,
    (row.locations || []).map((location) => locationSummary(location)).join(' '),
  ]);
  const csv = '\ufeff' + [header].concat(lines).map((line) => line.map(csvCell).join(',')).join('\r\n');
  try {
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = el('a', { href: url, download: 'bom-compare-' + Date.now() + '.csv', style: 'display:none' });
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast('已导出 CSV', 'ok');
  } catch (_) {
    copyText(csv, '当前环境不支持下载，已复制 CSV 文本');
  }
}

/* ------------------------------------------------------------------ */
/* Receipt                                                             */
/* ------------------------------------------------------------------ */

function renderReceipt() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('入库登记'));
    return;
  }
  if (state.receipt.success) {
    renderReceiptSuccess();
    return;
  }

  const receipt = state.receipt;
  const bootstrap = state.bootstrap;
  const locations = Array.isArray(bootstrap && bootstrap.locations) ? bootstrap.locations : [];
  const permissions = (bootstrap && bootstrap.permissions) || {};
  if (bootstrap && permissions.can_receipt === false) {
    showBanner('当前账号没有入库权限（lab_workflow.group_lab_operator），提交会被服务器拒绝。', 'warn');
  } else if (state.bootstrapError) {
    dom.view.appendChild(errorBox(state.bootstrapError, { retry: () => loadBootstrap() }));
  }

  const itemInput = el('input', { type: 'text', placeholder: 'C123 或 lcsc:C123', value: receipt.itemKey, class: 'mono' });
  itemInput.addEventListener('input', () => {
    receipt.itemKey = itemInput.value.trim();
  });
  itemInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void queryReceiptItem();
    }
  });

  const locationSelect = el(
    'select',
    {},
    locations.length
      ? locations.map((location) =>
          el('option', { value: String(location.id), selected: String(receipt.locationId) === String(location.id) }, location.path || location.name || String(location.id)),
        )
      : [el('option', { value: '' }, '暂无可用库位')],
  );
  locationSelect.addEventListener('change', () => {
    receipt.locationId = locationSelect.value;
  });

  const qtyInput = el('input', { type: 'number', min: '0.000001', step: 'any', value: receipt.quantity });
  qtyInput.addEventListener('input', () => {
    receipt.quantity = qtyInput.value;
  });

  const supplierInput = el('input', { type: 'text', placeholder: '可选：立创原厂袋二维码内容', value: receipt.supplierQr });
  supplierInput.addEventListener('input', () => {
    receipt.supplierQr = supplierInput.value;
  });

  const noteInput = el('textarea', { placeholder: '可选备注（不要填写密码等凭据）', value: receipt.note });
  noteInput.addEventListener('input', () => {
    receipt.note = noteInput.value;
  });

  const form = el('section', { class: 'panel' }, [
    el('h2', {}, '入库登记（生成新袋 + 真实库存移动）'),
    el('p', { class: 'muted' }, '入库会创建新的袋追溯码与 stock.lot，并写入 Odoo 原生库存。每次提交都有确认步骤和幂等请求号。'),
    el('div', { class: 'row' }, [
      el('div', { class: 'grow' }, field('物料编号', itemInput, '只接受 C 编号或 lab:<id>；不会用型号猜测 C 编号。')),
      el('button', { class: 'btn', type: 'button', disabled: receipt.detailLoading, onclick: () => queryReceiptItem() }, receipt.detailLoading ? '查询中…' : '查询器件'),
    ]),
  ]);

  if (receipt.detailError) form.appendChild(errorBox(receipt.detailError, { retry: () => queryReceiptItem() }));
  if (receipt.detail) {
    const item = receipt.detail.item || {};
    const templates = Array.isArray(receipt.detail.lab_templates) ? receipt.detail.lab_templates : [];
    form.appendChild(
      el('div', { class: 'panel', style: 'margin-top:10px;background:var(--panel-2)' }, [
        el('div', { class: 'chips' }, [
          el('span', { class: 'chip' }, item.item_key || '—'),
          el('span', { class: 'chip' }, '在库 ' + fmtQty(item.lab_quantity)),
          el('span', { class: 'chip' }, '可用 ' + fmtQty(item.lab_available_quantity)),
        ]),
        el('p', { style: 'margin-top:8px' }, (item.name || '未命名器件') + (item.mpn ? ' · ' + item.mpn : '') + (item.brand ? ' · ' + item.brand : '')),
        templates.length > 1
          ? (() => {
              const select = el('select', {}, [
                el('option', { value: '' }, '请选择要归属的 SN 档案（必选）'),
                ...templates.map((template) =>
                  el(
                    'option',
                    { value: String(template.id), selected: String(receipt.templateId) === String(template.id) },
                    (template.sn || '无 SN') + ' · ' + (template.name || '') + ' · 在库 ' + fmtQty(template.quantity),
                  ),
                ),
              ]);
              select.addEventListener('change', () => {
                receipt.templateId = select.value;
              });
              return field('同名 C 编号有多个档案，请选择 SN', select, '不选择会被服务器以 AMBIGUOUS_MATERIAL 拒绝，插件不会自动取第一个。');
            })()
          : el('p', { class: 'muted' }, templates.length === 1 ? '将使用唯一档案：' + (templates[0].sn || '无 SN') : '暂无本地档案，服务器将按 C 编号校验/建档。'),
      ]),
    );
  }

  form.appendChild(
    el('div', { class: 'grid-2', style: 'margin-top:10px' }, [
      field('入库库位', locationSelect),
      field('数量', qtyInput, '必须是大于 0 的数量；服务器按 UoM 校验。'),
    ]),
  );
  form.appendChild(el('div', { class: 'grid-2', style: 'margin-top:10px' }, [field('供应商二维码（可选）', supplierInput), field('备注（可选）', noteInput)]));

  if (receipt.error) {
    form.appendChild(
      el('div', { style: 'margin-top:10px' }, [
        errorBox(receipt.error, {
          retry: receipt.draft && (receipt.draft.state === 'ambiguous' || receipt.draft.state === 'error') ? () => submitReceipt(true) : null,
          retryLabel: '用同一请求号重试',
        }),
      ]),
    );
  }

  const keyLine = receipt.draft
    ? el('p', { class: 'muted' }, '当前请求号：' + shortKey(receipt.draft.key) + '（修改表单会自动换新请求号；未修改时重试复用）')
    : el('p', { class: 'muted' }, '提交时生成请求号；网络超时后可用同一请求号重试，不会重复入库。');

  form.appendChild(
    el('div', { class: 'row', style: 'margin-top:12px;justify-content:space-between' }, [
      keyLine,
      el('button', { class: 'btn primary', type: 'button', disabled: receipt.submitting, onclick: () => submitReceipt(false) }, receipt.submitting ? '提交中…' : '确认入库'),
    ]),
  );
  dom.view.appendChild(form);
}

async function queryReceiptItem() {
  const receipt = state.receipt;
  const parsed = parseItemKey(receipt.itemKey);
  if (!parsed.key) {
    receipt.detailError = { code: 'VALIDATION_ERROR', message: '物料编号无效：请输入 C123 或 lcsc:C123。' };
    receipt.detail = null;
    render();
    return;
  }
  receipt.itemKey = parsed.key;
  receipt.detailLoading = true;
  receipt.detailError = null;
  receipt.detail = null;
  receipt.templateId = '';
  render();
  try {
    receipt.detail = await call('catalog.detail', { item_key: parsed.key });
  } catch (error) {
    receipt.detailError = error;
  } finally {
    receipt.detailLoading = false;
    render();
  }
}

function buildReceiptPayload() {
  const receipt = state.receipt;
  const parsed = parseItemKey(receipt.itemKey);
  if (!parsed.key) throw Object.assign(new Error('物料编号无效。'), { code: 'VALIDATION_ERROR' });
  const locationId = Number(receipt.locationId);
  if (!Number.isInteger(locationId) || locationId <= 0) throw Object.assign(new Error('请选择入库库位。'), { code: 'VALIDATION_ERROR' });
  const quantity = Number(receipt.quantity);
  if (!Number.isFinite(quantity) || quantity <= 0) throw Object.assign(new Error('数量必须大于 0。'), { code: 'VALIDATION_ERROR' });
  const templates = receipt.detail && Array.isArray(receipt.detail.lab_templates) ? receipt.detail.lab_templates : [];
  if (templates.length > 1 && !receipt.templateId) {
    throw Object.assign(new Error('该 C 编号有多个本地档案，请先选择 SN 档案。'), { code: 'AMBIGUOUS_MATERIAL' });
  }
  return {
    item_key: parsed.key,
    product_template_id: receipt.templateId ? Number(receipt.templateId) : null,
    location_id: locationId,
    quantity,
    supplier_qr: receipt.supplierQr.trim(),
    note: receipt.note.trim(),
  };
}

async function submitReceipt(skipConfirm) {
  const receipt = state.receipt;
  if (receipt.submitting) return;
  let payload;
  try {
    payload = buildReceiptPayload();
  } catch (error) {
    receipt.error = error;
    render();
    return;
  }
  receipt.draft = receipt.draft ? withPayload(receipt.draft, payload) : createDraft('inventory.receipt', payload);
  if (!skipConfirm) {
    const templates = receipt.detail && Array.isArray(receipt.detail.lab_templates) ? receipt.detail.lab_templates : [];
    const chosen = templates.find((template) => String(template.id) === String(receipt.templateId));
    const confirmed = await confirmModal(
      '确认入库',
      el('div', {}, [
        el('p', {}, '物料：' + payload.item_key),
        el('p', {}, '库位：' + (state.bootstrap && state.bootstrap.locations || []).map((location) => String(location.id) === String(payload.location_id) ? location.path || location.name : '').filter(Boolean).join('')),
        el('p', {}, '数量：' + fmtQty(payload.quantity)),
        chosen ? el('p', {}, 'SN 档案：' + (chosen.sn || chosen.name || chosen.id)) : null,
        payload.supplier_qr ? el('p', { class: 'muted' }, '将同时记录供应商二维码（服务端校验一致性）') : null,
        el('p', { class: 'muted' }, '提交后会在 Odoo 创建真实库存移动与新袋追溯码。'),
      ]),
    );
    if (!confirmed) return;
  }
  let submitted;
  try {
    submitted = beginSubmit(receipt.draft);
  } catch (error) {
    receipt.error = error;
    toast(error.message, 'warn');
    return;
  }
  receipt.draft = submitted;
  receipt.submitting = true;
  receipt.error = null;
  render();
  try {
    const data = await call('inventory.receipt', Object.assign({}, payload, { request_key: submitted.key }), 60000);
    receipt.draft = markSuccess(submitted, data);
    receipt.success = data;
    receipt.error = null;
    receipt.draft = null;
    toast('入库成功' + (data.replayed ? '（服务器重放，未重复记账）' : ''), 'ok');
  } catch (error) {
    receipt.draft = markFailure(submitted, error);
    if (error.code === 'CONFLICT') receipt.draft = null;
    receipt.error = error;
    toast('入库失败：' + (error.code || error.message), 'error');
  } finally {
    receipt.submitting = false;
    render();
  }
}

function renderReceiptSuccess() {
  const data = state.receipt.success || {};
  const bag = data.bag || {};
  const operation = data.operation || {};
  dom.view.appendChild(
    el('section', { class: 'panel' }, [
      el('h2', {}, '入库成功' + (data.replayed ? '（服务器重放）' : '')),
      el('dl', { class: 'kv' }, [
        el('dt', {}, '作业单'), el('dd', {}, (operation.name || '—') + (operation.id ? '（ID ' + operation.id + '）' : '')),
        el('dt', {}, '袋追溯码'), el('dd', { class: 'mono' }, bag.trace_code || '—'),
        el('dt', {}, '库位'), el('dd', {}, bag.location_path || '—'),
        el('dt', {}, '袋内数量'), el('dd', {}, fmtQty(bag.quantity)),
        el('dt', {}, '物料'), el('dd', {}, (data.material && (data.material.name || data.material.mpn)) || data.item_key || '—'),
        el('dt', {}, '物料实时在库'), el('dd', {}, fmtQty(data.lab_quantity)),
      ]),
      el('div', { class: 'row', style: 'margin-top:12px' }, [
        el('button', { class: 'btn primary', type: 'button', onclick: () => copyText(bag.trace_code || '', '已复制追溯码') }, '复制追溯码'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => {
            state.trace.raw = bag.trace_code || '';
            state.trace.result = null;
            state.trace.error = null;
            nav('trace');
            if (state.trace.raw) setTimeout(() => resolveTrace(), 0);
          },
        }, '查看袋追溯'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => {
            state.receipt.success = null;
            state.receipt.itemKey = '';
            state.receipt.detail = null;
            state.receipt.quantity = '1';
            state.receipt.supplierQr = '';
            state.receipt.note = '';
            state.receipt.templateId = '';
            state.receipt.error = null;
            render();
          },
        }, '继续入库'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => call('ui.open', { action: 'operation_list' }).catch((error) => toast(error.message, 'error')),
        }, '打开 Odoo 作业流水'),
      ]),
      el('p', { class: 'muted', style: 'margin-top:10px' }, '标签打印请使用 Odoo 的「批量标签（A4）」入口；本插件不生成前端二维码。'),
    ]),
  );
}

/* ------------------------------------------------------------------ */
/* Issue                                                               */
/* ------------------------------------------------------------------ */

function prefillIssueBag(bag) {
  if (!bag || !bag.id) {
    toast('该袋没有有效 ID，无法领用。', 'error');
    return;
  }
  const available = bagAvailableQuantity(bag);
  if (available !== null && available <= 0) {
    toast('该袋实时可用数量为 0，不能领用。', 'warn');
    return;
  }
  const existing = state.issue.lines.find((line) => Number(line.bag_id) === Number(bag.id));
  if (existing) {
    toast('该袋已在领用明细中。', 'warn');
  } else {
    state.issue.lines.push({
      bag_id: Number(bag.id),
      trace_code: bag.trace_code || '',
      name: bag.name || bag.mpn || '',
      available,
      quantity: String(Math.min(1, available === null ? 1 : available) || 1),
    });
  }
  state.issue.bagInfo = bag;
  state.issue.bagRaw = bag.trace_code || '';
  nav('issue');
}

function renderIssue() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('领用出库'));
    return;
  }
  if (state.issue.success) {
    renderIssueSuccess();
    return;
  }
  const issue = state.issue;
  const bootstrap = state.bootstrap;
  const borrowers = Array.isArray(bootstrap && bootstrap.borrowers) ? bootstrap.borrowers : [];
  const permissions = (bootstrap && bootstrap.permissions) || {};
  if (bootstrap && permissions.can_issue === false) {
    showBanner('当前账号没有领料权限（lab_workflow.group_lab_operator），提交会被服务器拒绝。', 'warn');
  }
  if (bootstrap && borrowers.length === 0) {
    showBanner('没有可选的系统领用账号。领用人必须是已建立且启用的 Odoo 用户，请联系库存管理员。', 'warn');
  }

  const borrowerSelect = el(
    'select',
    {},
    borrowers.length
      ? borrowers.map((borrower) =>
          el(
            'option',
            { value: String(borrower.id), selected: String(issue.borrowerId) === String(borrower.id) },
            (borrower.name || borrower.login || String(borrower.id)) + (borrower.is_self ? '（本人）' : ''),
          ),
        )
      : [el('option', { value: '' }, '暂无授权领用人')],
  );
  borrowerSelect.addEventListener('change', () => {
    issue.borrowerId = borrowerSelect.value;
  });

  const projectInput = el('input', { type: 'text', placeholder: '例如：项目 A / 2026-10 打样', value: issue.project });
  projectInput.addEventListener('input', () => {
    issue.project = projectInput.value;
  });

  const bagInput = el('input', { type: 'text', placeholder: '扫描或粘贴 LABB: 追溯码', value: issue.bagRaw, class: 'mono' });
  bagInput.addEventListener('input', () => {
    issue.bagRaw = bagInput.value.trim();
  });
  bagInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void resolveIssueBag();
    }
  });

  const noteInput = el('textarea', { placeholder: '可选备注（不要填写密码等凭据）', value: issue.note });
  noteInput.addEventListener('input', () => {
    issue.note = noteInput.value;
  });

  const panel = el('section', { class: 'panel' }, [
    el('h2', {}, '领用出库（按袋，系统账号 + 项目）'),
    el('p', { class: 'muted' }, '领用人必须从服务器提供的授权系统账号中选择；操作人由服务器按登录会话记录。不能按器件总量扣减。'),
    el('div', { class: 'grid-2' }, [
      field('领用人', borrowerSelect, '必须是已建立的系统账号，不接受手填姓名。'),
      field('项目', projectInput, '必填；会写入领用记录。'),
    ]),
  ]);

  panel.appendChild(
    el('div', { class: 'row', style: 'margin-top:10px' }, [
      el('div', { class: 'grow' }, field('袋追溯码', bagInput, '也可从器件详情的袋列表直接点「领用」。')),
      el('button', { class: 'btn', type: 'button', disabled: issue.loadingBag, onclick: () => resolveIssueBag() }, issue.loadingBag ? '解析中…' : '解析袋码'),
    ]),
  );

  if (issue.bagError) panel.appendChild(el('div', { style: 'margin-top:10px' }, errorBox(issue.bagError)));
  if (issue.bagInfo) {
    const bag = issue.bagInfo;
    panel.appendChild(
      el('div', { class: 'panel', style: 'margin-top:10px;background:var(--panel-2)' }, [
        el('div', { class: 'chips' }, [
          el('span', { class: 'chip mono' }, bag.trace_code || '—'),
          el('span', { class: 'chip' }, '在库 ' + fmtQty(bag.quantity)),
          el('span', { class: 'chip' }, '可用 ' + (bagAvailableQuantity(bag) === null ? '—' : fmtQty(bagAvailableQuantity(bag)))),
          el('span', { class: 'chip' }, bag.location_path || bag.location_code || '—'),
        ]),
        el('p', { style: 'margin-top:8px' }, (bag.name || bag.mpn || '') + (bag.lot_name ? ' · 批次 ' + bag.lot_name : '')),
        el('button', {
          class: 'btn primary',
          type: 'button',
          onclick: () => {
            prefillIssueBag(bag);
          },
        }, '加入领用明细'),
      ]),
    );
  }

  const lines = issue.lines;
  if (lines.length) {
    const rows = lines.map((line, index) => {
      const qtyInput = el('input', { type: 'number', min: '0.000001', step: 'any', value: line.quantity, style: 'width:110px' });
      qtyInput.addEventListener('input', () => {
        line.quantity = qtyInput.value;
      });
      return [
        el('span', { class: 'mono' }, line.trace_code || String(line.bag_id)),
        line.name || '—',
        fmtQty(line.available),
        qtyInput,
        el('button', {
          class: 'btn small danger',
          type: 'button',
          onclick: () => {
            issue.lines.splice(index, 1);
            render();
          },
        }, '移除'),
      ];
    });
    panel.appendChild(el('h3', {}, '领用明细'));
    panel.appendChild(
      table([{ label: '袋追溯码' }, { label: '物料' }, { label: '可用', num: true }, { label: '本次领用' }, { label: '' }], rows),
    );
  } else {
    panel.appendChild(el('div', { class: 'empty', style: 'margin-top:10px' }, '领用明细为空。请先解析袋码并加入。'));
  }

  panel.appendChild(el('div', { style: 'margin-top:10px' }, field('备注（可选）', noteInput)));

  if (issue.error) {
    panel.appendChild(
      el('div', { style: 'margin-top:10px' }, [
        errorBox(issue.error, {
          retry: issue.draft && (issue.draft.state === 'ambiguous' || issue.draft.state === 'error') ? () => submitIssue(true) : null,
          retryLabel: '用同一请求号重试',
        }),
      ]),
    );
  }

  panel.appendChild(
    el('div', { class: 'row', style: 'margin-top:12px;justify-content:space-between' }, [
      el('p', { class: 'muted' }, issue.draft ? '当前请求号：' + shortKey(issue.draft.key) : '提交时生成请求号；修改明细会换新请求号。'),
      el('button', {
        class: 'btn primary',
        type: 'button',
        disabled: issue.submitting || (bootstrap && bootstrap.permissions && bootstrap.permissions.can_issue === false),
        onclick: () => submitIssue(false),
      }, issue.submitting ? '提交中…' : '确认领用'),
    ]),
  );
  dom.view.appendChild(panel);
}

async function resolveIssueBag() {
  const issue = state.issue;
  const raw = issue.bagRaw.trim();
  if (!raw) {
    issue.bagError = { code: 'VALIDATION_ERROR', message: '请先输入或扫描袋追溯码。' };
    render();
    return;
  }
  issue.loadingBag = true;
  issue.bagError = null;
  issue.bagInfo = null;
  render();
  try {
    const data = await call('inventory.resolve', { raw });
    if (data.kind !== 'bag' || !data.bag) {
      issue.bagError = {
        code: 'VALIDATION_ERROR',
        message:
          '扫码类型是「' + (data.kind || '未知') + '」，领用必须扫本系统袋标签（LABB:）。' +
          (data.location ? ' 这是库位码：' + (data.location.path || data.location.code) : '') +
          (data.item_key ? ' 物料：' + data.item_key : '') +
          (data.ambiguous_material ? ' 该 C 编号有多个档案，请先扫具体袋码。' : ''),
      };
    } else {
      issue.bagInfo = data.bag;
      issue.bagRaw = data.bag.trace_code || raw;
    }
  } catch (error) {
    issue.bagError = error;
  } finally {
    issue.loadingBag = false;
    render();
  }
}

function buildIssuePayload() {
  const issue = state.issue;
  const borrowerId = Number(issue.borrowerId);
  if (!Number.isInteger(borrowerId) || borrowerId <= 0) throw Object.assign(new Error('请选择领用人。'), { code: 'VALIDATION_ERROR' });
  const project = issue.project.trim();
  if (!project) throw Object.assign(new Error('请填写领用项目。'), { code: 'VALIDATION_ERROR' });
  if (!issue.lines.length) throw Object.assign(new Error('领用明细为空。'), { code: 'VALIDATION_ERROR' });
  const lines = issue.lines.map((line) => {
    const quantity = Number(line.quantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      throw Object.assign(new Error('明细数量必须大于 0。'), { code: 'VALIDATION_ERROR' });
    }
    if (line.available !== null && quantity - line.available > 1e-9) {
      throw Object.assign(new Error('袋 ' + (line.trace_code || line.bag_id) + ' 的领用数量超过解析时的可用量 ' + fmtQty(line.available) + '。'), {
        code: 'VALIDATION_ERROR',
      });
    }
    return { bag_id: Number(line.bag_id), quantity };
  });
  return { borrower_id: borrowerId, project, lines, note: issue.note.trim() };
}

async function submitIssue(skipConfirm) {
  const issue = state.issue;
  if (issue.submitting) return;
  let payload;
  try {
    payload = buildIssuePayload();
  } catch (error) {
    issue.error = error;
    render();
    return;
  }
  issue.draft = issue.draft ? withPayload(issue.draft, payload) : createDraft('inventory.issue', payload);
  if (!skipConfirm) {
    const borrowers = (state.bootstrap && state.bootstrap.borrowers) || [];
    const borrower = borrowers.find((item) => String(item.id) === String(payload.borrower_id));
    const confirmed = await confirmModal(
      '确认领用',
      el('div', {}, [
        el('p', {}, '领用人：' + (borrower ? borrower.name || borrower.login : payload.borrower_id)),
        el('p', {}, '项目：' + payload.project),
        el('p', {}, '明细：' + payload.lines.map((line) => {
          const local = issue.lines.find((entry) => Number(entry.bag_id) === Number(line.bag_id));
          return (local && local.trace_code ? local.trace_code : String(line.bag_id)) + ' × ' + fmtQty(line.quantity);
        }).join('；')),
        el('p', { class: 'muted' }, '提交后会写入 Odoo 领用记录与真实库存移动，操作人取当前登录账号。'),
      ]),
    );
    if (!confirmed) return;
  }
  let submitted;
  try {
    submitted = beginSubmit(issue.draft);
  } catch (error) {
    issue.error = error;
    toast(error.message, 'warn');
    return;
  }
  issue.draft = submitted;
  issue.submitting = true;
  issue.error = null;
  render();
  try {
    const data = await call('inventory.issue', Object.assign({}, payload, { request_key: submitted.key }), 60000);
    issue.draft = markSuccess(submitted, data);
    issue.success = data;
    issue.draft = null;
    issue.lines = [];
    issue.bagInfo = null;
    issue.bagRaw = '';
    toast('领用成功' + (data.replayed ? '（服务器重放，未重复记账）' : ''), 'ok');
  } catch (error) {
    issue.draft = markFailure(submitted, error);
    if (error.code === 'CONFLICT') issue.draft = null;
    issue.error = error;
    toast('领用失败：' + (error.code || error.message), 'error');
  } finally {
    issue.submitting = false;
    render();
  }
}

function renderIssueSuccess() {
  const data = state.issue.success || {};
  const operation = data.operation || {};
  const lines = Array.isArray(data.lines) ? data.lines : [];
  dom.view.appendChild(
    el('section', { class: 'panel' }, [
      el('h2', {}, '领用成功' + (data.replayed ? '（服务器重放）' : '')),
      el('dl', { class: 'kv' }, [
        el('dt', {}, '作业单'), el('dd', {}, (operation.name || '—') + (operation.id ? '（ID ' + operation.id + '）' : '')),
        el('dt', {}, '领用人'), el('dd', {}, operation.borrower_name || '—'),
        el('dt', {}, '项目'), el('dd', {}, operation.project || '—'),
        el('dt', {}, '操作人'), el('dd', {}, operation.actor_name || '—'),
      ]),
      el('h3', {}, '领用明细（归还时必须用 issue_line_id）'),
      table(
        [{ label: 'issue_line_id' }, { label: '袋' }, { label: '数量', num: true }, { label: '未归还', num: true }],
        lines.map((line) => [String(line.issue_line_id), line.trace_code || String(line.bag_id), fmtQty(line.quantity), fmtQty(line.outstanding_quantity)]),
      ),
      el('div', { class: 'row', style: 'margin-top:12px' }, [
        el('button', {
          class: 'btn primary',
          type: 'button',
          onclick: () => {
            state.issue.success = null;
            state.return.selected = null;
            state.return.issues = [];
            state.return.next = null;
            state.return.cursor = null;
            state.return.loaded = false;
            nav('return');
          },
        }, '去归还'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => call('ui.open', { action: 'issue_list' }).catch((error) => toast(error.message, 'error')),
        }, '打开 Odoo 领用记录'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => {
            state.issue.success = null;
            render();
          },
        }, '继续领用'),
      ]),
      el('p', { class: 'muted', style: 'margin-top:10px' }, '请保留 issue_line_id；归还接口只接受原领用明细，不能按器件总量归还。'),
    ]),
  );
}

/* ------------------------------------------------------------------ */
/* Return                                                              */
/* ------------------------------------------------------------------ */

function renderReturn() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('归还'));
    return;
  }
  if (state.return.success) {
    renderReturnSuccess();
    return;
  }
  const ret = state.return;

  const queryInput = el('input', { type: 'search', placeholder: '按袋追溯码或项目筛选', value: ret.query });
  queryInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      ret.query = queryInput.value.trim();
      void loadReturnIssues(true);
    }
  });

  const panel = el('section', { class: 'panel' }, [
    el('h2', {}, '按原领用单归还'),
    el('p', { class: 'muted' }, '归还必须选择真实 issue_line_id，数量不得超过未归还余额；服务器会在行锁后重新校验。'),
    el('div', { class: 'row' }, [
      el('div', { class: 'grow' }, queryInput),
      el('button', {
        class: 'btn',
        type: 'button',
        disabled: ret.loading,
        onclick: () => {
          ret.query = queryInput.value.trim();
          void loadReturnIssues(true);
        },
      }, ret.loading ? '查询中…' : '查询未归还'),
    ]),
  ]);

  if (ret.error) panel.appendChild(el('div', { style: 'margin-top:10px' }, errorBox(ret.error, { retry: () => loadReturnIssues(true) })));

  if (ret.issues.length) {
    panel.appendChild(
      table(
        [{ label: '领用单 ID' }, { label: '袋' }, { label: '领用', num: true }, { label: '已还', num: true }, { label: '未还', num: true }, { label: '领用人' }, { label: '项目' }, { label: '时间' }, { label: '' }],
        ret.issues.map((issue) => [
          String(issue.issue_line_id),
          el('span', { class: 'mono' }, issue.trace_code || String(issue.bag_id)),
          fmtQty(issue.quantity),
          fmtQty(issue.returned_quantity),
          fmtQty(issue.outstanding_quantity),
          issue.borrower_name || String(issue.borrower_id || ''),
          issue.project || '—',
          fmtDate(issue.date),
          el('button', {
            class: 'btn small' + (ret.selected && ret.selected.issue_line_id === issue.issue_line_id ? ' primary' : ''),
            type: 'button',
            onclick: () => {
              ret.selected = issue;
              ret.quantity = String(issue.outstanding_quantity);
              ret.error = null;
              render();
            },
          }, ret.selected && ret.selected.issue_line_id === issue.issue_line_id ? '已选择' : '选择'),
        ]),
      ),
    );
    if (ret.next) {
      panel.appendChild(
        el('div', { class: 'row', style: 'margin-top:10px;justify-content:center' }, [
          el('button', { class: 'btn', type: 'button', disabled: ret.loading, onclick: () => loadReturnIssues(false) }, '加载更多未归还'),
        ]),
      );
    }
  } else if (!ret.loading) {
    panel.appendChild(el('div', { class: 'empty', style: 'margin-top:10px' }, '没有未归还的领用记录。'));
  }

  if (ret.selected) {
    const selected = ret.selected;
    const qtyInput = el('input', { type: 'number', min: '0.000001', step: 'any', value: ret.quantity });
    qtyInput.addEventListener('input', () => {
      ret.quantity = qtyInput.value;
    });
    const noteInput = el('textarea', { placeholder: '可选备注', value: ret.note });
    noteInput.addEventListener('input', () => {
      ret.note = noteInput.value;
    });
    panel.appendChild(el('h3', {}, '归还明细'));
    panel.appendChild(
      el('div', { class: 'panel', style: 'background:var(--panel-2)' }, [
        el('dl', { class: 'kv' }, [
          el('dt', {}, '原领用单'), el('dd', {}, String(selected.issue_line_id)),
          el('dt', {}, '袋'), el('dd', { class: 'mono' }, selected.trace_code || '—'),
          el('dt', {}, '领用人 / 项目'), el('dd', {}, (selected.borrower_name || '—') + ' / ' + (selected.project || '—')),
          el('dt', {}, '原领用 / 已还 / 未还'), el('dd', {}, fmtQty(selected.quantity) + ' / ' + fmtQty(selected.returned_quantity) + ' / ' + fmtQty(selected.outstanding_quantity)),
        ]),
        el('div', { class: 'grid-2', style: 'margin-top:10px' }, [
          field('本次归还数量', qtyInput, '不能超过未归还数量 ' + fmtQty(selected.outstanding_quantity)),
          field('备注（可选）', noteInput),
        ]),
      ]),
    );
  }

  panel.appendChild(
    el('div', { class: 'row', style: 'margin-top:12px;justify-content:space-between' }, [
      el('p', { class: 'muted' }, ret.draft ? '当前请求号：' + shortKey(ret.draft.key) : '提交时生成请求号；修改内容会换新请求号。'),
      el('button', {
        class: 'btn primary',
        type: 'button',
        disabled: ret.submitting || !ret.selected,
        onclick: () => submitReturn(false),
      }, ret.submitting ? '提交中…' : '确认归还'),
    ]),
  );
  dom.view.appendChild(panel);
  if (!ret.loaded && !ret.loading) void loadReturnIssues(true);
}

async function loadReturnIssues(reset) {
  const ret = state.return;
  if (ret.loading) return;
  ret.loading = true;
  ret.error = null;
  if (reset) {
    ret.issues = [];
    ret.next = null;
    ret.cursor = null;
    ret.selected = null;
  }
  render();
  try {
    const data = await call('inventory.issues', {
      query: ret.query,
      outstanding_only: true,
      cursor: ret.cursor,
      limit: 30,
    });
    const issues = Array.isArray(data.issues) ? data.issues : [];
    ret.issues = reset ? issues : ret.issues.concat(issues);
    ret.next = data.next_cursor || null;
    ret.cursor = data.next_cursor || null;
    ret.loaded = true;
  } catch (error) {
    ret.error = error;
    ret.loaded = true;
  } finally {
    ret.loading = false;
    render();
  }
}

function buildReturnPayload() {
  const ret = state.return;
  if (!ret.selected) throw Object.assign(new Error('请选择原领用记录。'), { code: 'VALIDATION_ERROR' });
  const quantity = Number(ret.quantity);
  if (!Number.isFinite(quantity) || quantity <= 0) throw Object.assign(new Error('归还数量必须大于 0。'), { code: 'VALIDATION_ERROR' });
  if (quantity - Number(ret.selected.outstanding_quantity) > 1e-9) {
    throw Object.assign(new Error('归还数量超过未归还数量 ' + fmtQty(ret.selected.outstanding_quantity) + '。'), { code: 'VALIDATION_ERROR' });
  }
  return {
    issue_line_id: Number(ret.selected.issue_line_id),
    quantity,
    note: ret.note.trim(),
  };
}

async function submitReturn(skipConfirm) {
  const ret = state.return;
  if (ret.submitting) return;
  let payload;
  try {
    payload = buildReturnPayload();
  } catch (error) {
    ret.error = error;
    render();
    return;
  }
  ret.draft = ret.draft ? withPayload(ret.draft, payload) : createDraft('inventory.return', payload);
  if (!skipConfirm) {
    const confirmed = await confirmModal(
      '确认归还',
      el('div', {}, [
        el('p', {}, '原领用单：' + payload.issue_line_id),
        el('p', {}, '袋：' + (ret.selected.trace_code || '')),
        el('p', {}, '归还数量：' + fmtQty(payload.quantity) + ' / 未还 ' + fmtQty(ret.selected.outstanding_quantity)),
        el('p', { class: 'muted' }, '提交后会写回原袋原库位，并更新原领用明细的未归还余额。'),
      ]),
    );
    if (!confirmed) return;
  }
  let submitted;
  try {
    submitted = beginSubmit(ret.draft);
  } catch (error) {
    ret.error = error;
    toast(error.message, 'warn');
    return;
  }
  ret.draft = submitted;
  ret.submitting = true;
  ret.error = null;
  render();
  try {
    const data = await call('inventory.return', Object.assign({}, payload, { request_key: submitted.key }), 60000);
    ret.draft = markSuccess(submitted, data);
    ret.success = data;
    ret.draft = null;
    ret.selected = null;
    ret.quantity = '';
    ret.issues = [];
    ret.loaded = false;
    toast('归还成功' + (data.replayed ? '（服务器重放，未重复记账）' : ''), 'ok');
  } catch (error) {
    ret.draft = markFailure(submitted, error);
    if (error.code === 'CONFLICT') ret.draft = null;
    ret.error = error;
    toast('归还失败：' + (error.code || error.message), 'error');
  } finally {
    ret.submitting = false;
    render();
  }
}

function renderReturnSuccess() {
  const data = state.return.success || {};
  const operation = data.operation || {};
  const bag = data.bag || {};
  const issueLine = data.issue_line || {};
  dom.view.appendChild(
    el('section', { class: 'panel' }, [
      el('h2', {}, '归还成功' + (data.replayed ? '（服务器重放）' : '')),
      el('dl', { class: 'kv' }, [
        el('dt', {}, '作业单'), el('dd', {}, (operation.name || '—') + (operation.id ? '（ID ' + operation.id + '）' : '')),
        el('dt', {}, '袋'), el('dd', { class: 'mono' }, bag.trace_code || '—'),
        el('dt', {}, '本次归还后未归还'), el('dd', {}, fmtQty(data.outstanding_quantity)),
        el('dt', {}, '原领用单'), el('dd', {}, String(issueLine.issue_line_id || '—')),
      ]),
      el('div', { class: 'row', style: 'margin-top:12px' }, [
        el('button', {
          class: 'btn primary',
          type: 'button',
          onclick: () => {
            state.return.success = null;
            state.return.loaded = false;
            nav('return');
          },
        }, '继续归还'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => call('ui.open', { action: 'issue_list' }).catch((error) => toast(error.message, 'error')),
        }, '打开 Odoo 领用记录'),
      ]),
    ]),
  );
}

/* ------------------------------------------------------------------ */
/* Trace                                                               */
/* ------------------------------------------------------------------ */

const KIND_LABEL = {
  bag: '袋追溯码',
  location: '库位码',
  sn: '物料 SN',
  lcsc: '立创 C 编号',
  jlc: '立创原厂物料袋',
  unknown: '未知',
};

function renderTrace() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('袋/库位追溯'));
    return;
  }
  const trace = state.trace;
  const input = el('input', { type: 'text', placeholder: 'LABB:... / LABL:... / SN / C123 / 立创原厂袋二维码', value: trace.raw, class: 'mono' });
  input.addEventListener('input', () => {
    trace.raw = input.value.trim();
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void resolveTrace();
    }
  });

  dom.view.appendChild(
    el('section', { class: 'panel' }, [
      el('h2', {}, '袋 / 库位 / 物料追溯'),
      el('p', { class: 'muted' }, '服务端按真实编码规则识别；无法识别、歧义、无权限都会原样提示。'),
      el('div', { class: 'row' }, [
        el('div', { class: 'grow' }, input),
        el('button', { class: 'btn primary', type: 'button', disabled: trace.loading, onclick: () => resolveTrace() }, trace.loading ? '解析中…' : '解析'),
      ]),
    ]),
  );

  if (trace.error) dom.view.appendChild(el('div', { style: 'margin-top:10px' }, errorBox(trace.error, { retry: () => resolveTrace() })));
  if (!trace.result) return;

  const data = trace.result;
  const bag = data.bag;
  const location = data.location;
  const material = data.material;
  const candidates = Array.isArray(data.candidates) ? data.candidates : [];
  const supplier = data.supplier_metadata || {};

  const panel = el('section', { class: 'panel' }, [
    el('h2', {}, '解析结果：' + (KIND_LABEL[data.kind] || data.kind || '未知')),
    el('dl', { class: 'kv' }, [
      el('dt', {}, '原始内容'), el('dd', { class: 'mono' }, data.raw || '—'),
      el('dt', {}, '规范化'), el('dd', { class: 'mono' }, data.normalized || '—'),
      el('dt', {}, 'item_key'), el('dd', { class: 'mono' }, data.item_key || '—'),
    ]),
  ]);

  if (bag) {
    panel.appendChild(el('h3', {}, '袋'));
    panel.appendChild(
      el('dl', { class: 'kv' }, [
        el('dt', {}, '追溯码'), el('dd', { class: 'mono' }, bag.trace_code || '—'),
        el('dt', {}, '物料 / SN'), el('dd', {}, (bag.name || '') + ' / ' + (bag.sn || '—')),
        el('dt', {}, '库位'), el('dd', {}, bagLocationName(bag)),
        el('dt', {}, '在库 / 可用 / 未归还'), el('dd', {}, fmtQty(bag.quantity) + ' / ' + (bagAvailableQuantity(bag) === null ? '—' : fmtQty(bagAvailableQuantity(bag))) + ' / ' + fmtQty(bag.outstanding_quantity)),
        el('dt', {}, '批次'), el('dd', {}, bagLotName(bag) || '—'),
        el('dt', {}, '收货时间'), el('dd', {}, fmtDate(bag.receipt_date) || '—'),
        el('dt', {}, '供应商订单 / 型号'), el('dd', {}, [bag.supplier_order, bag.supplier_mpn].filter(Boolean).join(' / ') || '—'),
      ]),
    );
    panel.appendChild(
      el('div', { class: 'row', style: 'margin-top:10px' }, [
        el('button', { class: 'btn primary', type: 'button', onclick: () => prefillIssueBag(bag) }, '领用此袋'),
        el('button', { class: 'btn', type: 'button', onclick: () => copyText(bag.trace_code || '', '已复制追溯码') }, '复制追溯码'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => call('ui.open', { action: 'bag_list' }).catch((error) => toast(error.message, 'error')),
        }, '打开 Odoo 袋列表'),
        el('button', {
          class: 'btn',
          type: 'button',
          onclick: () => call('ui.open', { action: 'label_open' }).catch((error) => toast(error.message, 'error')),
        }, '标签入口（Odoo）'),
      ]),
      el('p', { class: 'muted', style: 'margin-top:8px' }, '标签 PDF 与二维码由 Odoo 现有标签功能生成；本插件不虚构前端二维码。标签入口通常仅库存管理员可用。'),
    );
  }

  if (location) {
    panel.appendChild(el('h3', {}, '库位'));
    panel.appendChild(
      el('dl', { class: 'kv' }, [
        el('dt', {}, '库码'), el('dd', { class: 'mono' }, location.code || '—'),
        el('dt', {}, '路径'), el('dd', {}, location.path || '—'),
      ]),
    );
  }

  if (material) {
    panel.appendChild(el('h3', {}, '物料'));
    panel.appendChild(
      el('dl', { class: 'kv' }, [
        el('dt', {}, 'item_key'), el('dd', { class: 'mono' }, material.item_key || '—'),
        el('dt', {}, '名称 / 型号'), el('dd', {}, (material.name || '') + ' / ' + (material.mpn || '—')),
        el('dt', {}, 'C 编号'), el('dd', { class: 'mono' }, material.catalog_code || '—'),
      ]),
    );
  }

  if (candidates.length) {
    panel.appendChild(el('h3', {}, '候选档案（必须人工选择，禁止自动取第一个）'));
    panel.appendChild(
      table(
        [{ label: '档案 ID' }, { label: 'SN' }, { label: '名称' }, { label: '型号' }, { label: '封装' }],
        candidates.map((candidate) => [
          String(candidate.product_template_id),
          candidate.sn || '—',
          candidate.name || '—',
          candidate.mpn || '—',
          candidate.package || '—',
        ]),
      ),
    );
  }

  if (Object.keys(supplier).length) {
    panel.appendChild(el('h3', {}, '供应商二维码元数据（仅供参考）'));
    panel.appendChild(el('pre', {}, JSON.stringify(supplier, null, 2)));
  }

  dom.view.appendChild(panel);
}

async function resolveTrace() {
  const trace = state.trace;
  const raw = trace.raw.trim();
  if (!raw) {
    trace.error = { code: 'VALIDATION_ERROR', message: '请输入要解析的追溯码。' };
    render();
    return;
  }
  trace.loading = true;
  trace.error = null;
  trace.result = null;
  render();
  try {
    trace.result = await call('inventory.resolve', { raw });
  } catch (error) {
    trace.error = error;
  } finally {
    trace.loading = false;
    render();
  }
}

/* ------------------------------------------------------------------ */
/* Settings / session                                                  */
/* ------------------------------------------------------------------ */

function connectionModeRadio(value, label, current) {
  const input = el('input', { type: 'radio', name: 'connection-mode', value, checked: current === value });
  input.addEventListener('change', () => {
    if (!input.checked) return;
    state.settings.mode = value;
    render();
  });
  return el('label', { class: 'check', style: 'padding-bottom:0' }, [input, el('span', {}, label)]);
}

function renderSettings() {
  const settings = state.settings;
  const session = state.session;
  const bootstrap = state.bootstrap;
  const permissions = (bootstrap && bootstrap.permissions) || {};
  const isRelay = settings.mode !== 'direct';

  const relayInput = el('input', { type: 'text', value: settings.relayUrl, placeholder: 'http://127.0.0.1:49621', class: 'mono' });
  relayInput.addEventListener('input', () => {
    settings.relayUrl = relayInput.value.trim();
  });
  const tokenInput = el('input', {
    type: 'password',
    value: settings.pairingToken,
    placeholder: settings.hasPairingToken ? '本次启动已连接；如需更换请输入新配对码' : '粘贴桥接窗口显示的配对码',
    autocomplete: 'off',
  });
  tokenInput.addEventListener('input', () => {
    settings.pairingToken = tokenInput.value.trim();
  });
  const serverInput = el('input', { type: 'text', value: settings.serverUrl, placeholder: 'http://lc.rm.com', class: 'mono' });
  serverInput.addEventListener('input', () => {
    settings.serverUrl = serverInput.value.trim();
  });
  const dbInput = el('input', { type: 'text', value: settings.db, placeholder: 'LcHardwareHouse', class: 'mono' });
  dbInput.addEventListener('input', () => {
    settings.db = dbInput.value.trim();
  });
  const loginInput = el('input', { type: 'text', value: settings.login, placeholder: 'Odoo 登录名', autocomplete: 'username' });
  loginInput.addEventListener('input', () => {
    settings.login = loginInput.value.trim();
  });
  const passwordInput = el('input', {
    type: 'password',
    value: settings.password,
    placeholder: 'Odoo 密码（仅本次登录使用）',
    autocomplete: 'current-password',
  });
  passwordInput.addEventListener('input', () => {
    settings.password = passwordInput.value;
  });

  const panel = el('section', { class: 'panel' }, [
    el('h2', {}, '连接与账户'),
    el('p', { class: 'muted' }, '推荐使用本机桥接：先运行压缩包里的「start-windows.cmd」，把窗口里的配对码填到下面。桥接只在本机运行，不需要修改 Odoo 服务器。'),
    el('div', { class: 'chips', style: 'margin:8px 0 12px' }, [
      connectionModeRadio('relay', '本机桥接（推荐）', settings.mode),
      connectionModeRadio('direct', '直接连接 Odoo（高级）', settings.mode),
    ]),
  ]);

  if (isRelay) {
    panel.appendChild(
      el('div', { class: 'grid-2' }, [
        field('本机地址', relayInput, '默认 http://127.0.0.1:49621；只接受本机地址。'),
        field('配对码', tokenInput, '每次启动桥接都会生成新配对码；只保存在内存中。'),
      ]),
    );
  } else {
    panel.appendChild(
      el('div', { class: 'grid-2' }, [
        field('Odoo 地址', serverInput, '默认 http://lc.rm.com；可改为 IP/端口。'),
        field('数据库名', dbInput, '默认 LcHardwareHouse。'),
      ]),
    );
  }

  panel.appendChild(
    el('div', { class: 'grid-2', style: 'margin-top:10px' }, [
      field('Odoo 登录名', loginInput, '只保存登录名，不保存密码。'),
      field('Odoo 密码', passwordInput, '只用于本次登录，不写入配置、不写日志。'),
    ]),
  );

  panel.appendChild(
    el('div', { class: 'row', style: 'margin-top:12px' }, [
      el('button', { class: 'btn', type: 'button', disabled: settings.busy, onclick: () => saveConnection() }, '保存设置'),
      el('button', { class: 'btn primary', type: 'button', disabled: settings.busy, onclick: () => login() }, settings.busy ? '处理中…' : (isRelay ? '连接并登录' : '直接登录')),
      el('button', { class: 'btn danger', type: 'button', disabled: settings.busy || !session.active, onclick: () => logout() }, '注销'),
    ]),
  );

  panel.appendChild(
    el('p', { class: 'notice', style: 'margin-top:12px' }, '登录状态只在当前 EDA 会话内保持，不承诺免密天数。密码和配对码不会被保存；关闭 EDA 或重载扩展后需要重新输入。'),
  );

  if (settings.error) panel.appendChild(el('div', { style: 'margin-top:10px' }, errorBox(settings.error)));
  if (settings.message) panel.appendChild(el('div', { class: 'notice ok', style: 'margin-top:10px' }, settings.message));

  panel.appendChild(el('h3', {}, '当前会话'));
  panel.appendChild(
    el('dl', { class: 'kv' }, [
      el('dt', {}, '状态'), el('dd', {}, session.active ? '已登录' : '未登录'),
      el('dt', {}, '连接方式'), el('dd', {}, isRelay ? '本机桥接（' + settings.relayUrl + '）' : '直接连接 Odoo'),
      el('dt', {}, '用户'), el('dd', {}, session.active ? (session.name || '') + '（' + (session.username || '') + '）' : '—'),
      el('dt', {}, 'UID'), el('dd', {}, session.uid ? String(session.uid) : '—'),
      el('dt', {}, '数据库'), el('dd', {}, session.db || settings.db || '—'),
    ]),
  );

  if (bootstrap) {
    panel.appendChild(el('h3', {}, '权限（服务器返回）'));
    panel.appendChild(
      table(
        [{ label: '能力' }, { label: '允许' }],
        [
          ['入库', permissions.can_receipt],
          ['领用', permissions.can_issue],
          ['归还', permissions.can_return],
          ['代他人领用', permissions.can_issue_for_others],
          ['新建库位', permissions.can_manage_locations],
          ['标签', permissions.can_manage_labels],
          ['管理员', permissions.is_manager],
        ].map(([label, value]) => [label, value ? '是' : '否']),
      ),
    );
    panel.appendChild(el('p', { class: 'muted', style: 'margin-top:8px' }, '权限以 Odoo 服务器校验为准。'));
  } else if (session.active) {
    panel.appendChild(
      el('div', { class: 'row', style: 'margin-top:10px' }, [
        el('button', { class: 'btn', type: 'button', onclick: () => loadBootstrap() }, '刷新权限与库位'),
        state.bootstrapError ? errorBox(state.bootstrapError) : el('span', { class: 'muted' }, state.bootstrapLoading ? '正在读取…' : '尚未读取权限。'),
      ]),
    );
  }

  if (isRelay) {
    panel.appendChild(el('h3', {}, '使用提示'));
    panel.appendChild(
      el('ul', { class: 'list' }, [
        el('li', {}, '连接失败时，先确认「start-windows.cmd」窗口仍然打开。'),
        el('li', {}, '配对码每次启动都会变化，请从桥接窗口重新复制。'),
        el('li', {}, '入库、领用、归还都要在确认弹窗后才会写入 Odoo。'),
        el('li', {}, '如果账号没有对应权限，界面会显示服务器返回的权限提示。'),
      ]),
    );
  }

  dom.view.appendChild(panel);
}

async function saveConnection() {
  const settings = state.settings;
  settings.busy = true;
  settings.error = null;
  settings.message = null;
  render();
  try {
    const result = await call('config.save', {
      mode: settings.mode,
      relayUrl: settings.relayUrl,
      pairingToken: settings.pairingToken,
      serverUrl: settings.serverUrl,
      db: settings.db,
      login: settings.login,
    });
    state.init.config = result.config;
    state.init.connection = result.connection;
    state.session = result.session;
    state.sessionError = null;
    settings.hasPairingToken = Boolean(result.connection && result.connection.hasPairingToken);
    settings.message = '设置已保存（未保存密码和配对码）。';
    toast('设置已保存', 'ok');
  } catch (error) {
    settings.error = error;
  } finally {
    settings.busy = false;
    render();
  }
}

async function login() {
  const settings = state.settings;
  if (!settings.login || !settings.password) {
    settings.error = { code: 'VALIDATION_ERROR', message: '请填写 Odoo 登录名和密码。' };
    render();
    return;
  }
  if (settings.mode !== 'direct' && !settings.pairingToken && !settings.hasPairingToken) {
    settings.error = { code: 'VALIDATION_ERROR', message: '请先运行本机桥接，并填写窗口里的配对码。' };
    render();
    return;
  }
  settings.busy = true;
  settings.error = null;
  settings.message = null;
  render();
  try {
    const result = await call(
      'session.login',
      {
        mode: settings.mode,
        relayUrl: settings.relayUrl,
        pairingToken: settings.pairingToken,
        serverUrl: settings.serverUrl,
        db: settings.db,
        login: settings.login,
        password: settings.password,
      },
      60000,
    );
    state.session = result.session;
    state.init.session = result.session;
    state.init.config = result.config;
    state.init.connection = result.connection;
    settings.hasPairingToken = Boolean(result.connection && result.connection.hasPairingToken);
    settings.password = '';
    settings.pairingToken = '';
    settings.message = '登录成功。会话仅在当前 EDA 会话内保持。';
    state.bootstrap = null;
    state.bootstrapError = null;
    toast('登录成功', 'ok');
    void loadBootstrap();
  } catch (error) {
    settings.error = error;
  } finally {
    settings.busy = false;
    render();
  }
}

async function logout() {
  const settings = state.settings;
  settings.busy = true;
  settings.error = null;
  settings.message = null;
  render();
  try {
    const result = await call('session.logout');
    state.session = { active: false, uid: null, sessionMode: 'none' };
    state.init.session = state.session;
    state.bootstrap = null;
    state.bootstrapError = null;
    settings.message = result.warning || '已注销并清除本地会话。';
    toast('已注销', 'ok');
  } catch (error) {
    settings.error = error;
  } finally {
    settings.busy = false;
    render();
  }
}

/* ------------------------------------------------------------------ */
/* Diagnostics                                                         */
/* ------------------------------------------------------------------ */

function renderDiagnostics() {
  const diag = state.diagnostics;
  const panel = el('section', { class: 'panel' }, [
    el('h2', {}, '诊断'),
    el('p', { class: 'muted' }, '日志会脱敏 password/token/session_id/cookie/authorization；仍建议只把必要片段交给管理员。'),
  ]);
  if (diag.error) panel.appendChild(errorBox(diag.error, { retry: () => loadDiagnostics() }));
  panel.appendChild(
    el('div', { class: 'row', style: 'margin-top:10px' }, [
      el('button', { class: 'btn primary', type: 'button', disabled: diag.loading, onclick: () => loadDiagnostics() }, diag.loading ? '读取中…' : '刷新'),
      el('button', { class: 'btn', type: 'button', disabled: !diag.data, onclick: () => copyText((diag.data && diag.data.text) || '', '已复制诊断日志') }, '复制日志'),
      el('button', {
        class: 'btn danger',
        type: 'button',
        disabled: !diag.data,
        onclick: async () => {
          try {
            await call('diag.clear');
            state.diagnostics.data = null;
            await loadDiagnostics();
            toast('日志已清空', 'ok');
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }, '清空'),
    ]),
  );

  if (diag.data) {
    const s = diag.data.state || {};
    const sdk = s.sdk || {};
    panel.appendChild(el('h3', {}, '环境'));
    panel.appendChild(
      el('dl', { class: 'kv' }, [
        el('dt', {}, '插件版本'), el('dd', {}, s.version || VERSION),
        el('dt', {}, '服务器 / 数据库'), el('dd', {}, ((s.config && s.config.serverUrl) || '—') + ' / ' + ((s.config && s.config.db) || '—')),
        el('dt', {}, '会话'), el('dd', {}, s.session && s.session.active ? '已登录（' + (s.session.sessionMode || '') + '）' : '未登录'),
        el('dt', {}, '连接方式'), el('dd', {}, s.connection && s.connection.mode === 'relay' ? '本机桥接 ' + (s.connection.relayUrl || '') : '直接连接 Odoo'),
        el('dt', {}, '网络接口'), el('dd', {}, sdk.clientUrl ? '可用' : '不可用'),
        el('dt', {}, '消息总线'), el('dd', {}, sdk.messageBus ? '可用' : '不可用'),
        el('dt', {}, 'sys_IFrame'), el('dd', {}, sdk.iframe ? '可用' : '不可用'),
        el('dt', {}, 'sys_Storage'), el('dd', {}, sdk.storage ? '可用' : '不可用'),
        el('dt', {}, '原理图器件/选中'), el('dd', {}, (sdk.schematicComponents ? '器件' : '无') + ' / ' + (sdk.schematicSelection ? '选中' : '无')),
      ]),
    );
    panel.appendChild(el('h3', {}, '接口'));
    panel.appendChild(
      el('pre', {}, [
        'POST /web/session/authenticate',
        'POST /web/session/get_session_info',
        'POST /web/session/destroy',
        'POST /lab/api/catalog/search|detail|categories|facets',
        'POST /lab/api/inventory/bootstrap|locations|resolve_code',
        'POST /lab/api/inventory/receipt|issue|return|issues|history',
        'GET  /lab/api/asset?url=...（仅用于图片，同源白名单）',
      ].join('\n')),
    );
    panel.appendChild(el('h3', {}, '日志'));
    panel.appendChild(el('pre', {}, diag.data.text || '（暂无日志）'));
  }

  dom.view.appendChild(panel);
  if (!diag.data && !diag.loading) void loadDiagnostics();
}

async function loadDiagnostics() {
  state.diagnostics.loading = true;
  state.diagnostics.error = null;
  render();
  try {
    state.diagnostics.data = await call('diag.logs');
  } catch (error) {
    state.diagnostics.error = error;
  } finally {
    state.diagnostics.loading = false;
    render();
  }
}
