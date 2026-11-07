#!/usr/bin/env node
/* ==========================================================================
 * workflow_core.js · LC.combobox（输入即候选）行为测试
 * --------------------------------------------------------------------------
 * 运行（仓库根目录，Node ≥ 16，零依赖，不需要 npm install）：
 *
 *     node server/ubuntu22.04/odoo_addons/lab_team_web/tests/test_combobox.mjs
 *
 * 退出码：全通过 0，任一失败 1。
 *
 * 测什么（对应 docs/requirements/WEB_UI_UNIFICATION_PLAN_20261102.md §3.1–§3.3）：
 *   1. 少于 minLength 不请求、也不开面板；
 *   2. 连打 5 个字符只发 1 次请求（去抖），并且输入后立刻有"搜索中"反馈；
 *   3. 晚到响应按序号丢弃，绝不覆盖新查询的结果；
 *   4. 中文输入法组字期间不检索，compositionend 才检索；
 *   5. ArrowDown/ArrowUp + Enter 选择：preventDefault、aria-activedescendant、
 *      onPick 收到正确条目；未高亮时 Enter 不被消费（页面保底解析）；
 *   6. Escape 关闭并 preventDefault；Tab / focusout 到外部 / 外部 mousedown 关闭；
 *      容器内 mousedown 不关（点选候选时保焦点）；
 *   7. 空结果与请求失败都有明确文案（不伪装成"有结果"）；
 *   8. disabled() 为真时不请求且关闭；
 *   9. 返回条数按 limit 截断，候选文本只用 textContent。
 *
 * 不测什么：真实 /lab/api/catalog/search 的返回形状与权限（那属于后端/HTTP 用例）。
 * ========================================================================== */
'use strict';

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CORE_PATH = path.join(HERE, '..', 'static', 'src', 'js', 'workflow_core.js');
const CORE_SOURCE = fs.readFileSync(CORE_PATH, 'utf8');

/* ------------------------------------------------------------------ 假 DOM */
function matches(node, selector) {
  if (!node || node.nodeType !== 1) return false;
  const sel = String(selector || '');
  if (sel.charAt(0) === '.') return node.classList.contains(sel.slice(1));
  if (sel.indexOf('.') > 0) {
    const parts = sel.split('.');
    return node.tagName === parts[0].toUpperCase() && node.classList.contains(parts[1]);
  }
  return node.tagName === sel.toUpperCase();
}

function makeEl(tag, attrs) {
  const node = {
    tagName: String(tag).toUpperCase(),
    nodeType: 1,
    children: [],
    listeners: {},
    _attrs: Object.assign({}, attrs || {}),
    _text: '',
    parentNode: null,
    disabled: false
  };
  Object.defineProperty(node, 'className', {
    get() { return node._attrs.class || ''; },
    set(value) { node._attrs.class = String(value); }
  });
  node.classList = {
    _list() { return String(node._attrs.class || '').split(/\s+/).filter(Boolean); },
    _write(list) { node._attrs.class = list.join(' '); },
    contains(name) { return this._list().indexOf(name) !== -1; },
    add(name) { const l = this._list(); if (l.indexOf(name) === -1) l.push(name); this._write(l); },
    remove(name) { this._write(this._list().filter((item) => item !== name)); },
    toggle(name, force) {
      const on = force === undefined ? !this.contains(name) : !!force;
      if (on) this.add(name); else this.remove(name);
      return on;
    }
  };
  Object.defineProperty(node, 'textContent', {
    get() {
      if (node.nodeType === 3) return node._text;
      return node.children.length ? node.children.map((child) => child.textContent).join('') : node._text;
    },
    set(value) { node._text = value === null || value === undefined ? '' : String(value); node.children = []; }
  });
  Object.defineProperty(node, 'firstChild', { get() { return node.children[0] || null; } });
  node.setAttribute = function (name, value) { node._attrs[name] = String(value); };
  node.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(node._attrs, name) ? node._attrs[name] : null;
  };
  node.removeAttribute = function (name) { delete node._attrs[name]; };
  node.hasAttribute = function (name) { return Object.prototype.hasOwnProperty.call(node._attrs, name); };
  node.appendChild = function (child) {
    if (child.parentNode && child.parentNode.removeChild) child.parentNode.removeChild(child);
    child.parentNode = node;
    node.children.push(child);
    return child;
  };
  node.removeChild = function (child) {
    const index = node.children.indexOf(child);
    if (index >= 0) node.children.splice(index, 1);
    child.parentNode = null;
    return child;
  };
  node.insertBefore = function (child, reference) {
    const index = reference ? node.children.indexOf(reference) : -1;
    if (index < 0) node.children.push(child);
    else node.children.splice(index, 0, child);
    child.parentNode = node;
    return child;
  };
  node.contains = function (other) {
    let cursor = other;
    while (cursor) {
      if (cursor === node) return true;
      cursor = cursor.parentNode;
    }
    return false;
  };
  node.closest = function (selector) {
    let cursor = node;
    while (cursor) {
      if (matches(cursor, selector)) return cursor;
      cursor = cursor.parentNode;
    }
    return null;
  };
  node.addEventListener = function (type, handler) {
    (node.listeners[type] = node.listeners[type] || []).push(handler);
  };
  node.querySelectedIndex = null;
  return node;
}

