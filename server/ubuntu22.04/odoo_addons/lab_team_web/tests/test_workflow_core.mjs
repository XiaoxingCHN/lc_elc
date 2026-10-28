#!/usr/bin/env node
/* ==========================================================================
 * workflow_core.js 行为测试（零依赖：node:vm + node:assert）
 * --------------------------------------------------------------------------
 * 运行（仓库根目录，Node ≥ 16 即可，不需要 npm install）：
 *
 *     node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_workflow_core.mjs
 *
 * 退出码：全部通过 0，任一失败 1（可直接进 CI/验收脚本）。
 *
 * 测什么（对应 frontend-contract.md §5.3 / §5.2 / §13 与 Lead decision #6）：
 *   1. 服务器可能已提交但网络断开 → 显式重试**同 key 同 payload**；
 *   2. 未知结果后"只编辑不提交"不得产生任何请求（不静默新 key 提交）；
 *   3. 已确认 VALIDATION_ERROR 后，同 payload 再提交也必须换新 key（服务端已回滚）；
 *   4. 重复点击（submit 事件连发）只执行一次，不产生并发重复写；
 *   5. 成功后同一逻辑操作再提交必须换新 key，且成功即清掉 attempt 记录；
 *   6. sessionStorage 不可用时退化为内存仍能保持同 key；
 *   7. 站外 URL / 未登记 endpoint 一律拒绝，且不发出任何 fetch；
 *   8. UNAUTHORIZED 时状态区给出"重新登录"，clear 后可恢复。
 *
 * 不测什么：业务字段、后端响应体形状（那是 backend-contract.md 的事）；
 * 这里只验证 core 自己的行为，用假 DOM/假 fetch，不引第三方依赖。
 * ========================================================================== */
'use strict';

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CORE_PATH = path.join(HERE, '..', 'static', 'src', 'js', 'workflow_core.js');
let CORE_SOURCE;
try {
  CORE_SOURCE = fs.readFileSync(CORE_PATH, 'utf8');
} catch (error) {
  console.error('无法读取 core：' + CORE_PATH + '\n' + error.message);
  process.exit(1);
}

/* ------------------------------------------------------------------ 假 DOM */
function makeElement(tag = 'div', attrs = {}) {
  const node = {
    tagName: String(tag).toUpperCase(),
    nodeName: String(tag).toUpperCase(),
    nodeType: 1,
    attributes: Object.assign({}, attrs),
    children: [],
    listeners: {},
    disabled: false,
    checked: false,
    value: '',
    _text: '',
    _parent: null
  };
  node.classList = {
    set: new Set((attrs.class || '').split(/\s+/).filter(Boolean)),
    add(name) { this.set.add(name); },
    remove(name) { this.set.delete(name); },
    contains(name) { return this.set.has(name); },
    toggle(name, force) {
      if (force === undefined) {
        if (this.set.has(name)) this.set.delete(name); else this.set.add(name);
      } else if (force) {
        this.set.add(name);
      } else {
        this.set.delete(name);
      }
      return this.set.has(name);
    }
  };
  Object.defineProperty(node, 'className', {
    get() { return node.attributes.class || ''; },
    set(value) { node.attributes.class = String(value); }
  });
  Object.defineProperty(node, 'textContent', {
    get() { return node._text; },
    set(value) { node._text = value === null || value === undefined ? '' : String(value); node.children = []; }
  });
  Object.defineProperty(node, 'firstChild', { get() { return node.children[0] || null; } });
  Object.defineProperty(node, 'parentNode', { get() { return node._parent; } });
  node.appendChild = function (child) {
    child._parent = node;
    node.children.push(child);
    return child;
  };
  node.removeChild = function (child) {
    const index = node.children.indexOf(child);
    if (index >= 0) node.children.splice(index, 1);
    child._parent = null;
    return child;
  };
  node.insertBefore = function (child, reference) {
    const index = reference ? node.children.indexOf(reference) : -1;
    if (index < 0) node.children.push(child);
    else node.children.splice(index, 0, child);
    child._parent = node;
    return child;
  };
  node.setAttribute = function (name, value) { node.attributes[name] = String(value); };
  node.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(node.attributes, name) ? node.attributes[name] : null;
  };
  node.removeAttribute = function (name) { delete node.attributes[name]; };
  node.hasAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(node.attributes, name);
  };
  node.addEventListener = function (type, handler) {
    (node.listeners[type] = node.listeners[type] || []).push(handler);
  };
  node.querySelector = function () { return null; };
  node.querySelectorAll = function () { return []; };
  node.closest = function () { return node._parent || null; };
  node.contains = function (other) { return other === node || node.children.indexOf(other) !== -1; };
  return node;
}

