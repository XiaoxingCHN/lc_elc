/* ==========================================================================
 * P3 作业流水页（/lab/history）· issue 子任务写域
 * --------------------------------------------------------------------------
 * 只读页面：不提供任何写操作、不提供导出、不提供修改/删除。
 * 接口一律走 window.LC；不拼 HTML，没有内联事件与 eval（CSP script-src self）。
 *
 * 用到的端点 key（frontend-contract §6 / backend-contract §3.6）：
 *   history   /lab/api/inventory/history  作业流水（next_cursor 分页）
 *             可选过滤：operation_type / date_from / date_to / actor_id /
 *             borrower_id / item_key / bag_id（非法值服务端返回 VALIDATION_ERROR）
 *   bootstrap /lab/api/inventory/bootstrap 系统账号列表（操作人 / 领用人下拉）
 *
 * 语义：
 *   * 数量来自 stock.move（服务端实值），页面不做任何加减；
 *   * 日期按服务器时区，参数格式 YYYY-MM-DD（含边界当天）；
 *   * 读失败保留旧结果，只显示错误，不用空表冒充"没有数据"。
 * ========================================================================== */
(function () {
  'use strict';

  var PAGE_SIZE = 50;
  var TYPE_LABEL = {
    receipt: '入库',
    issue: '领用',
    return: '归还',
    adopt: '历史适配'
  };

  function showText(value) {
    return value === null || value === undefined || value === '' ? '—' : String(value);
  }

  function qtyText(value) {
    return LC.fmt.quantity(value);
  }

  function describeError(error) {
    if (!error) return '操作失败。';
    if (error.unknown) return '结果未知（网络中断或超时）。';
    if (error.code === 'INTERNAL_ERROR') return LC.errorText(error);
    if (error.code === 'VALIDATION_ERROR' || error.code === 'NOT_FOUND' ||
        error.code === 'PRECONDITION_FAILED' || error.code === 'CONFLICT') {
      return error.message || LC.errorText(error);
    }
    return LC.errorText(error);
  }

  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

  LC.register('history', function (ctx) {
    var root = ctx.root || document.getElementById('workflow-root');
    if (!root) return;

    var els = {
      form: root.querySelector('[data-lc-form="history-filter"]'),
      type: root.querySelector('[name="operation_type"]'),
      dateFrom: root.querySelector('[name="date_from"]'),
      dateTo: root.querySelector('[name="date_to"]'),
      actor: root.querySelector('[name="actor_id"]'),
      borrower: root.querySelector('[name="borrower_id"]'),
      itemKey: root.querySelector('[name="item_key"]'),
      bagId: root.querySelector('[name="bag_id"]'),
      tbody: root.querySelector('[data-lc-rows="history"]'),
      empty: root.querySelector('[data-lc-empty="history"]'),
      loading: root.querySelector('[data-lc-loading="history"]'),
      more: root.querySelector('[data-lc-action="history-more"]')
    };

    var state = {
      cursor: null,
      loading: false,
      loaded: false
    };

    /* ------------------------------------------------------ 系统账号下拉 */
    function fillAccountSelect(select, label) {
      if (!select) return;
      var borrowers = state.borrowers || [];
      LC.clear(select);
      select.appendChild(LC.el('option', { value: '', text: '全部' }));
      borrowers.forEach(function (user) {
        var text = user.name || user.login || ('#' + user.id);
        if (user.login) text += '（' + user.login + '）';
        select.appendChild(LC.el('option', { value: String(user.id), text: text }));
      });
      if (!borrowers.length) {
        select.appendChild(LC.el('option', {
          value: '', text: '未读取到' + label + '列表', disabled: true
        }));
      }
    }

    function loadAccounts() {
      LC.rpc('bootstrap', {}).then(function (data) {
        state.borrowers = (data && data.borrowers) || [];
        fillAccountSelect(els.actor, '操作人');
        fillAccountSelect(els.borrower, '领用人');
      }).catch(function (error) {
        fillAccountSelect(els.actor, '操作人');
        fillAccountSelect(els.borrower, '领用人');
        LC.status.show({
          kind: 'error',
          code: error && error.code,
          message: '读取系统账号列表失败，操作人/领用人筛选暂不可用：' + describeError(error),
          retry: function () { loadAccounts(); }
        });
      });
    }

    /* ------------------------------------------------------------ 过滤参数 */
    function readFilters() {
      var filters = {
        operation_type: els.type ? els.type.value : '',
        date_from: els.dateFrom ? els.dateFrom.value.trim() : '',
        date_to: els.dateTo ? els.dateTo.value.trim() : '',
        actor_id: els.actor ? els.actor.value : '',
        borrower_id: els.borrower ? els.borrower.value : '',
        item_key: els.itemKey ? els.itemKey.value.trim() : '',
        bag_id: els.bagId ? els.bagId.value.trim() : ''
      };
      return filters;
    }

    function validateFilters(filters) {
      if (filters.date_from && !DATE_RE.test(filters.date_from)) {
        return { field: 'date_from', message: '开始日期格式应为 YYYY-MM-DD。' };
      }
      if (filters.date_to && !DATE_RE.test(filters.date_to)) {
        return { field: 'date_to', message: '结束日期格式应为 YYYY-MM-DD。' };
      }
      if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
        return { field: 'date_from', message: '开始日期不能晚于结束日期。' };
      }
      if (filters.bag_id) {
        var bagId = LC.parse.int(filters.bag_id, null);
        if (!bagId || bagId < 1) {
          return { field: 'bag_id', message: '袋 ID 必须是正整数。' };
        }
      }
      return null;
    }

    function buildParams(filters) {
      var params = { limit: PAGE_SIZE };
      if (filters.operation_type) params.operation_type = filters.operation_type;
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to) params.date_to = filters.date_to;
      if (filters.actor_id) params.actor_id = LC.parse.int(filters.actor_id, null);
      if (filters.borrower_id) params.borrower_id = LC.parse.int(filters.borrower_id, null);
      if (filters.item_key) params.item_key = filters.item_key;
      if (filters.bag_id) params.bag_id = LC.parse.int(filters.bag_id, null);
      return params;
    }

    /* -------------------------------------------------------------- 列表 */
    function load(reset) {
      if (state.loading) return;
      var filters = readFilters();
      var problem = validateFilters(filters);
      LC.clearFormErrors(els.form);
      if (problem) {
        LC.formError(els.form, problem.field, problem.message);
        LC.status.show({
          kind: 'error',
          code: 'VALIDATION_ERROR',
          message: problem.message
        });
        return;
      }
      var params = buildParams(filters);
      if (!reset && state.cursor) params.cursor = state.cursor;

      state.loading = true;
      LC.show(els.loading, true);
      LC.show(els.more, false);
      LC.rpc('history', params).then(function (data) {
        state.loading = false;
        state.loaded = true;
        LC.show(els.loading, false);
        var rows = (data && data.operations) || [];
        if (reset && els.tbody) LC.clear(els.tbody);
        state.cursor = (data && data.next_cursor) || null;
        if (els.tbody) {
          rows.forEach(function (row) { els.tbody.appendChild(renderRow(row)); });
        }
        var total = els.tbody ? els.tbody.children.length : 0;
        if (els.empty) {
          LC.show(els.empty, total === 0);
          if (total === 0) {
            LC.setText(els.empty,
              reset ? '没有符合条件的作业流水。' : '没有更多作业流水。');
          }
        }
        LC.show(els.more, !!state.cursor);
        if (reset) {
          if (!rows.length) {
            LC.status.show({ kind: 'empty', message: '没有符合条件的作业流水。' });
          } else {
            LC.status.clear();
          }
        }
      }).catch(function (error) {
        state.loading = false;
        LC.show(els.loading, false);
        LC.show(els.more, !!state.cursor);
        // 读失败保留已有结果，不把表清空冒充"没有数据"
        LC.status.show({
          kind: 'error',
          code: error && error.code,
          message: describeError(error),
          detail: fieldDetail(error),
          retry: function () { load(reset); }
        });
      });
    }

    function fieldDetail(error) {
      if (!error || error.unknown) return '';
      var messages = LC.fieldMessages(error);
      if (!messages.length) return '';
      return messages.map(function (item) {
        return item.field + '：' + item.message;
      }).join('；');
    }

    function renderRow(row) {
      var tr = LC.el('tr', { 'data-move-id': row.move_id });
      tr.appendChild(LC.el('td', { text: LC.fmt.datetime(row.date) }));
      var typeCell = LC.el('td');
      typeCell.appendChild(LC.el('span', {
        class: 'lc-badge',
        'data-tone': row.operation_type === 'return' ? 'ok' : 'warn',
        text: TYPE_LABEL[row.operation_type] || showText(row.operation_type)
      }));
      tr.appendChild(typeCell);
      tr.appendChild(LC.el('td', { class: 'lc-mono', text: showText(row.operation_name) }));
      tr.appendChild(LC.el('td', { class: 'lc-mono', text: showText(row.trace_code) }));
      var itemCell = LC.el('td');
      itemCell.appendChild(LC.el('div', { text: showText(row.item_key) }));
      tr.appendChild(itemCell);
      tr.appendChild(LC.el('td', { class: 'lc-mono', text: showText(row.lot_name) }));
      tr.appendChild(LC.el('td', { text: qtyText(row.quantity) }));
      tr.appendChild(LC.el('td', {
        text: showText(row.src_location) + ' → ' + showText(row.dest_location)
      }));
      tr.appendChild(LC.el('td', { text: showText(row.actor_name) }));
      tr.appendChild(LC.el('td', { text: showText(row.borrower_name) }));
      tr.appendChild(LC.el('td', { text: showText(row.project) }));
      return tr;
    }

    /* ---------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action]', 'click', function (event, element) {
      var action = element.getAttribute('data-lc-action');
      if (action === 'history-search') {
        event.preventDefault();
        state.cursor = null;
        load(true);
      } else if (action === 'history-more') {
        event.preventDefault();
        if (!state.cursor) return;
        load(false);
      } else if (action === 'history-reset') {
        event.preventDefault();
        [els.type, els.dateFrom, els.dateTo, els.actor, els.borrower].forEach(function (node) {
          if (node) node.value = '';
        });
        if (els.itemKey) els.itemKey.value = '';
        if (els.bagId) els.bagId.value = '';
        LC.clearFormErrors(els.form);
        state.cursor = null;
        load(true);
      }
    });

    if (els.form) {
      els.form.addEventListener('submit', function (event) {
        event.preventDefault();
        state.cursor = null;
        load(true);
      });
    }

    /* ---------------------------------------------------------------- 初始化 */
    function init() {
      loadAccounts();
      load(true);
    }

    init();
  });
})();