function fire(node, type, props) {
  const event = Object.assign({
    type,
    target: node,
    defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.stopped = true; }
  }, props || {});
  (node.listeners[type] || []).forEach((handler) => handler.call(node, event));
  return event;
}

/* ------------------------------------------------------------------ 装载 core */
function loadCore() {
  const body = makeEl('body', {
    'data-workflow-config': JSON.stringify({
      version: 1,
      base: '/team',
      page: 'receipts',
      domain: 'receipt',
      authenticated: true,
      identity: { uid: 7, company_id: 1 },
      endpoints: {},
      urls: {},
      permissions: { can_receipt: true },
      limits: { pageSize: 24 },
      attempt: { prefix: 'lc-wf-attempt:', ttlMs: 600000 },
      timeouts: { submitMs: 5000, readMs: 5000 }
    }),
    'data-base': '/team',
    'data-authenticated': '1',
    'data-active-page': 'receipts'
  });
  body.classList.add('lc-body');
  const root = makeEl('div', { 'data-workflow-page': 'receipts' });
  body.appendChild(root);
  const doc = {
    body,
    nodeType: 9,
    listeners: {},
    createElement: (tag) => makeEl(tag),
    createTextNode: (text) => ({ nodeType: 3, textContent: String(text), parentNode: null }),
    addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); },
    querySelector(selector) {
      if (selector === '#workflow-root') return root;
      if (selector === '[data-lc-status]') return makeEl('div', { 'data-lc-status': '' });
      return null;
    },
    querySelectorAll() { return []; },
    contains(node) { return node === body || node === root; }
  };
  const windowObj = {
    document: doc,
    location: { pathname: '/team/lab/receipts', search: '', href: 'http://host/team/lab/receipts', assign() {}, replace() {} },
    history: { replaceState() {}, pushState() {} },
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    setTimeout,
    clearTimeout,
    console
  };
  windowObj.window = windowObj;
  // 真实浏览器里 core 用 `children instanceof Node` 区分节点/文本：
  // 假 DOM 必须让 instanceof 成立，否则元素会被当文本节点塞进去。
  const FakeNode = {
    [Symbol.hasInstance](value) {
      return !!value && typeof value === 'object' && typeof value.nodeType === 'number';
    }
  };
  const sandbox = {
    window: windowObj,
    document: doc,
    Node: FakeNode,
    console,
    fetch: () => Promise.reject(new Error('这些用例不应发真实请求')),
    URLSearchParams,
    setTimeout,
    clearTimeout
  };
  vm.createContext(sandbox);
  vm.runInContext(CORE_SOURCE, sandbox, { filename: 'workflow_core.js' });
  return { LC: windowObj.LC, doc, body };
}

