/* ==========================================================================
 * P3 领用页（/lab/issues/new）· issue 子任务写域
 * --------------------------------------------------------------------------
 * 接口一律走 window.LC（workflow_core.js）：不手写 fetch / JSON-RPC 外层，
 * 不拼 HTML（只用 LC.el / textContent），没有内联事件与 eval（CSP script-src self）。
 *
 * 用到的端点 key（frontend-contract §6）：
 *   resolve  /lab/api/inventory/resolve_code   扫码解析（袋 / 库位 / 器件 / SN）
 *   bags     /lab/api/inventory/bags           扫到库位码时列出该库位在库袋
 *   bag      /lab/api/inventory/bag            单袋实时事实（提交后重新拉真实库存）
 *   bootstrap/lab/api/inventory/bootstrap      领用人白名单（系统账号）+ uid
 *   issue    /lab/api/inventory/issue          领用（唯一写入口，走 LC.submit）
 *
 * 业务不变量：
 *   1. 领用人必须是系统账号，取自 bootstrap.borrowers；
 *      can_issue_for_others=false 时锁定为本人（服务端 lab_check_borrower 仍会校验）。
 *   2. 数量一律展示服务端实时可用（bag.available_quantity，来自 stock.quant）；
 *      本页不缓存、不自算库存，提交后重新拉真实库存。
 *   3. 可领用量（可用）与该袋历史未归还（outstanding_quantity）分开展示，不混用。
 *   4. 结果未知（断网 / 超时 / 5xx）时 payload 与 request_key 原样保留，
 *      只提供显式"用同一请求重试"；不自动重试、不换 key、不在刷新时自动提交。
 * ========================================================================== */