function makeDocument(config, pageId, domain) {
  const body = makeElement('body', {
    'data-workflow-config': JSON.stringify(config),
    'data-base': config.base || '',
    'data-authenticated': config.authenticated ? '1' : '0',
    'data-active-page': pageId || ''
  });
  body.classList.add('lc-body');
  const root = makeElement('div', {
    'data-workflow-page': pageId || '',
    'data-domain': domain || '',
    'data-base': config.base || ''
  });
  const statusEl = makeElement('div', { 'data-lc-status': '' });
  const region = makeElement('div', { 'data-lc-status-region': '' });
  const doc = {
    body,
    listeners: {},
    documentElement: makeElement('html'),
    createElement: (tag) => makeElement(tag),
    createTextNode: (text) => ({ nodeType: 3, textContent: String(text) }),
    addEventListener(type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    querySelector(selector) {
      if (selector === '#workflow-root') return root;
      if (selector === '#lc-main') return null;
      if (selector === '[data-lc-status]') return statusEl;
      if (selector === '[data-lc-status-region]') return region;
      return null;
    },
    querySelectorAll() { return []; },
    contains(node) { return node === body || node === root || node === statusEl || node === region; }
  };
  return { doc, body, root, statusEl, region };
}

function makeStorage(options = {}) {
  const map = new Map();
  return {
    getItem(key) {
      return map.has(key) ? map.get(key) : null;
    },
    setItem(key, value) {
      if (options.failOnWrite) throw new Error('QuotaExceededError');
      map.set(key, String(value));
    },
    removeItem(key) {
      if (options.failOnWrite) throw new Error('QuotaExceededError');
      map.delete(key);
    },
    keys() { return Array.from(map.keys()); },
    size() { return map.size; }
  };
}

/* ------------------------------------------------------------------ 假 fetch */
/**
 * 记录每次请求的**完整 JSON-RPC 信封**与展开后的 params。
 *
 * 为什么必须分开记：request_key 在 `body.params.request_key`，不在信封顶层。
 * 早期夹具只读 `body.request_key` 得到 undefined，会让
 *   assert.equal(secondKey, firstKey)  Expected undefined / actual <新 key>
 * 看起来像"core 没带 key"，其实是夹具读错了层。这里同时保留 params/body
 * 两个别名，并额外记录 url，便于按 mutation endpoint 过滤（排除 session 等读请求）。
 */
function makeFetch() {
  const calls = [];
  const queue = [];
  const fake = function (url, init) {
    const raw = init && init.body ? String(init.body) : '';
    let payload = null;
    let params = null;
    try {
      payload = raw ? JSON.parse(raw) : null;
      params = payload && payload.params && typeof payload.params === 'object'
        ? payload.params : null;
    } catch (error) {
      params = null;
    }
    calls.push({ url: String(url), raw, payload, params, body: params });
    if (!queue.length) {
      return Promise.reject(new Error('测试未排队响应，却发生了请求：' + url));
    }
    const next = queue.shift();
    if (next instanceof Error) return Promise.reject(next);
    return Promise.resolve(next);
  };
  fake.calls = calls;
  fake.queue = queue;
  return fake;
}

/** 只取打到某个端点的请求（排除 /api/team/session 之类的读请求干扰）。 */
function callsTo(fetchMock, path) {
  return fetchMock.calls.filter((call) => call.url === path);
}

function jsonResponse(payload, status) {
  return {
    ok: (status || 200) < 400,
    status: status || 200,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(payload)
  };
}

function envelopeOk(data) {
  return jsonResponse({ jsonrpc: '2.0', id: 1, result: { ok: true, data: data || {}, error: null } });
}

function envelopeError(code, message, fields) {
  return jsonResponse({
    jsonrpc: '2.0', id: 1,
    result: { ok: false, data: null, error: { code, message: message || code, fields: fields || {} } }
  });
}

/* ------------------------------------------------------------------ 装载 core */
const DEFAULT_CONFIG = {
  version: 1,
  base: '/team',
  page: 'receipts',
  domain: 'receipt',
  authenticated: true,
  // 未决提交按 (uid, company) 命名空间隔离存储；server 在 data-workflow-config 下发
  identity: { uid: 7, company_id: 1 },
  endpoints: {
    session: '/api/team/session',
    issue: '/lab/api/inventory/issue',
    pendingCreate: '/lab/api/inventory/pending/create',
    labelsPlan: '/lab/api/labels/plan'
  },
  urls: { login: '/login', lab: '/lab', receipts: '/lab/receipts', scan: '/scan' },
  permissions: { can_lab: true, can_issue: true },
  limits: { pageSize: 24, maxPageSize: 100 },
  attempt: { prefix: 'lc-wf-attempt:', ttlMs: 600000 },
  timeouts: { submitMs: 5000, readMs: 5000 }
};

function loadCore(options = {}) {
  const config = Object.assign({}, DEFAULT_CONFIG, options.config || {});
  const fetchMock = options.fetch || makeFetch();
  const storage = options.storage || makeStorage();
  const { doc, body, root, statusEl, region } = makeDocument(config, config.page, config.domain);
  const navigation = { assigned: [], replaced: [] };
  const windowObj = {
    document: doc,
    location: {
      pathname: '/team/lab/receipts',
      search: '',
      href: 'http://host/team/lab/receipts',
      assign(url) { navigation.assigned.push(url); },
      replace(url) { navigation.replaced.push(url); }
    },
    history: { replaceState() {}, pushState() {} },
    sessionStorage: storage,
    setTimeout,
    clearTimeout,
    confirm: () => true,
    console
  };
  windowObj.window = windowObj;
  const sandbox = {
    window: windowObj,
    document: doc,
    console,
    fetch: fetchMock,
    URLSearchParams,
    setTimeout,
    clearTimeout
  };
  vm.createContext(sandbox);
  vm.runInContext(CORE_SOURCE, sandbox, { filename: 'workflow_core.js' });
  if (!windowObj.LC) throw new Error('core 没有导出 window.LC（脚本可能提前 return）');
  return { LC: windowObj.LC, fetch: fetchMock, storage, statusEl, root, body, doc, navigation, region };
}

/* ------------------------------------------------------------------ 小工具 */
function tick(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms || 0));
}

