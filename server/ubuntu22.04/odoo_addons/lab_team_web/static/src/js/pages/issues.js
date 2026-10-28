/* ==========================================================================
 * P3 领用记录 / 归还页（/lab/issues）· issue 子任务写域
 * --------------------------------------------------------------------------
 * 接口一律走 window.LC（workflow_core.js）；不拼 HTML，没有内联事件与 eval。
 *
 * 用到的端点 key（frontend-contract §6）：
 *   issues /lab/api/inventory/issues   领用记录（next_cursor 分页；服务端已按权限过滤）
 *   return /lab/api/inventory/return   归还（唯一写入口，走 LC.submit）
 *   bag    /lab/api/inventory/bag      该袋当前物理库存（stock.quant 实值）
 *   session/api/team/session           当前 uid（用于标出"本人"行）
 *
 * 安全与语义（backend-contract §3.8 A1、§5、§6）：
 *   1. 归还只提交 issue_line_id + quantity；上限用服务端 outstanding_quantity。
 *   2. 跨账号归还由服务端拒绝（FORBIDDEN fields.issue_line_id=not_owner）；
 *      本页从不构造他人的领用行 ID，只提交列表里服务端返回的行。
 *   3. 「可归还（未还）」与「袋物理库存」是两件事，分块展示，不混用。
 *   4. 非管理员列表只有本人记录（服务端过滤）；前端不另行过滤冒充权限。
 *   5. 结果未知时同 payload 同 request_key 显式重试；成功后再拉服务端实值。
 * ========================================================================== */