(function () {
  'use strict';

  var MAX_LINES = 100;

  //: 逻辑表单 scope：**只含页面与业务动作**，绝不含料号/袋/领用人等可编辑内容。
  //: 核心按 (user, company, scope, endpoint) 锁定未决提交；若把可编辑字段拼进
  //: scope，用户"换个袋换个数量"就会落到新 scope，等于绕过未决锁（security S2-1）。
  var ISSUE_SCOPE = 'issue_new/issue';
  var ISSUE_ENDPOINT = 'issue';

  function showText(value) {
    return value === null || value === undefined || value === '' ? '—' : String(value);
  }

  function qtyText(value, uom) {
    var formatted = LC.fmt.quantity(value);
    if (formatted === '—') return formatted;
    return uom ? (formatted + ' ' + uom) : formatted;
  }

  /** 按 code 分支的文案：PRECONDITION/CONFLICT/VALIDATION 直接用服务端中文上下文。 */
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

  LC.register('issue_new', function (ctx) {
    var root = ctx.root || document.getElementById('workflow-root');
    if (!root) return;

    var els = {
      toolbar: root.querySelector('.lc-issue-toolbar'),
      scan: root.querySelector('[data-lc-scan]'),
      scanPanel: root.querySelector('[data-lc-panel="scan"]'),
      scanRows: root.querySelector('[data-lc-rows="scan"]'),
      scanEmpty: root.querySelector('[data-lc-empty="scan"]'),
      cartPanel: root.querySelector('[data-lc-panel="cart"]'),
      cartRows: root.querySelector('[data-lc-rows="cart"]'),
      cartEmpty: root.querySelector('[data-lc-empty="cart"]'),
      cartCount: root.querySelector('[data-lc-count="cart"]'),
      formPanel: root.querySelector('[data-lc-panel="form"]'),
      form: root.querySelector('[data-lc-form="issue"]'),
      borrower: root.querySelector('[name="borrower_id"]'),
      borrowerNote: root.querySelector('[data-lc-borrower-note]'),
      project: root.querySelector('[name="project"]'),
      successPanel: root.querySelector('[data-lc-panel="success"]'),
      successSummary: root.querySelector('[data-lc-summary="success"]'),
      successRows: root.querySelector('[data-lc-rows="success"]'),
      replayNote: root.querySelector('[data-lc-replay-note]'),
      unknownPanel: root.querySelector('[data-lc-panel="unknown"]'),
      unknownDetail: root.querySelector('[data-lc-unknown-detail]'),
      pendingInfo: root.querySelector('[data-lc-pending-info]'),
      readonlyPanel: root.querySelector('[data-lc-panel="readonly"]'),
      issuesLink: root.querySelector('[data-lc-link="issues"]')
    };

    var state = {
      cart: [],          // [{bag_id, trace_code, name, mpn, item_key, location_path, uom, available, quantity, reserved, outstanding, qty}]
      found: {},         // bag_id -> 最近一次服务端 bag 字典（只用于展示）
      borrowers: [],
      uid: null,
      canIssueForOthers: false,
      attempt: null,     // 未知结果的显式重试载荷（同 params 同 key）
      lock: null,        // 未决锁：非空时禁止任何新提交（{params, source}）
      submitting: false
    };

    var canIssue = LC.has('can_issue');

    /* ---------------------------------------------------------------- 工具 */
    function factList(pairs) {
      var list = LC.el('dl', { class: 'lc-kv lc-issue-bag-facts' });
      pairs.forEach(function (pair) {
        list.appendChild(LC.el('dt', { text: pair[0] }));
        list.appendChild(LC.el('dd', { text: pair[1], class: pair[2] ? 'lc-mono' : '' }));
      });
      return list;
    }

    function bagPairs(bag) {
      var uom = bag.uom || '';
      return [
        ['追溯码', showText(bag.trace_code), true],
        ['器件', showText(bag.name || bag.mpn || bag.item_key)],
        ['MPN', showText(bag.mpn)],
        ['立创编号', showText(bag.catalog_code)],
        ['库位', showText(bag.location_path)],
        ['实时在库', qtyText(bag.quantity, uom)],
        ['实时可用', qtyText(bag.available_quantity, uom)],
        ['已预留', qtyText(bag.reserved_quantity, uom)],
        ['该袋历史未归还', qtyText(bag.outstanding_quantity, uom)]
      ];
    }

    function findBag(bagId) {
      var wanted = LC.parse.int(bagId, null);
      for (var i = 0; i < state.cart.length; i += 1) {
        if (state.cart[i].bag_id === wanted) return state.cart[i];
      }
      return null;
    }

    function statusError(error, retry) {
      LC.status.show({
        kind: 'error',
        code: error && error.code,
        message: describeError(error),
        detail: fieldDetail(error),
        retry: retry
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

    /* ------------------------------------------------------- 领用人（系统账号） */
    function fillBorrowers(data) {
      var borrowers = (data && data.borrowers) || [];
      state.borrowers = borrowers;
      var permissions = (data && data.permissions) || {};
      state.uid = permissions.uid || state.uid;
      if (permissions.can_issue_for_others !== undefined) {
        state.canIssueForOthers = !!permissions.can_issue_for_others;
      }
      var select = els.borrower;
      if (!select) return;
      LC.clear(select);
      var list = borrowers;
      if (!state.canIssueForOthers) {
        list = borrowers.filter(function (user) {
          return !!user.is_self || (state.uid && user.id === state.uid);
        });
      }
      if (!list.length) {
        select.appendChild(LC.el('option', { value: '', text: '没有可用的系统账号' }));
        if (els.borrowerNote) {
          LC.setText(els.borrowerNote, '未读取到可用的领用人；请让库存管理员确认账号已在实验室成员里。');
          LC.show(els.borrowerNote, true);
        }
        return;
      }
      list.forEach(function (user) {
        var label = user.name || user.login || ('#' + user.id);
        if (user.login) label += '（' + user.login + '）';
        if (user.is_self) label += ' · 本人';
        select.appendChild(LC.el('option', { value: String(user.id), text: label }));
      });
      var self = list.filter(function (user) { return user.is_self; })[0] ||
        list.filter(function (user) { return state.uid && user.id === state.uid; })[0];
      if (self) select.value = String(self.id);
      else if (list.length === 1) select.value = String(list[0].id);

      if (els.borrowerNote) {
        if (state.canIssueForOthers) {
          LC.setText(els.borrowerNote, '当前账号可以代他人领用（can_issue_for_others）。');
        } else {
          LC.setText(els.borrowerNote,
            '当前账号只能为自己领用：领用人已锁定为本人，代他人领用需要库存管理员权限。');
        }
        LC.show(els.borrowerNote, true);
      }
    }

    function loadBootstrap() {
      LC.rpc('bootstrap', {}).then(function (data) {
        fillBorrowers(data);
      }).catch(function (error) {
        if (els.borrower) {
          LC.clear(els.borrower);
          els.borrower.appendChild(LC.el('option', { value: '', text: '领用人读取失败' }));
        }
        statusError(error, function () { loadBootstrap(); });
      });
    }

    /* ------------------------------------------------------------------ 扫码 */
    function resolveRaw(raw) {
      var value = (raw || '').trim();
      if (!value) return;
      LC.status.clear();
      LC.show(els.scanPanel, true);
      LC.clear(els.scanRows);
      LC.show(els.scanEmpty, true);
      LC.setText(els.scanEmpty, '正在解析…');
      LC.rpc('resolve', { raw: value }).then(function (data) {
        LC.show(els.scanEmpty, false);
        renderResolved(data || {});
      }).catch(function (error) {
        LC.show(els.scanEmpty, false);
        renderResolveFailed(error);
      });
    }

    function renderResolveFailed(error) {
      LC.clear(els.scanRows);
      var box = LC.el('div', { class: 'lc-issue-result' });
      box.appendChild(LC.el('p', {
        class: 'lc-hint',
        text: describeError(error)
      }));
      if (error && error.code === 'PRECONDITION_FAILED') {
        box.appendChild(LC.el('p', {
          class: 'lc-hint',
          text: '扫到的袋码尚未入库或已取消：请先到「采购入库」的扫码上架完成入库。'
        }));
      }
      if (error && error.code === 'NOT_FOUND') {
        box.appendChild(LC.el('p', {
          class: 'lc-hint',
          text: '没有找到该编码对应的袋或器件（可能不属于当前公司，或编码不完整）。'
        }));
      }
      els.scanRows.appendChild(box);
      statusError(error, function () { resolveRaw(els.scan && els.scan.value); });
    }

    function renderResolved(data) {
      LC.clear(els.scanRows);
      var kind = data.kind || 'unknown';

      if (kind === 'bag' && data.bag) {
        state.found[data.bag.id] = data.bag;
        els.scanRows.appendChild(bagResultCard(data.bag, '扫到实物袋'));
        return;
      }

      if (kind === 'location' && data.location) {
        els.scanRows.appendChild(LC.el('p', {
          class: 'lc-lead',
          text: '扫到库位码：' + showText(data.location.path || data.location.name) +
            '。下面是该库位里仍有库存的袋，可直接加入领用明细。'
        }));
        loadLocationBags(data.location.id);
        return;
      }

      if ((kind === 'lcsc' || kind === 'jlc' || kind === 'sn') && data.ambiguous_material) {
        var candidates = data.candidates || [];
        els.scanRows.appendChild(LC.el('p', {
          class: 'lc-lead',
          text: '该立创编号下有 ' + candidates.length + ' 个本地档案，不自动取第一个：请按 SN 选择。'
        }));
        var list = LC.el('div', { class: 'lc-issue-results-list' });
        candidates.forEach(function (candidate) {
          var card = LC.el('div', { class: 'lc-issue-result' });
          card.appendChild(factList([
            ['档案 ID', String(candidate.product_template_id), true],
            ['SN', showText(candidate.sn), true],
            ['器件', showText(candidate.name)],
            ['MPN', showText(candidate.mpn)],
            ['封装', showText(candidate.package)]
          ]));
          if (candidate.sn) {
            card.appendChild(LC.el('button', {
              class: 'lc-btn lc-btn-outline', type: 'button',
              'data-lc-action': 'pick-sn', 'data-sn': candidate.sn,
              text: '按该 SN 查看在库袋'
            }));
          } else {
            card.appendChild(LC.el('p', {
              class: 'lc-hint',
              text: '该档案没有 SN：请到「器件档案」确认绑定关系后再领用。'
            }));
          }
          list.appendChild(card);
        });
        els.scanRows.appendChild(list);
        return;
      }

      if (data.material || (data.bags && data.bags.length)) {
        renderMaterialBags(data);
        return;
      }

      // unknown：中性提示，不猜成袋
      els.scanRows.appendChild(LC.el('p', {
        class: 'lc-lead',
        text: '无法识别这个编码。可识别的载荷：袋追溯码（LABB:）、库位库码（LABL:）、' +
          '立创编号（C 开头数字）、物料 SN。'
      }));
      els.scanRows.appendChild(LC.el('p', {
        class: 'lc-hint',
        text: '扫码枪请确认末尾带回车；也可以手工粘贴完整编码后点「解析」。'
      }));
    }

    function renderMaterialBags(data) {
      var material = data.material || {};
      var bags = data.bags || [];
      els.scanRows.appendChild(factList([
        ['器件', showText(material.name)],
        ['立创编号', showText(material.catalog_code), true],
        ['MPN', showText(material.mpn)],
        ['实验室总量', qtyText(material.lab_quantity, material.uom)]
      ]));
      if (!bags.length) {
        els.scanRows.appendChild(LC.el('p', {
          class: 'lc-hint',
          text: '该器件当前没有在库袋（实验室库存为 0），无法领用。'
        }));
        return;
      }
      els.scanRows.appendChild(LC.el('p', {
        class: 'lc-hint',
        text: '下面是该器件的在库袋（数量为服务端实时可用）：'
      }));
      var list = LC.el('div', { class: 'lc-issue-results-list' });
      bags.forEach(function (bag) {
        state.found[bag.id] = bag;
        list.appendChild(bagResultCard(bag, '在库袋'));
      });
      els.scanRows.appendChild(list);
    }

    function loadLocationBags(locationId) {
      var holder = LC.el('div', { class: 'lc-issue-results-list' });
      holder.appendChild(LC.el('p', { class: 'lc-loading', text: '正在读取该库位的袋…' }));
      els.scanRows.appendChild(holder);
      LC.rpc('bags', { location_id: locationId, has_stock: true, limit: 24 })
        .then(function (data) {
          LC.clear(holder);
          var bags = (data && data.bags) || [];
          if (!bags.length) {
            holder.appendChild(LC.el('p', {
              class: 'lc-hint',
              text: '该库位没有仍有库存的袋。'
            }));
            return;
          }
          bags.forEach(function (bag) {
            state.found[bag.id] = bag;
            holder.appendChild(bagResultCard(bag, '该库位在库袋'));
          });
          if (data.next_cursor) {
            holder.appendChild(LC.el('p', {
              class: 'lc-hint',
              text: '还有更多袋：请用袋码或器件编号缩小范围。'
            }));
          }
        })
        .catch(function (error) {
          LC.clear(holder);
          holder.appendChild(LC.el('p', { class: 'lc-hint', text: describeError(error) }));
        });
    }

    function bagResultCard(bag, title) {
      var card = LC.el('div', { class: 'lc-issue-result' });
      card.appendChild(LC.el('h3', { class: 'lc-issue-result-title', text: title }));
      card.appendChild(factList(bagPairs(bag)));
      var available = LC.parse.float(bag.available_quantity, 0);
      if (canIssue) {
        if (available > 0) {
          card.appendChild(LC.el('button', {
            class: 'lc-btn lc-btn-primary', type: 'button',
            'data-lc-action': 'add-bag', 'data-bag-id': bag.id,
            text: state.lock ? '未决提交未处理，暂不可加入' : '加入领用明细',
            disabled: !!state.lock
          }));
        } else {
          card.appendChild(LC.el('p', {
            class: 'lc-hint',
            text: '该袋实时可用为 0（可能已被预留或未归还未回库），不能领用。'
          }));
        }
      }
      return card;
    }

    /* ------------------------------------------------------------ 领用明细 */
    function addBag(bagId) {
      var bag = state.found[bagId];
      if (!bag) {
        LC.status.show({ kind: 'error', message: '找不到该袋的实时数据，请重新扫码。' });
        return;
      }
      if (findBag(bag.id)) {
        LC.status.show({
          kind: 'empty',
          message: '该袋已在领用明细里：请直接修改数量，同一袋不能重复提交。'
        });
        return;
      }
      if (state.cart.length >= MAX_LINES) {
        LC.status.show({
          kind: 'error',
          message: '一次领用最多 ' + MAX_LINES + ' 条明细，请分批提交。'
        });
        return;
      }
      var available = LC.parse.float(bag.available_quantity, 0);
      if (!(available > 0)) {
        LC.status.show({ kind: 'error', message: '该袋实时可用为 0，不能领用。' });
        return;
      }
      state.cart.push({
        bag_id: bag.id,
        trace_code: bag.trace_code,
        name: bag.name || bag.mpn || bag.item_key,
        mpn: bag.mpn || '',
        item_key: bag.item_key || '',
        location_path: bag.location_path || '',
        uom: bag.uom || '',
        available: available,
        quantity: LC.parse.float(bag.quantity, 0),
        reserved: LC.parse.float(bag.reserved_quantity, 0),
        outstanding: LC.parse.float(bag.outstanding_quantity, 0),
        qty: Math.min(1, available)
      });
      LC.status.clear();
      renderCart();
    }

    function renderCart() {
      if (!els.cartRows) return;
      LC.clear(els.cartRows);
      state.cart.forEach(function (line) {
        var tr = LC.el('tr', { 'data-cart-bag-id': line.bag_id });
        tr.appendChild(LC.el('td', { class: 'lc-mono', text: showText(line.trace_code) }));
        var itemCell = LC.el('td');
        itemCell.appendChild(LC.el('div', { text: showText(line.name) }));
        if (line.mpn) {
          itemCell.appendChild(LC.el('div', { class: 'lc-hint', text: 'MPN ' + line.mpn }));
        }
        tr.appendChild(itemCell);
        tr.appendChild(LC.el('td', { text: showText(line.location_path) }));
        var availableCell = LC.el('td');
        availableCell.appendChild(LC.el('span', {
          class: 'lc-badge', 'data-tone': 'ok', text: qtyText(line.available, line.uom)
        }));
        availableCell.appendChild(LC.el('div', {
          class: 'lc-hint',
          text: '在库 ' + qtyText(line.quantity, line.uom) +
            ' / 预留 ' + qtyText(line.reserved, line.uom)
        }));
        tr.appendChild(availableCell);
        var qtyCell = LC.el('td');
        qtyCell.appendChild(LC.el('input', {
          class: 'lc-input lc-issue-qty', type: 'number', step: 'any', min: '0',
          inputmode: 'decimal', 'data-lc-cart-qty': '', 'data-bag-id': line.bag_id,
          'aria-label': '领用数量（袋 ' + showText(line.trace_code) + '）',
          value: String(line.qty), disabled: !!state.lock
        }));
        qtyCell.appendChild(LC.el('div', {
          class: 'lc-hint', text: '最多 ' + qtyText(line.available, line.uom)
        }));
        tr.appendChild(qtyCell);
        var actionCell = LC.el('td');
        actionCell.appendChild(LC.el('button', {
          class: 'lc-btn lc-btn-ghost', type: 'button',
          'data-lc-action': 'remove-bag', 'data-bag-id': line.bag_id, text: '移除',
          disabled: !!state.lock
        }));
        tr.appendChild(actionCell);
        els.cartRows.appendChild(tr);
      });
      if (els.cartEmpty) {
        LC.show(els.cartEmpty, state.cart.length === 0);
        if (!state.cart.length) LC.setText(els.cartEmpty, '还没有明细：先扫码或从扫码结果里选择袋。');
      }
      if (els.cartCount) LC.setText(els.cartCount, String(state.cart.length));
    }

    function updateQty(bagId, rawValue) {
      var line = findBag(bagId);
      if (!line) return;
      var value = LC.parse.float(rawValue, null);
      var input = root.querySelector('[data-lc-cart-qty][data-bag-id="' + bagId + '"]');
      if (value === null || !(value > 0)) {
        LC.status.show({
          kind: 'error',
          message: '领用数量必须大于 0（袋 ' + showText(line.trace_code) + '）。'
        });
        if (input) input.value = String(line.qty);
        return;
      }
      if (value - line.available > 1e-9) {
        LC.status.show({
          kind: 'error',
          message: '袋 ' + showText(line.trace_code) + ' 实时可用只有 ' +
            qtyText(line.available, line.uom) + '，不能领用 ' + qtyText(value, line.uom) + '。'
        });
        if (input) input.value = String(line.available);
        line.qty = line.available;
        return;
      }
      line.qty = value;
      LC.status.clear();
    }

    /* -------------------------------------------------- 刷新实时数量（重新拉） */
    function refreshLive() {
      if (!state.cart.length) {
        LC.status.show({ kind: 'empty', message: '领用明细为空，没有需要刷新的数量。' });
        return;
      }
      var button = root.querySelector('[data-lc-action="refresh-live"]');
      LC.setBusy(button, true, '刷新中…');
      var tasks = state.cart.map(function (line) {
        return LC.rpc('bag', { bag_id: line.bag_id }).then(function (data) {
          var bag = (data && data.bag) || null;
          if (!bag) return null;
          state.found[bag.id] = bag;
          line.available = LC.parse.float(bag.available_quantity, line.available);
          line.quantity = LC.parse.float(bag.quantity, line.quantity);
          line.reserved = LC.parse.float(bag.reserved_quantity, line.reserved);
          line.outstanding = LC.parse.float(bag.outstanding_quantity, line.outstanding);
          if (line.qty - line.available > 1e-9) line.qty = Math.max(0, line.available);
          return bag.id;
        }).catch(function () {
          return null;
        });
      });
      Promise.all(tasks).then(function (ids) {
        LC.setBusy(button, false);
        renderCart();
        var failed = ids.filter(function (id) { return id === null; }).length;
        if (failed) {
          LC.status.show({
            kind: 'error',
            message: '有 ' + failed + ' 个袋的实时数量读取失败，页面显示的可能不是最新值。'
          });
        } else {
          LC.status.show({
            kind: 'success',
            message: '已按服务端实时库存刷新 ' + state.cart.length + ' 条明细。'
          });
        }
      });
    }

    /* -------------------------------------------------------------- 提交领用 */
    function buildParams(values) {
      var borrowerId = LC.parse.int(values.borrower_id, null);
      if (!borrowerId) borrowerId = state.uid;
      var project = (values.project || '').trim();
      var lines = state.cart.map(function (line) {
        return { bag_id: line.bag_id, quantity: line.qty };
      });
      return {
        borrower_id: borrowerId,
        project: project,
        lines: lines,
        note: (values.note || '').trim()
      };
    }

    function validate(params) {
      if (!state.cart.length) {
        return { field: 'lines', message: '请先扫码把要领用的袋加入明细。' };
      }
      if (!params.borrower_id) {
        return { field: 'borrower_id', message: '请选择领用人（必须是系统账号）。' };
      }
      if (!state.canIssueForOthers && state.uid && params.borrower_id !== state.uid) {
        return { field: 'borrower_id', message: '当前账号只能为自己领用。' };
      }
      if (!params.project) {
        return { field: 'project', message: '请填写领用项目。' };
      }
      for (var i = 0; i < state.cart.length; i += 1) {
        var line = state.cart[i];
        if (!(line.qty > 0)) {
          return { field: 'lines', message: '袋 ' + showText(line.trace_code) + ' 的数量必须大于 0。' };
        }
        if (line.qty - line.available > 1e-9) {
          return {
            field: 'lines',
            message: '袋 ' + showText(line.trace_code) + ' 的数量超过实时可用 ' +
              qtyText(line.available, line.uom) + '。'
          };
        }
      }
      return null;
    }

    function submitAttempt(attempt) {
      state.attempt = attempt;
      return LC.submit({
        scope: attempt.scope,
        endpoint: attempt.endpoint,
        params: attempt.params,
        button: attempt.button
      }).then(function (res) {
        state.attempt = null;
        clearLock();
        onSuccess(res);
      }).catch(function (error) {
        if (error && error.unknown) {
          showUnknown(error, attempt);
          return;
        }
        if (isPendingUnknown(error)) {
          // 核心在本地拦下"未决期间改内容再提交"，请求根本没发出去
          lockFromCore(error);
          return;
        }
        state.attempt = null;
        // 以 core 的未决记录为准：只有核心确实清掉了才允许新建提交
        var stillPending = LC.pendingAttempt
          ? LC.pendingAttempt(ISSUE_SCOPE, ISSUE_ENDPOINT) : null;
        if (stillPending) lockUnknown(stillPending.payload, 'after-error');
        else clearLock();
        showFormError(error);
      });
    }

    function isPendingUnknown(error) {
      return !!(error && error.code === 'CONFLICT' && error.fields &&
        error.fields.submit === 'pending_unknown');
    }

    /* ------------------------------------------- 未决提交锁（security S2-1）
     * 语义与 core 一致：未决期间
     *   (a) 只有"完全相同的 payload"能重发，且复用原 request_key；
     *   (b) 改动任何可编辑内容都不发请求（core 也会拦，本页先拦）；
     *   (c) 解除必须由用户核对过流水后显式 resolveUnknown(verification)。
     * 页面刷新后用 LC.pendingAttempt(scope, endpoint) 恢复横幅，**不自动重发**。
     */
    var LOCK_ACTIONS = '[data-lc-action="add-bag"],[data-lc-action="remove-bag"],' +
      '[data-lc-action="reset-cart"],[data-lc-action="submit-issue"]';

    function setLocked(locked) {
      LC.qsa(LOCK_ACTIONS, root).forEach(function (node) {
        node.disabled = !!locked;
        if (locked) node.setAttribute('aria-disabled', 'true');
        else node.removeAttribute('aria-disabled');
      });
      LC.qsa('[data-lc-cart-qty]', root).forEach(function (node) {
        node.disabled = !!locked;
      });
      if (els.form) {
        LC.qsa('input, select, textarea', els.form).forEach(function (node) {
          node.disabled = !!locked;
        });
      }
      if (els.unknownPanel) LC.show(els.unknownPanel, !!locked);
      root.setAttribute('data-lc-locked', locked ? '1' : '0');
    }

    function pendingInfoText(payload) {
      if (!payload) return '';
      var parts = [];
      if (payload.lines && payload.lines.length) parts.push(payload.lines.length + ' 条明细');
      if (payload.project) parts.push('项目「' + payload.project + '」');
      if (payload.borrower_id) parts.push('领用人 ID ' + payload.borrower_id);
      if (payload.note) parts.push('备注「' + payload.note + '」');
      return parts.length ? ('未决提交内容（重试会原样重发）：' + parts.join('，') + '。') : '';
    }

    function lockUnknown(payload, source) {
      state.lock = { params: payload || null, source: source || 'unknown' };
      setLocked(true);
      if (els.pendingInfo) LC.setText(els.pendingInfo, pendingInfoText(payload));
      if (els.unknownDetail) {
        var count = payload && payload.lines ? payload.lines.length : 0;
        LC.setText(els.unknownDetail,
          '重试会用完全相同的明细（' + count + ' 条）、领用人、项目与备注，并复用同一个 ' +
          'request_key；服务端若已处理会返回「已处理过（未重复入账）」。' +
          '在此期间改动数量或换袋都不会发出请求。');
      }
    }

    function showUnknown(error, attempt) {
      lockUnknown(attempt ? attempt.params : null, 'unknown');
      LC.status.show({
        kind: 'unknown',
        code: error && error.code,
        message: '结果未知（网络中断或超时）：领用是否已入账不确定。',
        detail: '本页已锁定输入与提交：不会自动重试，也不能改用新请求重发。' +
          '请点「用同一请求重试（同一份内容）」，或核对「领用记录」后按已核对结果解除。'
      });
    }

    /** 核心拦下的"未决期间换内容"：未发请求，按未决处理并恢复横幅。 */
    function lockFromCore(error) {
      var pending = LC.pendingAttempt ? LC.pendingAttempt(ISSUE_SCOPE, ISSUE_ENDPOINT) : null;
      lockUnknown(pending ? pending.payload : null, 'core');
      LC.status.show({
        kind: 'unknown',
        code: 'CONFLICT',
        message: '未决提交尚未处理，本次内容已被拦下（没有发出任何请求，未产生账目）。',
        detail: (error && error.message ? error.message + ' ' : '') +
          '请用「用同一请求重试（同一份内容）」，或核对「领用记录」后按已核对结果解除。'
      });
    }

    /** 页面加载时恢复未决提示；只提示，不自动重发。 */
    function restorePending() {
      if (!LC.pendingAttempt) return false;
      var pending = LC.pendingAttempt(ISSUE_SCOPE, ISSUE_ENDPOINT);
      if (!pending) return false;
      lockUnknown(pending.payload, 'restore');
      var minutes = Math.round((pending.ageMs || 0) / 60000);
      LC.status.show({
        kind: 'unknown',
        message: '检测到未决的领用提交：' +
          (minutes >= 1 ? (minutes + ' 分钟前') : '刚刚') + '发出，结果未知。',
        detail: '本页不会自动重发。请用「用同一请求重试（同一份内容）」重发同一份内容，' +
          '或先到「领用记录」核对，再按已核对结果（未入账 / 已入账）显式解除。'
      });
      return true;
    }

    function clearLock() {
      state.lock = null;
      setLocked(false);
      if (els.pendingInfo) LC.setText(els.pendingInfo, '');
    }

    function retryUnknown() {
      if (!state.lock || !state.lock.params) return;
      var button = els.form ? els.form.querySelector('button[type="submit"]') : null;
      submitAttempt({
        scope: ISSUE_SCOPE,
        endpoint: ISSUE_ENDPOINT,
        params: state.lock.params,
        button: button
      });
    }

    /** 显式解除：必须由用户先核对流水，并说明"未入账/已入账"。 */
    function verifyResolve(verification) {
      if (!state.lock) return;
      var question = verification === 'absent'
        ? '已到「领用记录」核对，并确认上一次提交【没有】入账？\n解除后可以重新提交（会生成新的 request_key），页面不会自动重发。'
        : '已到「领用记录」核对，并确认上一次提交【已经】入账？\n解除后页面不会重发，请勿重复领用。';
      if (!LC.confirmAction(question)) return;
      LC.resolveUnknown(ISSUE_SCOPE, ISSUE_ENDPOINT, {
        confirmed: true,
        verification: verification
      }).then(function () {
        clearLock();
        if (verification === 'present') {
          state.cart = [];
          renderCart();
          LC.status.show({
            kind: 'success',
            message: '已按「上次已入账」解除未决锁（未重发）。',
            detail: '请到「领用记录」按袋码/项目确认该单；本次明细已清空，避免重复领用。'
          });
        } else {
          LC.status.show({
            kind: 'empty',
            message: '已按「上次未入账」解除未决锁。',
            detail: '现在可以调整明细后重新提交（会生成新的 request_key）。'
          });
        }
      }).catch(function (error) {
        LC.status.show({
          kind: 'error',
          code: error && error.code,
          message: describeError(error)
        });
      });
    }

    function showFormError(error) {
      if (error && error.code === 'UNAUTHORIZED') return;   // core 已给"重新登录"
      var message = describeError(error);
      if (error && error.code === 'FORBIDDEN') {
        message = '当前账号没有领用权限，或领用人不在允许的系统账号范围内：' +
          (error.message || '请联系库存管理员。');
      }
      if (error && error.code === 'PRECONDITION_FAILED') {
        message = message + '（库存未变动；请点「刷新实时数量」核对后再提交）';
      }
      LC.status.show({
        kind: 'error',
        code: error && error.code,
        message: message,
        detail: fieldDetail(error),
        retry: null
      });
    }

    function onSuccess(res) {
      var data = (res && res.data) || {};
      var lines = data.lines || [];
      var operation = data.operation || {};

      if (els.successSummary) {
        LC.clear(els.successSummary);
        var pairs = [
          ['领用单号', showText(operation.name), true],
          ['领用人', showText(operation.borrower_name || operation.borrower_id)],
          ['项目', showText(operation.project)],
          ['明细条数', String(lines.length)],
          ['时间', LC.fmt.datetime(operation.create_date)]
        ];
        pairs.forEach(function (pair) {
          els.successSummary.appendChild(LC.el('dt', { text: pair[0] }));
          els.successSummary.appendChild(LC.el('dd', {
            text: pair[1], class: pair[2] ? 'lc-mono' : ''
          }));
        });
      }
      if (els.replayNote) LC.show(els.replayNote, !!(res && res.replayed));

      LC.clear(els.successRows);
      lines.forEach(function (line) {
        var tr = LC.el('tr', { 'data-success-bag-id': line.bag_id });
        tr.appendChild(LC.el('td', { class: 'lc-mono', text: showText(line.trace_code) }));
        tr.appendChild(LC.el('td', { text: qtyText(line.quantity) }));
        var outstandingCell = LC.el('td');
        outstandingCell.appendChild(LC.el('span', {
          class: 'lc-badge', 'data-tone': 'warn',
          text: qtyText(line.outstanding_quantity)
        }));
        tr.appendChild(outstandingCell);
        tr.appendChild(LC.el('td', { class: 'lc-mono', text: String(line.issue_line_id) }));
        var liveCell = LC.el('td', { 'data-success-live': String(line.bag_id), text: '读取中…' });
        tr.appendChild(liveCell);
        els.successRows.appendChild(tr);
      });

      LC.show(els.successPanel, true);

      // 成功后重新拉真实库存（不沿用提交前的缓存数字）
      lines.forEach(function (line) {
        LC.rpc('bag', { bag_id: line.bag_id }).then(function (bagData) {
          var bag = (bagData && bagData.bag) || null;
          var cell = root.querySelector('[data-success-live="' + line.bag_id + '"]');
          if (!bag) {
            if (cell) LC.setText(cell, '读取失败，请到「实物袋」查看');
            return;
          }
          state.found[bag.id] = bag;
          if (cell) {
            LC.setText(cell, qtyText(bag.quantity, bag.uom) +
              '（可用 ' + qtyText(bag.available_quantity, bag.uom) + '）');
          }
        }).catch(function () {
          var cell = root.querySelector('[data-success-live="' + line.bag_id + '"]');
          if (cell) LC.setText(cell, '实时库存读取失败，请刷新');
        });
      });

      // 明细已入账：清空草稿，避免同一批袋被重复提交
      state.cart = [];
      renderCart();

      LC.status.show({
        kind: 'success',
        message: '领用成功：单号 ' + showText(operation.name) + '，共 ' + lines.length + ' 条明细。',
        detail: res && res.replayed
          ? '该请求此前已处理过，本次未重复入账（replayed）。'
          : '每行都已生成领用明细 ID，归还时按该 ID 关联原领用行。'
      });
    }

    /* ---------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action]', 'click', function (event, element) {
      var action = element.getAttribute('data-lc-action');
      if (action === 'resolve') {
        event.preventDefault();
        resolveRaw(els.scan ? els.scan.value : '');
      } else if (action === 'refresh-live') {
        event.preventDefault();
        refreshLive();
      } else if (action === 'scan-clear') {
        event.preventDefault();
        LC.clear(els.scanRows);
        LC.show(els.scanPanel, false);
        if (els.scan) els.scan.value = '';
      } else if (action === 'scan-focus') {
        event.preventDefault();
        if (els.scan) els.scan.focus();
      } else if (action === 'add-bag') {
        event.preventDefault();
        if (state.lock) {
          LC.status.show({
            kind: 'unknown',
            message: '未决提交未处理：暂不能修改领用明细。',
            detail: '请先重试同一份内容，或核对流水后解除未决锁。'
          });
          return;
        }
        addBag(LC.parse.int(element.getAttribute('data-bag-id'), null));
      } else if (action === 'remove-bag') {
        event.preventDefault();
        if (state.lock) return;
        var bagId = LC.parse.int(element.getAttribute('data-bag-id'), null);
        state.cart = state.cart.filter(function (line) { return line.bag_id !== bagId; });
        renderCart();
      } else if (action === 'pick-sn') {
        event.preventDefault();
        resolveRaw(element.getAttribute('data-sn'));
      } else if (action === 'retry-unknown') {
        event.preventDefault();
        retryUnknown();
      } else if (action === 'verify-absent') {
        event.preventDefault();
        verifyResolve('absent');
      } else if (action === 'verify-present') {
        event.preventDefault();
        verifyResolve('present');
      } else if (action === 'reset-cart') {
        event.preventDefault();
        if (state.lock) return;
        if (!state.cart.length) return;
        if (!LC.confirmAction('清空领用明细？尚未提交，不会影响库存。')) return;
        state.cart = [];
        renderCart();
        LC.status.show({ kind: 'empty', message: '已清空领用明细。' });
      }
    });

    LC.on(root, '[data-lc-scan]', 'keydown', function (event, element) {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      resolveRaw(element.value);
    });

    LC.on(root, '[data-lc-cart-qty]', 'change', function (event, element) {
      updateQty(LC.parse.int(element.getAttribute('data-bag-id'), null), element.value);
    });

    if (els.form) {
      LC.guard(els.form, function (values, done) {
        if (state.lock) {
          // 未决未解除：绝不能用改动后的输入生成新 key 重发
          LC.status.show({
            kind: 'unknown',
            message: '上一次提交结果未知，尚未确认入账与否。',
            detail: '本页已锁定提交。请用「用同一请求重试（同一份内容）」，' +
              '或核对「领用记录」后按已核对结果解除未决锁。'
          });
          done();
          return;
        }
        if (!canIssue) {
          LC.status.show({
            kind: 'denied',
            message: '当前账号没有领用权限（can_issue），请让库存管理员开通。'
          });
          done();
          return;
        }
        var params = buildParams(values);
        var problem = validate(params);
        if (problem) {
          LC.clearFormErrors(els.form);
          if (problem.field === 'lines') {
            LC.status.show({ kind: 'error', code: 'VALIDATION_ERROR', message: problem.message });
          } else {
            LC.formError(els.form, problem.field, problem.message);
          }
          done();
          return;
        }
        LC.clearFormErrors(els.form);
        var button = els.form.querySelector('button[type="submit"]');
        submitAttempt({
          scope: ISSUE_SCOPE,
          endpoint: ISSUE_ENDPOINT,
          params: params,
          button: button
        }).then(function () {
          done();
        }).catch(function (error) {
          done(error && !error.unknown ? error : null);
        });
      });
    }

    /* ---------------------------------------------------------------- 初始化 */
    function init() {
      if (els.issuesLink) {
        els.issuesLink.setAttribute('href', LC.base + '/lab/issues');
      }
      if (!canIssue) {
        LC.show(els.readonlyPanel, true);
        LC.show(els.formPanel, false);
        LC.show(els.cartPanel, false);
        LC.status.show({
          kind: 'denied',
          message: '当前账号只读：没有领用权限（can_issue）。可以扫码查看，但不能提交领用。'
        });
      }
      renderCart();
      loadBootstrap();
      // 先恢复未决提示（跨刷新）：只提示 + 锁定，绝不自动重发
      restorePending();
      // 领用人列表失败时仍要有 uid：否则"只能为自己领用"的兜底无从判断
      LC.session().then(function (session) {
        if (!state.uid && session && session.uid) state.uid = session.uid;
      }).catch(function () {
        // 会话读取失败由 core 在状态区提示；这里不重复报错
      });
      prefill();
    }

    function prefill() {
      var bagPrefill = els.toolbar ? els.toolbar.getAttribute('data-lc-prefill-bag') : '';
      var itemPrefill = els.toolbar ? els.toolbar.getAttribute('data-lc-prefill-item') : '';
      if (bagPrefill) {
        var bagId = LC.parse.int(bagPrefill, null);
        if (bagId) {
          LC.show(els.scanPanel, true);
          LC.show(els.scanEmpty, true);
          LC.setText(els.scanEmpty, '正在读取袋…');
          LC.rpc('bag', { bag_id: bagId }).then(function (data) {
            LC.show(els.scanEmpty, false);
            var bag = (data && data.bag) || null;
            if (!bag) return;
            state.found[bag.id] = bag;
            LC.clear(els.scanRows);
            els.scanRows.appendChild(bagResultCard(bag, '来自链接的袋'));
          }).catch(function (error) {
            LC.show(els.scanEmpty, false);
            statusError(error, null);
          });
        }
        return;
      }
      if (itemPrefill) {
        resolveRaw(itemPrefill);
      }
    }

    init();
  });
})();
