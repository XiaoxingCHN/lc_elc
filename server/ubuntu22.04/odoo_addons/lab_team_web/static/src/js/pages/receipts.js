/* ==========================================================================
 * lab_team_web · P3 采购入库页（page_id = receipts）
 * --------------------------------------------------------------------------
 * 两阶段入库（frontend-contract.md §7.2）：
 *   ① 选料号 → 建待入库袋（不增库存）→ 打印追溯标签 PDF
 *   ② 扫待入库码 → 选库位 → 确认入库（这时才产生 stock.move）
 *
 * 硬约束：
 *   * 只用 window.LC（不写 fetch、不拼 JSON-RPC 外壳、不写 innerHTML）；
 *   * 一切写操作走 LC.submit：新提交=新 key；结果未知保留同 body 同 key 显式重试；
 *   * 数量一律展示服务端返回值（stock.quant 实时），本页不维护任何库存台账；
 *   * 只读角色（无 can_receipt）不渲染任何写按钮；
 *   * 错误只按 code 分支，message 直接用服务端中文。
 * ========================================================================== */
(function () {
  'use strict';

  if (!window.LC) return;

  var LABEL_FIELDS_PENDING = ['trace_code', 'name', 'mpn'];
  var LABEL_FIELDS_BAG = ['trace_code', 'name', 'mpn', 'location'];

  /* 未决提交锁（core v1.2：粒度 = (uid, company, scope, endpoint)）
   * scope 必须一对一到"一个逻辑操作"，否则用户改一个字段就能落到新桶绕锁。
   * 这里 4 个 scope 各自独立，且都只对应单一 endpoint。 */
  var LOCKS = {
    create: { scope: 'receipts/create', endpoint: 'pendingCreate', label: '建待入库袋' },
    material: { scope: 'receipts/create-material', endpoint: 'pendingCreate', label: '建档并建待入库袋' },
    confirm: { scope: 'receipts/confirm', endpoint: 'pendingConfirm', label: '确认入库' },
    update: { scope: 'receipts/pending-update', endpoint: 'pendingUpdate', label: '打印选择/取消' }
  };

  /* 未决期间必须禁用的可编辑控件：否则"改料号/数量再提交"会撞 CONFLICT，
   * 更糟的是用户不知道上一次可能已入账。 */
  var LOCK_TARGETS = {
    create: [
      '[data-lc-field="item_key"]',
      '[data-lc-action="resolve-item"]',
      '[data-lc-action="clear-item"]',
      '[data-lc-form="pending-create"] input',
      '[data-lc-form="pending-create"] select',
      '[data-lc-form="pending-create"] button'
    ],
    material: [
      '[data-lc-form="material-create"] input',
      '[data-lc-form="material-create"] button'
    ],
    confirm: [
      '[data-lc-form="pending-confirm"] input',
      '[data-lc-form="pending-confirm"] select',
      '[data-lc-form="pending-confirm"] button',
      '[data-lc-action="resolve-pending"]',
      '[data-lc-scan="shelve"]'
    ],
    update: []
  };

  var state = {
    locations: [],
    selected: null,        // {raw, item_key, product_template_id, name, mpn, package, sn, candidates}
    pending: [],
    cursor: null,
    confirm: null,         // {record, recommendations}
    lastBagId: null,
    locks: { create: null, material: null, confirm: null, update: null }
  };

  /* ------------------------------------------------------------------ 小工具 */
  function q(attr, value) {
    return LC.qs('[' + attr + '="' + value + '"]');
  }

  function slot(name) {
    return q('data-slot', name);
  }

  function setSlot(name, text) {
    var node = slot(name);
    if (node) node.textContent = text === null || text === undefined || text === '' ? '—' : String(text);
  }

  function areaError(name, message) {
    var node = q('data-lc-error', name);
    if (!node) return;
    node.textContent = message || '';
    LC.show(node, !!message);
  }

  function areaLoading(name, on) {
    var node = q('data-lc-loading', name);
    if (node) LC.show(node, on);
  }

  function canReceipt() {
    return LC.has('can_receipt');
  }

  /* 页面自造的中文提示（不是服务端错误，直接展示文字，不套 errorText） */
  function notify(message, kind) {
    LC.status.show({ kind: kind || 'error', message: message });
  }

  /* ------------------------------------------------------------------ 未决提交锁 */
  function lockBox(name) {
    return q('data-lc-lock', name);
  }

  function payloadSummary(name, payload) {
    var data = payload || {};
    if (name === 'create') {
      return '料号 ' + (data.item_key || '—') + '、数量 ' + data.quantity +
        '、袋数 ' + data.count;
    }
    if (name === 'material') {
      var material = data.material || {};
      return '器件 ' + (material.name || '—') + '、数量 ' + data.quantity;
    }
    if (name === 'confirm') {
      return '待入库 #' + data.pending_id + ' → 库位 #' + data.location_id +
        '、数量 ' + data.quantity;
    }
    if (data.action) {
      return '记录 #' + data.pending_id + '：' +
        (data.action === 'cancel' ? '取消' : ('打印选择=' + (data.selected ? '选' : '不选')));
    }
    return '原提交内容已保留';
  }

  function applyLockState(name, locked) {
    (LOCK_TARGETS[name] || []).forEach(function (selector) {
      LC.qsa(selector).forEach(function (node) {
        node.disabled = locked;
      });
    });
    if (name === 'update') renderPending();
  }

  /* 读 core 的未决记录并同步 UI（不在加载时提交任何东西）。 */
  function refreshLock(name) {
    var spec = LOCKS[name];
    if (!spec) return null;
    var pending = null;
    if (typeof LC.pendingAttempt === 'function') {
      pending = LC.pendingAttempt(spec.scope, spec.endpoint);
    }
    state.locks[name] = pending || null;
    var box = lockBox(name);
    if (box) {
      LC.show(box, !!pending);
      var meta = LC.qs('[data-lc-lock-meta]', box);
      if (meta) {
        if (pending) {
          var tail = String(pending.key || '').slice(-6);
          var ageSec = Math.max(0, Math.round((pending.ageMs || 0) / 1000));
          meta.textContent = '请求号 …' + tail + ' · ' + ageSec + ' 秒前 · 原内容：' +
            payloadSummary(name, pending.payload);
        } else {
          meta.textContent = '';
        }
      }
    }
    applyLockState(name, !!pending);
    return pending;
  }

  function refreshAllLocks() {
    Object.keys(LOCKS).forEach(refreshLock);
  }

  function isPendingConflict(err) {
    return !!(err && err.code === 'CONFLICT' && err.fields && err.fields.submit === 'pending_unknown');
  }

  /* 提交失败后的统一收尾：未知结果 / 未决冲突都只保留锁，绝不自动重发、不换 key。 */
  function afterSubmitFailure(name, err) {
    if (!err) return false;
    var locked = !!(err.unknown || isPendingConflict(err));
    refreshLock(name);
    return locked;
  }

  function notifyLocked(name, err) {
    var spec = LOCKS[name];
    var message = isPendingConflict(err)
      ? '上一次「' + spec.label + '」结果未知：不能改内容再次提交。请用原内容重试，或核对作业流水后显式解除。'
      : '「' + spec.label + '」结果未知（网络中断或超时）：请用原内容重试，或核对后显式解除；系统不会自动重发。';
    LC.status.show({ kind: 'unknown', code: err && err.code, message: message });
  }

  function lockRetry(name, button) {
    var spec = LOCKS[name];
    var pending = state.locks[name] ||
      (typeof LC.pendingAttempt === 'function' ? LC.pendingAttempt(spec.scope, spec.endpoint) : null);
    if (!pending) {
      refreshLock(name);
      notify('没有找到未决提交记录（可能已过期）。请刷新页面后核对作业流水。');
      return;
    }
    if (!pending.payload) {
      notify('浏览器没有保存原提交内容（sessionStorage 不可用）：请到作业流水核对后再决定是否重新提交。');
      return;
    }
    LC.submit({
      scope: spec.scope,
      endpoint: spec.endpoint,
      params: pending.payload,
      button: button
    }).then(function (res) {
      refreshLock(name);
      onLockRetrySuccess(name, res);
    }).catch(function (err) {
      if (afterSubmitFailure(name, err)) notifyLocked(name, err);
      else showError(err, function () { lockRetry(name, button); });
    });
  }

  function onLockRetrySuccess(name, res) {
    var data = (res && res.data) || {};
    if (name === 'create' || name === 'material') {
      var records = data.records || [];
      LC.status.show({
        kind: 'success',
        message: '未决提交已确认：' + records.length + ' 条待入库袋（' +
          records.map(function (record) { return record.trace_code; }).join('、') +
          '）。库存未变化。' + (res.replayed ? '（服务端判定为重放，未重复建袋）' : '')
      });
      state.cursor = null;
      loadPending(true);
      return;
    }
    if (name === 'confirm') {
      onConfirmSuccess(res);
      return;
    }
    if (name === 'update') {
      LC.status.show({ kind: 'success', message: '未决的打印选择/取消已确认生效，列表已刷新。' });
      state.cursor = null;
      loadPending(true);
    }
  }

  /* 显式解除：必须先由人核对流水，再选"没有生效/已经生效"。不允许"点一下就清"。 */
  function lockResolve(name, verification) {
    var spec = LOCKS[name];
    var question = verification === 'absent'
      ? '请先到「作业流水 / 待入库列表」核对：确认上一次「' + spec.label + '」没有生效，可以重新提交？'
      : '确认上一次「' + spec.label + '」已经生效，不要再重复提交？';
    if (!LC.confirmAction(question)) return;
    LC.resolveUnknown(spec.scope, spec.endpoint, {
      confirmed: true,
      verification: verification
    }).then(function (result) {
      refreshLock(name);
      LC.status.show({
        kind: 'success',
        message: (verification === 'absent'
          ? '已解除未决提交（确认上次未生效）。重新提交会使用新的请求号。'
          : '已解除未决提交（确认上次已生效）。请不要重复提交，已刷新列表供核对。') +
          (result && result.cleared ? '' : '（本地没有未决记录，已被清理）')
      });
      state.cursor = null;
      loadPending(true);
    }).catch(function (err) {
      showError(err, null);
    });
  }

  function findPending(id) {
    var found = null;
    state.pending.forEach(function (record) {
      if (String(record.id) === String(id)) found = record;
    });
    return found;
  }

  /* 统一的错误呈现：只按 code 分支；unknown 必须给出显式重试入口。 */
  function showError(err, retryFn) {
    if (!err) return;
    if (err.unknown) {
      LC.status.show({
        kind: 'unknown',
        code: err.code,
        message: '结果未知（网络中断或超时）。请先刷新确认，再用完全相同的请求内容重试；' +
                 '系统不会自动重复提交。',
        retry: retryFn
      });
      return;
    }
    if (err.code === 'UNAUTHORIZED') return;          // core 已给「重新登录」
    var detail = '';
    var fields = LC.fieldMessages(err);
    if (fields.length) {
      detail = fields.map(function (item) {
        return item.field + '：' + item.message;
      }).join('；');
    }
    LC.status.show({
      kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
      code: err.code,
      message: LC.errorText(err),
      detail: detail,
      retry: retryFn
    });
  }

  function offlineNote() {
    var online = navigator.onLine;
    if (online === false) {
      LC.status.show({
        kind: 'unknown',
        message: '当前浏览器处于离线状态：所有提交都会失败或结果未知，请恢复网络后再操作。'
      });
      return true;
    }
    return false;
  }

  /* ------------------------------------------------------------------ 权限渲染 */
  function applyPermissions(root) {
    var writable = canReceipt();
    [q('data-lc-write', 'prepare'), q('data-lc-write', 'confirm')].forEach(function (node) {
      LC.show(node, writable);
    });
    LC.show(LC.qs('[data-readonly-note]'), !writable);
    if (!writable) {
      // 只读角色：清掉可能存在的写入口，避免"看得见点不动"
      LC.qsa('[data-lc-action="print-pending"]', root).forEach(function (node) {
        LC.show(node, false);
      });
    }
  }

  /* ------------------------------------------------------------------ 库位 */
  function fillLocationSelect(select, locations, recommended) {
    if (!select) return;
    LC.clear(select);
    select.appendChild(LC.el('option', { value: '', text: '请选择库位' }));
    (recommended || []).forEach(function (item) {
      select.appendChild(LC.el('option', {
        value: String(item.id),
        text: (item.path || item.name || ('库位 #' + item.id)) + '（推荐：' + item.reason + '）'
      }));
    });
    var seen = {};
    (recommended || []).forEach(function (item) { seen[String(item.id)] = true; });
    (locations || []).forEach(function (item) {
      if (seen[String(item.id)]) return;
      seen[String(item.id)] = true;
      select.appendChild(LC.el('option', {
        value: String(item.id),
        text: (item.path || item.name || ('库位 #' + item.id))
      }));
    });
  }

  function loadBootstrap() {
    LC.rpc('bootstrap').then(function (data) {
      state.locations = (data && data.locations) || [];
      fillLocationSelect(slot('location-select'), state.locations, []);
    }).catch(function (err) {
      // 库位列表失败不阻塞建袋：只影响"无推荐时的手动兜底选项"
      if (err && err.code === 'UNAUTHORIZED') showError(err, loadBootstrap);
      else areaError('confirm', '库位列表加载失败：' + LC.errorText(err));
    });
  }

  /* ------------------------------------------------------------------ 待入库袋列表 */
  function loadPending(reset) {
    areaLoading('pending', true);
    areaError('pending', '');
    var params = {};
    if (!reset && state.cursor) params.cursor = state.cursor;
    LC.rpc('pendingList', params).then(function (data) {
      areaLoading('pending', false);
      var records = (data && data.records) || [];
      if (reset || !state.cursor) state.pending = records;
      else state.pending = state.pending.concat(records);
      state.cursor = (data && data.cursor) || null;
      renderPending();
    }).catch(function (err) {
      areaLoading('pending', false);
      areaError('pending', '待入库袋加载失败：' + LC.errorText(err));
      showError(err, function () { loadPending(reset); });
    });
  }

  function stateBadge(record) {
    var map = {
      pending: { text: '待入库', tone: '' },
      done: { text: '已入库', tone: 'ok' },
      cancelled: { text: '已取消', tone: 'bad' }
    };
    var info = map[record.state] || { text: record.state || '—', tone: '' };
    var badge = LC.el('span', { class: 'lc-badge', text: info.text });
    if (info.tone) badge.setAttribute('data-tone', info.tone);
    return badge;
  }

  function pendingRow(record) {
    var tr = LC.el('tr', { 'data-id': String(record.id) });
    var writable = canReceipt() && record.state === 'pending';

    var cellCheck = LC.el('td');
    if (writable) {
      var box = LC.el('input', {
        type: 'checkbox',
        'data-lc-action': 'toggle-select',
        'data-id': String(record.id),
        'aria-label': '选择打印 ' + record.trace_code
      });
      box.checked = !!record.selected;
      box.disabled = !!state.locks.update;
      cellCheck.appendChild(box);
    } else {
      cellCheck.appendChild(LC.el('span', { class: 'lc-hint', text: '—' }));
    }

    var cellTrace = LC.el('td', { class: 'lc-mono', text: record.trace_code });

    var itemLine = LC.el('div', { text: record.name || '—' });
    var metaLine = LC.el('div', {
      class: 'lc-hint',
      text: [record.mpn, record.package, record.sn].filter(Boolean).join(' · ') || '—'
    });
    var cellItem = LC.el('td', {}, [itemLine, metaLine]);

    var cellQty = LC.el('td', { text: LC.fmt.quantity(record.quantity) });
    var cellState = LC.el('td', {}, [stateBadge(record)]);

    var cellBag = LC.el('td');
    if (record.bag_id) {
      cellBag.appendChild(LC.el('a', {
        class: 'lc-card-link',
        href: LC.urls.bag + record.bag_id,
        text: '查看袋'
      }));
    } else {
      cellBag.appendChild(LC.el('span', { class: 'lc-hint', text: '—' }));
    }

    var cellOps = LC.el('td');
    var ops = LC.el('div', { class: 'lc-inline' });
    var updateLocked = !!state.locks.update;
    if (canReceipt() && record.state !== 'cancelled') {
      ops.appendChild(LC.el('button', {
        class: 'lc-btn lc-btn-ghost', type: 'button',
        'data-lc-action': 'print-one', 'data-id': String(record.id),
        text: '打印标签'
      }));
    }
    if (writable) {
      // 追溯码在制袋时分配、标签印的就是它：改数量只能取消后按新码重建，
      // 页面**不提供**"换码"入口（见面板内的说明）。
      ops.appendChild(LC.el('button', {
        class: 'lc-btn lc-btn-ghost', type: 'button',
        'data-lc-action': 'cancel-pending', 'data-id': String(record.id),
        disabled: updateLocked,
        text: '取消'
      }));
    }
    if (!ops.firstChild) ops.appendChild(LC.el('span', { class: 'lc-hint', text: '—' }));
    cellOps.appendChild(ops);

    tr.appendChild(cellCheck);
    tr.appendChild(cellTrace);
    tr.appendChild(cellItem);
    tr.appendChild(cellQty);
    tr.appendChild(cellState);
    tr.appendChild(cellBag);
    tr.appendChild(cellOps);
    return tr;
  }

  function renderPending() {
    var tbody = q('data-lc-rows', 'pending');
    LC.renderRows(tbody, state.pending, pendingRow);
    LC.show(q('data-lc-empty', 'pending'), state.pending.length === 0);
    LC.show(q('data-lc-action', 'pending-more'), !!state.cursor);
    var count = q('data-lc-count', 'pending');
    if (count) {
      var pendingCount = state.pending.filter(function (record) {
        return record.state === 'pending';
      }).length;
      count.textContent = '共 ' + state.pending.length + ' 条（待入库 ' + pendingCount + ' 条）';
    }
  }

  /* ------------------------------------------------------------------ 料号解析 */
  function renderMaterialSelect(candidates) {
    var select = slot('material-select');
    if (!select) return;
    LC.clear(select);
    select.appendChild(LC.el('option', { value: '', text: '请选择本地档案' }));
    (candidates || []).forEach(function (item) {
      var label = [item.sn, item.name, item.mpn].filter(Boolean).join(' · ');
      select.appendChild(LC.el('option', {
        value: String(item.product_template_id),
        text: (label || ('档案 #' + item.product_template_id)) + '（#' + item.product_template_id + '）'
      }));
    });
  }

  function renderMaterialCard() {
    var card = q('data-lc-selected', 'material');
    if (!card) return;
    var picked = state.selected;
    if (!picked) {
      LC.show(card, false);
      return;
    }
    LC.show(card, true);
    setSlot('material-key', picked.item_key || '—');
    setSlot('material-name', picked.name || '（未命名档案）');
    setSlot('material-meta', [
      picked.mpn ? '型号 ' + picked.mpn : '',
      picked.package ? '封装 ' + picked.package : '',
      picked.sn ? 'SN ' + picked.sn : '',
      picked.ambiguous ? '注意：同一编号有多个本地档案，必须在下方选择' : ''
    ].filter(Boolean).join(' · '));
    renderMaterialSelect(picked.candidates || []);
    var select = slot('material-select');
    if (select) {
      if (picked.candidates && picked.candidates.length === 1) {
        select.value = String(picked.candidates[0].product_template_id);
        picked.product_template_id = picked.candidates[0].product_template_id;
      } else {
        select.value = '';
        picked.product_template_id = null;
      }
    }
  }

  function clearSelection() {
    state.selected = null;
    areaError('resolve', '');
    renderMaterialCard();
    var input = q('data-lc-field', 'item_key');
    if (input) input.value = '';
  }

  /* 解析错误文案：**必须带真实 code**（不把失败说成"没数据"，也不造空成功）。 */
  function resolveErrorText(err) {
    var code = (err && err.code) || 'INTERNAL_ERROR';
    var base = err && err.code === 'VALIDATION_ERROR' && err.message
      ? err.message
      : LC.errorText(err);
    return base + '（' + code + '）';
  }

  /* 「解析料号」的输入契约：页面承诺两种 key，两条真实接口，各走各的。
   *
   *   lcsc:C123 / lcsc:C0…  → 剥前缀成裸 C 码，仍用扫码端点 resolve_code
   *                           （保留多档案候选 / 立创原厂码 / SN 逻辑不变）
   *   lab:42                → catalogDetail（后端明确支持 lab:<id>，含"仅本地"档案），
   *                           返回值适配成页面的 picked 形状，保持指定本地档案
   *   其余（LABB:/LABL:/SN/立创原厂 JSON/裸 C 码）→ 原路径原样发给 resolve_code
   */
  function resolveItem() {
    var input = q('data-lc-field', 'item_key');
    var typed = input ? String(input.value || '').trim() : '';
    if (!typed) {
      areaError('resolve', '请先扫码或粘贴统一料号。');
      return;
    }
    areaError('resolve', '');
    areaLoading('resolve', true);

    var lcscMatch = /^lcsc\s*:\s*(.+)$/i.exec(typed);
    if (lcscMatch) {
      var code = lcscMatch[1].trim();
      requestResolve(code, typed, 'lcsc:' + code);
      return;
    }
    var labMatch = /^lab\s*:\s*(\d+)$/i.exec(typed);
    if (labMatch) {
      requestLocalDetail('lab:' + labMatch[1], typed);
      return;
    }
    requestResolve(typed, typed, '');
  }

  /* 扫码端点：raw 是发给服务端的载荷，typed 是用户输入（用于"输入已改动"校验）。
   * assumeItemKey：仅当输入本身是 lcsc:Cxxx 且本地暂无档案时，用它作为待建档的 item_key
   * （pendingCreate 会在建袋时建最小档案；建袋结果仍以服务端返回为准）。 */
  function requestResolve(raw, typed, assumeItemKey) {
    LC.rpc('resolve', { raw: raw }).then(function (data) {
      areaLoading('resolve', false);
      var kind = (data && data.kind) || '';
      if (kind === 'bag' || kind === 'location') {
        clearSelection();
        areaError('resolve', '解析结果是' + (kind === 'bag' ? '袋追溯码' : '库位库码') +
          '，不是料号；请在「扫码」页处理，或改为扫描统一料号（lcsc:C… / lab:…）。');
        return;
      }
      var candidates = (data && data.candidates) || [];
      var material = data && data.material ? data.material : null;
      var picked = {
        raw: typed,
        item_key: (data && data.item_key) || (material && material.item_key) || '',
        product_template_id: (data && data.product_template_id) || (material && material.product_template_id) || null,
        name: (material && material.name) || '',
        mpn: (material && material.mpn) || '',
        package: (material && material.package) || '',
        sn: (material && material.sn) || '',
        ambiguous: !!(data && data.ambiguous_material) || candidates.length > 1,
        candidates: candidates
      };
      state.selected = picked;
      renderMaterialCard();
      if (!picked.item_key && assumeItemKey) {
        // 输入是 lcsc:Cxxx，但本地还没有档案：保留该编号本身，让建袋时由服务端建最小档案。
        // 这不是"空成功"——建袋仍是真实写操作，结果以服务端返回的 records 为准。
        picked.item_key = assumeItemKey;
        state.selected = picked;
        renderMaterialCard();
        areaError('resolve', '该 C 编号在本地还没有物料档案：可以直接建袋，服务端会按该编号建立最小档案（只建档、不写库存）。');
        return;
      }
      if (!picked.item_key) {
        areaError('resolve', '服务端没有返回统一料号，请确认扫码内容（可识别 LABB:/LABL:/C 编号/SN）。');
        return;
      }
      if (picked.ambiguous) {
        areaError('resolve', '同一编号在本地有多个档案：请在「本地档案」下拉里选一个，系统不会自动选择。');
      }
      var jlc = (data && data.supplier_metadata) || {};
      if (jlc && (jlc.order_no || jlc.mpn)) {
        LC.status.show({
          kind: 'success',
          message: '已识别立创原厂袋：订单 ' + (jlc.order_no || '—') +
                   '，型号 ' + (jlc.mpn || '—') + '，数量 ' + (jlc.quantity === undefined || jlc.quantity === null ? '—' : jlc.quantity) +
                   '。建袋后请在「扫码上架」时把原厂袋二维码一并提交，才会落库供应商信息。'
        });
      }
    }).catch(function (err) {
      areaLoading('resolve', false);
      areaError('resolve', '料号解析失败：' + resolveErrorText(err));
      if (err && err.code !== 'VALIDATION_ERROR') showError(err, resolveItem);
    });
  }

  /* 本地档案编号（lab:<id>）：复用 catalogDetail，不新增 route、不做 ORM 透传。
   * 适配成页面既有的 picked 形状，candidates 用 lab_templates + lab_template_ids 合并，
   * 多个档案时仍全部列出、不自动首选（只有唯一档案才带 product_template_id）。 */
  function requestLocalDetail(itemKey, typed) {
    LC.rpc('catalogDetail', { item_key: itemKey }).then(function (data) {
      areaLoading('resolve', false);
      var item = (data && data.item) || {};
      var templates = (data && data.lab_templates) || [];
      var candidates = [];
      var seen = {};
      templates.forEach(function (tpl) {
        var id = LC.parse.int(tpl && tpl.id, 0);
        if (!id || seen[String(id)]) return;
        seen[String(id)] = true;
        candidates.push({
          product_template_id: id,
          sn: (tpl && tpl.sn) || null,
          name: (tpl && tpl.name) || item.name || '',
          mpn: item.mpn || null,
          package: item.package || null
        });
      });
      (item.lab_template_ids || []).forEach(function (rawId) {
        var id = LC.parse.int(rawId, 0);
        if (!id || seen[String(id)]) return;
        seen[String(id)] = true;
        candidates.push({
          product_template_id: id,
          sn: null,
          name: item.name || '',
          mpn: item.mpn || null,
          package: item.package || null
        });
      });
      if (!candidates.length) {
        // 不造空成功：detail 没给出任何档案就明确说是服务端没返回，而不是"已选好"
        areaError('resolve', '该本地档案没有返回任何可入库的物料档案（catalogDetail 返回空 lab_templates）。');
        return;
      }
      var single = candidates.length === 1 ? candidates[0] : null;
      var picked = {
        raw: typed,
        item_key: item.item_key || itemKey,
        product_template_id: single ? single.product_template_id : null,
        name: item.name || (single && single.name) || '',
        mpn: item.mpn || '',
        package: item.package || '',
        sn: (single && single.sn) || '',
        ambiguous: candidates.length > 1,
        candidates: candidates
      };
      state.selected = picked;
      renderMaterialCard();
      if (picked.ambiguous) {
        areaError('resolve', '该料号在本地有多个档案：请在「本地档案」下拉里选一个，系统不会自动选择。');
      }
    }).catch(function (err) {
      areaLoading('resolve', false);
      var hint = '';
      if (err && err.code === 'FORBIDDEN') {
        hint = '；按本地档案解析需要器件资料读取权限，请改用该物料的 C 编号或 SN 扫码';
      } else if (err && err.code === 'NOT_FOUND') {
        hint = '；该本地档案不存在或不属于当前公司';
      }
      areaError('resolve', '按本地档案解析失败：' + resolveErrorText(err) + hint);
      showError(err, resolveItem);
    });
  }

  /* ------------------------------------------------------------------ 建袋（写） */
  function wireCreateForm(root) {
    var form = LC.qs('[data-lc-form="pending-create"]', root);
    if (!form) return;
    LC.guard(form, function (values, done) {
      var input = q('data-lc-field', 'item_key');
      var typed = input ? String(input.value || '').trim() : '';
      var picked = state.selected;
      if (!picked || !picked.item_key) {
        done();
        notify('请先解析并选择统一料号。');
        return;
      }
      if (typed && picked.raw && typed !== picked.raw) {
        done();
        areaError('resolve', '料号输入已改动，请重新点「解析料号」后再建袋。');
        return;
      }
      var templateId = LC.parse.int(values.product_template_id, 0);
      if (picked.ambiguous && !templateId) {
        done();
        areaError('resolve', '同一编号有多个本地档案：请先选定一个档案。');
        return;
      }
      var quantity = LC.parse.float(values.quantity, 0);
      if (!quantity || quantity <= 0) {
        done();
        LC.formError(form, 'quantity', '数量必须大于 0。');
        return;
      }
      var count = LC.parse.int(values.count, 1);
      if (!count || count < 1 || count > 100) {
        done();
        LC.formError(form, 'count', '袋数必须是 1~100 的整数。');
        return;
      }
      if (offlineNote()) { done(); return; }

      var params = {
        item_key: picked.item_key,
        quantity: quantity,
        count: count,
        note: String(values.note || '').trim()
      };
      if (templateId) params.product_template_id = templateId;
      var button = form.querySelector('button[type="submit"]');
      submitCreate(params, button, function () { done(); }, function (err) { done(err); });
    });
  }

  function submitCreate(params, button, onOk, onFail) {
    if (state.locks.create) {
      notifyLocked('create', { code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
      onFail({ code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
      return;
    }
    LC.submit({
      scope: LOCKS.create.scope,
      endpoint: LOCKS.create.endpoint,
      params: params,
      button: button
    }).then(function (res) {
      refreshLock('create');
      var records = (res.data && res.data.records) || [];
      var codes = records.map(function (record) { return record.trace_code; });
      LC.status.show({
        kind: 'success',
        message: '已建 ' + records.length + ' 条待入库袋（未增加库存）：' + codes.join('、') +
                 '。下一步：勾选并打印标签，或到「扫码上架」扫码入库。'
      });
      onOk();
      state.cursor = null;
      loadPending(true);
    }).catch(function (err) {
      if (err && err.code === 'AMBIGUOUS_MATERIAL') {
        var candidates = (err.fields && err.fields.candidates) || [];
        if (candidates.length) {
          state.selected = state.selected || {};
          state.selected.candidates = candidates;
          state.selected.ambiguous = true;
          renderMaterialCard();
          areaError('resolve', err.message || '同一编号有多个本地档案，请选择。');
        }
      }
      onFail(err);
      if (afterSubmitFailure('create', err)) {
        notifyLocked('create', err);
        return;
      }
      showError(err, function () { submitCreate(params, button, onOk, onFail); });
    });
  }

  function wireMaterialCreateForm(root) {
    var form = LC.qs('[data-lc-form="material-create"]', root);
    if (!form) return;
    LC.guard(form, function (values, done) {
      var name = String(values.material_name || '').trim();
      if (!name) {
        done();
        LC.formError(form, 'material_name', '请填写器件名称。');
        return;
      }
      var quantity = LC.parse.float(values.quantity, 0);
      if (!quantity || quantity <= 0) {
        done();
        LC.formError(form, 'quantity', '数量必须大于 0。');
        return;
      }
      if (offlineNote()) { done(); return; }
      var params = {
        material: {
          name: name,
          mpn: String(values.material_mpn || '').trim(),
          package: String(values.material_package || '').trim(),
          brand: String(values.material_brand || '').trim(),
          specification: String(values.material_specification || '').trim()
        },
        quantity: quantity,
        count: 1
      };
      var button = form.querySelector('button[type="submit"]');
      if (state.locks.material) {
        done();
        notifyLocked('material', { code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
        return;
      }
      LC.submit({
        scope: LOCKS.material.scope,
        endpoint: LOCKS.material.endpoint,
        params: params,
        button: button
      }).then(function (res) {
        done();
        refreshLock('material');
        var records = (res.data && res.data.records) || [];
        LC.status.show({
          kind: 'success',
          message: '已建档并建 ' + records.length + ' 条待入库袋（未增加库存）：' +
                   records.map(function (record) { return record.trace_code; }).join('、')
        });
        state.cursor = null;
        loadPending(true);
      }).catch(function (err) {
        done(err);
        if (afterSubmitFailure('material', err)) {
          notifyLocked('material', err);
          return;
        }
        showError(err, function () {
          LC.submit({
            scope: LOCKS.material.scope,
            endpoint: LOCKS.material.endpoint,
            params: params,
            button: button
          });
        });
      });
    });
  }

  /* ------------------------------------------------------------------ 待入库袋写操作
   *
   * 只做后端真实支持的两种 action（select / cancel）。**没有**"编辑数量"：
   * 追溯码在制袋时分配、标签印的就是它，前端不得用"新建 + 取消旧记录"换码
   * （那会让已打印的标签指向一条已取消记录）。需要原地改数量时由后端补
   * pending/update action=edit，页面再接入。
   *
   * 两个 action 共用一个 scope（receipts/pending-update）：未决期间不允许改到别的行，
   * 否则同一批状态变更会绕过本地未决锁。 */
  function updateLocked() {
    return !!state.locks.update;
  }

  function toggleSelect(node) {
    var recordId = node.getAttribute('data-id');
    var next = !!node.checked;
    if (updateLocked()) {
      node.checked = !next;
      notifyLocked('update', { code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
      return;
    }
    LC.submit({
      scope: LOCKS.update.scope,
      endpoint: LOCKS.update.endpoint,
      params: { pending_id: LC.parse.int(recordId, 0), action: 'select', selected: next },
      button: node
    }).then(function (res) {
      var updated = (res.data && res.data.record) || null;
      state.pending = state.pending.map(function (record) {
        return updated && record.id === updated.id ? updated : record;
      });
      renderPending();
    }).catch(function (err) {
      node.checked = !next;
      if (afterSubmitFailure('update', err)) {
        notifyLocked('update', err);
        return;
      }
      showError(err, null);
    });
  }

  function cancelPending(node) {
    var recordId = node.getAttribute('data-id');
    var record = findPending(recordId);
    if (!record) return;
    if (updateLocked()) {
      notifyLocked('update', { code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
      return;
    }
    if (!LC.confirmAction('确认取消待入库袋 ' + record.trace_code + '？取消后不能恢复；' +
      '该追溯码已印在标签上，取消后标签作废，需要重新建袋并重打标签。')) return;
    LC.submit({
      scope: LOCKS.update.scope,
      endpoint: LOCKS.update.endpoint,
      params: { pending_id: record.id, action: 'cancel' },
      button: node
    }).then(function (res) {
      var updated = (res.data && res.data.record) || null;
      state.pending = state.pending.map(function (item) {
        return updated && item.id === updated.id ? updated : item;
      });
      renderPending();
      LC.status.show({
        kind: 'success',
        message: '待入库袋 ' + record.trace_code + ' 已取消（库存未变化，记录保留追溯）。'
      });
    }).catch(function (err) {
      if (afterSubmitFailure('update', err)) {
        notifyLocked('update', err);
        return;
      }
      showError(err, null);
    });
  }

  function selectAllPending(checked) {
    if (updateLocked()) {
      notifyLocked('update', { code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
      return;
    }
    var targets = state.pending.filter(function (record) {
      return record.state === 'pending' && !!record.selected !== checked;
    });
    if (!targets.length) {
      LC.status.show({ kind: 'empty', message: '没有需要变更选择的待入库袋。' });
      return;
    }
    var queue = targets.slice();
    function step() {
      var record = queue.shift();
      if (!record) {
        state.cursor = null;
        loadPending(true);
        return;
      }
      LC.submit({
        scope: LOCKS.update.scope,
        endpoint: LOCKS.update.endpoint,
        params: { pending_id: record.id, action: 'select', selected: checked }
      }).then(step).catch(function (err) {
        if (afterSubmitFailure('update', err)) {
          notifyLocked('update', err);
          state.cursor = null;
          loadPending(true);
          return;
        }
        showError(err, null);
      });
    }
    step();
  }

  /* ------------------------------------------------------------------ PDF（真实表单 POST） */
  function submitPdf(kind, ids, copies, fields, widthMm, heightMm) {
    var form = LC.qs('[data-lc-pdf-form="labels"]');
    if (!form) {
      LC.status.show({ kind: 'error', message: '页面缺少标签表单，无法下载 PDF。' });
      return;
    }
    if (!ids || !ids.length) {
      LC.status.show({ kind: 'error', message: '请先选择要打印的对象。' });
      return;
    }
    if (ids.length > LC.limits.labelMaxIds) {
      LC.status.show({
        kind: 'error',
        message: '一次最多打印 ' + LC.limits.labelMaxIds + ' 个标签，请分批下载。'
      });
      return;
    }
    form.elements.kind.value = kind;
    form.elements.ids.value = ids.join(',');
    form.elements.copies.value = String(copies || 1);
    form.elements.width_mm.value = String(widthMm || 60);
    form.elements.height_mm.value = String(heightMm || 40);
    form.elements.margin_mm.value = '10';
    form.elements.gap_mm.value = '2';
    form.elements.fields.value = (fields || []).join(',');
    form.submit();
    LC.status.show({
      kind: 'success',
      message: '已提交 PDF 生成请求（新标签页打开）。若浏览器拦截了弹窗，请允许本站弹窗后重试。'
    });
  }

  function renderPlan(name, plan) {
    var node = q('data-lc-plan', name);
    if (!node) return;
    LC.clear(node);
    LC.show(node, true);
    var ready = plan && plan.ready !== false;
    node.appendChild(LC.el('p', {
      text: '标签 ' + (plan.label_count || 0) + ' 张 · 每页 ' + (plan.labels_per_page || 0) +
            ' 张 · 共 ' + (plan.page_count || 0) + ' 页'
    }));
    if (plan.preview_title_pt || plan.preview_body_pt) {
      node.appendChild(LC.el('p', {
        class: 'lc-hint',
        text: '预览字号：标题 ' + (plan.preview_title_pt || '—') + 'pt / 正文 ' +
              (plan.preview_body_pt || '—') + 'pt（下限 ' + (plan.min_title_pt || '—') + ' / ' +
              (plan.min_body_pt || '—') + 'pt）'
      }));
    }
    if (!ready) {
      node.appendChild(LC.el('p', {
        class: 'lc-alert lc-alert-error',
        role: 'alert',
        text: '当前参数不可排版：' + (plan.blocking_reason || '未知原因')
      }));
    } else if (plan.may_need_scaling) {
      node.appendChild(LC.el('p', {
        class: 'lc-hint',
        text: '文字可能放不下（估算 ' + (plan.estimated_text_height_mm || '—') + 'mm / 可用 ' +
              (plan.available_text_height_mm || '—') + 'mm），建议加大尺寸或减少字段。'
      }));
    }
  }

  function planPending() {
    var ids = selectedIds();
    if (!ids.length) {
      areaError('print', '请先勾选要打印的待入库袋。');
      return;
    }
    areaError('print', '');
    var copies = LC.parse.int(readCopies(), 1) || 1;
    LC.rpc('labelsPlan', {
      kind: 'pending',
      ids: ids,
      copies: copies,
      width_mm: 60,
      height_mm: 40,
      margin_mm: 10,
      gap_mm: 2,
      fields: LABEL_FIELDS_PENDING
    }).then(function (plan) {
      renderPlan('pending', plan);
    }).catch(function (err) {
      if (err && err.code === 'VALIDATION_ERROR') {
        var fields = LC.fieldMessages(err);
        areaError('print', (fields.length ? fields.map(function (item) {
          return item.field + '：' + item.message;
        }).join('；') : err.message) || LC.errorText(err));
        return;
      }
      areaError('print', '排版试算失败：' + LC.errorText(err));
      showError(err, planPending);
    });
  }

  function selectedIds() {
    return state.pending.filter(function (record) {
      return record.state === 'pending' && record.selected;
    }).map(function (record) { return record.id; });
  }

  function readCopies() {
    var node = q('data-lc-copies', 'pending');
    return node ? node.value : '1';
  }

  /* ------------------------------------------------------------------ 扫码上架 */
  function renderRecommendations(recommendations) {
    var list = q('data-lc-rows', 'recommend');
    LC.renderRows(list, recommendations, function (item) {
      return LC.el('li', {
        class: 'lc-recommend-item',
        text: (item.name || ('库位 #' + item.id)) + '（' + (item.reason || '推荐') + '）'
      });
    });
    LC.show(q('data-lc-empty', 'recommend'), recommendations.length === 0);
  }

  function resolvePending() {
    var input = LC.qs('[data-lc-scan="shelve"]');
    var raw = input ? String(input.value || '').trim() : '';
    if (!raw) {
      areaError('confirm', '请先扫描或输入待入库袋追溯码（LABB:…）。');
      return;
    }
    areaError('confirm', '');
    areaLoading('confirm', true);
    LC.rpc('pendingResolve', { raw: raw }).then(function (data) {
      areaLoading('confirm', false);
      var record = data && data.record ? data.record : null;
      var bag = data && data.bag ? data.bag : null;
      if (!record) {
        LC.show(q('data-lc-result', 'shelve'), false);
        if (bag) {
          LC.status.show({
            kind: 'success',
            message: '该袋已入库：' + bag.trace_code + '（库位 ' +
                     (bag.location_path || bag.location_code || '—') + '）。',
            detail: '已入库的袋不能再确认一次；如需查看追溯请打开袋详情。'
          });
          setSlot('success-trace', bag.trace_code);
          state.lastBagId = bag.id;
          var link = slot('success-bag-link');
          if (link) {
            link.setAttribute('href', LC.urls.bag + bag.id);
            LC.show(link, true);
          }
          LC.show(q('data-lc-success', 'shelve'), true);
        } else {
          LC.status.show({ kind: 'empty', message: '没有解析到待入库袋。' });
        }
        return;
      }
      if (record.state === 'done') {
        LC.show(q('data-lc-result', 'shelve'), false);
        LC.status.show({
          kind: 'success',
          message: '该待入库袋已确认入库（' + record.trace_code + '）。重复确认不会重复记账。'
        });
        loadPending(true);
        return;
      }
      if (record.state === 'cancelled') {
        LC.show(q('data-lc-result', 'shelve'), false);
        LC.status.show({ kind: 'error', message: '该待入库袋已取消，不能入库；请重新建袋。' });
        return;
      }
      state.confirm = {
        record: record,
        recommendations: (data && data.recommendations) || [],
        retry: null
      };
      LC.show(q('data-lc-result', 'shelve'), true);
      LC.show(q('data-lc-success', 'shelve'), false);
      setSlot('pending-trace', record.trace_code);
      setSlot('pending-item', [record.name, record.mpn, record.package].filter(Boolean).join(' · '));
      setSlot('pending-quantity', LC.fmt.quantity(record.quantity) + '（初始 ' +
        LC.fmt.quantity(record.initial_quantity) + '）');
      setSlot('pending-state', record.state === 'pending' ? '待入库' : (record.state || '—'));
      renderRecommendations(state.confirm.recommendations);
      fillLocationSelect(slot('location-select'), state.locations, state.confirm.recommendations);
      var confirmForm = LC.qs('[data-lc-form="pending-confirm"]');
      if (confirmForm) {
        LC.clearFormErrors(confirmForm);
        LC.setFieldValue(confirmForm, 'quantity', LC.fmt.quantity(record.quantity));
        LC.setFieldValue(confirmForm, 'sn', record.sn || '');
        LC.setFieldValue(confirmForm, 'supplier_qr', '');
      }
      var writeArea = q('data-lc-write', 'confirm');
      LC.show(writeArea, canReceipt());
      if (!canReceipt()) {
        LC.status.show({
          kind: 'denied',
          message: '当前账号没有入库权限：可以看到该待入库袋的事实，但确认入库按钮不会显示。'
        });
      }
    }).catch(function (err) {
      areaLoading('confirm', false);
      LC.show(q('data-lc-result', 'shelve'), false);
      if (err && err.code === 'NOT_FOUND') {
        areaError('confirm', '找不到该待入库袋：可能属于其他账号、已删除，或不是本系统的袋码。' +
          '（服务端按当前账号与公司过滤，不会泄露他人记录）');
        return;
      }
      areaError('confirm', '解析失败：' + LC.errorText(err));
      showError(err, resolvePending);
    });
  }

  function doConfirm(params, button, done) {
    if (state.locks.confirm) {
      if (done) done();
      notifyLocked('confirm', { code: 'CONFLICT', fields: { submit: 'pending_unknown' } });
      return;
    }
    LC.submit({
      scope: LOCKS.confirm.scope,
      endpoint: LOCKS.confirm.endpoint,
      params: params,
      button: button
    }).then(function (res) {
      refreshLock('confirm');
      if (done) done();
      onConfirmSuccess(res);
    }).catch(function (err) {
      if (done) done(err);
      onConfirmError(err);
    });
  }

  function onConfirmError(err) {
    if (afterSubmitFailure('confirm', err)) {
      notifyLocked('confirm', err);
      return;
    }
    showError(err, null);
    if (err && (err.code === 'PRECONDITION_FAILED' || err.code === 'VALIDATION_ERROR' ||
        err.code === 'NOT_FOUND' || err.code === 'FORBIDDEN')) {
      // 失败后刷新列表，让用户看到真实状态（不猜结果）
      state.cursor = null;
      loadPending(true);
    }
  }

  function onConfirmSuccess(res) {
    var data = res.data || {};
    var record = data.record || null;
    var bag = data.bag || null;
    var replayed = !!res.replayed;
    var trace = bag ? bag.trace_code : (record ? record.trace_code : '—');
    var location = bag ? (bag.location_path || bag.location_code || '—') : '—';
    var quantity = bag ? bag.quantity : (record ? record.quantity : '');

    LC.show(q('data-lc-result', 'shelve'), false);
    LC.show(q('data-lc-success', 'shelve'), true);
    setSlot('success-trace', trace);
    setSlot('success-location', location);
    setSlot('success-quantity', LC.fmt.quantity(quantity));
    setSlot('success-total', LC.fmt.quantity(data.lab_quantity));

    var bagId = bag ? bag.id : (record && record.bag_id ? record.bag_id : null);
    state.lastBagId = bagId;
    var link = slot('success-bag-link');
    if (link) {
      if (bagId) {
        link.setAttribute('href', LC.urls.bag + bagId);
        LC.show(link, true);
      } else {
        LC.show(link, false);
      }
    }

    LC.status.show({
      kind: 'success',
      message: (replayed ? '该袋此前已处理过（服务端未重复入账，replayed=true）：' : '入库成功：') +
               '袋 ' + trace + '，库位 ' + location + '，数量 ' + LC.fmt.quantity(quantity) +
               '，该物料实验室库存合计 ' + LC.fmt.quantity(data.lab_quantity) + '。'
    });
    state.confirm = null;
    state.cursor = null;
    loadPending(true);
  }

  function wireConfirmForm(root) {
    var form = LC.qs('[data-lc-form="pending-confirm"]', root);
    if (!form) return;
    LC.guard(form, function (values, done) {
      if (!state.confirm || !state.confirm.record) {
        done();
        areaError('confirm', '请先扫描待入库袋。');
        return;
      }
      var locationId = LC.parse.int(values.location_id, 0);
      if (!locationId) {
        done();
        LC.formError(form, 'location_id', '请选择入库库位（推荐只是顺序，必须由你选定）。');
        return;
      }
      var quantity = LC.parse.float(values.quantity, 0);
      if (!quantity || quantity <= 0) {
        done();
        LC.formError(form, 'quantity', '实收数量必须大于 0。');
        return;
      }
      if (offlineNote()) { done(); return; }
      var params = {
        pending_id: state.confirm.record.id,
        location_id: locationId,
        quantity: quantity
      };
      var supplier = String(values.supplier_qr || '').trim();
      if (supplier) params.supplier_qr = supplier;
      var sn = String(values.sn || '').trim();
      if (sn) params.sn = sn;
      var button = form.querySelector('button[type="submit"]');
      doConfirm(params, button, done);
    });
  }

  /* ------------------------------------------------------------------ 标签页 ---------- */
  function wireTabs(root) {
    var tabs = LC.qsa('[data-lc-action="tab"]', root);
    function activate(name) {
      tabs.forEach(function (tab) {
        var active = tab.getAttribute('data-tab') === name;
        tab.classList.toggle('is-active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      LC.show(q('data-lc-panel', 'prepare'), name === 'prepare');
      LC.show(q('data-lc-panel', 'shelve'), name === 'shelve');
      LC.setQuery({ tab: name });
    }
    return activate;
  }

  /* ------------------------------------------------------------------ 事件分发 */
  function wireActions(root, activateTab) {
    LC.on(root, '[data-lc-action]', 'click', function (ev, node) {
      var action = node.getAttribute('data-lc-action');
      if (action === 'tab') {
        ev.preventDefault();
        activateTab(node.getAttribute('data-tab'));
        return;
      }
      if (action === 'resolve-item') { ev.preventDefault(); resolveItem(); return; }
      if (action === 'clear-item') { ev.preventDefault(); clearSelection(); return; }
      if (action === 'select-all') { ev.preventDefault(); selectAllPending(true); return; }
      if (action === 'select-none') { ev.preventDefault(); selectAllPending(false); return; }
      if (action === 'plan-pending') { ev.preventDefault(); planPending(); return; }
      if (action === 'print-pending') {
        ev.preventDefault();
        var ids = selectedIds();
        if (!ids.length) { areaError('print', '请先勾选要打印的待入库袋。'); return; }
        if (!canReceipt()) { areaError('print', '当前账号没有标签打印权限。'); return; }
        var copies = LC.parse.int(readCopies(), 1) || 1;
        submitPdf('pending', ids, copies, LABEL_FIELDS_PENDING, 60, 40);
        return;
      }
      if (action === 'print-one') {
        ev.preventDefault();
        if (!canReceipt()) { areaError('print', '当前账号没有标签打印权限。'); return; }
        var oneId = LC.parse.int(node.getAttribute('data-id'), 0);
        if (!oneId) return;
        submitPdf('pending', [oneId], 1, LABEL_FIELDS_PENDING, 60, 40);
        return;
      }
      if (action === 'pending-more') { ev.preventDefault(); loadPending(false); return; }
      if (action === 'toggle-select') { toggleSelect(node); return; }
      if (action === 'cancel-pending') { ev.preventDefault(); cancelPending(node); return; }
      if (action === 'resolve-pending') { ev.preventDefault(); resolvePending(); return; }
      if (action === 'lock-retry' || action === 'lock-absent' || action === 'lock-present') {
        ev.preventDefault();
        var box = node.closest ? node.closest('[data-lc-lock]') : null;
        var lockName = box ? box.getAttribute('data-lc-lock') : '';
        if (!lockName || !LOCKS[lockName]) return;
        if (action === 'lock-retry') lockRetry(lockName, node);
        else lockResolve(lockName, action === 'lock-absent' ? 'absent' : 'present');
        return;
      }
      if (action === 'scan-next') {
        ev.preventDefault();
        LC.show(q('data-lc-success', 'shelve'), false);
        LC.show(q('data-lc-result', 'shelve'), false);
        var input = LC.qs('[data-lc-scan="shelve"]');
        if (input) {
          input.value = '';
          if (input.focus) input.focus();
        }
        LC.status.clear();
        return;
      }
      if (action === 'print-last') {
        ev.preventDefault();
        if (!state.lastBagId) {
          LC.status.show({ kind: 'error', message: '还没有可重打的袋。' });
          return;
        }
        submitPdf('bag', [state.lastBagId], 1, LABEL_FIELDS_BAG, 60, 40);
        return;
      }
    });
  }

  function wireScanInput(root) {
    LC.on(root, '[data-lc-scan]', 'keydown', function (ev, node) {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      if (node.getAttribute('data-lc-scan') === 'shelve') resolvePending();
    });
  }

  /* ------------------------------------------------------------------ 初始化 */
  LC.register('receipts', function (ctx) {
    var root = ctx.root;
    var activateTab = wireTabs(root);
    applyPermissions(root);
    wireCreateForm(root);
    wireMaterialCreateForm(root);
    wireConfirmForm(root);
    wireActions(root, activateTab);
    wireScanInput(root);

    window.addEventListener('online', function () { LC.status.clear(); });
    window.addEventListener('offline', function () { offlineNote(); });

    // 未决提交恢复：只读 core 本地记录并渲染横幅，**不做任何提交**（不在加载时重发）。
    refreshAllLocks();

    loadBootstrap();
    loadPending(true);

    var query = ctx.page.query;
    var tab = query.get('tab') || '';
    if (tab === '2' || tab === 'shelve') {
      activateTab('shelve');
      var deepRaw = query.get('scan') || query.get('raw') || '';
      if (deepRaw) {
        var input = LC.qs('[data-lc-scan="shelve"]');
        if (input) {
          input.value = deepRaw;
          resolvePending();
        }
      }
    }
    var searchText = ctx.page.query.get('q') || '';
    var itemKey = ctx.page.query.get('item_key') || '';
    var keyInput = q('data-lc-field', 'item_key');
    if (keyInput && (itemKey || searchText)) keyInput.value = itemKey || searchText;
  });
})();