function attemptKeys(storage) {
  return storage.keys().filter((key) => key.indexOf('lc-wf-attempt:') === 0);
}

function statusKind(statusEl) {
  return statusEl.getAttribute('data-kind');
}

function findChildWith(statusEl, attr, prefix) {
  for (const child of statusEl.children) {
    const value = child.getAttribute(attr);
    if (value && value.indexOf(prefix) === 0) return child;
  }
  return null;
}

async function expectUnknown(promise) {
  let caught = null;
  try {
    await promise;
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, '期望失败但成功了');
  assert.equal(caught.unknown, true, '未知结果必须标记 unknown=true，实际 code=' + caught.code);
  return caught;
}

async function expectBusinessError(promise, code) {
  let caught = null;
  try {
    await promise;
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, '期望业务失败但成功了');
  assert.equal(caught.unknown, false, '业务失败不应该是 unknown');
  assert.equal(caught.code, code, '错误码应为 ' + code + '，实际 ' + caught.code);
  return caught;
}

/* ------------------------------------------------------------------ 用例 */
const tests = [];
function test(name, fn) { tests.push({ name, fn }); }

const ISSUE_PARAMS = { borrower_id: 7, project: '电源板', lines: [{ bag_id: 3, quantity: 2 }] };

test('未知结果：显式重试复用同一 request_key 与同一 payload', async () => {
  const fetchMock = makeFetch();
  const { LC, storage } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(new TypeError('network down'));
  await expectUnknown(LC.submit({ scope: 'issue/new', endpoint: 'issue', params: ISSUE_PARAMS }));
  assert.equal(fetchMock.calls.length, 1, '第一次提交应只发一次请求');
  assert.equal(attemptKeys(storage).length, 1, '未知结果必须保留 attempt 记录供重试');

  fetchMock.queue.push(envelopeOk({ operation: { name: 'LAB/ISS/0001' } }));
  const result = await LC.submit({ scope: 'issue/new', endpoint: 'issue', params: ISSUE_PARAMS });

  const mutations = callsTo(fetchMock, '/lab/api/inventory/issue');
  assert.equal(mutations.length, 2, '两次提交都应打到 issue mutation endpoint');
  assert.equal(fetchMock.calls.length, 2, '除 mutation 外不得混入其它请求（例如 session 读）');

  const first = mutations[0].params;
  const second = mutations[1].params;
  assert.ok(first, '首次 mutation 必须带 params（不是空请求）');
  assert.equal(typeof first.request_key, 'string', '首次 mutation 必须自带 request_key，不能靠重试才补');
  assert.ok(first.request_key.length >= 8, 'request_key 长度必须符合服务端约束');
  assert.equal(second.request_key, first.request_key, '网络未知后的重试必须复用同一 request_key');
  assert.deepEqual(second, first, '重试的 payload 必须与第一次逐字相同（含 key）');
  assert.equal(result.requestKey, first.request_key);
  assert.equal(attemptKeys(storage).length, 0, '成功后必须清掉该 attempt 记录');
});

