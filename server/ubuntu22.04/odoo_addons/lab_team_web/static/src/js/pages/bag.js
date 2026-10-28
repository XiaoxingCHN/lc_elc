/* ==========================================================================
 * lab_team_web · P3 袋追溯（page_id = bag，/lab/bags/<id>）
 * --------------------------------------------------------------------------
 * 只读：/lab/api/inventory/bag → {bag, item, open_issues, history, label_facts}
 * border 事实全部来自服务端（实时 quant）；本页不缓存、不推演库存。
 * label_facts 只对 operator/manager 返回；没有它就不显示「重打标签」。
 * 标签 PDF 走真实表单 POST（见模板 data-lc-pdf-form），不用 iframe/blob。
 * ========================================================================== */
(function () {
  'use strict';

  if (!window.LC) return;

  var OP_TEXT = {
    receipt: '入库',
    issue: '领用',
    return: '归还',
    adopt: '历史适配'
  };

  var bagId = 0;
  var labelFacts = null;

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

  function notify(message, kind) {
    LC.status.show({ kind: kind || 'error', message: message });
  }

  function showError(err, retryFn) {
    if (!err) return;
    if (err.unknown) {
      LC.status.show({
        kind: 'unknown',
        code: err.code,
        message: '结果未知（网络中断或超时）。核对网络后重新加载；本页只读，不会产生任何写入。',
        retry: retryFn
      });
      return;
    }
    if (err.code === 'UNAUTHORIZED') return;
    var detail = '';
    if (err.code === 'NOT_FOUND') {
      detail = '袋可能已被删除，或不属于当前公司。';
    }
    LC.status.show({
      kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
      code: err.code,
      message: LC.errorText(err),
      detail: detail,
      retry: retryFn
    });
  }

  /* ------------------------------------------------------------------ 渲染 */
  function renderBag(bag) {
    setSlot('trace-code', bag.trace_code);
    setSlot('bag-trace', bag.trace_code);
    setSlot('bag-payload', bag.payload);
    setSlot('bag-item', [bag.name, bag.mpn, bag.package].filter(Boolean).join(' · '));
    setSlot('bag-sn', bag.sn || '');
    setSlot('bag-location', (bag.location_path || '—') + (bag.location_code ? '（' + bag.location_code + '）' : ''));
    setSlot('bag-quantity', LC.fmt.quantity(bag.quantity) + ' / ' +
      LC.fmt.quantity(bag.available_quantity) + ' / ' + LC.fmt.quantity(bag.reserved_quantity) +
      ' ' + (bag.uom || ''));
    setSlot('bag-outstanding', LC.fmt.quantity(bag.outstanding_quantity));
    setSlot('bag-receipt-date', LC.fmt.datetime(bag.receipt_date));
    setSlot('bag-supplier', [bag.supplier_order, bag.supplier_mpn].filter(Boolean).join(' / '));
    setSlot('bag-note', bag.note || '');
    setSlot('trace-code', bag.trace_code);
  }

  function renderItem(item) {
    if (!item) {
      LC.show(q('data-lc-item', 'bag'), false);
      return;
    }
    LC.show(q('data-lc-item', 'bag'), true);
    setSlot('item-key', item.item_key);
    setSlot('item-name', item.name);
    setSlot('item-meta', [item.mpn, item.brand, item.package].filter(Boolean).join(' · '));
    setSlot('item-quantity', LC.fmt.quantity(item.lab_quantity));
    setSlot('item-counts', (item.bag_count === undefined ? '—' : item.bag_count) + ' 袋 / ' +
      (item.location_count === undefined ? '—' : item.location_count) + ' 个库位');
    var params = item.parameters || [];
    LC.show(q('data-lc-params', 'bag'), params.length > 0);
    LC.show(q('data-lc-empty', 'params'), params.length === 0);
    var dl = q('data-lc-rows', 'params');
    if (dl) {
      LC.clear(dl);
      params.forEach(function (param) {
        dl.appendChild(LC.el('dt', { text: param.name || param.code || '—' }));
        dl.appendChild(LC.el('dd', { text: param.value || '—' }));
      });
    }
  }

  function renderIssues(issues) {
    var tbody = q('data-lc-rows', 'open-issues');
    LC.renderRows(tbody, issues, function (line) {
      var tr = LC.el('tr');
      tr.appendChild(LC.el('td', { text: line.issue_operation_name || ('#' + line.issue_operation_id) }));
      tr.appendChild(LC.el('td', { text: line.borrower_name || '—' }));
      tr.appendChild(LC.el('td', { text: line.project || '—' }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(line.quantity) }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(line.returned_quantity) }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(line.outstanding_quantity) }));
      tr.appendChild(LC.el('td', { text: LC.fmt.date(line.date) }));
      return tr;
    });
    LC.show(q('data-lc-empty', 'open-issues'), !(issues && issues.length));
  }

  function renderHistory(rows) {
    var tbody = q('data-lc-rows', 'history');
    LC.renderRows(tbody, rows, function (row) {
      var tr = LC.el('tr');
      tr.appendChild(LC.el('td', { text: LC.fmt.datetime(row.date) }));
      tr.appendChild(LC.el('td', { text: OP_TEXT[row.operation_type] || row.operation_type || '—' }));
      tr.appendChild(LC.el('td', { class: 'lc-mono', text: row.operation_name || '—' }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(row.quantity) }));
      tr.appendChild(LC.el('td', {
        text: (row.src_location || '—') + ' → ' + (row.dest_location || '—')
      }));
      tr.appendChild(LC.el('td', { text: row.actor_name || '—' }));
      return tr;
    });
    LC.show(q('data-lc-empty', 'history'), !(rows && rows.length));
  }

  function renderLabelFacts(facts) {
    labelFacts = facts || null;
    var box = q('data-lc-label', 'bag');
    var note = q('data-lc-label-note', 'bag');
    if (!facts) {
      LC.show(box, false);
      LC.show(note, true);
      return;
    }
    LC.show(note, false);
    LC.show(box, true);
    setSlot('label-title', facts.title || facts.item_name || '—');
    setSlot('label-location-code', facts.location_code || '—');
    setSlot('label-initial', LC.fmt.quantity(facts.initial_quantity));
    var plan = q('data-lc-plan', 'bag');
    if (plan) {
      plan.textContent = '默认 A4 排版：标签 60×40mm，每袋 1 个追溯二维码，' +
        '文字字段 追溯码/名称/型号/库码。实际页数与字号由服务端排版决定。';
      LC.show(plan, true);
    }
  }

  function submitPdf() {
    var form = LC.qs('[data-lc-pdf-form="labels"]');
    if (!form) {
      notify('页面缺少标签表单，无法下载 PDF。');
      return;
    }
    if (!bagId) {
      notify('缺少袋 id，无法打印。');
      return;
    }
    form.elements.kind.value = 'bag';
    form.elements.ids.value = String(bagId);
    form.elements.copies.value = '1';
    form.elements.width_mm.value = '60';
    form.elements.height_mm.value = '40';
    form.elements.margin_mm.value = '10';
    form.elements.gap_mm.value = '2';
    form.elements.fields.value = labelFacts && labelFacts.location_code
      ? 'trace_code,name,mpn,location'
      : 'trace_code,name,mpn';
    form.submit();
    notify('已提交 PDF 生成请求（新标签页打开）。若浏览器拦截弹窗，请允许本站弹窗后重试。', 'success');
  }

  /* ------------------------------------------------------------------ 加载 */
  function load() {
    if (!bagId) {
      areaError('bag', '页面缺少袋 id：请从「实物袋」列表点进来。');
      return;
    }
    areaLoading('bag', true);
    areaError('bag', '');
    LC.rpc('bag', { bag_id: bagId, history_limit: 20, issues_limit: 50 }).then(function (data) {
      areaLoading('bag', false);
      LC.show(q('data-lc-result', 'bag'), true);
      renderBag((data && data.bag) || {});
      renderItem(data && data.item ? data.item : null);
      renderIssues((data && data.open_issues) || []);
      renderHistory((data && data.history) || []);
      renderLabelFacts(data && data.label_facts ? data.label_facts : null);
    }).catch(function (err) {
      areaLoading('bag', false);
      LC.show(q('data-lc-result', 'bag'), false);
      areaError('bag', '袋追溯加载失败：' + LC.errorText(err));
      showError(err, load);
      if (err && err.code === 'NOT_FOUND') {
        LC.show(q('data-lc-empty', 'history'), false);
      }
    });
  }

  function wireActions(root) {
    LC.on(root, '[data-lc-action]', 'click', function (ev, node) {
      if (node.getAttribute('data-lc-action') === 'print-bag') {
        ev.preventDefault();
        submitPdf();
      }
    });
  }

  LC.register('bag', function (ctx) {
    var root = ctx.root;
    var holder = LC.qs('[data-bag-id]', root);
    bagId = LC.parse.int(holder ? holder.getAttribute('data-bag-id') : 0, 0);
    wireActions(root);
    window.addEventListener('online', function () { LC.status.clear(); });
    load();
  });
})();