/* ------------------------------------------------------------------ 夹具 */
const ROWS = [
  { catalog_code: 'C123', name: '电阻 10k 0603', mpn: 'RC0603', package: '0603', lab_quantity: 500, has_stock: true, lab_template_ids: [11] },
  { catalog_code: 'C456', name: '电容 100nF 0603', mpn: 'CC0603', package: '0603', lab_quantity: 0, has_stock: false, lab_template_ids: [] }
];

function setup(options) {
  const opts = options || {};
  const { LC, doc } = loadCore();
  const input = makeEl('input', { type: 'text' });
  input.value = '';
  const container = makeEl('div', { class: 'lc-combobox' });
  const label = makeEl('label', { class: 'lc-field' });
  label.appendChild(input);
  container.appendChild(label);
  const body = doc.body;
  body.appendChild(container);

  const calls = [];
  const queue = [];
  const box = LC.combobox({
    input,
    container,
    minLength: opts.minLength === undefined ? 2 : opts.minLength,
    limit: opts.limit === undefined ? 8 : opts.limit,
    debounceMs: opts.debounceMs === undefined ? 5 : opts.debounceMs,
    disabled: opts.disabled || function () { return false; },
    loadingText: '正在检索器件资料…',
    emptyText: '没有匹配的器件。',
    errorText: function (err) { return '检索失败：' + ((err && err.code) || 'NETWORK'); },
    viewAllLabel: opts.viewAllLabel,
    viewAllHref: opts.viewAllHref,
    fetch: function (query) {
      calls.push(query);
      if (!queue.length) return Promise.resolve(ROWS);
      const next = queue.shift();
      return next instanceof Error ? Promise.reject(next) : next;
    },
    describe: function (item) {
      return { primary: item.name, meta: '型号 ' + item.mpn, badge: item.has_stock ? '本地库存' : '本地无库存' };
    },
    onPick: opts.onPick || function () {},
    onQuery: opts.onQuery || function () {}
  });
  const pop = container.children[container.children.length - 1];
  return { LC, box, input, container, pop, calls, queue, doc };
}

const tick = (ms) => new Promise((resolve) => setTimeout(resolve, ms === undefined ? 12 : ms));

function type(input, text) {
  input.value = text;
  fire(input, 'input');
}

function options(pop) {
  const list = pop.children[0];
  return (list ? list.children : []).slice();
}

/* ------------------------------------------------------------------ 用例 */
const tests = [];
function test(name, fn) { tests.push({ name, fn }); }

test('少于 minLength：不请求、不开面板', async () => {
  const { box, input, pop, calls } = setup();
  type(input, 'a');
  await tick();
  assert.equal(calls.length, 0, '单字符不应请求');
  assert.equal(box.isOpen(), false);
  assert.equal(pop.hasAttribute('hidden'), true);
  input.value = '';
  fire(input, 'input');
  await tick();
  assert.equal(calls.length, 0);
});

test('去抖：连打 5 个字符只发 1 次请求，且立即给出加载反馈', async () => {
  const { box, input, pop, calls } = setup({ debounceMs: 20 });
  type(input, '电');
  type(input, '电阻');
  type(input, '电阻 1');
  type(input, '电阻 10');
  type(input, '电阻 10k');
  // 防抖期内就已经打开面板并显示"搜索中"（不是等请求回来才有反馈）
  assert.equal(box.isOpen(), true, '输入后应立刻打开面板给反馈');
  const note = pop.children[1];
  assert.equal(note.getAttribute('data-kind'), 'loading');
  assert.ok(note.textContent.indexOf('正在检索') !== -1);
  await tick(40);
  assert.deepEqual(calls, ['电阻 10k'], '应该只请求最后一次输入');
  assert.equal(options(pop).length, ROWS.length);
});