test('未知结果不自动重试、加载时也不自动提交', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock });
  assert.equal(fetchMock.calls.length, 0, 'core 加载不得自动提交任何写请求');

  fetchMock.queue.push(new TypeError('timeout'));
  await expectUnknown(LC.submit({ scope: 'auto', endpoint: 'issue', params: ISSUE_PARAMS }));
  await tick(40);
  assert.equal(fetchMock.calls.length, 1, '未知结果后不得自动重发，必须由用户显式重试');
  const mutations = callsTo(fetchMock, '/lab/api/inventory/issue');
  assert.equal(mutations.length, 1, '唯一一次请求必须是 mutation 端点');
  assert.equal(typeof mutations[0].params.request_key, 'string', '这次 mutation 必须自带 request_key');
});

test('未决期间改动 payload 再次提交：本地拒绝、不发请求、不换 key', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(new TypeError('drop'));
  await expectUnknown(LC.submit({ scope: 'issue/new', endpoint: 'issue', params: ISSUE_PARAMS }));
  const original = callsTo(fetchMock, '/lab/api/inventory/issue')[0].params;
  assert.equal(typeof original.request_key, 'string', '首次 mutation 必须自带 request_key');

  // 真实场景：断网后用户"修正输入再提交"（数量 2 → 5）
  const edited = { borrower_id: 7, project: '电源板', lines: [{ bag_id: 3, quantity: 5 }] };
  let caught = null;
  try {
    await LC.submit({ scope: 'issue/new', endpoint: 'issue', params: edited });
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, '未决期间改内容提交必须被本地拒绝');
  assert.equal(caught.code, 'CONFLICT');
  assert.equal(caught.fields.submit, 'pending_unknown');
  assert.equal(callsTo(fetchMock, '/lab/api/inventory/issue').length, 1,
    '被本地拒绝的提交不得发出任何请求（否则可能多领一笔）');

  const pending = LC.pendingAttempt('issue/new', 'issue');
  assert.ok(pending, '未决记录必须仍然存在');
  assert.equal(pending.key, original.request_key, '未决记录必须锁住原 key');
  assert.equal(pending.payload.lines[0].quantity, 2, '未决记录保存的必须是原 payload');

  // 唯一允许的继续方式：用原内容重试 → 复用原 key
  fetchMock.queue.push(envelopeOk({}));
  const result = await LC.submit({ scope: 'issue/new', endpoint: 'issue', params: ISSUE_PARAMS });
  assert.equal(result.requestKey, original.request_key);
  assert.equal(callsTo(fetchMock, '/lab/api/inventory/issue').length, 2);
  assert.equal(LC.pendingAttempt('issue/new', 'issue'), null, '成功后未决记录必须清除');
});

