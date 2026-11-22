import { createBridge, readPanelPayload } from './bridge-client.js';
import { beginSubmit, markSuccess, markFailure } from '../shared/idempotency.js';
import {
  groupBom,
  compareLine,
  summarize,
  bomTsv,
  bagTraceSummary,
  equivalentsRequestLines,
  groupUnmappedByValue,
  attachValueMatches,
  pickValueCandidate,
  valueSubstituteLines,
  valueSubstitutionNote,
  attachEquivalents,
  substituteLines,
  substitutionNote,
  BOM_STATUS,
} from '../shared/bom.js';
import {
  OUTBOUND_OUTCOME,
  freezeOutboundAttempt,
  outboundRequestParams,
  classifyOutboundResponse,
  classifyOutboundError,
  outboundNotice,
  outboundToast,
} from '../shared/outbound.js';
import {
  bagAvailableQuantity,
  bagLocationName,
  bagLotName,
  issueBagName,
  issueBorrowerName,
  locationSummary,
} from '../shared/detail.js';

const VERSION = '4.1.1';

const TABS = [
  { id: 'inventory', label: '器件库' },
  { id: 'bom', label: '原理图库存' },
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

/**
 * BOM one-click outbound state. `attempt` is the immutable, key-bound action
 * (confirmed bags + borrower + project); it survives an UNKNOWN result so the
 * operator can retry with the SAME request key.
 */
function emptyBomOutbound() {
  return {
    computing: false,
    submitting: false,
    plan: null,
    sourceLines: null,
    shortage: null,
    error: null,
    attempt: null,
    result: null,
    outcome: null,
    notice: null,
  };
}

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
    scope: 'selected',
    loading: false,
    refreshing: false,
    scan: null,
    warnings: [],
    rows: [],
    summary: null,
    unmapped: [],
    error: null,
    // S5 equivalents: candidates are suggestions only; `row.substitute` is set
    // by an explicit operator click and is the ONLY way a substitute is issued.
    valueMatchLoading: false,
    valueMatchError: null,
    valueMatchToken: 0,
    unmappedGroups: null,
    equivalentsLoading: false,
    equivalentsError: null,
    equivalentsExpanded: new Set(),
    equivalentsToken: 0,
    outbound: emptyBomOutbound(),
  },
  settings: {
    serverUrl: '',
    token: '',
    hasToken: false,
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
  const body = [];
  rows.forEach((row, index) => {
    body.push(el('tr', {}, row.map((cell, column) => el('td', { class: headers[column] && headers[column].num ? 'num' : '' }, cell))));
    // Optional extra row rendered directly below a data row (e.g. BOM equivalents).
    if (typeof options.rowAfter === 'function') {
      const extra = options.rowAfter(row, index);
      if (extra) body.push(extra);
    }
  });
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
  const cfg = (state.init && state.init.config) || {};
  parts.push(cfg.serverUrl || '未配置服务器');
  if (isActive()) {
    parts.push('用户 ' + (state.session.name || state.session.username || 'uid ' + state.session.uid));
    parts.push('密钥认证');
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
  } catch (error) {
    state.bootstrapError = error;
  } finally {
    state.bootstrapLoading = false;
    if (['settings', 'bom'].includes(state.tab)) render();
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
  state.settings.serverUrl = config.serverUrl || 'https://team.l-creation.club';
  state.settings.hasToken = Boolean(config.hasToken);
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
  // EDA 插件不加载器件图片：<img> 发不了 Authorization 头，而图片端点
  // 只认 bearer。BOM 对比与库存查询不需要图，详情页直接显示占位。

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
        [{ label: '追溯码' }, { label: '在库', num: true }, { label: '可用', num: true }, { label: '未归还', num: true }, { label: '库位' }, { label: '批次/收货' }],
        bags.map((bag) => [
          el('span', { class: 'mono' }, bag.trace_code || '—'),
          fmtQty(bag.quantity),
          bagAvailableQuantity(bag) === null ? '—' : fmtQty(bagAvailableQuantity(bag)),
          fmtQty(bag.outstanding_quantity),
          bagLocationName(bag),
          [bagLotName(bag), fmtDate(bag.receipt_date)].filter(Boolean).join(' / ') || '—',
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
    panel.appendChild(el('p', { class: 'muted' }, '归还需按原领用明细（issue_line_id），请在 Odoo 网页端或 Flutter 客户端办理。'));
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

/** Column count of the comparison table (the equivalents sub-row spans all of them). */
const BOM_COLUMNS = 9;

function bomStatusChip(status) {
  const cls = status === BOM_STATUS.OK ? 'ok' : status === BOM_STATUS.SHORT ? 'danger' : status === BOM_STATUS.UNKNOWN ? 'warn' : '';
  return el('span', { class: 'chip ' + cls }, BOM_STATUS_LABEL[status] || status);
}

/** Status cell: an explicit substitute selection overrides the stock status. */
function bomStatusCell(row) {
  if (row.substitute) {
    return el('div', {}, [
      el('span', { class: 'chip ok' }, '已选替代'),
      el('div', { class: 'mono muted', style: 'margin-top:4px' }, row.code + ' → ' + codeOf(row.substitute)),
    ]);
  }
  return bomStatusChip(row.status);
}

/* ------------------------------------------------------------------ */
/* BOM equivalents (S5): candidates only, the operator chooses         */
/* ------------------------------------------------------------------ */

function toggleBomEquivalents(row) {
  const key = row.itemKey || 'lcsc:' + row.code;
  if (state.bom.equivalentsExpanded.has(key)) state.bom.equivalentsExpanded.delete(key);
  else state.bom.equivalentsExpanded.add(key);
  render();
}

/**
 * Select (or clear) one candidate for a BOM line. A row holds at most ONE
 * substitute; picking another replaces the previous choice. Nothing is ever
 * auto-selected.
 */
function selectBomSubstitute(row, candidate, checked) {
  const key = row.itemKey || 'lcsc:' + row.code;
  state.bom.rows = state.bom.rows.map((entry) => {
    if ((entry.itemKey || 'lcsc:' + entry.code) !== key) return entry;
    const next = Object.assign({}, entry);
    if (checked) next.substitute = candidate;
    else delete next.substitute;
    return next;
  });
  render();
}

function bomEquivalentCandidateLine(row, candidate) {
  const chosen = Boolean(row.substitute && row.substitute.item_key === candidate.item_key);
  const box = el('input', { type: 'checkbox', checked: chosen });
  box.addEventListener('change', () => selectBomSubstitute(row, candidate, box.checked));
  const locations = (candidate.locations || [])
    .map((location) => location.location || location.name || location.path || '')
    .filter(Boolean)
    .join(' ');
  const bags = (candidate.bags || [])
    .map((bag) => bag.trace_code || '')
    .filter(Boolean)
    .join(',');
  const line = el('div', { class: 'bom-equivalent-row' }, [
    el('label', { class: 'check bom-equivalent-check' }, [box, el('span', {}, chosen ? '已选' : '选用')]),
    el('span', { class: 'mono' }, codeOf(candidate) || candidate.item_key || '—'),
    el('span', {}, candidate.brand || '—'),
    el('span', { class: 'bom-equivalent-name' }, candidate.name || '—'),
    el('span', {}, '可用 ' + fmtQty(candidate.available)),
    el('span', { class: 'muted' }, locations || '—'),
    el('span', { class: 'muted' }, '袋 ' + (bags || '—')),
    candidate.confidence === 'weak' ? el('span', { class: 'chip weak' }, '依据较弱') : null,
  ]);
  const details = [];
  if ((candidate.matched || []).length) {
    details.push(
      el('div', { class: 'bom-equivalent-note' }, '一致：' + candidate.matched.map((item) => item.name + ' ' + item.value).join('、')),
    );
  }
  if ((candidate.conflicts || []).length) {
    details.push(
      el(
        'div',
        { class: 'bom-equivalent-note muted' },
        '差异：' + candidate.conflicts.map((item) => item.name + ' ' + (item.source ?? '') + ' → ' + (item.candidate ?? '')).join('、'),
      ),
    );
  }
  return el('div', { class: 'bom-equivalent-candidate' }, [line].concat(details));
}

/** The extra table row rendered under one BOM line; null when it has no candidates. */
function bomEquivalentsExtraRow(row, columnCount) {
  // 无 C 编号的行没有 equivalents（候选直接显示在库位列里）。
  if (!row || row.unmappedGroup) return null;
  const eq = row.equivalents;
  if (!eq || !Array.isArray(eq.candidates) || !eq.candidates.length) return null;
  const key = row.itemKey || 'lcsc:' + row.code;
  const expanded = state.bom.equivalentsExpanded.has(key);
  const toggle = el(
    'button',
    {
      class: 'bom-equivalents-toggle',
      type: 'button',
      'aria-expanded': expanded ? 'true' : 'false',
      onclick: () => toggleBomEquivalents(row),
    },
    (expanded ? '▾ ' : '▸ ') + '等效 ' + eq.candidates.length,
  );
  const content = el('div', { class: 'bom-equivalents' }, [toggle]);
  if (expanded) {
    if (eq.basis === 'package_category') {
      content.appendChild(
        el('div', { class: 'bom-equivalent-note warn' }, '源器件缺少参数，以下候选仅按封装与分类匹配，请人工确认'),
      );
    }
    for (const candidate of eq.candidates) content.appendChild(bomEquivalentCandidateLine(row, candidate));
  }
  return el('tr', { class: 'bom-equivalents-row' }, el('td', { colspan: String(columnCount) }, content));
}

function renderBom() {
  if (!isActive()) {
    dom.view.appendChild(loginGate('原理图库存'));
    return;
  }
  const bom = state.bom;

  const scope = bom.scope;
  const radios = el('div', { class: 'chips' }, [
    scopeRadio('selected', '选中器件', scope),
    scopeRadio('project', '当前工程 BOM', scope),
    scopeRadio('page', '当前图页', scope),
    scopeRadio('loaded', '已加载图页', scope),
  ]);

  dom.view.appendChild(
    el('section', { class: 'panel' }, [
      el('h2', {}, '原理图库存与库位'),
      el('p', { class: 'muted' }, '选中器件后可直接查看库存与库位：按立创 C 编号归并器件，只读取 EDA 与 Odoo，不会修改原理图、BOM 或库存。数量按 1 块板计算。'),
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
      scope === 'selected'
        ? el('p', { class: 'notice', style: 'margin-top:10px' }, '在原理图中选中器件后点击「读取并对比」，即可查看这些器件的可用库存、库位路径与袋追溯码。未选中器件时请改用「当前图页」或「当前工程 BOM」。')
        : scope === 'project'
          ? el('p', { class: 'notice', style: 'margin-top:10px' }, '当前工程 BOM 由 EDA 制造数据导出（sch_/pcb_ManufactureData.getBomFile），覆盖全部图页，不依赖图页是否已加载。若导出不可用会自动改用已加载图页。')
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

  if (bom.outbound.notice) {
    const notice = bom.outbound.notice;
    dom.view.appendChild(
      el('div', { class: 'notice ' + notice.tone, style: 'margin-top:10px' }, [
        el('strong', {}, notice.title + '：'),
        notice.text,
      ]),
    );
  }
  if (bom.outbound.outcome === OUTBOUND_OUTCOME.UNKNOWN && bom.outbound.attempt) {
    const key = bom.outbound.attempt.draft.key;
    dom.view.appendChild(
      el('div', { style: 'margin-top:8px' }, [
        el('p', { class: 'muted' }, '本次请求号：' + shortKey(key) + '（原样重试会复用同一请求号）'),
        el('div', { class: 'row' }, [
          el(
            'button',
            {
              class: 'btn primary',
              type: 'button',
              disabled: bom.outbound.submitting,
              onclick: () => retryBomOutbound(),
            },
            bom.outbound.submitting ? '重试中…' : '原样重试（同一请求号）',
          ),
          el('button', { class: 'btn', type: 'button', onclick: () => copyText(key, '已复制请求号') }, '复制请求号'),
          el(
            'button',
            {
              class: 'btn',
              type: 'button',
              onclick: () => call('ui.open', { action: 'request_log' }).catch((error) => toast(error.message, 'error')),
            },
            '打开 Odoo 请求记账（人工核对）',
          ),
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
  if (bom.outbound.outcome === OUTBOUND_OUTCOME.SUCCESS && bom.outbound.result) {
    const data = bom.outbound.result;
    const lines = Array.isArray(data.lines) ? data.lines : [];
    dom.view.appendChild(
      section('一键出库已完成（真实领用单）', [
        table(
          [{ label: 'issue_line_id' }, { label: '袋' }, { label: '数量', num: true }, { label: '未归还', num: true }],
          lines.map((line) => [
            String(line.issue_line_id),
            line.trace_code || String(line.bag_id),
            fmtQty(line.quantity),
            fmtQty(line.outstanding_quantity),
          ]),
        ),
        el('p', { class: 'muted', style: 'margin-top:8px' }, '归还需使用上面的 issue_line_id，可在 Odoo 网页端或 Flutter 客户端的领用记录中办理。'),
      ]),
    );
  }

  if (bom.equivalentsLoading) {
    dom.view.appendChild(el('p', { class: 'muted', style: 'margin-top:8px' }, '正在检索等效候选…'));
  }
  if (bom.equivalentsError) {
    // Equivalents are an aid; a failure here never blocks the main comparison.
    dom.view.appendChild(
      el('div', { class: 'notice warn', style: 'margin-top:8px' }, [
        '等效候选检索失败：' + ((bom.equivalentsError && bom.equivalentsError.message) || '未知错误') + '（主表库存对比不受影响）',
      ]),
    );
  }

  const rows = bom.rows || [];
  // 无 C 编号的器件**并进主表**，不再单独一栏。用户说「没必要把没有立创
  // C 编号的器件单拿出来」——它们在 BOM 里同样是器件，只是身份靠值+封装。
  const unmappedRows = (bom.unmappedGroups || []).map((group) => ({
    unmappedGroup: group,
    status: BOM_STATUS.NO_CODE,
    code: '',
    name: group.value || '—',
    designators: group.designators || [],
    need: group.quantity,
  }));
  const allRows = rows.concat(unmappedRows);
  if (allRows.length) {
    const tableRows = allRows.map((row) => {
      if (row.unmappedGroup) {
        // 无编号行：C 编号列显示「无」，可用/缺口留空，库位列显示候选。
        return [
          bomStatusCell(row),
          el('span', { class: 'muted' }, '无'),
          el('span', {}, (row.unmappedGroup.value || '—') +
            (row.unmappedGroup.footprint ? ' · ' + row.unmappedGroup.footprint : '')),
          (row.designators || []).join(','),
          fmtQty(row.need),
          '—',
          '—',
          renderValueCandidates(row.unmappedGroup),
          '—',
        ];
      }
      // NOT_IN_CATALOG 是「资料库里没有这个 C 编号」，不是「库存为 0」。
      // 用户看到「库存未知」会以为是数据延迟，其实要去抓取或建档。
      const isNotInCatalog = row.status === BOM_STATUS.NOT_IN_CATALOG;
      return [
        bomStatusCell(row),
        el('span', { class: 'mono' }, row.code),
        row.name || '—',
        (row.designators || []).join(','),
        fmtQty(row.need),
        row.available === null ? '未知' : fmtQty(row.available),
        row.gap === null ? '未知' : fmtQty(row.gap),
        isNotInCatalog
          ? el('span', { class: 'muted' }, '资料库无此编号，需抓取或建档')
          : ((row.locations || [])
              .map((location) => locationSummary(location))
              .join(' ') || '—'),
        isNotInCatalog ? '—' : bagTraceSummary(row.bags),
      ];
    });
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
            { label: '袋' },
          ],
          tableRows,
          { rowAfter: (cells, index) => bomEquivalentsExtraRow(allRows[index], BOM_COLUMNS) },
        ),
        el('div', { class: 'row', style: 'margin-top:10px' }, [
          el('button', { class: 'btn', type: 'button', onclick: () => copyText(bomTsv(rows), '已复制对比表') }, '复制对比表'),
          el('button', { class: 'btn', type: 'button', onclick: () => exportBomCsv(rows) }, '导出 CSV'),
        ]),
      ]),
    );
  }

  // 无 C 编号的器件不再单独一栏——用户说「没必要把没有立创 C 编号的器件
  // 单拿出来」。它们的候选已经并进主表（见 bomUnmappedRows），
  // 这里只在检索失败时提示一句，避免静默。
  if (bom.valueMatchError) {
    dom.view.appendChild(
      section('值 + 封装检索失败', [
        errorBox(bom.valueMatchError, { retry: () => loadValueMatches() }),
        el('p', { class: 'muted' },
          '主表里「无 C 编号」的行暂时没有候选，但库存对比不受影响。'),
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

/**
 * Outbound lines. A row with an explicitly selected substitute issues ONLY the
 * candidate's C code for the gap; the original code is never issued as well.
 */
/**
 * 领用备注：既写明有编号行的等效替代，也写明无编号分组的替代。
 *
 * 用户要求「能选择并确定替代料」——选了什么必须留在领用单上，
 * 否则事后没法追溯这批料是按什么替换发的。
 */
function buildOutboundNote() {
  const parts = [substitutionNote(state.bom.rows)];
  const valueNote = valueSubstitutionNote(state.bom.unmappedGroups);
  if (valueNote) parts.push('无编号替代：' + valueNote);
  return parts.filter(Boolean).join('；').slice(0, 500);
}

function bomOutboundSourceLines(rows) {
  // 两部分：有 C 编号的行（含勾选的等效件），以及无编号但用户勾了替代料的分组。
  const lines = substituteLines(rows);
  const valueLines = valueSubstituteLines(state.bom.unmappedGroups);
  return lines.concat(valueLines);
}

async function openBomOutbound() {
  const out = state.bom.outbound;
  out.computing = true;
  out.error = null;
  out.shortage = null;
  out.plan = null;
  out.attempt = null;
  out.result = null;
  out.outcome = null;
  out.notice = null;
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

/** Apply a terminal outcome to the page. Only SUCCESS renders success wording. */
function applyOutboundOutcome(out, outcome, options = {}) {
  out.outcome = outcome;
  out.notice = outboundNotice(outcome, options);
  if (outcome !== OUTBOUND_OUTCOME.SUCCESS) out.result = null;
}

async function confirmBomOutbound() {
  const out = state.bom.outbound;
  const bootstrap = state.bootstrap || {};
  const borrowers = Array.isArray(bootstrap.borrowers) ? bootstrap.borrowers : [];
  if (!borrowers.length) {
    toast('没有可用的领用人，请先刷新连接或确认权限。', 'error');
    return;
  }
  const self = borrowers.find((borrower) => borrower.is_self);
  let borrowerId = String((self && self.id) || (borrowers[0] && borrowers[0].id) || '');
  let project = '';
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
    el('p', { class: 'muted' }, '确认后立即按袋扣减云端库存并生成领用单，不可撤销；归还需按原领用单，在 Odoo 网页端或 Flutter 客户端办理。'),
  ]);
  const ok = await confirmModal('一键出库（' + (out.plan || []).length + ' 个型号）', content, '确认出库');
  if (!ok) return;
  if (!project.trim()) {
    toast('请填写项目/用途。', 'error');
    return;
  }
  // A fresh confirmation always starts a NEW attempt (and therefore a new
  // request key). An existing UNKNOWN attempt is retried only via its own
  // 「原样重试」 button, never by re-running the confirm dialog.
  let attempt;
  try {
    attempt = freezeOutboundAttempt({
      borrowerId,
      project: project.trim(),
      note: buildOutboundNote(),
      plan: out.plan,
    });
  } catch (error) {
    out.error = error;
    render();
    toast(String(error.message || error), 'error', 6000);
    return;
  }
  out.attempt = attempt;
  out.shortage = null;
  out.result = null;
  out.outcome = null;
  out.notice = null;
  await submitBomOutbound(attempt);
}

/** Submit (or retry) the frozen attempt. Retry reuses the same request key. */
async function submitBomOutbound(attempt) {
  const out = state.bom.outbound;
  let submitted;
  try {
    submitted = beginSubmit(attempt.draft);
  } catch (error) {
    out.error = error;
    toast(error.message, 'warn');
    return;
  }
  attempt.draft = submitted;
  out.attempt = attempt;
  out.submitting = true;
  out.error = null;
  out.outcome = null;
  out.notice = null;
  render();
  try {
    const response = await call('inventory.outbound', outboundRequestParams(attempt), 120000);
    const outcome = classifyOutboundResponse(response);
    out.submitting = false;
    if (outcome === OUTBOUND_OUTCOME.SUCCESS) {
      attempt.draft = markSuccess(submitted, response);
      out.result = response.result || null;
      applyOutboundOutcome(out, OUTBOUND_OUTCOME.SUCCESS, {
        count: (response.plan || attempt.plan || []).length,
        replayed: Boolean(response.result && response.result.replayed),
      });
      const done = outboundToast(OUTBOUND_OUTCOME.SUCCESS, {
        count: (response.plan || attempt.plan || []).length,
      });
      toast(done.text, done.tone);
      await runBom();
      // runBom() resets outbound state; restore the terminal success so the
      // operator still sees the real issue lines.
      state.bom.outbound.result = out.result;
      state.bom.outbound.outcome = OUTBOUND_OUTCOME.SUCCESS;
      state.bom.outbound.notice = out.notice;
      render();
      return;
    }
    if (outcome === OUTBOUND_OUTCOME.RECONFIRM) {
      // Nothing written; the frozen allocation is stale. Drop it and let the
      // operator re-preview against live stock.
      attempt.draft = markFailure(submitted, { code: 'PRECONDITION_FAILED' });
      out.attempt = null;
      applyOutboundOutcome(out, OUTBOUND_OUTCOME.RECONFIRM);
      out.shortage = (response && response.shortage) || null;
      const redo = outboundToast(OUTBOUND_OUTCOME.RECONFIRM);
      toast(redo.text, redo.tone, 6000);
      render();
      return;
    }
    // FAILED / UNKNOWN from a business envelope: keep the attempt for retry.
    // UNKNOWN must stay retryable with the SAME key, so mark it ambiguous
    // rather than success (success would rotate the key on the next attempt).
    attempt.draft =
      outcome === OUTBOUND_OUTCOME.UNKNOWN
        ? markFailure(submitted, { code: 'TIMEOUT_AMBIGUOUS', mayHaveBeenSent: true })
        : markFailure(submitted, { code: (response && response.code) || 'FAILED' });
    applyOutboundOutcome(out, outcome);
    out.error = null;
    const failed = outboundToast(outcome);
    toast(failed.text, failed.tone, 6000);
    render();
  } catch (error) {
    const outcome = classifyOutboundError(error);
    attempt.draft = markFailure(submitted, error);
    out.submitting = false;
    out.error = error;
    applyOutboundOutcome(out, outcome);
    if (outcome === OUTBOUND_OUTCOME.RECONFIRM) out.attempt = null;
    const failed = outboundToast(outcome);
    // Include the server message, but never success wording for a non-success outcome.
    toast(failed.text + ' ' + String(error.message || error.code || error), failed.tone, 6000);
    render();
  }
}

async function retryBomOutbound() {
  const out = state.bom.outbound;
  if (!out.attempt || out.submitting) return;
  await submitBomOutbound(out.attempt);
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
      // Invalidate any in-flight equivalents response for the old scope.
      state.bom.equivalentsToken = (state.bom.equivalentsToken || 0) + 1;
      state.bom.equivalentsLoading = false;
      state.bom.equivalentsError = null;
      state.bom.equivalentsExpanded = new Set();
      state.bom.outbound = emptyBomOutbound();
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

/**
 * One batch equivalents request for the whole BOM (never per line). Failures
 * are recorded separately and never block the main stock comparison.
 */
/**
 * 一个分组的候选单元格：每个候选可勾选。
 *
 * 用户要求「能选择并确定替代料」——勾选是唯一入口，绝不自动选。
 * 同一组只能选一条，勾第二条自动替换第一条。
 */
function renderValueCandidates(group) {
  const candidates = Array.isArray(group && group.candidates) ? group.candidates : [];
  if (!candidates.length) {
    return el('span', { class: 'muted' },
      group && group.query ? '实验室没有这个规格的现货' : '缺少值或封装，无法检索');
  }
  const chosen = group.substitute && group.substitute.item_key;
  return el('div', {}, candidates.map((item) => {
    const picked = chosen === item.item_key;
    const box = el('input', { type: 'checkbox', checked: picked });
    box.addEventListener('change', () => {
      state.bom.unmappedGroups = pickValueCandidate(
        state.bom.unmappedGroups, group.key, box.checked ? item.item_key : null);
      render();
    });
    // 实验室的识别主键是 SN，不是立创编号——后者只是给 EDA 做对应的辅助。
    const label = item.sn
      ? item.sn + '  ' + (item.name || '') + '  可用 ' + fmtQty(item.available)
      : (item.catalog_code || item.item_key || '—') + '  ' +
        (item.name || '') + '  可用 ' + fmtQty(item.lab_available_quantity);
    return el('label', { class: 'check', style: 'line-height:1.7' }, [
      box, el('span', { class: 'mono' }, label),
    ]);
  }));
}

/**
 * 无 C 编号器件：按「值 + 封装」查候选。
 *
 * 这些器件以前只出现在「未并入库存」表里，什么都帮不上。现在按值和封装去
 * 器件库搜，把候选列出来让用户自己判断——**绝不自动合并或替换**。
 */
async function loadValueMatches() {
  const bom = state.bom;
  const token = (bom.valueMatchToken || 0) + 1;
  bom.valueMatchToken = token;

  const groups = groupUnmappedByValue(bom.unmapped);
  bom.unmappedGroups = groups;
  const queries = groups.map((g) => g.query).filter(Boolean);
  if (!queries.length) {
    bom.valueMatchLoading = false;
    bom.valueMatchError = null;
    render();
    return;
  }

  bom.valueMatchLoading = true;
  bom.valueMatchError = null;
  render();
  try {
    const response = await call('catalog.valueMatch', { queries, limit: 3 }, 60000);
    if (bom.valueMatchToken !== token) return;
    bom.unmappedGroups = attachValueMatches(groups, response);
  } catch (error) {
    if (bom.valueMatchToken !== token) return;
    bom.valueMatchError = error;
  } finally {
    if (bom.valueMatchToken === token) {
      bom.valueMatchLoading = false;
      render();
    }
  }
}

async function loadBomEquivalents() {
  const bom = state.bom;
  const token = (bom.equivalentsToken || 0) + 1;
  bom.equivalentsToken = token;
  const requestLines = equivalentsRequestLines(bom.rows);
  if (!requestLines.length) {
    bom.equivalentsLoading = false;
    bom.equivalentsError = null;
    bom.rows = attachEquivalents(bom.rows, { lines: [] });
    render();
    return;
  }
  bom.equivalentsLoading = true;
  bom.equivalentsError = null;
  render();
  try {
    const response = await call('catalog.equivalents', { lines: requestLines, limit_per_line: 5 }, 60000);
    if (bom.equivalentsToken !== token) return;
    bom.rows = attachEquivalents(bom.rows, response);
  } catch (error) {
    if (bom.equivalentsToken !== token) return;
    bom.equivalentsError = error;
  } finally {
    if (bom.equivalentsToken === token) {
      bom.equivalentsLoading = false;
      render();
    }
  }
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
    bom.outbound = emptyBomOutbound();
  } catch (error) {
    bom.error = error;
  } finally {
    bom.loading = false;
    render();
  }
  if (!bom.error) await loadBomEquivalents();
  if (!bom.error) await loadValueMatches();
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
  if (!bom.error) await loadBomEquivalents();
  if (!bom.error) await loadValueMatches();
}

function csvCell(value) {
  const text = String(value ?? '');
  return '"' + text.replace(/"/g, '""') + '"';
}

function exportBomCsv(rows) {
  const header = ['状态', 'C 编号', '名称', '型号', '位号', '需求', '可用', '缺口', '库位', '袋'];
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
    bagTraceSummary(row.bags),
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

/* Settings / session                                                  */
/* ------------------------------------------------------------------ */

function renderSettings() {
  const settings = state.settings;
  const session = state.session;
  const bootstrap = state.bootstrap;
  const permissions = (bootstrap && bootstrap.permissions) || {};

  const serverInput = el('input', {
    type: 'text', value: settings.serverUrl,
    placeholder: 'https://team.l-creation.club', class: 'mono',
  });
  serverInput.addEventListener('input', () => {
    settings.serverUrl = serverInput.value.trim();
  });
  const tokenInput = el('input', {
    type: 'password',
    value: settings.token,
    placeholder: settings.hasToken ? '已保存；留空则沿用现有密钥' : '粘贴管理员给你的 EDA 密钥（eda_…）',
    autocomplete: 'off',
  });
  tokenInput.addEventListener('input', () => {
    settings.token = tokenInput.value.trim();
  });

  const panel = el('section', { class: 'panel' }, [
    el('h2', {}, '连接与账户'),
    el('p', { class: 'muted' }, 'EDA 插件用密钥直连服务器，不需要安装任何额外程序。密钥由库存管理员在网页端「管理 → EDA 插件密钥」里发放，绑定到你的账号。'),
    el('div', { class: 'grid-2' }, [
      field('服务器地址', serverInput, '默认 https://team.l-creation.club；内网可改为 http://192.168.31.105:8069。'),
      field('EDA 密钥', tokenInput, '形如 eda_xxxxxxxx。密钥明文保存在本机 EDA 配置里，与浏览器保存密码同一水位；离职时管理员可随时吊销。'),
    ]),
  ]);

  panel.appendChild(
    el('div', { class: 'row', style: 'margin-top:12px' }, [
      el('button', { class: 'btn primary', type: 'button', disabled: settings.busy, onclick: () => saveConnection() }, settings.busy ? '连接中…' : '保存并连接'),
      el('button', { class: 'btn danger', type: 'button', disabled: settings.busy || !session.active, onclick: () => logout() }, '断开并清除密钥'),
    ]),
  );

  if (settings.error) panel.appendChild(el('div', { style: 'margin-top:10px' }, errorBox(settings.error)));
  if (settings.message) panel.appendChild(el('div', { class: 'notice ok', style: 'margin-top:10px' }, settings.message));

  panel.appendChild(el('h3', {}, '当前会话'));
  panel.appendChild(
    el('dl', { class: 'kv' }, [
      el('dt', {}, '状态'), el('dd', {}, session.active ? '已连接' : '未连接'),
      el('dt', {}, '服务器'), el('dd', {}, settings.serverUrl || '—'),
      el('dt', {}, '用户'), el('dd', {}, session.active ? (session.name || '') + '（' + (session.username || '') + '）' : '—'),
      el('dt', {}, 'UID'), el('dd', {}, session.uid ? String(session.uid) : '—'),
    ]),
  );

  if (bootstrap) {
    panel.appendChild(el('h3', {}, '权限（服务器返回）'));
    panel.appendChild(
      table(
        [{ label: '能力' }, { label: '允许' }],
        [
          ['一键出库（领用）', permissions.can_issue],
          ['代他人领用', permissions.can_issue_for_others],
          ['管理员', permissions.is_manager],
        ].map(([label, value]) => [label, value ? '是' : '否']),
      ),
    );
    panel.appendChild(el('p', { class: 'muted', style: 'margin-top:8px' }, '权限以 Odoo 服务器校验为准；插件不能越权。'));
  } else if (session.active) {
    panel.appendChild(
      el('div', { class: 'row', style: 'margin-top:10px' }, [
        el('button', { class: 'btn', type: 'button', onclick: () => loadBootstrap() }, '刷新权限与库位'),
        state.bootstrapError ? errorBox(state.bootstrapError) : el('span', { class: 'muted' }, state.bootstrapLoading ? '正在读取…' : '尚未读取权限。'),
      ]),
    );
  }

  panel.appendChild(el('h3', {}, '使用提示'));
  panel.appendChild(
    el('ul', { class: 'list' }, [
      el('li', {}, '没有密钥时，请找库存管理员在网页端「管理」页发放；离职或换机时管理员可以吊销旧密钥。'),
      el('li', {}, '「一键出库」要在确认弹窗后才会写入 Odoo；入库、归还、扫码追溯请在网页端或 Flutter 客户端办理。'),
      el('li', {}, '如果账号没有对应权限，界面会显示服务器返回的权限提示。'),
    ]),
  );

  dom.view.appendChild(panel);
}

async function saveConnection() {
  const settings = state.settings;
  if (!settings.token && !settings.hasToken) {
    settings.error = { code: 'VALIDATION_ERROR', message: '请填写 EDA 密钥。没有的话请找库存管理员发放。' };
    render();
    return;
  }
  settings.busy = true;
  settings.error = null;
  settings.message = null;
  render();
  try {
    const payload = { serverUrl: settings.serverUrl };
    if (settings.token) payload.token = settings.token;
    const result = await call('config.save', payload, 60000);
    state.init.config = result.config;
    state.session = result.session;
    state.sessionError = null;
    settings.hasToken = Boolean(result.config && result.config.hasToken);
    settings.token = '';
    settings.message = '已连接：' + ((result.session && result.session.name) || '') +
      '（' + ((result.session && result.session.username) || '') + '）';
    state.bootstrap = null;
    state.bootstrapError = null;
    toast('已连接', 'ok');
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
    await call('session.disconnect');
    state.session = { active: false, uid: null, sessionMode: 'none' };
    state.init.session = state.session;
    state.bootstrap = null;
    state.bootstrapError = null;
    settings.hasToken = false;
    settings.message = '已断开，本机保存的密钥已清除。';
    toast('已断开', 'ok');
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
        el('dt', {}, '认证方式'), el('dd', {}, s.session && s.session.active ? 'EDA 密钥（bearer）' : '未连接'),
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
        'POST /lab/api/inventory/bootstrap',
        'POST /lab/api/inventory/issue（仅经 inventory.outbound 一键出库调用）',
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