test('晚到响应被序号丢弃，不覆盖新查询', async () => {
  const { input, pop, calls, queue } = setup({ debounceMs: 1 });
  let releaseFirst;
  const slow = new Promise((resolve) => { releaseFirst = resolve; });
  queue.push(slow);
  type(input, '电阻');
  await tick(10);
  assert.equal(calls.length, 1);
  queue.push([{ catalog_code: 'C999', name: '新结果', mpn: 'NEW', lab_template_ids: [] }]);
  type(input, '电容');
  await tick(10);
  assert.equal(calls.length, 2);
  const names = options(pop).map((node) => node.textContent);
  assert.ok(names.join('|').indexOf('新结果') !== -1, '应渲染第二次查询的结果');
  releaseFirst([{ catalog_code: 'C111', name: '旧结果', mpn: 'OLD', lab_template_ids: [] }]);
  await tick(10);
  const after = options(pop).map((node) => node.textContent).join('|');
  assert.ok(after.indexOf('旧结果') === -1, '晚到的旧响应绝不能回填');
  assert.ok(after.indexOf('新结果') !== -1);
});

test('输入法组字期间不检索，compositionend 后才检索', async () => {
  const { input, calls } = setup({ debounceMs: 1 });
  fire(input, 'compositionstart');
  input.value = 'dian';
  fire(input, 'input');
  await tick(10);
  assert.deepEqual(calls, [], '组字中不应发请求');
  input.value = '电阻';
  fire(input, 'input');
  await tick(10);
  assert.deepEqual(calls, [], '组字中继续输入也不应发请求');
  fire(input, 'compositionend');
  await tick(10);
  assert.deepEqual(calls, ['电阻'], 'compositionend 后才检索');
});

test('方向键 + Enter 选择：preventDefault 且 onPick 收到正确条目', async () => {
  const picked = [];
  const { LC: _LC, input, pop } = setup({ debounceMs: 1, onPick: (item) => picked.push(item.catalog_code) });
  type(input, '电阻');
  await tick(15);
  assert.equal(options(pop).length, 2);
  const down1 = fire(input, 'keydown', { key: 'ArrowDown' });
  assert.equal(down1.defaultPrevented, true, 'ArrowDown 应被消费');
  assert.equal(input.getAttribute('aria-activedescendant'), pop.children[0].children[0].getAttribute('id'));
  fire(input, 'keydown', { key: 'ArrowDown' });
  const enter = fire(input, 'keydown', { key: 'Enter' });
  assert.equal(enter.defaultPrevented, true);
  assert.deepEqual(picked, ['C456'], 'Enter 应选中当前高亮条目');
});

test('未高亮时 Enter 不被消费，交给页面保底解析', async () => {
  const { input, pop } = setup({ debounceMs: 1 });
  type(input, '电阻');
  await tick(15);
  assert.ok(options(pop).length > 0);
  const enter = fire(input, 'keydown', { key: 'Enter' });
  assert.equal(enter.defaultPrevented, false, '页面需要在未选候选时自己解析扫码内容');
});

test('Escape 关闭并 preventDefault，再次输入可重新打开', async () => {
  const { box, input, pop } = setup({ debounceMs: 1 });
  type(input, '电阻');
  await tick(15);
  assert.equal(box.isOpen(), true);
  const esc = fire(input, 'keydown', { key: 'Escape' });
  assert.equal(esc.defaultPrevented, true);
  assert.equal(box.isOpen(), false);
  assert.equal(pop.hasAttribute('hidden'), true);
  assert.equal(input.getAttribute('aria-expanded'), 'false');
  type(input, '电容');
  await tick(15);
  assert.equal(box.isOpen(), true, '关闭后再次输入必须能重新打开');
});

