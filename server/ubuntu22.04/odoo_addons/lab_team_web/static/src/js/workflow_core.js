/* ==========================================================================
 * lab_team_web · 业务页面共享运行时（window.LC）
 * --------------------------------------------------------------------------
 * 原生 ES2019，无框架、无打包器、无内联脚本（CSP script-src 'self'）。
 * 加载顺序：workflow_core.js -> team.js -> pages/<page_id>.js，全部 defer。
 *
 * 职责（只做"外壳级"的公共事，不含任何业务规则）：
 *   1. 解析 body[data-workflow-config]（服务端下发的地址/权限/上限）；
 *   2. 统一 JSON-RPC 调用与错误收敛（按 error.code 分支，不解析 message）；
 *   3. 幂等提交：一次新提交 = 一个 request_key；**结果未知时同 payload 同 key 重试**，
 *      确认失败或用户改输入时换新 key；不自动重试、不在加载时自动提交；
 *   4. 状态区六态（loading/empty/denied/error/unknown/success）；
 *   5. 表单工具（防重复提交、字段错误、值读取）；
 *   6. DOM/格式化/扫码预判等小工具（一律 textContent，禁止 HTML 拼接）。
 *
 * 不做的事：
 *   * 不读写 localStorage 存业务数据/凭据；幂等键只存 sessionStorage（30 分钟）；
 *   * 不接管登录/退出（登录页由 team.js + 原生 /web/session/authenticate 完成，
 *     退出是原生 POST 表单 + CSRF）；
 *   * 不实现任何页面交互（那是 pages/*.js 与三路 UI 子任务的事）。
 * ========================================================================== */