test('确认 VALIDATION_ERROR 后：同 payload 再提交也换新 key', async () => {
  const fetchMock = makeFetch();
  const { LC, storage } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(envelopeError('VALIDATION_ERROR', '数量不合法', { quantity: 'invalid' }));
  const error = await expectBusinessError(
    LC.submit({ scope: 'invalid', endpoint: 'issue', params: ISSUE_PARAMS }), 'VALIDATION_ERROR');
  assert.strictEqual(error.fields.quantity, 'invalid', '字段错误应透传给页面标红');
  const failedKey = fetchMock.calls[0].params.request_key;
  assert.equal(typeof failedKey, 'string', '首次 mutation 必须自带 request_key');
  assert.equal(attemptKeys(storage).length, 0, '确认失败后必须清掉 attempt 记录');

  fetchMock.queue.push(envelopeOk({}));
  const result = await LC.submit({ scope: 'invalid', endpoint: 'issue', params: ISSUE_PARAMS });
  assert.notEqual(result.requestKey, failedKey, '服务端已回滚，再次提交应使用新 key');
});

test('重复点击：同一表单 submit 连发只执行一次', async () => {
  const { LC } = loadCore();
  const button = makeElement('button', { type: 'submit', text: '提交' });
  const projectInput = makeElement('input', { name: 'project', type: 'text' });
  projectInput.value = '电源板';
  const qtyInput = makeElement('input', { name: 'quantity', type: 'number' });
  qtyInput.value = '2';
  const form = makeElement('form', {});
  form.elements = [projectInput, qtyInput];
  form.querySelector = (selector) => (selector.indexOf('button') !== -1 ? button : null);

  let handled = 0;
  LC.guard(form, function (values, done) {
    handled += 1;
    assert.equal(values.project, '电源板');
    // 故意不调用 done：模拟"请求还在飞"，第二次点击必须被 aria-busy 挡住
    // 注意：done 由 vm 上下文创建，不能用主上下文的 instanceof Function 判断
    assert.equal(typeof done, 'function');
  });

  const listeners = form.listeners.submit || [];
  assert.equal(listeners.length, 1, 'guard 只应绑定一次 submit');
  const event = { preventDefault() {} };
  listeners[0](event);
  listeners[0](event);
  assert.equal(handled, 1, '重复点击不得触发第二次提交');
  assert.equal(form.getAttribute('aria-busy'), 'true', '提交中表单应标记 aria-busy');
  assert.equal(button.disabled, true, '提交中按钮应禁用');
});

test('成功后下一次逻辑操作必须有新 key，且成功即清空 attempt', async () => {
  const fetchMock = makeFetch();
  const { LC, storage } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(envelopeOk({ bag: { trace_code: 'LABB-1' } }));
  const first = await LC.submit({ scope: 'loop', endpoint: 'pendingCreate', params: { item_key: 'lcsc:C1', quantity: 10, count: 1 } });
  assert.equal(attemptKeys(storage).length, 0, '成功后不得留下 attempt 记录');

  fetchMock.queue.push(envelopeOk({ bag: { trace_code: 'LABB-2' } }));
  const second = await LC.submit({ scope: 'loop', endpoint: 'pendingCreate', params: { item_key: 'lcsc:C1', quantity: 10, count: 1 } });
  assert.notEqual(second.requestKey, first.requestKey, '连续两次"新建一袋"是两个独立操作，必须各自新 key');
  assert.equal(fetchMock.calls.length, 2);
});