test('Tab / focusout 到外部 / 外部 mousedown 都会关闭；容器内点按不关', async () => {
  const first = setup({ debounceMs: 1 });
  type(first.input, '电阻');
  await tick(15);
  fire(first.input, 'keydown', { key: 'Tab' });
  assert.equal(first.box.isOpen(), false, 'Tab 应关闭');

  const second = setup({ debounceMs: 1 });
  type(second.input, '电阻');
  await tick(15);
  fire(second.input, 'focusout', { relatedTarget: null });
  assert.equal(second.box.isOpen(), false, '焦点离开外部应关闭');

  const third = setup({ debounceMs: 1 });
  type(third.input, '电阻');
  await tick(15);
  const inside = options(third.pop)[0];
  const insideDown = fire(third.container, 'mousedown', { target: inside });
  assert.equal(insideDown.defaultPrevented, true, '容器内 mousedown 要 preventDefault 以保住焦点');
  assert.equal(third.box.isOpen(), true, '容器内点按不应关闭面板');

  const fourth = setup({ debounceMs: 1 });
  type(fourth.input, '电阻');
  await tick(15);
  const outside = makeEl('div');
  fire(fourth.doc, 'mousedown', { target: outside });
  assert.equal(fourth.box.isOpen(), false, '面板外 mousedown 应关闭');
});

test('点选候选：click 选中并关闭，onPick 收到条目', async () => {
  const picked = [];
  const { box, input, pop, container } = setup({ debounceMs: 1, onPick: (item) => picked.push(item.catalog_code) });
  type(input, '电容');
  await tick(15);
  const option = options(pop)[0];
  const event = fire(container, 'click', { target: option });
  assert.equal(event.defaultPrevented, true);
  assert.deepEqual(picked, ['C123']);
  assert.equal(box.isOpen(), false);
});

test('空结果：给出明确文案而不是"有结果"的空面板', async () => {
  const { input, pop, queue } = setup({ debounceMs: 1 });
  queue.push([]);
  type(input, '不存在的器件');
  await tick(15);
  const note = pop.children[1];
  assert.equal(note.getAttribute('data-kind'), 'empty');
  assert.ok(note.textContent.indexOf('没有匹配') !== -1);
  assert.equal(options(pop).length, 0);
});

test('请求失败：显示错误文案（含错误码），不伪造结果', async () => {
  const { input, pop, queue } = setup({ debounceMs: 1 });
  const error = new Error('boom');
  error.code = 'ACCESS_ERROR';
  queue.push(error);
  type(input, '电阻');
  await tick(20);
  const note = pop.children[1];
  assert.equal(note.getAttribute('data-kind'), 'error');
  assert.ok(note.textContent.indexOf('ACCESS_ERROR') !== -1, '错误文案要带真实 code，便于对日志');
  assert.equal(options(pop).length, 0);
});

test('disabled()：锁定期间不请求也不开面板', async () => {
  let locked = false;
  const { box, input, calls } = setup({ debounceMs: 1, disabled: () => locked });
  locked = true;
  type(input, '电阻');
  await tick(15);
  assert.equal(calls.length, 0, '锁定后不得再检索');
  assert.equal(box.isOpen(), false);
});

test('limit：返回很多条也只渲染 limit 条', async () => {
  const many = [];
  for (let i = 0; i < 20; i += 1) {
    many.push({ catalog_code: 'C' + i, name: '器件 ' + i, mpn: 'M' + i, lab_template_ids: [] });
  }
  const { input, pop, queue } = setup({ debounceMs: 1, limit: 8 });
  queue.push(many);
  type(input, '器件');
  await tick(15);
  assert.equal(options(pop).length, 8);
});

test('onQuery 每次输入都收到（页面据此作废旧选择）', async () => {
  const seen = [];
  const { input } = setup({ debounceMs: 1, onQuery: (text) => seen.push(text) });
  type(input, '电阻');
  type(input, '电容');
  await tick(15);
  assert.deepEqual(seen, ['电阻', '电容']);
});