(function () {
  'use strict';

  var body = document.body;
  if (!body || !body.classList.contains('lc-body')) return;

  /* ------------------------------------------------------------------ 配置 */
  var DEFAULT_CONFIG = {
    version: 1,
    base: '',
    page: '',
    domain: '',
    authenticated: false,
    // 身份命名空间（uid + company）：未决提交按"人 + 公司"隔离存储，
    // 换账号/公司后绝不会看到别人的未决操作（server 在 data-workflow-config 下发）。
    identity: { uid: null, company_id: null },
    endpoints: {},
    urls: {},
    permissions: {},
    limits: { pageSize: 24, maxPageSize: 100, maxIssueLines: 100,
              maxPendingCount: 100, labelMaxIds: 200, labelMaxCopies: 200,
              labelMinMm: 5 },
    attempt: { prefix: 'lc-wf-attempt:', ttlMs: 1800000 },
    timeouts: { submitMs: 30000, readMs: 20000 }
  };

  function parseConfig(raw) {
    var parsed = null;
    if (typeof raw === 'string' && raw) {
      try {
        parsed = JSON.parse(raw);
      } catch (error) {
        parsed = null;
      }
    }
    var config = parsed && typeof parsed === 'object' ? parsed : {};
    var merged = {};
    Object.keys(DEFAULT_CONFIG).forEach(function (key) {
      merged[key] = config[key] === undefined ? DEFAULT_CONFIG[key] : config[key];
    });
    // 服务端渲染的兜底（配置缺失时仍能工作）
    if (!merged.base) merged.base = normalizeBase(body.getAttribute('data-base'));
    if (!merged.authenticated) {
      merged.authenticated = body.getAttribute('data-authenticated') === '1';
    }
    if (!merged.page) merged.page = body.getAttribute('data-active-page') || '';
    return merged;
  }

  function normalizeBase(value) {
    var base = typeof value === 'string' ? value.trim() : '';
    if (!base) return '';
    while (base.length > 1 && base.charAt(base.length - 1) === '/') {
      base = base.slice(0, -1);
    }
    if (base.charAt(0) !== '/') base = '/' + base;
    return base === '/' ? '' : base;
  }

  var CONFIG = parseConfig(body.getAttribute('data-workflow-config'));
  var BASE = CONFIG.base;

  /* ------------------------------------------------------------------ 小工具 */
  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function setHidden(node, hidden) {
    if (!node) return;
    if (hidden) node.setAttribute('hidden', 'hidden');
    else node.removeAttribute('hidden');
  }

  function setText(node, text) {
    if (node) node.textContent = text === null || text === undefined ? '' : String(text);
  }

  function clear(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  /** 建元素：只接受安全的属性名，永不设置 on* 事件属性，也永不注入原始 HTML。 */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    var map = attrs || {};
    Object.keys(map).forEach(function (name) {
      var value = map[name];
      if (value === null || value === undefined || value === false) return;
      if (/^on/i.test(name)) return;                       // 内联事件一律忽略
      if (name === 'text') {
        node.textContent = String(value);
        return;
      }
      if (name === 'class' || name === 'className') {
        node.className = String(value);
        return;
      }
      // 明确拒绝 HTML/脚本相关属性名（防止有人把 HTML 注入当捷径）
      if (name === 'html' || name === 'innerHTML' || name === 'outerHTML') return;
      if (name === 'disabled' || name === 'checked' || name === 'hidden' ||
          name === 'required' || name === 'readOnly') {
        node[name === 'readOnly' ? 'readOnly' : name] = !!value;
        return;
      }
      node.setAttribute(name, String(value));
    });
    appendChildren(node, children);
    return node;
  }

  function appendChildren(node, children) {
    if (children === null || children === undefined) return;
    if (Array.isArray(children)) {
      children.forEach(function (child) { appendChildren(node, child); });
      return;
    }
    node.appendChild(children instanceof Node ? children
      : document.createTextNode(String(children)));
  }

  function on(root, selector, type, handler) {
    var scope = root || document;
    scope.addEventListener(type, function (event) {
      var target = event.target;
      if (!target || !target.closest) return;
      var match = target.closest(selector);
      if (!match || !scope.contains(match)) return;
      handler.call(match, event, match);
    });
  }

  function debounce(fn, ms) {
    var timer = 0;
    return function () {
      var args = arguments;
      var self = this;
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        timer = 0;
        fn.apply(self, args);
      }, Math.max(0, ms || 0));
    };
  }

  function query() {
    try {
      return new URLSearchParams(window.location.search);
    } catch (error) {
      return new URLSearchParams('');
    }
  }

  function setQuery(patch) {
    try {
      var url = new URL(window.location.href);
      Object.keys(patch || {}).forEach(function (key) {
        var value = patch[key];
        if (value === null || value === undefined || value === '') url.searchParams.delete(key);
        else url.searchParams.set(key, String(value));
      });
      var target = url.pathname + url.search + url.hash;
      var current = window.location.pathname + window.location.search + window.location.hash;
      if (target !== current) window.history.replaceState({ lcWorkflow: true }, '', target);
    } catch (error) {
      // 地址栏同步失败不影响业务（例如受限嵌入环境）
    }
  }

  function navigate(url, options) {
    var target = String(url || '');
    if (!target || target.charAt(0) !== '/' || target.charAt(1) === '/') {
      // 只允许站内相对路径；绝对 origin 会丢端口并被 CSP form-action 拦
      LC.status.show({ kind: 'error', code: 'VALIDATION_ERROR', message: '目标地址不合法。' });
      return;
    }
    if (options && options.replace) window.location.replace(target);
    else window.location.assign(target);
  }

  /* ------------------------------------------------------------------ UUID / 指纹 */
  function newRequestKey() {
    try {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
      }
    } catch (error) {
      // 老浏览器/非安全上下文：走下面的兜底
    }
    var rand = '';
    try {
      var bytes = new Uint8Array(16);
      if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes);
      else for (var i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
      for (var j = 0; j < bytes.length; j += 1) rand += (bytes[j] + 256).toString(16).slice(1);
    } catch (error) {
      rand = String(Math.random()).slice(2) + String(Math.random()).slice(2);
    }
    return 'lc-' + Date.now().toString(36) + '-' + rand.slice(0, 24);
  }

  /** 稳定序列化（键排序），用于幂等键与"输入是否变化"的判定。 */
  function stableStringify(value) {
    if (value === null || typeof value !== 'object') {
      if (typeof value === 'number' && !isFinite(value)) return 'null';
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) {
      return '[' + value.map(stableStringify).join(',') + ']';
    }
    var keys = Object.keys(value).sort();
    return '{' + keys.map(function (key) {
      return JSON.stringify(key) + ':' + stableStringify(value[key]);
    }).join(',') + '}';
  }

  /** FNV-1a 32 位；只用于本地去重，不作为安全摘要。 */
  function fingerprint(text) {
    var hash = 0x811c9dc5;
    for (var i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = (hash + ((hash << 1) + (hash << 4) + (hash << 7) +
        (hash << 8) + (hash << 24))) >>> 0;
    }
    return ('0000000' + hash.toString(16)).slice(-8);
  }

  function payloadFingerprint(endpoint, params) {
    var filtered = {};
    Object.keys(params || {}).forEach(function (key) {
      if (key === 'request_key') return;      // key 不参与指纹
      filtered[key] = params[key];
    });
    return fingerprint(String(endpoint) + '|' + stableStringify(filtered));
  }

  /* ------------------------------------------------------------------ 未决提交锁（S2-1）
   *
   * 为什么按 scope+endpoint 锁定，而不按 payload 指纹分桶：
   * 按 payload 分桶时，用户在"结果未知"之后把数量从 2 改成 3，就会落到新桶、
   * 拿到新 request_key 并直接发出——服务端如果其实已经记账，就变成两笔
   * （security-round2 S2-1 实测路径）。正确做法是：
   *   * 一个 (user, company, scope, endpoint) 只允许存在一条未决记录；
   *   * 未决期间只有"完全相同的 payload"可以重试，且必须复用原 key；
   *   * payload 变了 → 本地拒绝，不发出请求；只能
   *     (a) 用原 payload 重试，或 (b) 用户核对流水后显式 resolveUnknown()。
   * 记录在**发送之前**落盘：页面刷新/崩溃后仍是"未决"，不会静默丢失。
   */
  var attemptMemory = {};

  function attemptPrefix() {
    return (CONFIG.attempt && CONFIG.attempt.prefix) || 'lc-wf-attempt:';
  }

  function attemptNamespace() {
    var identity = CONFIG.identity || {};
    var uid = identity.uid === null || identity.uid === undefined || identity.uid === ''
      ? 'anon' : String(identity.uid);
    var companyId = identity.company_id === null || identity.company_id === undefined ||
      identity.company_id === '' ? '0' : String(identity.company_id);
    return uid + ':' + companyId;
  }

  function attemptKey(scope, endpoint) {
    var clean = function (value) {
      return String(value === null || value === undefined ? '' : value)
        .replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 80);
    };
    return attemptPrefix() + attemptNamespace() + ':' + clean(scope) + ':' + clean(endpoint);
  }

  function attemptRead(storageKey) {
    var ttl = (CONFIG.attempt && CONFIG.attempt.ttlMs) || 1800000;
    var record = attemptMemory[storageKey] || null;
    try {
      var raw = window.sessionStorage.getItem(storageKey);
      if (raw) {
        var parsed = JSON.parse(raw);
        if (parsed && parsed.key && typeof parsed.at === 'number') record = parsed;
      }
    } catch (error) {
      // sessionStorage 不可用（隐私模式/被禁用）：只用内存
    }
    if (!record) return null;
    if (Date.now() - record.at > ttl) {
      attemptClear(storageKey);
      return null;
    }
    return record;
  }

  function attemptWrite(storageKey, record) {
    attemptMemory[storageKey] = record;
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(record));
    } catch (error) {
      // 忽略：内存里仍然有效（此时跨刷新无法恢复，但不影响不重复提交）
    }
  }

  function attemptClear(storageKey) {
    delete attemptMemory[storageKey];
    try {
      window.sessionStorage.removeItem(storageKey);
    } catch (error) {
      // 忽略
    }
  }

  /** 读出未决记录（不带副作用，供页面在加载时判断是否需要横幅/禁用表单）。 */
  function pendingAttempt(scope, endpoint) {
    var record = attemptRead(attemptKey(scope, endpoint));
    if (!record) return null;
    var payload = null;
    try {
      payload = record.payload ? JSON.parse(record.payload) : null;
    } catch (error) {
      payload = null;
    }
    return {
      scope: scope,
      endpoint: endpoint,
      key: record.key,
      fingerprint: record.fingerprint,
      payload: payload,
      at: record.at,
      ageMs: Date.now() - record.at
    };
  }

  /**
   * 显式解除未决提交。**必须**由"已核对记录"的人发起：
   *   resolveUnknown(scope, endpoint, {confirmed: true, verification: 'absent'|'present'})
   * verification 语义：
   *   'absent'  = 已核对流水，确认上一次**没有**入账（页面可放心重新提交）
   *   'present' = 已核对流水，确认上一次**已经**入账（页面不要重发）
   * 缺 confirmed 或 verification 非法 → 拒绝（不允许"点一下就清"）。
   */
  function resolveUnknown(scope, endpoint, options) {
    var opts = options || {};
    var verification = opts.verification;
    if (opts.confirmed !== true ||
        (verification !== 'absent' && verification !== 'present')) {
      return Promise.reject(new ApiError({
        code: 'VALIDATION_ERROR',
        fields: { confirmed: 'required', verification: 'absent|present' },
        message: '解除未决提交前必须先核对作业流水/领用记录，并明确说明'
          + '“已确认未入账（absent）”或“已确认已入账（present）”。'
      }));
    }
    var pending = pendingAttempt(scope, endpoint);
    if (!pending) {
      return Promise.resolve({ cleared: false, verification: verification });
    }
    attemptClear(attemptKey(scope, endpoint));
    return Promise.resolve({
      cleared: true,
      verification: verification,
      requestKey: pending.key
    });
  }

  /* ------------------------------------------------------------------ 错误 */
  var ERROR_TEXT = {
    UNAUTHORIZED: '登录状态已失效，请重新登录。',
    FORBIDDEN: '当前账号没有该操作权限，请联系库存管理员。',
    NOT_FOUND: '找不到该对象（可能已删除或不属于当前公司）。',
    VALIDATION_ERROR: '请检查填写的参数。',
    PRECONDITION_FAILED: '当前条件不满足，无法完成该操作。',
    CONFLICT: '请求内容已变化或系统繁忙，请刷新后重新提交。',
    DUPLICATE_REQUEST: '该请求已处理，没有重复入账。',
    INTERNAL_ERROR: '服务器处理失败，请把错误编号提供给管理员。',
    AMBIGUOUS_MATERIAL: '同一立创编号存在多个本地档案，请先选择具体档案。'
  };

  //: 只有"服务端明确拒绝、且在写入前回滚"的业务码才允许丢弃未决记录。
  //: UNAUTHORIZED / INTERNAL_ERROR / 未知结果**不在**此列——它们不能证明
  //: 上一次没有提交成功（例如 401 可能发生在写入之后）。
  var CLEARABLE_CODES = {
    VALIDATION_ERROR: true,
    FORBIDDEN: true,
    NOT_FOUND: true,
    PRECONDITION_FAILED: true,
    CONFLICT: true,
    DUPLICATE_REQUEST: true,
    AMBIGUOUS_MATERIAL: true
  };

  function ApiError(options) {
    var opts = options || {};
    this.name = 'LC.ApiError';
    this.code = opts.code || 'INTERNAL_ERROR';
    this.message = opts.message || ERROR_TEXT[this.code] || '操作失败。';
    this.fields = opts.fields && typeof opts.fields === 'object' ? opts.fields : {};
    this.status = opts.status || 0;
    this.unknown = !!opts.unknown;     // true = 结果未知，必须同 key 重试
    this.errorId = this.fields.error_id || '';
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function errorText(error) {
    if (!error) return ERROR_TEXT.INTERNAL_ERROR;
    if (error.unknown) return '结果未知（网络中断或超时），可以用同一请求安全重试。';
    var base = ERROR_TEXT[error.code] || '';
    if (error.code === 'INTERNAL_ERROR' && error.errorId) {
      return base + '（错误编号 ' + error.errorId + '）';
    }
    return base || error.message || '操作失败。';
  }

  function fieldMessages(error) {
    var out = [];
    var fields = error && error.fields ? error.fields : {};
    Object.keys(fields).forEach(function (key) {
      var value = fields[key];
      if (key === 'error_id') return;
      out.push({ field: key, message: typeof value === 'string' ? value : String(value) });
    });
    return out;
  }

  /* ------------------------------------------------------------------ HTTP */
  function rawPost(url, params, options) {
    var opts = options || {};
    var timeoutMs = opts.timeoutMs || (CONFIG.timeouts && CONFIG.timeouts.submitMs) || 30000;
    var controller = null;
    var timer = 0;
    if (typeof AbortController === 'function') controller = new AbortController();

    var requestOptions = {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params || {} })
    };
    if (controller) {
      requestOptions.signal = controller.signal;
      timer = window.setTimeout(function () {
        try { controller.abort(); } catch (error) { /* 忽略 */ }
      }, timeoutMs);
    }

    return fetch(url, requestOptions).then(function (response) {
      if (timer) window.clearTimeout(timer);
      var contentType = response.headers.get('Content-Type') || '';
      if (response.status === 401 || response.status === 403) {
        throw new ApiError({ code: 'UNAUTHORIZED', status: response.status });
      }
      if (!response.ok) {
        if (response.status >= 500 || response.status === 429) {
          throw new ApiError({
            code: 'INTERNAL_ERROR', status: response.status, unknown: true,
            message: '服务器暂时不可用（' + response.status + '），结果未知。'
          });
        }
        throw new ApiError({
          code: 'INTERNAL_ERROR', status: response.status,
          message: '接口不可用（' + response.status + '），请联系管理员。'
        });
      }
      if (contentType.indexOf('json') === -1) {
        // 会话过期时 Odoo 会 303 到登录页，fetch 跟随重定向后拿到 HTML
        throw new ApiError({ code: 'UNAUTHORIZED', status: response.status });
      }
      return response.json();
    }).then(function (payload) {
      if (!payload || typeof payload !== 'object') {
        throw new ApiError({ code: 'INTERNAL_ERROR', unknown: true,
                             message: '服务器返回内容无法解析，结果未知。' });
      }
      if (payload.error) {
        // JSON-RPC 级错误：控制器信封之外的异常，按"结果未知"处理以免丢幂等键
        var detail = payload.error.data && payload.error.data.message;
        throw new ApiError({
          code: 'INTERNAL_ERROR', unknown: true,
          message: detail ? String(detail) : '服务器异常，结果未知。'
        });
      }
      var result = payload.result;
      if (!result || typeof result !== 'object') {
        throw new ApiError({ code: 'INTERNAL_ERROR', unknown: true,
                             message: '服务器返回内容不完整，结果未知。' });
      }
      if (result.ok === false) {
        var info = result.error || {};
        throw new ApiError({
          code: info.code || 'INTERNAL_ERROR',
          message: info.message || '',
          fields: info.fields || {}
        });
      }
      return result.data === undefined ? {} : result.data;
    }).catch(function (error) {
      if (timer) window.clearTimeout(timer);
      if (error instanceof ApiError) {
        if (error.code === 'UNAUTHORIZED') {
          LC.status.show({ kind: 'denied', code: 'UNAUTHORIZED',
                           message: ERROR_TEXT.UNAUTHORIZED, relogin: true });
        }
        throw error;
      }
      // 网络异常 / AbortError / 解析异常 -> 结果未知
      throw new ApiError({
        code: 'INTERNAL_ERROR', unknown: true,
        message: '网络异常或超时，结果未知。'
      });
    });
  }

  function rpc(name, params, options) {
    var url = CONFIG.endpoints && CONFIG.endpoints[name];
    if (!url) {
      return Promise.reject(new ApiError({
        code: 'INTERNAL_ERROR',
        message: '接口未登记：' + name + '（前端契约缺少该端点）。'
      }));
    }
    var opts = options || {};
    return rawPost(url, params || {}, {
      timeoutMs: opts.timeoutMs || (CONFIG.timeouts && CONFIG.timeouts.readMs) || 20000
    });
  }

  /* ------------------------------------------------------------------ 幂等提交（未决锁） */
  function submit(options) {
    var opts = options || {};
    var endpoint = opts.endpoint;
    if (!endpoint) {
      return Promise.reject(new ApiError({
        code: 'INTERNAL_ERROR', message: '提交缺少 endpoint。'
      }));
    }
    var params = {};
    Object.keys(opts.params || {}).forEach(function (key) {
      if (key === 'request_key') return;    // key 只能由本函数生成
      params[key] = opts.params[key];
    });
    var url = CONFIG.endpoints && CONFIG.endpoints[endpoint];
    if (!url) {
      return Promise.reject(new ApiError({
        code: 'INTERNAL_ERROR',
        message: '接口未登记：' + endpoint + '（前端契约缺少该端点）。'
      }));
    }
    var scope = opts.scope || ((CONFIG.page || 'page') + ':' + endpoint);
    var storageKey = attemptKey(scope, endpoint);
    var fingerprintNow = payloadFingerprint(endpoint, params);
    var pending = attemptRead(storageKey);
    var requestKey;

    if (pending) {
      if (pending.fingerprint !== fingerprintNow) {
        // 关键：未决期间**绝不**因为"改了内容"就换新 key 发出去。
        // 用户只能 (a) 用原内容重试，或 (b) 核对记录后 resolveUnknown()。
        return Promise.reject(new ApiError({
          code: 'CONFLICT',
          fields: {
            submit: 'pending_unknown',
            scope: scope,
            endpoint: endpoint,
            request_key: pending.key
          },
          message: '上一次提交结果未知（可能已经入账）。不能修改内容后再次提交；'
            + '请先用原内容重试，或核对作业流水后显式解除未决提交。'
        }));
      }
      requestKey = pending.key;    // 同 payload：复用原 key（跨刷新也成立）
    } else {
      requestKey = newRequestKey();
    }

    // 先落盘再发送：中途崩溃/刷新后仍是"未决"，页面可恢复而不是静默重发。
    attemptWrite(storageKey, {
      key: requestKey,
      fingerprint: fingerprintNow,
      payload: stableStringify(params),
      at: Date.now()
    });

    var body = {};
    Object.keys(params).forEach(function (key) { body[key] = params[key]; });
    body.request_key = requestKey;

    var button = opts.button || null;
    setBusy(button, true, opts.busyLabel);
    LC.status.busy(true, opts.busyLabel || '提交中…');

    return rawPost(url, body, {
      timeoutMs: opts.timeoutMs || (CONFIG.timeouts && CONFIG.timeouts.submitMs) || 30000
    }).then(function (data) {
      // 已确认成功：该逻辑操作的 key 用完了，下一次提交必须换新 key
      attemptClear(storageKey);
      setBusy(button, false);
      LC.status.busy(false);
      return { data: data, replayed: !!(data && data.replayed), requestKey: requestKey };
    }).catch(function (error) {
      setBusy(button, false);
      LC.status.busy(false);
      // 只有"服务端明确拒绝且已回滚"的业务码才清除未决；
      // unknown、UNAUTHORIZED、INTERNAL_ERROR 一律保留（无法推断未提交）。
      if (error instanceof ApiError && !error.unknown && CLEARABLE_CODES[error.code]) {
        attemptClear(storageKey);
      }
      throw error;
    });
  }

  /* ------------------------------------------------------------------ 状态区 */
  var statusNode = null;

  function ensureStatusNode() {
    if (statusNode && document.contains(statusNode)) return statusNode;
    statusNode = qs('[data-lc-status]');
    if (statusNode) return statusNode;
    var root = qs('#workflow-root') || qs('#lc-main') || body;
    var region = qs('[data-lc-status-region]', root);
    statusNode = el('div', { class: 'lc-status', 'data-lc-status': '', role: 'status',
                             'aria-live': 'polite', hidden: true });
    (region || root).insertBefore(statusNode, (region || root).firstChild);
    return statusNode;
  }

  var KIND_ICON = {
    loading: '…', empty: '·', denied: '!', error: '×', unknown: '?', success: '✓'
  };

  var status = {
    mount: function (node) {
      if (node) statusNode = node;
      return statusNode;
    },
    show: function (options) {
      var opts = options || {};
      var kind = opts.kind || 'error';
      var node = ensureStatusNode();
      clear(node);
      node.setAttribute('data-kind', kind);
      node.setAttribute('role', kind === 'error' || kind === 'denied' ? 'alert' : 'status');
      node.setAttribute('aria-live', kind === 'error' || kind === 'denied' ? 'assertive' : 'polite');
      setHidden(node, false);

      var mark = el('span', { class: 'lc-status-mark', 'aria-hidden': 'true',
                              text: KIND_ICON[kind] || '·' });
      var text = el('span', { class: 'lc-status-text', text: opts.message || '' });
      node.appendChild(mark);
      node.appendChild(text);

      if (opts.detail) {
        node.appendChild(el('p', { class: 'lc-status-detail', text: opts.detail }));
      }
      if (opts.relogin && CONFIG.urls && CONFIG.urls.login) {
        var next = window.location.pathname + window.location.search;
        node.appendChild(el('a', {
          class: 'lc-btn lc-btn-primary lc-status-action',
          href: CONFIG.urls.login + (next ? ('?next=' + encodeURIComponent(next)) : ''),
          text: '重新登录'
        }));
      }
      if (typeof opts.retry === 'function') {
        var retry = el('button', { class: 'lc-btn lc-btn-outline lc-status-action',
                                   type: 'button', text: opts.retryLabel || '重试' });
        retry.addEventListener('click', function () {
          status.clear();
          opts.retry();
        });
        node.appendChild(retry);
      }
      return node;
    },
    clear: function () {
      if (!statusNode) return;
      clear(statusNode);
      statusNode.removeAttribute('data-kind');
      setHidden(statusNode, true);
    },
    busy: function (active, label) {
      body.setAttribute('aria-busy', active ? 'true' : 'false');
      var root = qs('#workflow-root');
      if (root) root.classList.toggle('is-busy', !!active);
      if (active && label) {
        status.show({ kind: 'loading', message: label });
      } else if (!active && statusNode && statusNode.getAttribute('data-kind') === 'loading') {
        status.clear();
      }
    }
  };

  /* ------------------------------------------------------------------ 表单 */
  function setBusy(node, active, label) {
    if (!node) return;
    if (active) {
      if (!node.getAttribute('data-lc-label')) {
        node.setAttribute('data-lc-label', node.textContent || '');
      }
      node.disabled = true;
      node.setAttribute('aria-busy', 'true');
      if (label) node.textContent = label;
    } else {
      node.disabled = false;
      node.removeAttribute('aria-busy');
      var original = node.getAttribute('data-lc-label');
      if (original) node.textContent = original;
    }
  }

  function formValues(form) {
    var values = {};
    var nodes = form && form.elements ? Array.prototype.slice.call(form.elements) : [];
    nodes.forEach(function (node) {
      var name = node.getAttribute('name');
      if (!name || node.disabled) return;
      var type = (node.getAttribute('type') || '').toLowerCase();
      if (type === 'submit' || type === 'button' || type === 'reset') return;
      if (type === 'checkbox') {
        if (node.checked) values[name] = node.value;
        else if (!(name in values)) values[name] = '';
        return;
      }
      if (type === 'radio') {
        if (node.checked) values[name] = node.value;
        else if (!(name in values)) values[name] = '';
        return;
      }
      if (type === 'select-multiple' || node.tagName === 'SELECT' && node.multiple) {
        values[name] = Array.prototype.filter.call(node.options, function (opt) {
          return opt.selected;
        }).map(function (opt) { return opt.value; });
        return;
      }
      values[name] = node.value;
    });
    return values;
  }

  function fieldControl(form, field) {
    if (!form) return null;
    return form.querySelector('[data-lc-field="' + field + '"]') ||
      form.querySelector('[name="' + field + '"]');
  }

  function formError(form, field, message) {
    var control = fieldControl(form, field);
    if (!control) return;
    control.setAttribute('data-lc-invalid', 'true');
    var holder = control.closest('.lc-field') || control.parentNode;
    if (!holder) return;
    var note = holder.querySelector('.lc-field-error');
    if (!note) {
      note = el('p', { class: 'lc-field-error', role: 'alert' });
      holder.appendChild(note);
    }
    note.textContent = message || '请检查该项。';
  }

  function clearFormErrors(form) {
    if (!form) return;
    qsa('[data-lc-invalid]', form).forEach(function (node) {
      node.removeAttribute('data-lc-invalid');
    });
    qsa('.lc-field-error', form).forEach(function (node) {
      if (node.parentNode) node.parentNode.removeChild(node);
    });
  }

  function showFieldErrors(form, error) {
    if (!form || !error || error.unknown) return;
    var messages = fieldMessages(error);
    var shown = 0;
    messages.forEach(function (item) {
      if (fieldControl(form, item.field)) {
        formError(form, item.field, item.message);
        shown += 1;
      }
    });
    if (!shown) {
      status.show({ kind: 'error', code: error.code, message: errorText(error) });
    }
  }

  function guard(form, handler) {
    if (!form || form.getAttribute('data-lc-guard') === '1') return;
    form.setAttribute('data-lc-guard', '1');
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      if (form.getAttribute('aria-busy') === 'true') return;   // 防重复提交
      form.setAttribute('aria-busy', 'true');
      form.removeAttribute('data-lc-invalid');
      clearFormErrors(form);
      var button = form.querySelector('button[type="submit"]') ||
        form.querySelector('button:not([type])');
      setBusy(button, true, '提交中…');
      var finished = false;
      var done = function (error) {
        if (finished) return;
        finished = true;
        form.setAttribute('aria-busy', 'false');
        setBusy(button, false);
        if (error) showFieldErrors(form, error);
      };
      try {
        handler(formValues(form), done);
      } catch (error) {
        done(error);
      }
    });
  }

  function setFieldValue(form, name, value) {
    var control = fieldControl(form, name);
    if (!control) return;
    control.value = value === null || value === undefined ? '' : String(value);
  }

  /* ------------------------------------------------------------------ 格式化 / 解析 */
  function fmtQuantity(value) {
    if (value === null || value === undefined || value === '') return '—';
    var number = Number(value);
    if (!isFinite(number)) return '—';
    if (Number.isInteger(number)) return String(number);
    return number.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  }

  function fmtPrice(value, currency) {
    if (value === null || value === undefined || value === '') return '价格待询';
    var number = Number(value);
    if (!isFinite(number)) return '价格待询';
    var code = String(currency || 'CNY').toUpperCase();
    var symbols = { CNY: '¥', RMB: '¥', USD: '$', EUR: '€' };
    var text = Number.isInteger(number) ? String(number) : number.toFixed(2);
    return (symbols[code] || code + ' ') + text;
  }

  function fmtDateTime(value) {
    var text = value === null || value === undefined ? '' : String(value);
    return text ? text.replace('T', ' ').slice(0, 19) : '—';
  }

  function fmtDate(value) {
    var text = value === null || value === undefined ? '' : String(value);
    return text ? text.slice(0, 10) : '—';
  }

  function parseScan(raw) {
    var value = typeof raw === 'string' ? raw : (raw === null || raw === undefined ? '' : String(raw));
    var trimmed = value.trim();
    var folded = '';
    for (var i = 0; i < trimmed.length; i += 1) {
      var code = trimmed.charCodeAt(i);
      folded += (code >= 0xFF01 && code <= 0xFF5E)
        ? String.fromCharCode(code - 0xFEE0) : trimmed.charAt(i);
    }
    folded = folded.toUpperCase();
    var out = { kind: 'unknown', raw: value, normalized: folded };
    if (!folded) return out;
    if (folded.indexOf('LABB:') === 0 || folded.indexOf('LABB-') === 0) {
      out.kind = 'bag';
      return out;
    }
    if (folded.indexOf('LABL:') === 0 || folded.indexOf('LABL-') === 0) {
      out.kind = 'location';
      return out;
    }
    if (/^C[0-9]+$/.test(folded)) {
      out.kind = 'lcsc';
      return out;
    }
    if (/^SN[\s:：-]/.test(folded)) {
      out.kind = 'sn';
      return out;
    }
    return out;
  }

  /* ------------------------------------------------------------------ 会话 */
  var sessionPromise = null;

  /** 原地替换对象内容：LC.permissions 与 CONFIG.permissions 必须保持同一引用。 */
  function replaceInPlace(target, source) {
    if (!target || typeof target !== 'object') return target;
    Object.keys(target).forEach(function (key) { delete target[key]; });
    Object.keys(source || {}).forEach(function (key) { target[key] = source[key]; });
    return target;
  }

  /** 把会话接口返回的权限位/身份合入本地配置（S2-6：刷新必须真的生效）。 */
  function applySession(data) {
    if (!data || typeof data !== 'object') return data;
    if (data.permissions && typeof data.permissions === 'object') {
      replaceInPlace(CONFIG.permissions, data.permissions);
      // LC.permissions 就是 CONFIG.permissions 这个对象，原地替换后引用仍有效
      LC.permissions = CONFIG.permissions;
    }
    if (!CONFIG.identity) CONFIG.identity = { uid: null, company_id: null };
    replaceInPlace(CONFIG.identity, {
      uid: data.uid === undefined ? null : data.uid,
      company_id: data.company && data.company.id !== undefined ? data.company.id : null
    });
    LC.identity = CONFIG.identity;
    return data;
  }

  function session() {
    if (!sessionPromise) {
      sessionPromise = rpc('session', {}).then(applySession).catch(function (error) {
        sessionPromise = null;      // 失败不缓存，下次重试
        throw error;
      });
    }
    return sessionPromise;
  }

  function refreshSession() {
    sessionPromise = null;
    return session();
  }

  function has(permission) {
    if (!permission) return false;
    return !!(CONFIG.permissions && CONFIG.permissions[permission]);
  }

  function requirePermission(permission) {
    if (has(permission)) return true;
    status.show({
      kind: 'denied',
      code: 'FORBIDDEN',
      message: '当前账号没有该操作权限（' + permission + '），请联系库存管理员。'
    });
    return false;
  }

  /* ------------------------------------------------------------------ 初始化 / 页面注册 */
  var initializers = [];
  var pageListeners = [];
  var readyCallbacks = [];
  var domReady = false;
  var initsRan = false;

  function rootNode() {
    return qs('#workflow-root') || qs('#lc-main') || body;
  }

  function pageInfo() {
    var root = qs('#workflow-root');
    return {
      id: (root && root.getAttribute('data-workflow-page')) || CONFIG.page || '',
      domain: (root && root.getAttribute('data-domain')) || CONFIG.domain || '',
      query: query()
    };
  }

  function runInits() {
    if (initsRan) return;
    initsRan = true;
    var info = pageInfo();
    var ctx = { root: rootNode(), page: info, config: CONFIG, permissions: CONFIG.permissions || {} };
    var all = pageListeners.concat(initializers);
    all.forEach(function (fn) {
      try {
        fn(ctx);
      } catch (error) {
        status.show({
          kind: 'error',
          code: 'INTERNAL_ERROR',
          message: '页面脚本初始化失败，请刷新重试（详情见控制台）。'
        });
        if (window.console && console.error) console.error('[LC] init failed', error);
      }
    });
  }

  function onReady(fn) {
    if (typeof fn !== 'function') return;
    if (domReady) fn();
    else readyCallbacks.push(fn);
  }

  document.addEventListener('DOMContentLoaded', function () {
    domReady = true;
    readyCallbacks.splice(0).forEach(function (fn) {
      try { fn(); } catch (error) { if (window.console) console.error(error); }
    });
    runInits();
  }, { once: true });

  /* ------------------------------------------------------------------ 导出 */
  var LC = {
    version: 1,
    config: CONFIG,
    base: BASE,
    endpoints: CONFIG.endpoints || {},
    urls: CONFIG.urls || {},
    permissions: CONFIG.permissions || {},
    identity: CONFIG.identity || { uid: null, company_id: null },
    limits: CONFIG.limits || DEFAULT_CONFIG.limits,
    page: pageInfo(),

    ApiError: ApiError,
    errorText: errorText,
    fieldMessages: fieldMessages,

    rpc: rpc,
    postJson: function (url, params, options) {
      return rawPost(url, params || {}, options || {});
    },
    submit: submit,
    newRequestKey: newRequestKey,
    fingerprint: payloadFingerprint,
    // 未决提交（S2-1）：页面加载时先查，再决定渲染"结果未知"横幅/禁用表单
    pendingAttempt: pendingAttempt,
    resolveUnknown: resolveUnknown,

    session: session,
    refreshSession: refreshSession,
    has: has,
    require: requirePermission,

    status: status,
    setBusy: setBusy,

    guard: guard,
    formValues: formValues,
    formError: formError,
    clearFormErrors: clearFormErrors,
    setFieldValue: setFieldValue,

    el: el,
    clear: clear,
    qs: qs,
    qsa: qsa,
    show: function (node, visible) { setHidden(node, !visible); },
    setText: setText,
    on: on,
    renderRows: function (container, rows, rowFn) {
      if (!container) return;
      clear(container);
      (rows || []).forEach(function (row, index) {
        var node = rowFn ? rowFn(row, index) : null;
        if (node) container.appendChild(node);
      });
    },

    fmt: {
      quantity: fmtQuantity,
      price: fmtPrice,
      date: fmtDate,
      datetime: fmtDateTime,
      bool: function (value) { return value ? '是' : '否'; }
    },
    parse: {
      int: function (value, fallback) {
        var number = parseInt(value, 10);
        return isFinite(number) ? number : (fallback === undefined ? null : fallback);
      },
      float: function (value, fallback) {
        var number = parseFloat(value);
        return isFinite(number) ? number : (fallback === undefined ? null : fallback);
      },
      scan: parseScan
    },

    debounce: debounce,
    navigate: navigate,
    query: query,
    setQuery: setQuery,
    confirmAction: function (message) {
      return window.confirm(message || '确认执行该操作？');
    },

    register: function (pageIds, fn) {
      if (typeof fn !== 'function') return;
      var ids = Array.isArray(pageIds) ? pageIds : [pageIds];
      var current = pageInfo().id;
      if (ids.indexOf(current) !== -1) pageListeners.push(fn);
    },
    init: function (fn) {
      if (typeof fn === 'function') initializers.push(fn);
    },
    ready: onReady
  };

  window.LC = LC;
})();