test('服务端重放：replayed 透传给页面，不会当成第二次成功', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock });
  fetchMock.queue.push(envelopeOk({ replayed: true, operation: { name: 'LAB/ISS/0009' } }));
  const result = await LC.submit({ scope: 'replay', endpoint: 'issue', params: ISSUE_PARAMS });
  assert.equal(result.replayed, true);
});

test('sessionStorage 不可用：退化为内存，重试仍复用同一 key', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock, storage: makeStorage({ failOnWrite: true }) });

  fetchMock.queue.push(new TypeError('offline'));
  await expectUnknown(LC.submit({ scope: 'memory', endpoint: 'issue', params: ISSUE_PARAMS }));
  const firstKey = fetchMock.calls[0].params.request_key;
  assert.equal(typeof firstKey, 'string', '首次 mutation 必须自带 request_key（内存兜底路径）');

  fetchMock.queue.push(envelopeOk({}));
  const result = await LC.submit({ scope: 'memory', endpoint: 'issue', params: ISSUE_PARAMS });
  assert.equal(result.requestKey, firstKey, '存储不可用时也必须保持同 key（内存兜底）');
});

test('站外 URL 与未登记 endpoint 一律拒绝，且不发出 fetch', async () => {
  const fetchMock = makeFetch();
  const { LC, statusEl, navigation } = loadCore({ fetch: fetchMock });

  LC.navigate('https://evil.example/x');
  LC.navigate('//evil.example/x');
  assert.deepEqual(navigation.assigned, [], '站外绝对地址不得导航');
  assert.equal(statusKind(statusEl), 'error', '拒绝时应给出错误状态');

  let caught = null;
  try {
    await LC.rpc('evilEndpoint', {});
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, '未登记 endpoint 必须拒绝');
  assert.equal(fetchMock.calls.length, 0, '未登记 endpoint 不得发出请求');

  caught = null;
  try {
    await LC.submit({ scope: 'evil', endpoint: 'evilEndpoint', params: {} });
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, '未登记 endpoint 的写操作必须拒绝');
  assert.equal(fetchMock.calls.length, 0);
});

test('UNAUTHORIZED：状态区给"重新登录"，clear 后恢复', async () => {
  const fetchMock = makeFetch();
  const { LC, statusEl } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(jsonResponse({ error: 'session expired' }, 403));
  let caught = null;
  try {
    await LC.rpc('session', {});
  } catch (error) {
    caught = error;
  }
  assert.ok(caught);
  assert.equal(caught.code, 'UNAUTHORIZED');
  assert.equal(statusKind(statusEl), 'denied');
  const link = findChildWith(statusEl, 'href', '/login?next=');
  assert.ok(link, '必须提供带 next 的"重新登录"链接，实际子节点：' +
    statusEl.children.map((child) => child.getAttribute('href')).join(','));

  LC.status.clear();
  assert.equal(statusKind(statusEl), null, 'clear 应移除 data-kind');
  assert.equal(statusEl.getAttribute('hidden'), 'hidden', 'clear 后状态区应隐藏');

  LC.status.show({ kind: 'success', message: '已恢复' });
  assert.equal(statusKind(statusEl), 'success', '错误后可正常恢复为成功状态');
  assert.equal(statusEl.getAttribute('hidden'), null, '显示时应移除 hidden');
});

test('不同 scope 互不串用：同 payload 也各自独立 key', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(envelopeOk({}));
  const first = await LC.submit({ scope: 'page-a', endpoint: 'issue', params: ISSUE_PARAMS });
  fetchMock.queue.push(envelopeOk({}));
  const second = await LC.submit({ scope: 'page-b', endpoint: 'issue', params: ISSUE_PARAMS });
  assert.notEqual(first.requestKey, second.requestKey,
    '不同 scope 是不同逻辑操作，不得复用同一个 request_key（否则服务端 CONFLICT）');
});

