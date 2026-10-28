/* ==========================================================================
 * lab_team_web · P3 实物袋列表（page_id = bags）
 * --------------------------------------------------------------------------
 * 只读：/lab/api/inventory/bags（分页键是 next_cursor，注意不是 pending 的 cursor）。
 * 数量是服务端实时值（详情页以 stock.quant 为准）；列表的"只看在库"用袋缓存字段过滤。
 * 所有写操作都在别的页面，本页不提供任何写按钮。
 * ========================================================================== */
(function () {
  'use strict';

  if (!window.LC) return;

  var state = {
    rows: [],
    cursor: null,
    filter: { query: '', location_id: '', has_stock: true, outstanding_only: false },
    loading: false
  };

  function q(attr, value) {
    return LC.qs('[' + attr + '="' + value + '"]');
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
        message: '结果未知（网络中断或超时）。核对网络后重新查询即可，本页不写库存。',
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
        message: '当前浏览器处于离线状态：实物袋数量来自服务器，离线时无法查询。'
      });
      return true;
    }
    return false;
  }

  /* ------------------------------------------------------------------ 库位筛选 */
  function loadLocations() {
    var select = q('data-slot', 'location-filter');
    if (!select) return;
    LC.rpc('locations', {}).then(function (data) {
      var rows = (data && data.locations) || [];
      rows.forEach(function (location) {
        select.appendChild(LC.el('option', {
          value: String(location.id),
          text: (location.path || location.name || ('库位 #' + location.id)) +
                (location.code ? '（' + location.code + '）' : '')
        }));
      });
      if (state.filter.location_id) select.value = String(state.filter.location_id);
    }).catch(function (err) {
      // 库位筛选失败不阻塞列表：只影响按库位过滤
      if (err && err.code === 'UNAUTHORIZED') showError(err, loadLocations);
      else notify('库位列表加载失败：' + LC.errorText(err) + '。仍可按袋码/器件搜索。');
    });
  }

  /* ------------------------------------------------------------------ 列表 */
  function render() {
    var tbody = q('data-lc-rows', 'bags');
    LC.renderRows(tbody, state.rows, function (bag) {
      var tr = LC.el('tr');
      tr.appendChild(LC.el('td', { class: 'lc-mono' }, [
        LC.el('a', { href: LC.urls.bag + bag.id, text: bag.trace_code })
      ]));
      tr.appendChild(LC.el('td', {}, [
        LC.el('div', { text: bag.name || '—' }),
        LC.el('div', {
          class: 'lc-hint',
          text: [bag.mpn, bag.package, bag.sn].filter(Boolean).join(' · ') || '—'
        })
      ]));
      tr.appendChild(LC.el('td', {}, [
        LC.el('div', { text: bag.location_path || '—' }),
        LC.el('div', { class: 'lc-hint lc-mono', text: bag.location_code || '' })
      ]));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(bag.quantity) }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(bag.available_quantity) }));
      var outstanding = LC.el('td', { text: LC.fmt.quantity(bag.outstanding_quantity) });
      if (Number(bag.outstanding_quantity) > 0) {
        outstanding.appendChild(LC.el('span', { class: 'lc-badge', 'data-tone': 'warn', text: '未还' }));
      }
      tr.appendChild(outstanding);
      tr.appendChild(LC.el('td', { text: LC.fmt.date(bag.receipt_date) }));
      return tr;
    });

    LC.show(q('data-lc-empty', 'bags'), state.rows.length === 0);
    LC.show(q('data-lc-action', 'load-more'), !!state.cursor);
    LC.show(q('data-lc-filter-note', 'bags'), state.filter.outstanding_only);

    var count = q('data-lc-count', 'bags');
    if (count) count.textContent = '已加载 ' + state.rows.length + ' 个袋' + (state.cursor ? '（还有更多）' : '');
  }

  function load(reset) {
    if (state.loading) return;
    if (offlineNote()) return;
    state.loading = true;
    areaLoading('bags', true);
    areaError('bags', '');
    var params = {
      query: state.filter.query || undefined,
      has_stock: !!state.filter.has_stock,
      outstanding_only: !!state.filter.outstanding_only,
      limit: 24
    };
    if (state.filter.location_id) params.location_id = state.filter.location_id;
    if (!reset && state.cursor) params.cursor = state.cursor;

    LC.rpc('bags', params).then(function (data) {
      state.loading = false;
      areaLoading('bags', false);
      var rows = (data && data.bags) || [];
      state.rows = reset ? rows : state.rows.concat(rows);
      state.cursor = (data && data.next_cursor) || null;
      render();
    }).catch(function (err) {
      state.loading = false;
      areaLoading('bags', false);
      areaError('bags', '实物袋加载失败：' + LC.errorText(err));
      showError(err, function () { load(reset); });
    });
  }

  /* ------------------------------------------------------------------ 事件 */
  function wireFilter(root) {
    var form = LC.qs('[data-lc-form="bags-filter"]', root);
    if (!form) return;
    LC.guard(form, function (values, done) {
      state.filter.query = String(values.query || '').trim();
      state.filter.location_id = String(values.location_id || '').trim();
      state.filter.has_stock = !!values.has_stock;
      state.filter.outstanding_only = !!values.outstanding_only;
      state.cursor = null;
      state.rows = [];
      LC.setQuery({
        q: state.filter.query,
        location_id: state.filter.location_id,
        stock_only: state.filter.has_stock ? '' : '0',
        outstanding_only: state.filter.outstanding_only ? '1' : ''
      });
      load(true);
      done();
    });
  }

  function wireActions(root) {
    LC.on(root, '[data-lc-action]', 'click', function (ev, node) {
      if (node.getAttribute('data-lc-action') === 'load-more') {
        ev.preventDefault();
        load(false);
      }
    });
  }

  /* ------------------------------------------------------------------ 初始化 */
  LC.register('bags', function (ctx) {
    var root = ctx.root;
    var query = ctx.page.query;

    state.filter.query = query.get('q') || '';
    state.filter.location_id = query.get('location_id') || '';
    state.filter.has_stock = query.get('stock_only') !== '0';
    state.filter.outstanding_only = query.get('outstanding_only') === '1';

    var form = LC.qs('[data-lc-form="bags-filter"]', root);
    if (form) {
      LC.setFieldValue(form, 'query', state.filter.query);
      LC.setFieldValue(form, 'location_id', state.filter.location_id);
      LC.setFieldValue(form, 'has_stock', state.filter.has_stock ? '1' : '');
      if (form.elements.has_stock) form.elements.has_stock.checked = state.filter.has_stock;
      LC.setFieldValue(form, 'outstanding_only', state.filter.outstanding_only ? '1' : '');
      if (form.elements.outstanding_only) {
        form.elements.outstanding_only.checked = state.filter.outstanding_only;
      }
    }

    wireFilter(root);
    wireActions(root);
    window.addEventListener('online', function () { LC.status.clear(); });
    window.addEventListener('offline', function () { offlineNote(); });

    loadLocations();
    load(true);
  });
})();
