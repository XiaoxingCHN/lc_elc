/* ==========================================================================
 * lab_team_web · P3 标签中心（page_id = labels）
 * --------------------------------------------------------------------------
 * 三类标签：待入库（pending）/ 器件袋（bag）/ 库位（location）。
 *   * 对象来自服务端列表（pending/list、bags、locations），本页不造数据；
 *   * 毫米参数与字段白名单与 lab_workflow.tools.label_render 一致；
 *   * labels/plan 只做排版试算（只读），PDF 走真实表单 POST（csrf + target=_blank）；
 *   * 不显示 font_path（服务端已删除），不提供二维码类字段，不做 blob/iframe；
 *   * 只读角色（无 can_manage_labels）不显示选题、试算与下载按钮。
 * ========================================================================== */
(function () {
  'use strict';

  if (!window.LC) return;

  var FIELDS = [
    { key: 'trace_code', label: '追溯码' },
    { key: 'sn', label: 'SN' },
    { key: 'name', label: '名称' },
    { key: 'mpn', label: '型号' },
    { key: 'location', label: '库码/库位' },
    { key: 'catalog_code', label: 'C 编号' },
    { key: 'brand', label: '品牌' },
    { key: 'package', label: '封装' },
    { key: 'parameters', label: '参数' },
    { key: 'initial_quantity', label: '初始数量' }
  ];

  var REQUIRED = {
    pending: ['trace_code'],
    bag: ['trace_code'],
    location: ['location']
  };

  var state = {
    kind: 'pending',
    rows: [],
    selected: {},
    cursor: null,
    loading: false,
    plan: null
  };

  /* 每次加载递增：只有最新一次请求可以写回列表（防止切页签时旧响应覆盖新数据） */
  var loadToken = 0;

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

  function canPrint() {
    return LC.has('can_manage_labels');
  }

  function showError(err, retryFn) {
    if (!err) return;
    if (err.unknown) {
      LC.status.show({
        kind: 'unknown',
        code: err.code,
        message: '结果未知（网络中断或超时）。排版试算是只读请求，可安全重试；PDF 下载是表单提交，' +
                 '请在网络恢复后重新点击。',
        retry: retryFn
      });
      return;
    }
    if (err.code === 'UNAUTHORIZED') return;
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
    if (navigator.onLine === false) {
      LC.status.show({
        kind: 'unknown',
        message: '当前浏览器处于离线状态：标签对象与排版试算都要访问服务器，请恢复网络后再操作。'
      });
      return true;
    }
    return false;
  }

  /* ------------------------------------------------------------------ 参数 */
  function readNumber(name, fallback) {
    var node = q('data-lc-label-field', name);
    var value = node ? LC.parse.float(node.value, fallback) : fallback;
    return value === null || isNaN(value) ? fallback : value;
  }

  function readCopies() {
    var value = readNumber('copies', 1);
    var copies = Math.round(value);
    if (copies < 1) copies = 1;
    if (copies > LC.limits.labelMaxCopies) copies = LC.limits.labelMaxCopies;
    return copies;
  }

  function readFields() {
    var boxes = LC.qsa('input[name="label_fields"]');
    var out = [];
    boxes.forEach(function (box) {
      if (box.checked) out.push(box.value);
    });
    (REQUIRED[state.kind] || []).forEach(function (required) {
      if (out.indexOf(required) === -1) out.push(required);
    });
    return out;
  }

  function params() {
    return {
      kind: state.kind,
      ids: selectedIds(),
      copies: readCopies(),
      width_mm: readNumber('width_mm', 60),
      height_mm: readNumber('height_mm', 40),
      margin_mm: readNumber('margin_mm', 10),
      gap_mm: readNumber('gap_mm', 2),
      fields: readFields()
    };
  }

  function selectedIds() {
    return Object.keys(state.selected).filter(function (key) {
      return state.selected[key];
    }).map(function (key) {
      return LC.parse.int(key, 0);
    }).filter(function (id) {
      return !!id;
    });
  }

  /* ------------------------------------------------------------------ 对象渲染 */
  function sourceLabel(row) {
    if (state.kind === 'location') return row.code || row.name || ('库位 #' + row.id);
    return row.trace_code || ('#' + row.id);
  }

  function sourceDetail(row) {
    if (state.kind === 'location') return row.path || row.name || '';
    return [row.name, row.mpn, row.package, row.sn].filter(Boolean).join(' · ');
  }

  function sourceLocation(row) {
    if (state.kind === 'location') return '';
    return row.location_path || row.location_code || '';
  }

  function sourceQuantity(row) {
    if (state.kind === 'location') return '';
    return LC.fmt.quantity(row.quantity);
  }

  function renderSource() {
    var tbody = q('data-lc-rows', 'source');
    LC.renderRows(tbody, state.rows, function (row) {
      var tr = LC.el('tr');
      var box = LC.el('input', {
        type: 'checkbox',
        'data-lc-action': 'source-toggle',
        'data-id': String(row.id),
        'aria-label': '选择 ' + sourceLabel(row)
      });
      box.checked = !!state.selected[String(row.id)];
      tr.appendChild(LC.el('td', {}, [box]));

      var labelCell = LC.el('td', { class: 'lc-mono', text: sourceLabel(row) });
      tr.appendChild(labelCell);
      tr.appendChild(LC.el('td', { text: sourceDetail(row) || '—' }));
      tr.appendChild(LC.el('td', { text: sourceLocation(row) || '—' }));
      tr.appendChild(LC.el('td', { text: sourceQuantity(row) || '—' }));
      return tr;
    });

    LC.show(q('data-lc-empty', 'source'), state.rows.length === 0);
    LC.show(q('data-lc-action', 'source-more'), !!state.cursor);
    var count = q('data-lc-count', 'source');
    if (count) {
      count.textContent = '已选 ' + selectedIds().length + ' 个 / 本页 ' + state.rows.length + ' 个';
    }
    schedulePlan();
  }

  /* ------------------------------------------------------------------ 数据加载 */
  function loadSource(reset) {
    if (offlineNote()) return;
    state.loading = true;
    loadToken += 1;
    var token = loadToken;
    areaLoading('labels', true);
    areaError('labels', '');
    if (reset) {
      state.rows = [];
      state.cursor = null;
    }

    var request = null;
    if (state.kind === 'pending') {
      var pendingParams = {};
      if (!reset && state.cursor) pendingParams.cursor = state.cursor;
      request = LC.rpc('pendingList', pendingParams).then(function (data) {
        var records = (data && data.records) || [];
        var rows = records.filter(function (record) {
          return record.state !== 'cancelled';
        });
        state.cursor = (data && data.cursor) || null;
        return rows;
      });
    } else if (state.kind === 'bag') {
      var bagParams = { has_stock: false, limit: 24 };
      var queryText = q('data-lc-field', 'source-query');
      if (queryText && String(queryText.value || '').trim()) {
        bagParams.query = String(queryText.value).trim();
      }
      if (!reset && state.cursor) bagParams.cursor = state.cursor;
      request = LC.rpc('bags', bagParams).then(function (data) {
        state.cursor = (data && data.next_cursor) || null;
        return (data && data.bags) || [];
      });
    } else {
      request = LC.rpc('locations', {}).then(function (data) {
        state.cursor = null;
        return (data && data.locations) || [];
      });
    }

    request.then(function (rows) {
      if (token !== loadToken) return;
      state.loading = false;
      areaLoading('labels', false);
      LC.show(q('data-lc-workbench', 'labels'), canPrint());
      if (!canPrint()) return;
      state.rows = reset ? rows : state.rows.concat(rows);
      renderSource();
    }).catch(function (err) {
      if (token !== loadToken) return;
      state.loading = false;
      areaLoading('labels', false);
      areaError('labels', '可打印对象加载失败：' + LC.errorText(err));
      showError(err, function () { loadSource(reset); });
    });
  }

  /* ------------------------------------------------------------------ 排版试算 */
  function renderPlan(plan) {
    state.plan = plan || null;
    var dl = q('data-lc-plan', 'labels');
    var empty = q('data-lc-empty', 'plan');
    if (!plan) {
      LC.show(dl, false);
      LC.show(empty, true);
      return;
    }
    LC.show(empty, false);
    LC.show(dl, true);
    setSlot('plan-count', String(plan.label_count === undefined ? '—' : plan.label_count) + ' 张');
    setSlot('plan-pages', String(plan.labels_per_page === undefined ? '—' : plan.labels_per_page) +
      ' 张/页 · 共 ' + String(plan.page_count === undefined ? '—' : plan.page_count) + ' 页');
    setSlot('plan-font', String(plan.preview_title_pt === undefined ? '—' : plan.preview_title_pt) +
      ' / ' + String(plan.preview_body_pt === undefined ? '—' : plan.preview_body_pt) +
      '（下限 ' + String(plan.min_title_pt === undefined ? '—' : plan.min_title_pt) + ' / ' +
      String(plan.min_body_pt === undefined ? '—' : plan.min_body_pt) + '）');
    if (plan.ready === false) {
      setSlot('plan-ready', '不可排版：' + (plan.blocking_reason || '参数不合法'));
    } else if (plan.may_need_scaling) {
      setSlot('plan-ready', '可打印，但文字可能放不下（估算 ' +
        String(plan.estimated_text_height_mm === undefined ? '—' : plan.estimated_text_height_mm) +
        'mm / 可用 ' +
        String(plan.available_text_height_mm === undefined ? '—' : plan.available_text_height_mm) +
        'mm），建议加大尺寸或减少字段');
    } else {
      setSlot('plan-ready', '可打印');
    }
  }

  function runPlan() {
    if (!canPrint()) return;
    var ids = selectedIds();
    if (!ids.length) {
      renderPlan(null);
      notify('请先选择要打印的对象。', 'empty');
      return;
    }
    if (ids.length > LC.limits.labelMaxIds) {
      notify('一次最多 ' + LC.limits.labelMaxIds + ' 个标签，请分批试算。');
      return;
    }
    if (offlineNote()) return;
    var payload = params();
    LC.rpc('labelsPlan', {
      kind: payload.kind,
      ids: payload.ids,
      copies: payload.copies,
      width_mm: payload.width_mm,
      height_mm: payload.height_mm,
      margin_mm: payload.margin_mm,
      gap_mm: payload.gap_mm,
      fields: payload.fields
    }).then(function (plan) {
      renderPlan(plan);
    }).catch(function (err) {
      renderPlan(null);
      if (err && err.code === 'VALIDATION_ERROR') {
        var fields = LC.fieldMessages(err);
        notify((fields.length ? fields.map(function (item) {
          return item.field + '：' + item.message;
        }).join('；') : '') || LC.errorText(err));
        return;
      }
      showError(err, runPlan);
    });
  }

  var schedulePlan = LC.debounce(function () {
    if (!canPrint()) return;
    if (!selectedIds().length) {
      renderPlan(null);
      return;
    }
    runPlan();
  }, 600);

  /* ------------------------------------------------------------------ PDF */
  function submitPdf() {
    if (!canPrint()) {
      notify('当前账号没有标签打印权限。');
      return;
    }
    var ids = selectedIds();
    if (!ids.length) {
      notify('请先选择要打印的对象。');
      return;
    }
    if (ids.length > LC.limits.labelMaxIds) {
      notify('一次最多 ' + LC.limits.labelMaxIds + ' 个标签，请分批下载。');
      return;
    }
    var form = LC.qs('[data-lc-pdf-form="labels"]');
    if (!form) {
      notify('页面缺少标签表单，无法下载 PDF。');
      return;
    }
    if (state.plan && state.plan.ready === false) {
      notify('当前参数不可排版：' + (state.plan.blocking_reason || '请调整尺寸或字段') ,
        'error');
      return;
    }
    var payload = params();
    form.elements.kind.value = payload.kind;
    form.elements.ids.value = payload.ids.join(',');
    form.elements.copies.value = String(payload.copies);
    form.elements.width_mm.value = String(payload.width_mm);
    form.elements.height_mm.value = String(payload.height_mm);
    form.elements.margin_mm.value = String(payload.margin_mm);
    form.elements.gap_mm.value = String(payload.gap_mm);
    form.elements.fields.value = payload.fields.join(',');
    form.submit();
    notify('已提交 PDF 生成请求（新标签页打开）。若浏览器拦截弹窗，请允许本站弹窗后重试。', 'success');
  }

  /* ------------------------------------------------------------------ 事件 */
  function switchKind(kind, root) {
    state.kind = kind;
    state.selected = {};
    state.cursor = null;
    state.rows = [];
    LC.qsa('[data-lc-action="kind"]', root).forEach(function (tab) {
      var active = tab.getAttribute('data-kind') === kind;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    var note = q('data-lc-kind-note', 'labels');
    if (note) {
      note.textContent = kind === 'pending'
        ? '待入库标签打印本人尚未入库（或已入库保留）的袋；每张标签必须包含追溯码。'
        : (kind === 'bag'
          ? '器件袋标签用于重打已经入库的袋；追溯码必填，库码可选。'
          : '库位标签只印库码二维码（LABL:），不混印器件信息。');
    }
    var rule = q('data-lc-kind-rule', 'labels');
    if (rule) {
      rule.textContent = kind === 'location'
        ? '库位标签必须包含「库码/库位」字段。'
        : '待入库/器件袋标签必须包含追溯码（缺省会由页面自动加入）。';
    }
    LC.show(q('data-lc-source-search', 'labels'), kind === 'bag');
    LC.show(q('data-lc-workbench', 'labels'), canPrint());
    renderPlan(null);
    loadSource(true);
  }

  function wireActions(root) {
    LC.on(root, '[data-lc-action]', 'click', function (ev, node) {
      var action = node.getAttribute('data-lc-action');
      if (action === 'kind') {
        ev.preventDefault();
        switchKind(node.getAttribute('data-kind') || 'pending', root);
        return;
      }
      if (action === 'source-toggle') {
        var id = String(node.getAttribute('data-id') || '');
        state.selected[id] = !!node.checked;
        if (node.checked) {
          var total = selectedIds().length;
          if (total > LC.limits.labelMaxIds) {
            state.selected[id] = false;
            node.checked = false;
            notify('一次最多 ' + LC.limits.labelMaxIds + ' 个标签，请分批下载。');
          }
        }
        var count = q('data-lc-count', 'source');
        if (count) {
          count.textContent = '已选 ' + selectedIds().length + ' 个 / 本页 ' + state.rows.length + ' 个';
        }
        schedulePlan();
        return;
      }
      if (action === 'source-all') {
        ev.preventDefault();
        state.rows.forEach(function (row) { state.selected[String(row.id)] = true; });
        renderSource();
        return;
      }
      if (action === 'source-none') {
        ev.preventDefault();
        state.selected = {};
        renderSource();
        return;
      }
      if (action === 'source-more') { ev.preventDefault(); loadSource(false); return; }
      if (action === 'plan') { ev.preventDefault(); runPlan(); return; }
      if (action === 'print') { ev.preventDefault(); submitPdf(); return; }
    });

    LC.on(root, '[data-lc-label-field]', 'change', function () { schedulePlan(); });
    LC.on(root, 'input[name="label_fields"]', 'change', function () { schedulePlan(); });
  }

  function wireSearch(root) {
    var input = q('data-lc-field', 'source-query');
    if (!input) return;
    var reload = LC.debounce(function () {
      state.selected = {};
      state.cursor = null;
      loadSource(true);
    }, 400);
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        reload();
      }
    });
    input.addEventListener('change', reload);
  }

  /* ------------------------------------------------------------------ 初始化 */
  LC.register('labels', function (ctx) {
    var root = ctx.root;
    var writable = canPrint();

    LC.show(LC.qs('[data-readonly-note]'), !writable);
    LC.show(q('data-lc-workbench', 'labels'), writable);

    LC.qsa('[data-lc-action="kind"]', root).forEach(function (tab) {
      LC.show(tab, writable);
    });
    LC.qsa('[data-lc-action="plan"], [data-lc-action="print"]').forEach(function (node) {
      LC.show(node, writable);
    });

    if (!writable) {
      // 只读角色：不显示选题/试算/下载，只保留说明与空态
      LC.show(q('data-lc-empty', 'source'), true);
      var count = q('data-lc-count', 'source');
      if (count) count.textContent = '无打印权限';
      return;
    }

    wireActions(root);
    wireSearch(root);
    window.addEventListener('online', function () { LC.status.clear(); });
    window.addEventListener('offline', function () { offlineNote(); });

    var kind = ctx.page.query.get('kind') || 'pending';
    if (kind !== 'bag' && kind !== 'location') kind = 'pending';
    switchKind(kind, root);
  });
})();