test('未决期间遇到 401/403：不得清除未决（无法推断"没提交"）', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock });

  fetchMock.queue.push(new TypeError('drop'));
  await expectUnknown(LC.submit({ scope: 's401', endpoint: 'issue', params: ISSUE_PARAMS }));
  const key = callsTo(fetchMock, '/lab/api/inventory/issue')[0].params.request_key;

  fetchMock.queue.push(jsonResponse({ error: 'session expired' }, 403));
  let caught = null;
  try {
    await LC.submit({ scope: 's401', endpoint: 'issue', params: ISSUE_PARAMS });
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, '应返回 UNAUTHORIZED');
  assert.equal(caught.code, 'UNAUTHORIZED');

  const pending = LC.pendingAttempt('s401', 'issue');
  assert.ok(pending, '401/403 之后未决记录必须保留（可能已入账）');
  assert.equal(pending.key, key, '未决记录仍锁原 key');
});

test('刷新页面：pendingAttempt 恢复未决，同 payload 跨刷新复用 key', async () => {
  const storage = makeStorage();
  const first = loadCore({ fetch: makeFetch(), storage });
  first.fetch.queue.push(new TypeError('drop'));
  await expectUnknown(first.LC.submit({ scope: 'reload', endpoint: 'issue', params: ISSUE_PARAMS }));
  const key = callsTo(first.fetch, '/lab/api/inventory/issue')[0].params.request_key;

  // 模拟刷新：同一 sessionStorage，新的 core 实例
  const fetchSecond = makeFetch();
  const second = loadCore({ fetch: fetchSecond, storage });
  const pending = second.LC.pendingAttempt('reload', 'issue');
  assert.ok(pending, '刷新后必须仍能发现未决提交');
  assert.equal(pending.key, key);

  let refused = null;
  try {
    await second.LC.submit({
      scope: 'reload', endpoint: 'issue',
      params: { borrower_id: 7, project: '电源板', lines: [{ bag_id: 3, quantity: 9 }] }
    });
  } catch (error) {
    refused = error;
  }
  assert.ok(refused && refused.fields.submit === 'pending_unknown', '刷新后改内容提交同样必须被拒');
  assert.equal(fetchSecond.calls.length, 0, '刷新后改内容提交不得发出请求');

  fetchSecond.queue.push(envelopeOk({}));
  const result = await second.LC.submit({ scope: 'reload', endpoint: 'issue', params: ISSUE_PARAMS });
  assert.equal(result.requestKey, key, '跨刷新同 payload 必须复用同一 key');
});

test('存储按 user/company 命名空间隔离', async () => {
  const storage = makeStorage();
  const owner = loadCore({
    fetch: makeFetch(), storage, config: { identity: { uid: 7, company_id: 1 } }
  });
  owner.fetch.queue.push(new TypeError('drop'));
  await expectUnknown(owner.LC.submit({ scope: 'iso', endpoint: 'issue', params: ISSUE_PARAMS }));

  const keys = attemptKeys(storage);
  assert.equal(keys.length, 1);
  assert.equal(keys[0].indexOf('lc-wf-attempt:7:1:'), 0,
    '存储键必须包含 user/company 命名空间，实际：' + keys[0]);

  const other = loadCore({
    fetch: makeFetch(), storage, config: { identity: { uid: 8, company_id: 1 } }
  });
  assert.equal(other.LC.pendingAttempt('iso', 'issue'), null,
    '另一个账号不得看到前一个账号的未决提交');
});