function setupCustom(fetchImpl, extra) {
  const opts = extra || {};
  const { LC, doc } = loadCore();
  const input = makeEl('input', { type: 'text' });
  input.value = '';
  const container = makeEl('div', { class: 'lc-combobox' });
  container.appendChild(input);
  doc.body.appendChild(container);
  const calls = [];
  let aborted = 0;
  const box = LC.combobox({
    input,
    container,
    minLength: opts.minLength === undefined ? 2 : opts.minLength,
    limit: 8,
    debounceMs: opts.debounceMs === undefined ? 1 : opts.debounceMs,
    maxInflight: opts.maxInflight === undefined ? 2 : opts.maxInflight,
    disabled: function () { return false; },
    loadingText: '正在检索器件资料…',
    emptyText: '没有匹配的器件。',
    errorText: function (err) { return '检索失败：' + ((err && err.code) || 'NETWORK'); },
    fetch: function (query, ctx) {
      calls.push(query);
      return fetchImpl(query, ctx, { count: calls.length });
    },
    describe: function (item) {
      return { primary: item.name, meta: '型号 ' + item.mpn, badge: '' };
    },
    onPick: function () {},
    onQuery: function () {}
  });
  const pop = container.children[container.children.length - 1];
  return { box, input, container, pop, calls, doc, LC };
}

test('请求预算：在途最多 2 个，只保留最新待发，最新查询最终出结果', async () => {
  const gates = [];
  let inflight = 0;
  let peak = 0;
  const ctx = setupCustom(function (query) {
    inflight += 1;
    peak = Math.max(peak, inflight);
    return new Promise(function (resolve, reject) {
      gates.push({ query, resolve: function (rows) { inflight -= 1; resolve(rows); } });
    });
  }, { debounceMs: 1, maxInflight: 2 });
  type(ctx.input, '一');
  type(ctx.input, '一二');
  await tick(8);
  type(ctx.input, '一二三');
  await tick(8);
  type(ctx.input, '一二三四');
  await tick(8);
  type(ctx.input, '一二三四五');
  await tick(8);
  assert.equal(ctx.calls.length, 2, '在途已满 2 个后不得再发请求：' + ctx.calls.join(','));
  assert.equal(ctx.box.stats().inflight, 2);
  assert.equal(ctx.box.stats().pending, '一二三四五', '只保留最新一条待发');
  // 放行一个：应立刻补发最新待发（而不是排队里的中间查询）
  gates.shift().resolve([{ catalog_code: 'C1', name: '旧结果', mpn: 'OLD', lab_template_ids: [] }]);
  await tick(10);
  assert.equal(peak, 2, '在途峰值不得超过 2：实测 ' + peak);
  assert.ok(ctx.calls.indexOf('一二三四') === -1, '中间查询应被丢弃：' + ctx.calls.join(','));
  const lastCall = ctx.calls[ctx.calls.length - 1];
  assert.equal(lastCall, '一二三四五');
  gates.shift().resolve([{ catalog_code: 'C2', name: '中间结果', mpn: 'MID', lab_template_ids: [] }]);
  await tick(10);
  gates.shift().resolve([{ catalog_code: 'C3', name: '最终结果', mpn: 'FINAL', lab_template_ids: [] }]);
  await tick(10);
  const names = ctx.pop.children[0].children.map((node) => node.textContent).join('|');
  assert.ok(names.indexOf('最终结果') !== -1, '最新查询的候选应被渲染：' + names);
  assert.equal(ctx.box.stats().inflight, 0, '完成后在途应归零');
  assert.equal(ctx.box.stats().pending, null);
});

test('失败后「重试检索」用同一关键词重发并渲染真实候选', async () => {
  const ctx = setupCustom(function (query, options_, meta) {
    if (meta.count === 1) return Promise.reject({ code: 'NETWORK' });
    return Promise.resolve(ROWS);
  });
  type(ctx.input, '电阻');
  await tick(15);
  const note = ctx.pop.children[1];
  assert.equal(note.getAttribute('data-kind'), 'error');
  assert.ok(note.textContent.indexOf('检索失败') !== -1);
  assert.ok(note.textContent.indexOf('重试检索') !== -1, '错误文案里必须有可点的重试入口');
  const retry = note.children.filter(function (node) {
    return node.tagName === 'BUTTON';
  })[0];
  assert.ok(retry, '重试必须是真实按钮，而不是一句"请重试"');
  assert.equal(ctx.input.value, '电阻', '重试不得改动输入');
  fire(retry, 'click');
  await tick(15);
  assert.deepEqual(ctx.calls, ['电阻', '电阻'], '重试必须用同一关键词再发一次');
  assert.equal(ctx.input.value, '电阻');
  assert.equal(ctx.pop.children[0].children.length, ROWS.length, '重试成功应渲染真实候选');
  assert.equal(note.getAttribute('data-kind'), '');
});