(function () {
  'use strict';

  var PAGE_SIZE = 50;

  //: 逻辑表单 scope：只含页面与业务动作，不含 issue_line_id / quantity 等可编辑内容
  //: （否则"换一行、改个数量"就会落到新 scope，等于绕过 core 的未决锁）。
  var RETURN_SCOPE = 'issues/return';
  var RETURN_ENDPOINT = 'return';

  function showText(value) {
    return value === null || value === undefined || value === '' ? '—' : String(value);
  }

  function qtyText(value, uom) {
    var formatted = LC.fmt.quantity(value);
    if (formatted === '—') return formatted;
    return uom ? (formatted + ' ' + uom) : formatted;
  }

  function describeError(error) {
    if (!error) return '操作失败。';
    if (error.unknown) return '结果未知（网络中断或超时）。';
    if (error.code === 'INTERNAL_ERROR') return LC.errorText(error);
    if (error.code === 'PRECONDITION_FAILED' || error.code === 'CONFLICT' ||
        error.code === 'DUPLICATE_REQUEST' || error.code === 'VALIDATION_ERROR') {
      return error.message || LC.errorText(error);
    }
    return LC.errorText(error);
  }

  LC.register('issues', function (ctx) {
    var root = ctx.root || document.getElementById('workflow-root');
    if (!root) return;

    var els = {
      filter: root.querySelector('[data-lc-form="issues-filter"]'),
      query: root.querySelector('[name="query"]'),
      scope: root.querySelector('[name="outstanding_only"]'),
      tbody: root.querySelector('[data-lc-rows="issues"]'),
      empty: root.querySelector('[data-lc-empty="issues"]'),
      loading: root.querySelector('[data-lc-loading="issues"]'),
      more: root.querySelector('[data-lc-action="more"]'),
      ownNote: root.querySelector('[data-lc-own-note]'),
      panel: root.querySelector('[data-lc-panel="return"]'),
      summary: root.querySelector('[data-lc-summary="return"]'),
      outstanding: root.querySelector('[data-lc-metric="outstanding"]'),
      stock: root.querySelector('[data-lc-metric="stock"]'),
      stockDetail: root.querySelector('[data-lc-metric="stock-detail"]'),
      form: root.querySelector('[data-lc-form="return"]'),
      quantity: root.querySelector('[name="quantity"]'),
      unknownPanel: root.querySelector('[data-lc-panel="unknown"]'),
      unknownDetail: root.querySelector('[data-lc-unknown-detail]'),
      pendingInfo: root.querySelector('[data-lc-pending-info]')
    };

    var state = {
      items: [],
      cursor: null,
      loading: false,
      uid: null,
      canReturn: LC.has('can_return'),
      canIssueForOthers: LC.has('can_issue_for_others'),
      target: null,       // 当前归还目标（服务端返回的领用行）
      attempt: null,      // 未知结果的显式重试载荷
      lock: null          // 未决锁：非空时禁止任何新归还（{params, source}）
    };

    /* ------------------------------------------------------------ 列表加载 */
    function currentFilters() {
      return {
        query: els.query ? els.query.value.trim() : '',
        outstanding_only: !els.scope || els.scope.value !== '0'
      };
    }

    function load(reset) {
      if (state.loading) return;
      state.loading = true;
      LC.show(els.loading, true);
      LC.show(els.more, false);
      var params = {
        query: currentFilters().query,
        outstanding_only: currentFilters().outstanding_only,
        limit: PAGE_SIZE
      };
      if (!reset && state.cursor) params.cursor = state.cursor;
      return LC.rpc('issues', params).then(function (data) {
        state.loading = false;
        LC.show(els.loading, false);
        var rows = (data && data.issues) || [];
        if (reset) state.items = [];
        state.items = state.items.concat(rows);
        state.cursor = (data && data.next_cursor) || null;
        renderAll();
        LC.show(els.more, !!state.cursor);
        if (reset) {
          if (!rows.length) {
            LC.status.show({ kind: 'empty', message: '没有符合条件的领用记录。' });
          } else {
            LC.status.clear();
          }
        }
      }).catch(function (error) {
        state.loading = false;
        LC.show(els.loading, false);
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

    function renderAll() {
      if (!els.tbody) return;
      LC.clear(els.tbody);
      state.items.forEach(function (item) {
        els.tbody.appendChild(renderRow(item));
      });
      var isEmpty = state.items.length === 0;
      if (els.empty) {
        LC.show(els.empty, isEmpty && !state.loading);
        if (isEmpty) LC.setText(els.empty, '没有符合条件的领用记录。');
      }
    }

    function itemText(item) {
      return item.mpn || item.catalog_code || item.item_key || ('档案 ' + item.product_template_id);
    }

    function renderRow(item) {
      var tr = LC.el('tr', {
        'data-issue-line-id': item.issue_line_id,
        'data-outstanding': String(item.outstanding_quantity)
      });
      tr.appendChild(LC.el('td', { text: LC.fmt.datetime(item.date) }));
      tr.appendChild(LC.el('td', { class: 'lc-mono', text: showText(item.trace_code) }));
      var itemCell = LC.el('td');
      itemCell.appendChild(LC.el('div', { text: itemText(item) }));
      if (item.sn) itemCell.appendChild(LC.el('div', { class: 'lc-hint', text: 'SN ' + item.sn }));
      tr.appendChild(itemCell);
      tr.appendChild(LC.el('td', { text: showText(item.location_path) }));
      tr.appendChild(LC.el('td', { text: qtyText(item.quantity) }));
      tr.appendChild(LC.el('td', { text: qtyText(item.returned_quantity) }));
      var outstandingCell = LC.el('td');
      var outstanding = LC.parse.float(item.outstanding_quantity, 0);
      outstandingCell.appendChild(LC.el('span', {
        class: 'lc-badge',
        'data-tone': outstanding > 0 ? 'warn' : 'ok',
        text: qtyText(item.outstanding_quantity)
      }));
      tr.appendChild(outstandingCell);
      var borrowerCell = LC.el('td');
      borrowerCell.appendChild(LC.el('div', { text: showText(item.borrower_name) }));
      if (state.uid && item.borrower_id === state.uid) {
        borrowerCell.appendChild(LC.el('div', { class: 'lc-hint', text: '本人' }));
      } else if (state.uid && item.borrower_id !== state.uid) {
        borrowerCell.appendChild(LC.el('div', { class: 'lc-hint', text: '他人（需管理员代还）' }));
      }
      tr.appendChild(borrowerCell);
      tr.appendChild(LC.el('td', { text: showText(item.project) }));

      var actions = LC.el('td');
      var actionsBox = LC.el('div', { class: 'lc-issue-row-actions' });
      if (state.canReturn && outstanding > 0) {
        actionsBox.appendChild(LC.el('button', {
          class: 'lc-btn lc-btn-ghost', type: 'button',
          'data-lc-action': 'return-open', 'data-issue-line-id': item.issue_line_id,
          text: '归还',
          disabled: !!state.lock
        }));
      }
      var historyLink = LC.el('a', {
        class: 'lc-btn lc-btn-ghost',
        href: LC.base + '/lab/history?bag_id=' + item.bag_id,
        text: '该袋流水'
      });
      actionsBox.appendChild(historyLink);
      actions.appendChild(actionsBox);
      tr.appendChild(actions);
      return tr;
    }

    /* ------------------------------------------------------------ 归还面板 */
    function findItem(issueLineId) {
      for (var i = 0; i < state.items.length; i += 1) {
        if (state.items[i].issue_line_id === issueLineId) return state.items[i];
      }
      return null;
    }

    function openReturn(issueLineId) {
      if (state.lock) {
        LC.status.show({
          kind: 'unknown',
          message: '有未决的归还尚未处理：暂不能发起新的归还。',
          detail: '请先重试同一份内容，或核对流水后按已核对结果解除未决锁。'
        });
        return;
      }
      var item = findItem(issueLineId);
      if (!item) {
        LC.status.show({ kind: 'error', message: '找不到该领用行，请刷新列表后重试。' });
        return;
      }
      state.target = item;
      LC.show(els.panel, true);
      renderReturnSummary(item);
      setOutstanding(item.outstanding_quantity);
      if (els.quantity) {
        els.quantity.value = String(item.outstanding_quantity);
        els.quantity.focus();
      }
      if (els.panel && els.panel.scrollIntoView) {
        els.panel.scrollIntoView({ block: 'nearest' });
      }
      loadBagStock(item.bag_id);
      LC.status.clear();
    }

    function renderReturnSummary(item) {
      if (!els.summary) return;
      LC.clear(els.summary);
      var pairs = [
        ['领用明细 ID', String(item.issue_line_id), true],
        ['袋码', showText(item.trace_code), true],
        ['器件', itemText(item)],
        ['领用日期', LC.fmt.datetime(item.date)],
        ['领用人', showText(item.borrower_name)],
        ['操作人', showText(item.actor_name)],
        ['项目', showText(item.project)],
        ['原领用数量', qtyText(item.quantity)],
        ['已归还', qtyText(item.returned_quantity)]
      ];
      pairs.forEach(function (pair) {
        els.summary.appendChild(LC.el('dt', { text: pair[0] }));
        els.summary.appendChild(LC.el('dd', {
          text: pair[1], class: pair[2] ? 'lc-mono' : ''
        }));
      });
    }

    function setOutstanding(value) {
      if (!els.outstanding) return;
      LC.setText(els.outstanding, qtyText(value));
    }

    /** 物理库存（stock.quant 实值）——与"可归还量"分开，不混成一个数。 */
    function loadBagStock(bagId) {
      if (els.stock) LC.setText(els.stock, '读取中…');
      if (els.stockDetail) LC.setText(els.stockDetail, '正在读取该袋的实时库存…');
      LC.rpc('bag', { bag_id: bagId }).then(function (data) {
        var bag = (data && data.bag) || null;
        if (!bag) {
          if (els.stock) LC.setText(els.stock, '读取失败');
          if (els.stockDetail) LC.setText(els.stockDetail, '请到「实物袋」页面查看该袋库存。');
          return;
        }
        if (els.stock) LC.setText(els.stock, qtyText(bag.quantity, bag.uom));
        if (els.stockDetail) {
          LC.setText(els.stockDetail,
            '在库 ' + qtyText(bag.quantity, bag.uom) +
            ' / 可用 ' + qtyText(bag.available_quantity, bag.uom) +
            ' / 已预留 ' + qtyText(bag.reserved_quantity, bag.uom) +
            '（库位 ' + showText(bag.location_path) + '）');
        }
      }).catch(function (error) {
        if (els.stock) LC.setText(els.stock, '读取失败');
        if (els.stockDetail) {
          LC.setText(els.stockDetail, describeError(error) + ' 物理库存不影响可归还量。');
        }
      });
    }

    function closeReturn() {
      state.target = null;
      LC.show(els.panel, false);
      LC.clearFormErrors(els.form);
    }

    /* -------------------------------------------------------------- 提交归还 */
    function submitReturn(attempt) {
      state.attempt = attempt;
      return LC.submit({
        scope: attempt.scope,
        endpoint: attempt.endpoint,
        params: attempt.params,
        button: attempt.button
      }).then(function (res) {
        state.attempt = null;
        clearLock();
        onReturnSuccess(res, attempt.target);
      }).catch(function (error) {
        if (error && error.unknown) {
          showUnknown(error, attempt);
          return;
        }
        if (isPendingUnknown(error)) {
          lockFromCore(error);
          return;
        }
        state.attempt = null;
        // 以 core 的未决记录为准：只有核心确实清掉了才允许新建归还
        var stillPending = LC.pendingAttempt
          ? LC.pendingAttempt(RETURN_SCOPE, RETURN_ENDPOINT) : null;
        if (stillPending) lockUnknown(stillPending.payload, 'after-error');
        else clearLock();
        showReturnError(error);
      });
    }

    function isPendingUnknown(error) {
      return !!(error && error.code === 'CONFLICT' && error.fields &&
        error.fields.submit === 'pending_unknown');
    }

    /* ------------------------------------------- 未决提交锁（security S2-1）
     * 与 core 同一语义：未决期间只有"完全相同的 payload"能重发（复用原 key）；
     * 改数量/换领用行都不发请求；解除必须由用户核对流水后显式 resolveUnknown。
     * 刷新后用 LC.pendingAttempt(scope, endpoint) 恢复横幅，**不自动重发**。
     */
    function setReturnLocked(locked) {
      if (els.quantity) els.quantity.disabled = !!locked;
      LC.qsa('[data-lc-action="submit-return"],[data-lc-action="return-full"],' +
        '[data-lc-action="return-open"]', root).forEach(function (node) {
        node.disabled = !!locked;
        if (locked) node.setAttribute('aria-disabled', 'true');
        else node.removeAttribute('aria-disabled');
      });
      LC.show(els.unknownPanel, !!locked);
      root.setAttribute('data-lc-locked', locked ? '1' : '0');
    }

    function pendingInfoText(payload) {
      if (!payload) return '';
      var parts = [];
      if (payload.issue_line_id) parts.push('领用明细 ID ' + payload.issue_line_id);
      if (payload.quantity !== undefined && payload.quantity !== null) {
        parts.push('归还数量 ' + payload.quantity);
      }
      return parts.length ? ('未决提交内容（重试会原样重发）：' + parts.join('，') + '。') : '';
    }

    function lockUnknown(payload, source) {
      state.lock = { params: payload || null, source: source || 'unknown' };
      setReturnLocked(true);
      if (els.pendingInfo) LC.setText(els.pendingInfo, pendingInfoText(payload));
      if (els.unknownDetail) {
        LC.setText(els.unknownDetail,
          '重试会用完全相同的领用行与数量，并复用同一个 request_key；' +
          '服务端若已处理会返回「已处理过（未重复入账）」。' +
          '在此期间改数量或换领用行都不会发出请求。');
      }
    }

    function showUnknown(error, attempt) {
      lockUnknown(attempt ? attempt.params : null, 'unknown');
      LC.status.show({
        kind: 'unknown',
        code: error && error.code,
        message: '结果未知（网络中断或超时）：归还是否入账不确定。',
        detail: '本页已锁定归还表单与所有「归还」按钮：不会自动重试，也不能改用新请求重发。' +
          '请点「用同一请求重试（同一份内容）」，或核对流水后按已核对结果解除。'
      });
    }

    function lockFromCore(error) {
      var pending = LC.pendingAttempt ? LC.pendingAttempt(RETURN_SCOPE, RETURN_ENDPOINT) : null;
      lockUnknown(pending ? pending.payload : null, 'core');
      LC.status.show({
        kind: 'unknown',
        code: 'CONFLICT',
        message: '未决归还未处理，本次内容已被拦下（没有发出任何请求，未产生账目）。',
        detail: (error && error.message ? error.message + ' ' : '') +
          '请用「用同一请求重试（同一份内容）」，或核对流水后按已核对结果解除。'
      });
    }

    function restorePending() {
      if (!LC.pendingAttempt) return false;
      var pending = LC.pendingAttempt(RETURN_SCOPE, RETURN_ENDPOINT);
      if (!pending) return false;
      lockUnknown(pending.payload, 'restore');
      var minutes = Math.round((pending.ageMs || 0) / 60000);
      LC.status.show({
        kind: 'unknown',
        message: '检测到未决的归还提交：' +
          (minutes >= 1 ? (minutes + ' 分钟前') : '刚刚') + '发出，结果未知。',
        detail: '本页不会自动重发。请用「用同一请求重试（同一份内容）」，' +
          '或先看「该袋流水」核对，再按已核对结果（未入账 / 已入账）显式解除。'
      });
      return true;
    }

    function clearLock() {
      state.lock = null;
      setReturnLocked(false);
      if (els.pendingInfo) LC.setText(els.pendingInfo, '');
    }

    function retryUnknown() {
      if (!state.lock || !state.lock.params) return;
      var params = state.lock.params;
      var button = els.form ? els.form.querySelector('button[type="submit"]') : null;
      var target = findItem(LC.parse.int(params.issue_line_id, null));
      submitReturn({
        scope: RETURN_SCOPE,
        endpoint: RETURN_ENDPOINT,
        params: params,
        button: button,
        target: target
      });
    }

    function verifyResolve(verification) {
      if (!state.lock) return;
      var question = verification === 'absent'
        ? '已核对「该袋流水」/「刷新」后的可归还量，并确认上一次归还【没有】入账？\n解除后可以重新归还（会生成新的 request_key），页面不会自动重发。'
        : '已核对「该袋流水」，并确认上一次归还【已经】入账？\n解除后页面不会重发，请勿重复归还。';
      if (!LC.confirmAction(question)) return;
      LC.resolveUnknown(RETURN_SCOPE, RETURN_ENDPOINT, {
        confirmed: true,
        verification: verification
      }).then(function () {
        clearLock();
        state.cursor = null;
        // 先按服务端实值重拉，再显示提示（load 成功会清状态区，顺序反了会擦掉提示）
        return Promise.resolve(load(true)).then(function () {
          LC.status.show({
            kind: verification === 'present' ? 'success' : 'empty',
            message: verification === 'present'
              ? '已按「上次已入账」解除未决锁（未重发）。'
              : '已按「上次未入账」解除未决锁。',
            detail: '列表已按服务端最新未还余额重新加载；请核对每一行的可归还量。'
          });
        });
      }).catch(function (error) {
        LC.status.show({
          kind: 'error',
          code: error && error.code,
          message: describeError(error)
        });
      });
    }

    function showReturnError(error) {
      if (error && error.code === 'UNAUTHORIZED') return;   // core 已给"重新登录"
      var fields = (error && error.fields) || {};
      var message = describeError(error);
      var notOwner = !!(error && error.code === 'FORBIDDEN' &&
        fields.issue_line_id === 'not_owner');
      if (notOwner) {
        message = '只能归还自己的领用记录；代他人归还需要库存管理员权限。';
      } else if (error && error.code === 'FORBIDDEN') {
        message = '当前账号没有归还权限（can_return），请联系库存管理员。';
      } else if (error && error.code === 'PRECONDITION_FAILED') {
        message = message + '（本次归还未入账，请按最新未还数量重试）';
      }
      var present = function () {
        LC.status.show({
          kind: 'error',
          code: error && error.code,
          message: message,
          detail: fieldDetail(error)
        });
      };
      present();
      if (notOwner) {
        // 刷新列表会清状态区：刷新完成后再把这条提示放回去
        Promise.resolve(load(true)).then(present).catch(present);
        return;
      }
      if (error && error.code === 'PRECONDITION_FAILED' && state.target) {
        // 未还余额可能已被别人归还：重新拉服务端未还数量
        refreshTarget(state.target.issue_line_id);
      }
    }

    function refreshTarget(issueLineId) {
      var item = findItem(issueLineId);
      if (!item) return;
      LC.rpc('issues', {
        query: item.trace_code || '',
        outstanding_only: false,
        limit: 50
      }).then(function (data) {
        var rows = (data && data.issues) || [];
        var fresh = rows.filter(function (row) {
          return row.issue_line_id === issueLineId;
        })[0];
        if (!fresh) return;
        applyIssueLine(fresh);
      }).catch(function () {
        // 读失败不改动页面上的数字：宁可不刷新，也不显示猜测值
      });
    }

    function applyIssueLine(fresh) {
      for (var i = 0; i < state.items.length; i += 1) {
        if (state.items[i].issue_line_id === fresh.issue_line_id) {
          state.items[i] = Object.assign({}, state.items[i], fresh);
          break;
        }
      }
      if (state.target && state.target.issue_line_id === fresh.issue_line_id) {
        state.target = Object.assign({}, state.target, fresh);
        renderReturnSummary(state.target);
        setOutstanding(state.target.outstanding_quantity);
      }
      renderAll();
    }

    function onReturnSuccess(res, target) {
      var data = (res && res.data) || {};
      var issueLine = data.issue_line || null;
      var outstanding = data.outstanding_quantity;
      var operation = data.operation || {};
      // 重试路径（刷新后重放）可能拿不到行对象：ID 以服务端响应为准，不依赖闭包里的 target
      var targetId = issueLine && issueLine.issue_line_id
        ? issueLine.issue_line_id
        : (target && target.issue_line_id ? target.issue_line_id : null);

      if (issueLine) {
        applyIssueLine(issueLine);
      } else if (target && outstanding !== undefined) {
        applyIssueLine(Object.assign({}, target, {
          outstanding_quantity: outstanding
        }));
      }

      var remaining = LC.parse.float(
        issueLine ? issueLine.outstanding_quantity : outstanding, 0);

      if (state.target) {
        setOutstanding(remaining);
        // 成功后重新拉实际物理库存（不沿用归还前的数字）
        loadBagStock(state.target.bag_id);
      } else if (target && target.bag_id) {
        loadBagStock(target.bag_id);
      }

      var message = '归还成功：单号 ' + showText(operation.name) +
        '，剩余未归还 ' + qtyText(remaining) + '。';
      if (res && res.replayed) {
        message += '（该请求此前已处理过，本次未重复入账）';
      }
      LC.status.show({
        kind: 'success',
        message: message,
        detail: remaining <= 1e-9
          ? '该领用行已还清，不再出现在「只看未归还」里。'
          : '可继续归还剩余数量；可归还量以服务端未还数量为准。'
      });

      if (remaining <= 1e-9) {
        if (els.quantity) els.quantity.value = '0';
        closeReturn();
        if (els.scope && els.scope.value !== '0' && targetId) {
          state.items = state.items.filter(function (row) {
            return row.issue_line_id !== targetId;
          });
          renderAll();
        }
        if (!findItem(targetId)) {
          // 行不在当前列表页（例如刷新后重放、或已还清被过滤）：列表本身没有陈旧数字可修，
          // 这里不整表重拉，避免把刚显示的"归还成功"提示又清掉。
        }
      }
    }

    /* ---------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action]', 'click', function (event, element) {
      var action = element.getAttribute('data-lc-action');
      if (action === 'search') {
        event.preventDefault();
        state.cursor = null;
        load(true);
      } else if (action === 'reload') {
        event.preventDefault();
        state.cursor = null;
        load(true);
      } else if (action === 'more') {
        event.preventDefault();
        if (!state.cursor) return;
        load(false);
      } else if (action === 'return-open') {
        event.preventDefault();
        openReturn(LC.parse.int(element.getAttribute('data-issue-line-id'), null));
      } else if (action === 'return-close') {
        event.preventDefault();
        closeReturn();
      } else if (action === 'retry-unknown') {
        event.preventDefault();
        retryUnknown();
      } else if (action === 'verify-absent') {
        event.preventDefault();
        verifyResolve('absent');
      } else if (action === 'verify-present') {
        event.preventDefault();
        verifyResolve('present');
      } else if (action === 'return-full') {
        event.preventDefault();
        if (!state.target) return;
        var outstanding = LC.parse.float(state.target.outstanding_quantity, 0);
        if (els.quantity) els.quantity.value = String(outstanding);
        LC.clearFormErrors(els.form);
      }
    });

    if (els.filter) {
      els.filter.addEventListener('submit', function (event) {
        event.preventDefault();
        state.cursor = null;
        load(true);
      });
    }

    if (els.form) {
      LC.guard(els.form, function (values, done) {
        if (state.lock) {
          LC.status.show({
            kind: 'unknown',
            message: '上一次归还是否入账未知，尚未确认。',
            detail: '本页已锁定归还。请用「用同一请求重试（同一份内容）」，' +
              '或核对流水后按已核对结果解除未决锁。'
          });
          done();
          return;
        }
        var target = state.target;
        if (!target) {
          LC.status.show({ kind: 'error', message: '请先选择要归还的领用记录。' });
          done();
          return;
        }
        var quantity = LC.parse.float(values.quantity, null);
        var outstanding = LC.parse.float(target.outstanding_quantity, 0);
        if (quantity === null || !(quantity > 0)) {
          LC.formError(els.form, 'quantity', '归还数量必须大于 0。');
          done();
          return;
        }
        if (quantity - outstanding > 1e-9) {
          LC.formError(els.form, 'quantity',
            '归还数量不能超过可归还量 ' + qtyText(outstanding) + '。');
          done();
          return;
        }
        LC.clearFormErrors(els.form);
        var button = els.form.querySelector('button[type="submit"]');
        submitReturn({
          scope: RETURN_SCOPE,
          endpoint: RETURN_ENDPOINT,
          params: {
            issue_line_id: target.issue_line_id,
            quantity: quantity
          },
          button: button,
          target: target
        }).then(function () {
          done();
        }).catch(function (error) {
          done(error && !error.unknown ? error : null);
        });
      });
    }

    /* ---------------------------------------------------------------- 初始化 */
    function init() {
      var notes = [];
      if (!state.canIssueForOthers) {
        notes.push('当前账号不是库存管理员：列表只显示我自己的领用记录（由服务端过滤，不是前端筛选）。');
      }
      if (!state.canReturn) {
        notes.push('当前账号没有归还权限（can_return）：只能查看记录，不能提交归还。');
      }
      if (notes.length && els.ownNote) {
        LC.setText(els.ownNote, notes.join(' '));
        LC.show(els.ownNote, true);
      }
      LC.session().then(function (session) {
        state.uid = session && session.uid ? session.uid : null;
        renderAll();
      }).catch(function () {
        renderAll();
      });
      load(true);
      // 跨刷新恢复未决提示（只提示 + 锁定，不自动重发）
      restorePending();
    }

    init();
  });
})();