test('显式解除未决：必须带核对结论；解除后才允许新内容新 key', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({ fetch: fetchMock });
  fetchMock.queue.push(new TypeError('drop'));
  await expectUnknown(LC.submit({ scope: 'resolve', endpoint: 'issue', params: ISSUE_PARAMS }));
  const originalKey = callsTo(fetchMock, '/lab/api/inventory/issue')[0].params.request_key;

  let refused = null;
  try {
    await LC.resolveUnknown('resolve', 'issue', {});
  } catch (error) {
    refused = error;
  }
  assert.ok(refused, '没有核对结论不得解除未决');
  assert.equal(refused.code, 'VALIDATION_ERROR');
  assert.ok(LC.pendingAttempt('resolve', 'issue'), '被拒绝的解除不得清掉未决');

  refused = null;
  try {
    await LC.resolveUnknown('resolve', 'issue', { confirmed: true, verification: 'maybe' });
  } catch (error) {
    refused = error;
  }
  assert.ok(refused, 'verification 非法不得解除');

  const cleared = await LC.resolveUnknown('resolve', 'issue',
    { confirmed: true, verification: 'absent' });
  assert.equal(cleared.cleared, true);
  assert.equal(cleared.requestKey, originalKey, '解除结果要带上原 key 供页面提示/核对');
  assert.equal(LC.pendingAttempt('resolve', 'issue'), null);

  fetchMock.queue.push(envelopeOk({}));
  const edited = { borrower_id: 7, project: '电源板', lines: [{ bag_id: 3, quantity: 5 }] };
  const result = await LC.submit({ scope: 'resolve', endpoint: 'issue', params: edited });
  assert.notEqual(result.requestKey, originalKey, '解除后新内容必须拿到新 key');
  assert.equal(fetchMock.calls.length, 2, '解除后新内容才允许发出请求');
});

test('刷新会话：权限位与身份引用原地更新（S2-6）', async () => {
  const fetchMock = makeFetch();
  const { LC } = loadCore({
    fetch: fetchMock,
    config: {
      permissions: { can_lab: true, can_issue: false },
      identity: { uid: 7, company_id: 1 }
    }
  });
  assert.equal(LC.has('can_issue'), false);
  const permissionsRef = LC.permissions;
  const identityRef = LC.identity;

  fetchMock.queue.push(envelopeOk({
    uid: 7,
    company: { id: 1 },
    permissions: { can_lab: true, can_issue: true, can_receipt: true }
  }));
  await LC.refreshSession();

  assert.equal(LC.has('can_issue'), true, '刷新后权限位必须真的更新');
  assert.equal(LC.has('can_receipt'), true);
  assert.equal(LC.permissions, permissionsRef, 'LC.permissions 应保持同一对象引用');
  assert.equal(permissionsRef.can_issue, true, '引用方也能看到新权限');
  assert.equal(LC.identity, identityRef, 'identity 同样原地更新');
});

test('错误状态可恢复：连续 show/clear 不残留旧内容', async () => {
  const { LC, statusEl } = loadCore();
  LC.status.show({ kind: 'error', code: 'VALIDATION_ERROR', message: '参数不合法' });
  const firstText = statusEl.children.map((child) => child.textContent).join('|');
  assert.ok(firstText.indexOf('参数不合法') !== -1);
  LC.status.show({ kind: 'empty', message: '没有数据' });
  const secondText = statusEl.children.map((child) => child.textContent).join('|');
  assert.ok(secondText.indexOf('参数不合法') === -1, '新状态不得保留旧文案');
  assert.ok(secondText.indexOf('没有数据') !== -1);
});

/* ------------------------------------------------------------------ 运行器 */
async function main() {
  let failed = 0;
  for (const item of tests) {
    try {
      await item.fn();
      console.log('ok   - ' + item.name);
    } catch (error) {
      failed += 1;
      console.error('FAIL - ' + item.name);
      console.error('       ' + (error && error.message ? error.message : String(error)));
      if (error && error.stack) {
        console.error(error.stack.split('\n').slice(1, 4).join('\n'));
      }
    }
  }
  const total = tests.length;
  console.log('');
  console.log((total - failed) + '/' + total + ' passed, ' + failed + ' failed');
  if (failed) process.exitCode = 1;
}

main().catch((error) => {
  console.error('测试运行器异常：' + (error && error.stack ? error.stack : error));
  process.exitCode = 1;
});