test('关闭面板会丢弃待发查询（不会在关闭后又弹出来）', async () => {
  const gates = [];
  const ctx = setupCustom(function (query) {
    return new Promise(function (resolve) {
      gates.push(function () { resolve(ROWS); });
    });
  });
  type(ctx.input, '电');
  type(ctx.input, '电阻');
  await tick(8);
  type(ctx.input, '电容');
  await tick(8);
  type(ctx.input, '电感');
  await tick(8);
  assert.ok(ctx.box.stats().pending, '应有待发查询');
  fire(ctx.input, 'keydown', { key: 'Escape' });
  assert.equal(ctx.box.stats().pending, null, '关闭后必须丢弃待发');
  assert.equal(ctx.box.isOpen(), false);
  gates.forEach(function (fn) { fn(); });
  await tick(10);
  assert.equal(ctx.box.isOpen(), false, '晚到响应不得重新打开面板');
});

test('有结果时显示「查看全部结果」，空结果/失败时隐藏', async () => {
  const hrefs = [];
  const ctx = setup({
    debounceMs: 1,
    viewAllLabel: '查看全部结果',
    viewAllHref: function (text) {
      hrefs.push(text);
      return '/team/lab?q=' + encodeURIComponent(text);
    }
  });
  type(ctx.input, '电阻');
  await tick(15);
  const footer = ctx.pop.children.filter(function (node) {
    return node.classList.contains('lc-combobox-viewall');
  })[0];
  assert.ok(footer, '有结果时应出现查看全部入口');
  assert.equal(footer.hasAttribute('hidden'), false);
  assert.deepEqual(hrefs, ['电阻']);
  const link = footer.children[0];
  assert.equal(link.tagName, 'A');
  assert.equal(link.getAttribute('href'), '/team/lab?q=%E7%94%B5%E9%98%BB');
  assert.equal(link.textContent, '查看全部结果');

  ctx.queue.push([]);
  type(ctx.input, '没有匹配');
  await tick(15);
  assert.equal(footer.hasAttribute('hidden'), true, '空结果不该保留查看全部入口');

  ctx.queue.push(new Error('boom'));
  type(ctx.input, '电容');
  await tick(20);
  assert.equal(footer.hasAttribute('hidden'), true, '请求失败也不该保留查看全部入口');

  const plain = setup({ debounceMs: 1 });
  type(plain.input, '电阻');
  await tick(15);
  assert.equal(plain.pop.children.filter(function (node) {
    return node.classList.contains('lc-combobox-viewall');
  }).length, 0, '未提供 viewAllHref 时不改变原有 DOM');
});

/* 手工控制 settle 时机的夹具：用来验证"槽位必须真实释放才补发"与"销毁/锁定作废待发"。
 * 并入自独立审查的 6 例草稿（local/web-ui-implementation/combo-draft/），只取与正式用例不重复的 3 例。 */
function setupDeferred(opts) {
  const o = opts || {};
  const loaded = loadCore();
  const LC = loaded.LC;
  const doc = loaded.doc;
  const input = makeEl('input', { type: 'text' });
  input.value = '';
  const container = makeEl('div', { class: 'lc-combobox' });
  container.appendChild(input);
  doc.body.appendChild(container);
  const calls = [];
  const waiting = [];
  const picked = [];
  const box = LC.combobox({
    input: input,
    container: container,
    minLength: 2,
    limit: 8,
    debounceMs: 1,
    maxInflight: 2,
    loadingText: '正在检索…',
    emptyText: '没有匹配。',
    retryText: '重试检索',
    errorText: function (err) { return '检索失败：' + ((err && err.code) || 'NETWORK'); },
    disabled: o.disabled || function () { return false; },
    fetch: function (text) {
      calls.push(text);
      return new Promise(function (resolve, reject) {
        waiting.push({ text: text, resolve: resolve, reject: reject });
      });
    },
    describe: function (item) { return { primary: item.name || String(item) }; },
    onPick: function (item) { picked.push(item); },
    onQuery: function () {}
  });
  const pop = container.children[container.children.length - 1];
  return { LC: LC, box: box, input: input, container: container, pop: pop,
           calls: calls, waiting: waiting, picked: picked, doc: doc };
}

