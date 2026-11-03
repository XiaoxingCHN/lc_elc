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
      bagCode: root.querySelector('[name="bag_code"]'),
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
        bag_code: els.bagCode ? els.bagCode.value.trim() : ''
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
      return null;
    }

    function buildParams(filters) {
      var params = { limit: PAGE_SIZE };
      if (filters.operation_type) params.operation_type = filters.operation_type;
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to) params.date_to = filters.date_to;
      if (filters.actor_id) params.actor_id = LC.parse.int(filters.actor_id, null);
      if (filters.borrower_id) params.borrower_id = LC.parse.int(filters.borrower_id, null);
      return params;
    }

    /* ------------------------------------------------- 用户输入 → 真实查询值 */
    var ITEM_PREFIX_RE = /^(lcsc|lab)\s*:\s*(.+)$/i;

    /* 器件筛选只接受「编号或扫码内容」：立创 C 码、物料 SN、袋码。
     * 明确前缀直接换算，裸 C 码补 lcsc:，纯数字当本地档案；
     * 其余交给 resolve_code 解析（它只认 LABB:/LABL:/SN/立创 C 码/原厂袋码，
     * 不支持名称或型号关键词搜索）；解析不到就明确报错，
     * 不把「没解析出来」当成「没有数据」，也不把服务端原文抛给用户。
     */
    var ITEM_HELP = '只认编号或扫码：立创 C 码（C12345）、物料 SN、袋码（LABB:…）。'
      + '本页不支持按名称/型号关键词搜索，按名称找请到「器件档案」。';
    function resolveItemKey(raw) {
      var value = String(raw || '').trim();
      if (!value) return Promise.resolve('');
      var match = ITEM_PREFIX_RE.exec(value);
      if (match) {
        var prefix = match[1].toLowerCase();
        var body = match[2].trim();
        return Promise.resolve(prefix === 'lcsc' ? 'lcsc:' + body.toUpperCase() : 'lab:' + body);
      }
      if (/^C\d+$/i.test(value)) return Promise.resolve('lcsc:' + value.toUpperCase());
      if (/^\d+$/.test(value)) return Promise.resolve('lab:' + value);
      return LC.rpc('resolve', { raw: value }).then(function (data) {
        var key = (data && data.item_key) || '';
        if (!key) throw notFoundItem(value);
        return key;
      }).catch(function (error) {
        if (error && error.field) throw error;
        throw notFoundItem(value);
      });
    }

    function notFoundItem(value) {
      return {
        code: 'NOT_FOUND', field: 'item_key',
        message: '没有识别到器件「' + value + '」。' + ITEM_HELP
      };
    }

    function notFoundBag(value) {
      return {
        code: 'NOT_FOUND', field: 'bag_code',
        message: '没有识别到袋「' + value + '」。请扫袋标签或填完整袋码（LABB:…）；'
          + '只填数字（如 123）会按袋编号精确匹配，一般用不到。'
      };
    }

    /* 袋筛选允许直接填袋码（可扫），换算成服务端要的袋编号。 */
    function resolveBagId(raw) {
      var value = String(raw || '').trim();
      if (!value) return Promise.resolve(null);
      if (/^\d+$/.test(value)) return Promise.resolve(parseInt(value, 10));
      return LC.rpc('resolve', { raw: value }).then(function (data) {
        var bag = data && data.bag;
        if (!bag || !bag.id) throw notFoundBag(value);
        return bag.id;
      }).catch(function (error) {
        if (error && error.field) throw error;
        throw notFoundBag(value);
      });
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
      state.loading = true;
      LC.show(els.loading, true);
      LC.show(els.more, false);
      Promise.all([
        resolveItemKey(filters.item_key),
        resolveBagId(filters.bag_code)
      ]).then(function (resolved) {
        var params = buildParams(filters);
        if (resolved[0]) {
          params.item_key = resolved[0];
          // 把换算结果回填，用户能看到实际查询用的编号（不是黑箱）
          if (els.itemKey && els.itemKey.value.trim() !== resolved[0]) {
            els.itemKey.value = resolved[0];
          }
        }
        if (resolved[1]) params.bag_id = resolved[1];
        if (!reset && state.cursor) params.cursor = state.cursor;
        return LC.rpc('history', params);
      }).then(function (data) {
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
        if (error && error.field) {
          LC.formError(els.form, error.field, error.message);
        }
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

    /* 行内只用可读口径：lcsc:C123 → 立创 C123；lab:42 → 本地档案 #42。
     * 原始 item_key 仍按用户输入回填在筛选框里，诊断需要时看得到。 */
    function itemKeyText(value) {
      if (!value) return '—';
      var text = String(value);
      var match = /^lcsc:(.+)$/i.exec(text);
      if (match) return '立创 ' + match[1].toUpperCase();
      match = /^lab:(\d+)$/i.exec(text);
      if (match) return '本地档案 #' + match[1];
      return text;
    }

    function renderRow(row) {
      var tr = LC.el('tr', { 'data-move-id': row.move_id });
      tr.appendChild(LC.el('td', { 'data-label': '时间', text: LC.fmt.datetime(row.date) }));
      var typeCell = LC.el('td', { 'data-label': '类型' });
      typeCell.appendChild(LC.el('span', {
        class: 'lc-badge',
        'data-tone': row.operation_type === 'return' ? 'ok' : 'warn',
        text: TYPE_LABEL[row.operation_type] || showText(row.operation_type)
      }));
      tr.appendChild(typeCell);
      tr.appendChild(LC.el('td', { 'data-label': '单号', class: 'lc-mono', text: showText(row.operation_name) }));
      tr.appendChild(LC.el('td', { 'data-label': '袋码', class: 'lc-mono', text: showText(row.trace_code) }));
      var itemCell = LC.el('td', { 'data-label': '器件' });
      itemCell.appendChild(LC.el('div', { text: itemKeyText(row.item_key) }));
      tr.appendChild(itemCell);
      tr.appendChild(LC.el('td', { 'data-label': '批次', class: 'lc-mono', text: showText(row.lot_name) }));
      tr.appendChild(LC.el('td', { 'data-label': '数量', text: qtyText(row.quantity) }));
      tr.appendChild(LC.el('td', {
        'data-label': '来源 → 目标',
        text: showText(row.src_location) + ' → ' + showText(row.dest_location)
      }));
      tr.appendChild(LC.el('td', { 'data-label': '操作人', text: showText(row.actor_name) }));
      tr.appendChild(LC.el('td', { 'data-label': '领用人', text: showText(row.borrower_name) }));
      tr.appendChild(LC.el('td', { 'data-label': '项目', text: showText(row.project) }));
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
        if (els.bagCode) els.bagCode.value = '';
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