async function typeDeferred(ctx, text) {
  ctx.input.value = text;
  fire(ctx.input, 'input');
  await tick(8);
}

function settleDeferred(entry, rows) {
  entry.resolve(rows === undefined ? ROWS : rows);
}

test('清空与锁定：输入清空/控件禁用时待发作废、面板关闭', async () => {
  const ctx = setupDeferred();
  await typeDeferred(ctx, 'aa');
  await typeDeferred(ctx, 'bb');
  await typeDeferred(ctx, 'cc');
  assert.equal(ctx.box.stats().pending, 'cc');
  ctx.input.value = '';
  fire(ctx.input, 'input');
  await tick(8);
  assert.equal(ctx.box.stats().pending, null);
  assert.equal(ctx.box.isOpen(), false);
  settleDeferred(ctx.waiting[0], ROWS);
  settleDeferred(ctx.waiting[1], ROWS);
  await tick(8);
  assert.deepEqual(ctx.calls, ['aa', 'bb']);

  let locked = false;
  const ctx2 = setupDeferred({ disabled: function () { return locked; } });
  await typeDeferred(ctx2, 'aa');
  await typeDeferred(ctx2, 'bb');
  await typeDeferred(ctx2, 'cc');
  assert.equal(ctx2.box.stats().pending, 'cc');
  locked = true;
  await typeDeferred(ctx2, 'dd');
  assert.equal(ctx2.box.stats().pending, null, '锁定时待发必须作废');
  assert.equal(ctx2.box.isOpen(), false);
  settleDeferred(ctx2.waiting[0], ROWS);
  settleDeferred(ctx2.waiting[1], ROWS);
  await tick(8);
  assert.deepEqual(ctx2.calls, ['aa', 'bb']);
});

test('Home/End 保留原生：不 preventDefault、不触发检索', async () => {
  const ctx = setupDeferred();
  await typeDeferred(ctx, 'aa');
  settleDeferred(ctx.waiting[0], ROWS);
  await tick(8);
  assert.equal(ctx.box.isOpen(), true);
  const home = fire(ctx.input, 'keydown', { key: 'Home' });
  assert.equal(home.defaultPrevented, false, 'Home 必须保留原生光标行为');
  const end = fire(ctx.input, 'keydown', { key: 'End' });
  assert.equal(end.defaultPrevented, false, 'End 必须保留原生光标行为');
  assert.deepEqual(ctx.calls, ['aa']);
  assert.equal(ctx.picked.length, 0);
});

test('销毁：待发作废、晚到回调不重开、不再补发', async () => {
  const ctx = setupDeferred();
  await typeDeferred(ctx, 'aa');
  await typeDeferred(ctx, 'bb');
  await typeDeferred(ctx, 'cc');
  ctx.box.destroy();
  assert.equal(ctx.box.stats().pending, null);
  settleDeferred(ctx.waiting[0], ROWS);
  settleDeferred(ctx.waiting[1], ROWS);
  await tick(8);
  assert.deepEqual(ctx.calls, ['aa', 'bb']);
  assert.equal(ctx.box.isOpen(), false);
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
    }
  }
  console.log('');
  console.log((tests.length - failed) + '/' + tests.length + ' passed, ' + failed + ' failed');
  if (failed) process.exitCode = 1;
}

main().catch((error) => {
  console.error('测试运行器异常：' + (error && error.stack ? error.stack : error));
  process.exitCode = 1;
});
