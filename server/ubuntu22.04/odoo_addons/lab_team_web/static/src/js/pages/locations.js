/* ==========================================================================
 * lab_team_web · P3 库位页（page_id=locations，/lab/locations）
 * --------------------------------------------------------------------------
 * 契约来源：local/build/p3-web-20261028/{frontend-contract,backend-contract}.md
 *
 * 只用 window.LC 公共 core：LC.rpc 读、LC.submit 写、LC.guard 管表单、
 * LC.el/textContent 渲染。没有 fetch、没有 innerHTML、没有内联事件、
 * 没有本地台账/模拟库存：所有数量都是服务端 locations?with_stats=1 的投影。
 *
 * 端点（LC.endpoints）
 *   locations       读   /lab/api/inventory/locations  {with_stats:true}
 *   locationCreate  写   /lab/api/inventory/location_create   {name,parent_id?}
 *   locationUpdate  写   /lab/api/inventory/location_update   {location_id,name|active,note,...}
 *
 * 权限：读需要 lab 角色（页面级已由服务端挡）；写仅 can_manage_locations。
 * 本页没有"改数量/删库存/删库位记录"的入口（后端也不提供）。
 * ========================================================================== */
(function () {
  'use strict';

  var LC = window.LC;
  if (!LC) return;

  LC.register('locations', function (ctx) {
    var root = ctx.root;
    var manager = LC.has('can_manage_locations');

    var nodes = {
      rows: LC.qs('[data-lc-rows="locations"]', root),
      count: LC.qs('[data-lc-count="locations"]', root),
      empty: LC.qs('[data-lc-empty="locations"]', root),
      loading: LC.qs('[data-lc-loading="locations"]', root),
      filter: LC.qs('[data-lc-inv-filter="locations"]', root),
      createPanel: LC.qs('[data-lc-inv-create-panel="locations"]', root),
      editPanel: LC.qs('[data-lc-inv-edit-panel="locations"]', root),
      editBadge: LC.qs('[data-lc-inv-edit-target]', root),
      editStats: LC.qs('[data-lc-inv-edit-stats]', root),
      movePanel: LC.qs('[data-lc-inv-move-panel="locations"]', root),
      movePath: LC.qs('[data-lc-inv-move-path]', root),
      parentSelect: LC.qs('#lc-inv-loc-parent', root),
      locks: LC.qs('[data-lc-inv-locks="locations"]', root),
      lockRows: LC.qs('[data-lc-rows="locks"]', root)
    };
    var createForm = LC.qs('[data-lc-form="location-create"]', root);
    var editForm = LC.qs('[data-lc-form="location-edit"]', root);
    var moveForm = LC.qs('[data-lc-form="location-move"]', root);
    var moveParent = LC.qs('#lc-inv-move-parent', root);

    var treeRows = [];
    var expanded = new Map();
    var revealId = null;
    var moveTarget = null;
    var hierarchyAvailable = false;
    var all = [];          // 服务端最近一次返回的库位
    var byId = {};         // id -> 库位（行按钮用）
    var editTarget = null; // 当前编辑中的库位
    var loadSeq = 0;
    var pendingLocks = {}; // lockKey -> {spec, pending}（core v1.2 未决恢复）

    /* ------------------------------------------------- 未决提交（core v1.2）
     * 一次"结果未知"的提交会被 core 按 (user,company,scope,endpoint) 锁住：
     *   * 加载时用 LC.pendingAttempt 恢复横幅（**不自动重发**）；
     *   * 只能"用原内容重试"（LC.submit 复用原 request_key，跨刷新成立）；
     *   * 或由人核对真实库位列表后 LC.resolveUnknown({confirmed,verification}) 显式解除。
     * 绝不允许"清一下锁"就换新 key 重发（那是新业务操作）。
     */
    var SPEC_CREATE = { key: 'create', scope: 'locations/create',
                        endpoint: 'locationCreate', label: '新建库位' };

    function specRename(id) {
      return { key: 'rename:' + id, scope: 'locations/rename/' + id,
               endpoint: 'locationUpdate', label: '库位改名 #' + id };
    }

    function specDeactivate(id) {
      return { key: 'deactivate:' + id, scope: 'locations/deactivate/' + id,
               endpoint: 'locationUpdate', label: '停用库位 #' + id };
    }

    function specMove(id) {
      return { key: 'move:' + id, scope: 'locations/move/' + id,
               endpoint: 'locationUpdate', label: '更改上级 #' + id };
    }

    function lockSpecs() {
      var specs = [SPEC_CREATE];
      all.forEach(function (loc) {
        specs.push(specRename(loc.id));
        specs.push(specDeactivate(loc.id));
        specs.push(specMove(loc.id));
      });
      return specs;
    }

    function readPending(spec) {
      if (typeof LC.pendingAttempt !== 'function') return null;
      try {
        return LC.pendingAttempt(spec.scope, spec.endpoint) || null;
      } catch (error) {
        return null;
      }
    }

    function isPendingConflict(err) {
      return !!(err && err.code === 'CONFLICT' && err.fields &&
                err.fields.submit === 'pending_unknown');
    }

    function payloadSummary(payload) {
      var data = payload || {};
      if (!data || !Object.keys(data).length) return '浏览器未保存明细';
      if (data.active === false) return '停用库位 #' + data.location_id;
      if (data.update_parent) {
        return '库位 #' + data.location_id + ' → ' + (data.parent_id ? '上级 #' + data.parent_id : '根级');
      }
      if (data.name) {
        return '名称「' + data.name + '」' + (data.parent_id ? '，上级 #' + data.parent_id : '，根级');
      }
      if (data.location_id) return '库位 #' + data.location_id;
      return '原提交内容已保留';
    }

    function lockBlock(spec, pending) {
      var tail = String(pending.key || '').slice(-6);
      var ageSec = Math.max(0, Math.round((pending.ageMs || 0) / 1000));
      return LC.el('li', { class: 'lc-inv-lock-item', 'data-lc-inv-lock-item': spec.key }, [
        LC.el('p', { class: 'lc-inv-lock-title' }, [
          LC.el('span', { text: spec.label }),
          LC.el('span', { class: 'lc-mono lc-hint', 'data-lc-inv-lock-key': spec.key,
                          text: ' 请求号 …' + tail })
        ]),
        LC.el('p', { class: 'lc-hint',
                     text: ageSec + ' 秒前提交 · 原内容：' + payloadSummary(pending.payload) }),
        LC.el('div', { class: 'lc-actions' }, [
          LC.el('button', {
            class: 'lc-btn lc-btn-outline lc-inv-btn-sm', type: 'button',
            'data-lc-action': 'locks-retry', 'data-lc-inv-lock-key': spec.key,
            'data-lc-inv-lock-retry': spec.key, text: '用原内容重试'
          }),
          LC.el('button', {
            class: 'lc-btn lc-btn-danger lc-inv-btn-sm', type: 'button',
            'data-lc-action': 'locks-resolve', 'data-lc-inv-lock-key': spec.key,
            'data-lc-inv-lock-resolve-absent': spec.key, text: '已核对：上次未生效'
          }),
          LC.el('button', {
            class: 'lc-btn lc-btn-ghost lc-inv-btn-sm', type: 'button',
            'data-lc-action': 'locks-resolve', 'data-lc-inv-lock-key': spec.key,
            'data-lc-inv-lock-resolve-present': spec.key, text: '已核对：上次已生效'
          })
        ])
      ]);
    }

    function refreshLocks() {
      pendingLocks = {};
      var items = [];
      lockSpecs().forEach(function (spec) {
        var pending = readPending(spec);
        if (!pending) return;
        pendingLocks[spec.key] = { spec: spec, pending: pending };
        items.push(pendingLocks[spec.key]);
      });
      if (nodes.lockRows) {
        LC.clear(nodes.lockRows);
        items.forEach(function (item) {
          nodes.lockRows.appendChild(lockBlock(item.spec, item.pending));
        });
      }
      LC.show(nodes.locks, items.length > 0);
      if (createForm) {
        var button = createForm.querySelector('button[type="submit"]');
        if (button) button.disabled = !!pendingLocks.create;
      }
      return items.length;
    }

    function retryLock(spec, pending, button) {
      if (!pending || !pending.payload) {
        LC.status.show({
          kind: 'error',
          message: '浏览器没有保存原提交内容（sessionStorage 不可用），无法安全重试；请核对列表后显式解除。'
        });
        return;
      }
      LC.submit({
        scope: spec.scope, endpoint: spec.endpoint,
        params: pending.payload, button: button, busyLabel: '重试中…'
      }).then(function (res) {
        refreshLocks();
        var loc = (res && res.data && res.data.location) || null;
        if (loc) revealId = loc.id;
        if (moveTarget && spec.key === 'move:' + moveTarget.id) closeMove();
        LC.status.show({
          kind: 'success',
          message: '未决提交已确认生效' + (loc ? '：' + (loc.path || loc.name || '') : '') +
            (res.replayed ? '（系统判定为重复提交，未重复执行）' : '')
        });
        load();
      }).catch(function (err) {
        if (err && (err.unknown || isPendingConflict(err))) {
          refreshLocks();
          LC.status.show({
            kind: 'unknown', code: err.code,
            message: '仍未确认结果：未决记录保留，请继续用原内容重试，或核对后显式解除。'
          });
          return;
        }
        refreshLocks();
        LC.status.show({ kind: 'error', code: err && err.code, message: LC.errorText(err) });
        load();
      });
    }

    function resolveLock(spec, verification, button) {
      var question = verification === 'absent'
        ? '请先刷新库位列表核对：确认上次「' + spec.label + '」没有生效，可以重新提交？'
        : '确认上次「' + spec.label + '」已经生效，不要再重复提交？';
      if (!LC.confirmAction(question)) return;
      LC.setBusy(button, true, '解除中…');
      LC.resolveUnknown(spec.scope, spec.endpoint, {
        confirmed: true, verification: verification
      }).then(function (result) {
        LC.setBusy(button, false);
        refreshLocks();
        LC.status.show({
          kind: 'success',
          message: (verification === 'absent'
            ? '已解除未决提交（确认上次未生效）。重新提交会使用新的请求号。'
            : '已解除未决提交（确认上次已生效）。请不要重复提交，列表已刷新供核对。') +
            (result && result.cleared ? '' : '（本地没有未决记录，已清理）')
        });
        load();
      }).catch(function (err) {
        LC.setBusy(button, false);
        LC.status.show({ kind: 'error', code: err && err.code, message: LC.errorText(err) });
      });
    }

    function handleUnknownSubmit(err, spec) {
      refreshLocks();
      render();
      if (editTarget) showEdit(editTarget, true);   // 让编辑面板的按钮同步为禁用
      LC.status.show({
        kind: 'unknown',
        code: err && err.code,
        message: isPendingConflict(err)
          ? '上一次「' + spec.label + '」结果未知：不能修改内容后再次提交。'
          : '「' + spec.label + '」结果未知（网络中断或超时）：本页不会自动重发。',
        detail: '请在上方未决区点「用原内容重试」，或核对库位列表后点「已核对：上次未生效 / 已生效」显式解除。',
        retry: function () { refreshLocks(); }
      });
    }

    /* -------------------------------------------------------------- 渲染 */
    function numCell(value) {
      return LC.el('td', { class: 'lc-inv-num', text: LC.fmt.quantity(value) });
    }

    function actionsCell(loc) {
      var renameLocked = !!pendingLocks['rename:' + loc.id];
      var deactivateLocked = !!pendingLocks['deactivate:' + loc.id];
      var rename = LC.el('button', {
        class: 'lc-btn lc-btn-outline lc-inv-btn-sm',
        type: 'button',
        'data-lc-action': 'locations-edit',
        'data-lc-inv-loc-id': String(loc.id),
        title: renameLocked ? '该库位有未决提交，请先在上方未决区解除' : '',
        disabled: renameLocked,
        text: '改名'
      });
      var deactivate = LC.el('button', {
        class: 'lc-btn lc-btn-danger lc-inv-btn-sm',
        type: 'button',
        'data-lc-action': 'locations-deactivate',
        'data-lc-inv-loc-id': String(loc.id),
        title: deactivateLocked ? '该库位有未决提交，请先在上方未决区解除' : '',
        disabled: deactivateLocked,
        text: '停用'
      });
      var buttons = [rename];
      if (hierarchyAvailable && moveForm) {
        buttons.push(LC.el('button', {
          class: 'lc-btn lc-btn-outline lc-inv-btn-sm', type: 'button',
          'data-lc-action': 'locations-move', 'data-lc-inv-loc-id': String(loc.id),
          disabled: !!pendingLocks['move:' + loc.id], text: '更改上级'
        }));
      }
      buttons.push(deactivate);
      return LC.el('td', {}, [LC.el('div', { class: 'lc-inv-actions' }, buttons)]);
    }

    /* 窄屏卡片化：把表头文案复制到每个单元格的 data-label，
     * CSS 在 ≤760px 用 ::before 显示（操作按钮不用横向滚动找）。 */
    function labelCells() {
      var table = root.querySelector('[data-lc-table="locations"]');
      if (!table) return;
      var heads = table.querySelectorAll('thead th');
      var labels = [];
      for (var i = 0; i < heads.length; i += 1) {
        labels.push(String(heads[i].textContent || '').trim());
      }
      var rows = table.querySelectorAll('tbody tr');
      for (var r = 0; r < rows.length; r += 1) {
        var cells = rows[r].children;
        for (var c = 0; c < cells.length; c += 1) {
          if (labels[c] && !cells[c].getAttribute('data-label')) {
            cells[c].setAttribute('data-label', labels[c]);
          }
        }
      }
    }

    function ancestorsOf(loc) {
      var parents = [];
      var seen = new Set([loc.id]);
      for (var parent = byId[loc.parent_id]; parent && !seen.has(parent.id); parent = byId[parent.parent_id]) {
        seen.add(parent.id);
        parents.push(parent);
      }
      return parents;
    }

    function rebuildTree(data) {
      all = data.locations || [];
      hierarchyAvailable = Array.isArray(data.ancestors);
      var entries = (data.ancestors || []).concat(all);
      byId = Object.create(null);
      entries.forEach(function (loc) { byId[loc.id] = loc; });
      var children = new Map();
      entries.forEach(function (loc) {
        var parent = byId[loc.parent_id];
        var key = parent ? parent.id : null;
        if (!children.has(key)) children.set(key, []);
        children.get(key).push(loc);
      });
      treeRows = [];
      function appendChildren(parentId, depth) {
        (children.get(parentId) || []).sort(function (a, b) {
          return String(a.name).localeCompare(String(b.name), 'zh-CN', { numeric: true });
        }).forEach(function (loc) {
          var hasChildren = children.has(loc.id);
          treeRows.push({ loc: loc, depth: depth, hasChildren: hasChildren });
          if (hasChildren) {
            if (!expanded.has(loc.id)) expanded.set(loc.id, depth < 2);
            appendChildren(loc.id, depth + 1);
          }
        });
      }
      appendChildren(null, 0);
      var reveal = byId[revealId];
      if (reveal) {
        ancestorsOf(reveal).forEach(function (parent) { expanded.set(parent.id, true); });
        if (nodes.filter && !matches(reveal, nodes.filter.value.trim().toLowerCase())) nodes.filter.value = '';
      }
      revealId = null;
    }

    function row(entry, searching) {
      var loc = entry.loc;
      var isView = loc.usage === 'view';
      var open = expanded.get(loc.id);
      var caption = LC.el('span', { text: hierarchyAvailable ? loc.name : (loc.path || loc.name), title: loc.path });
      var label = entry.hasChildren && !searching
        ? LC.el('button', {
            class: 'lc-inv-tree-toggle', type: 'button',
            'data-lc-action': 'locations-toggle-branch', 'data-lc-inv-loc-id': String(loc.id),
            'aria-expanded': open ? 'true' : 'false', title: loc.path
          }, [LC.el('span', { 'aria-hidden': 'true', text: open ? '▾' : '▸' }), caption])
        : LC.el('span', { class: 'lc-inv-tree-leaf' }, caption);
      var node = LC.el('div', { class: 'lc-inv-tree-node' }, label);
      node.style.setProperty('--lc-inv-depth', String(Math.min(entry.depth, 8)));
      var cells = [
        LC.el('td', {}, [LC.el('span', { class: 'lc-mono', text: isView ? '—' : loc.code || '—' })]),
        LC.el('td', { class: 'lc-inv-tree-cell' }, node),
        isView ? LC.el('td', { class: 'lc-inv-num', text: '—' }) : numCell(loc.bag_count),
        isView ? LC.el('td', { class: 'lc-inv-num', text: '—' }) : numCell(loc.bag_quantity),
        isView ? LC.el('td', { class: 'lc-inv-num', text: '—' }) : numCell(loc.quantity)
      ];
      if (manager) cells.push(isView ? LC.el('td') : actionsCell(loc));
      return LC.el('tr', { 'data-lc-inv-loc': String(loc.id), 'data-lc-inv-depth': String(entry.depth),
        class: isView ? 'lc-inv-view-location' : '' }, cells);
    }

    function matches(loc, needle) {
      if (!needle) return true;
      var haystack = String((loc.code || '') + ' ' + (loc.path || '') + ' ' + (loc.name || '')).toLowerCase();
      return haystack.indexOf(needle) !== -1;
    }

    function render() {
      var needle = nodes.filter ? nodes.filter.value.trim().toLowerCase() : '';
      var visible = new Set();
      var matched = 0;
      if (needle) {
        treeRows.forEach(function (entry) {
          if (!matches(entry.loc, needle)) return;
          if (entry.loc.usage !== 'view') matched += 1;
          visible.add(entry.loc.id);
          ancestorsOf(entry.loc).forEach(function (parent) { visible.add(parent.id); });
        });
      }
      var rows = treeRows.filter(function (entry) {
        return needle ? visible.has(entry.loc.id) : ancestorsOf(entry.loc).every(function (parent) {
          return expanded.get(parent.id);
        });
      });
      LC.renderRows(nodes.rows, rows, function (entry) { return row(entry, !!needle); });
      labelCells();
      LC.setText(nodes.count, String(needle ? matched : all.length));
      LC.setText(nodes.empty, needle
        ? '没有匹配的库位。清空搜索可查看全部库位。'
        : '当前公司还没有内部库位。');
      LC.show(nodes.empty, rows.length === 0);
    }

    function fillParentSelect(select, target) {
      var previous = select.value;
      LC.clear(select);
      if (target) select.appendChild(LC.el('option', { value: '', text: '选择新上级' }));
      if (!target || target.parent_id) {
        select.appendChild(LC.el('option', { value: target ? '0' : '', text: '（根级，无上级）' }));
      }
      treeRows.forEach(function (entry) {
        var loc = entry.loc;
        if (target && (loc.id === target.id || loc.id === target.parent_id ||
            ancestorsOf(loc).some(function (parent) { return parent.id === target.id; }))) return;
        select.appendChild(LC.el('option', {
          value: String(loc.id), text: (loc.code ? '[' + loc.code + '] ' : '') + (loc.path || loc.name)
        }));
      });
      select.value = Array.from(select.options).some(function (option) { return option.value === previous; })
        ? previous : '';
    }

    /* -------------------------------------------------------------- 读取 */
    function load(button) {
      loadSeq += 1;
      var seq = loadSeq;
      LC.show(nodes.loading, true);
      LC.show(nodes.empty, false);
      LC.setBusy(button, true, '刷新中…');
      return LC.rpc('locations', { with_stats: true, with_tree: true }).then(function (data) {
        if (seq !== loadSeq) return;
        rebuildTree(data || {});
        refreshLocks();
        render();
        if (nodes.parentSelect) fillParentSelect(nodes.parentSelect);
        if (moveTarget) {
          var updated = byId[moveTarget.id];
          if (updated) showMove(updated, true);
          else closeMove();
        }
        LC.show(nodes.loading, false);
        LC.setBusy(button, false);
        if (editTarget && byId[String(editTarget.id)]) {
          editTarget = byId[String(editTarget.id)];
          showEdit(editTarget, true);
        }
      }).catch(function (err) {
        if (seq !== loadSeq) return;
        LC.show(nodes.loading, false);
        LC.setBusy(button, false);
        LC.status.show({
          kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
          code: err.code,
          message: LC.errorText(err),
          detail: err.unknown ? '列表结果未知，可直接重试刷新。' : '',
          retry: err.unknown ? function () { load(button); } : null
        });
      });
    }

    /* ------------------------------------------------------------ 新建库位 */
    function submitCreate(values, button) {
      var params = { name: String(values.name || '').trim() };
      if (values.parent_id) params.parent_id = LC.parse.int(values.parent_id, null);
      return LC.submit({
        scope: 'locations/create',
        endpoint: 'locationCreate',
        params: params,
        button: button,
        busyLabel: '创建中…'
      });
    }

    function handleCreateError(err, values, button) {
      if (err.unknown || isPendingConflict(err)) {
        handleUnknownSubmit(err, SPEC_CREATE);
        return;
      }
      if (err.code === 'FORBIDDEN') {
        LC.status.show({ kind: 'denied', code: err.code, message: LC.errorText(err) });
        return;
      }
      LC.status.show({
        kind: 'error',
        code: err.code,
        message: LC.errorText(err),
        detail: err.code === 'INTERNAL_ERROR' && err.fields && err.fields.error_id
          ? '请把错误编号 ' + err.fields.error_id + ' 提供给管理员。' : '',
        retry: err.code === 'CONFLICT' ? function () { load(); } : null
      });
      showFieldErrors(createForm, err);
    }

    function onCreated(res) {
      var loc = (res && res.data && res.data.location) || null;
      LC.status.show({
        kind: 'success',
        message: loc
          ? '已创建库位 ' + (loc.code ? '[' + loc.code + '] ' : '') + (loc.path || loc.name || '')
          : '库位已创建。'
      });
      if (loc) revealId = loc.id;
      if (createForm) {
        LC.setFieldValue(createForm, 'name', '');
        LC.setFieldValue(createForm, 'parent_id', '');
        LC.clearFormErrors(createForm);
      }
      LC.show(nodes.createPanel, false);
      refreshLocks();
      load();
    }

    function showFieldErrors(form, err) {
      if (!form || !err || err.unknown) return;
      LC.fieldMessages(err).forEach(function (item) {
        if (item.field === 'name' || item.field === 'parent_id') {
          LC.formError(form, item.field, item.message);
        }
      });
    }

    function showMove(loc, keepSelection) {
      if (!manager || !moveForm || !hierarchyAvailable || loc.usage === 'view') return;
      moveTarget = loc;
      if (!keepSelection) moveParent.value = '';
      fillParentSelect(moveParent, loc);
      LC.setText(nodes.movePath, loc.path || loc.name);
      moveForm.querySelector('button[type="submit"]').disabled = !!pendingLocks['move:' + loc.id];
      LC.show(nodes.movePanel, true);
      if (!keepSelection) moveParent.focus();
    }

    function closeMove() {
      moveTarget = null;
      LC.show(nodes.movePanel, false);
      LC.clearFormErrors(moveForm);
    }

    /* -------------------------------------------------------- 改名 / 停用 */
    function showEdit(loc, keepPanel) {
      editTarget = loc;
      if (!nodes.editPanel || !editForm) return;
      LC.setFieldValue(editForm, 'location_id', loc.id);
      if (!keepPanel) LC.setFieldValue(editForm, 'name', loc.name || '');
      LC.setText(nodes.editBadge, (loc.code ? '[' + loc.code + '] ' : '') + (loc.path || loc.name || ''));
      LC.setText(nodes.editStats,
        '当前库位有 ' + LC.fmt.quantity(loc.bag_count) + ' 袋 / 数量 ' +
        LC.fmt.quantity(loc.quantity) + '（袋内数量 ' + LC.fmt.quantity(loc.bag_quantity) + '）');
      LC.show(nodes.editPanel, true);
      // 该对象有未决提交时，禁用对应动作（解除入口在上方未决区）
      var renameLocked = !!pendingLocks['rename:' + loc.id];
      var deactivateLocked = !!pendingLocks['deactivate:' + loc.id];
      var submitBtn = editForm.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = renameLocked;
        submitBtn.title = renameLocked ? '该库位改名有未决提交，请先在未决区解除' : '';
      }
      var deactivateBtn = LC.qs('[data-lc-action="locations-deactivate"]', nodes.editPanel);
      if (deactivateBtn) {
        deactivateBtn.disabled = deactivateLocked;
        deactivateBtn.title = deactivateLocked ? '该库位停用有未决提交，请先在未决区解除' : '';
      }
      if (!keepPanel && editForm.elements && editForm.elements.name) editForm.elements.name.focus();
    }

    function closeEdit() {
      editTarget = null;
      LC.show(nodes.editPanel, false);
      if (editForm) LC.clearFormErrors(editForm);
    }

    function submitRename(values, button) {
      return LC.submit({
        scope: 'locations/rename/' + String(values.location_id || ''),
        endpoint: 'locationUpdate',
        params: {
          location_id: LC.parse.int(values.location_id, null),
          name: String(values.name || '').trim()
        },
        button: button,
        busyLabel: '保存中…'
      });
    }

    function handleRenameDone(res, button, values) {
      var loc = (res && res.data && res.data.location) || null;
      LC.status.show({
        kind: 'success',
        message: loc ? '已改名为 ' + (loc.path || loc.name || '') : '改名已保存。'
      });
      closeEdit();
      refreshLocks();
      load(button);
    }

    function handleRenameError(err, values, button) {
      if (err.unknown || isPendingConflict(err)) {
        handleUnknownSubmit(err, specRename(LC.parse.int(values.location_id, 0)));
        return;
      }
      LC.status.show({
        kind: 'error',
        code: err.code,
        message: err.code === 'PRECONDITION_FAILED' ? (err.message || LC.errorText(err)) : LC.errorText(err),
        retry: err.code === 'CONFLICT' ? function () { load(); } : null
      });
      showFieldErrors(editForm, err);
    }

    function submitDeactivate(loc, button) {
      return LC.submit({
        scope: 'locations/deactivate/' + String(loc.id),
        endpoint: 'locationUpdate',
        params: { location_id: LC.parse.int(loc.id, null), active: false },
        button: button,
        busyLabel: '停用中…'
      });
    }

    function handleDeactivateError(err, loc, button) {
      if (err.unknown || isPendingConflict(err)) {
        handleUnknownSubmit(err, specDeactivate(loc.id));
        return;
      }
      if (err.code === 'PRECONDITION_FAILED') {
        // 服务端 fields 只有 {location: reason}，数量在 message 里（bag_count/quantity）
        var reason = (err.fields && err.fields.location) || '';
        var detail = '';
        if (reason === 'has_stock') {
          detail = '该库位（含子库位）仍有实物袋或库存；请先把袋搬到其他库位或调拨后再停用。';
        } else if (reason === 'is_root') {
          detail = '根库位不能停用。';
        } else if (reason === 'not_internal') {
          detail = '只有内部库位可以修改；视图/客户位/损失位不允许改。';
        }
        LC.status.show({
          kind: 'error',
          code: err.code,
          message: err.message || LC.errorText(err),
          detail: detail,
          retry: function () { load(); }
        });
        return;
      }
      LC.status.show({
        kind: 'error',
        code: err.code,
        message: LC.errorText(err),
        retry: err.code === 'CONFLICT' ? function () { load(); } : null
      });
    }

    function onDeactivated(res, loc) {
      var data = (res && res.data) || {};
      LC.status.show({
        kind: 'success',
        message: '已停用库位 ' + ((data.location && (data.location.path || data.location.name)) ||
          (loc && (loc.path || loc.name)) || '')
      });
      closeEdit();
      refreshLocks();
      load();
    }

    /* -------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action="locks-retry"]', 'click', function (ev, btn) {
      var item = pendingLocks[btn.getAttribute('data-lc-inv-lock-key')];
      if (!item) {
        refreshLocks();
        LC.status.show({ kind: 'error', message: '未决记录已不存在（可能已过期），请刷新页面后核对列表。' });
        return;
      }
      LC.status.clear();
      retryLock(item.spec, item.pending, btn);
    });

    LC.on(root, '[data-lc-action="locks-resolve"]', 'click', function (ev, btn) {
      var item = pendingLocks[btn.getAttribute('data-lc-inv-lock-key')];
      if (!item) {
        refreshLocks();
        LC.status.show({ kind: 'error', message: '未决记录已不存在（可能已过期），请刷新页面后核对列表。' });
        return;
      }
      var verification = btn.hasAttribute('data-lc-inv-lock-resolve-absent') ? 'absent' : 'present';
      LC.status.clear();
      resolveLock(item.spec, verification, btn);
    });

    LC.on(root, '[data-lc-action="locations-reload"]', 'click', function (ev, btn) {
      LC.status.clear();
      load(btn);
    });

    LC.on(root, '[data-lc-action="locations-toggle-create"]', 'click', function () {
      if (!manager) {
        LC.status.show({ kind: 'denied', code: 'FORBIDDEN',
                         message: '当前账号没有库位管理权限。' });
        return;
      }
      var visible = nodes.createPanel && !nodes.createPanel.hasAttribute('hidden');
      LC.show(nodes.createPanel, !visible);
      if (!visible && createForm && createForm.elements && createForm.elements.name) {
        createForm.elements.name.focus();
      }
    });

    LC.on(root, '[data-lc-action="locations-cancel-create"]', 'click', function () {
      LC.show(nodes.createPanel, false);
      if (createForm) LC.clearFormErrors(createForm);
    });

    LC.on(root, '[data-lc-action="locations-toggle-branch"]', 'click', function (ev, button) {
      var loc = byId[button.getAttribute('data-lc-inv-loc-id')];
      if (!loc) return;
      expanded.set(loc.id, !expanded.get(loc.id));
      render();
      var toggle = LC.qs('[data-lc-action="locations-toggle-branch"][data-lc-inv-loc-id="' + loc.id + '"]', root);
      if (toggle) toggle.focus();
    });

    LC.on(root, '[data-lc-action="locations-move"]', 'click', function (ev, button) {
      var loc = byId[button.getAttribute('data-lc-inv-loc-id')];
      if (!loc) return;
      LC.status.clear();
      showMove(loc, false);
      nodes.movePanel.scrollIntoView({ block: 'nearest' });
    });

    LC.on(root, '[data-lc-action="locations-cancel-move"]', 'click', closeMove);

    LC.on(root, '[data-lc-action="locations-edit"]', 'click', function (ev, btn) {
      var loc = byId[String(btn.getAttribute('data-lc-inv-loc-id'))];
      if (!loc) return;
      LC.status.clear();
      showEdit(loc, false);
    });

    LC.on(root, '[data-lc-action="locations-close-edit"]', 'click', function () {
      closeEdit();
    });

    LC.on(root, '[data-lc-action="locations-deactivate"]', 'click', function (ev, btn) {
      var id = btn.getAttribute('data-lc-inv-loc-id') ||
        (editForm ? editForm.elements.location_id.value : '');
      var loc = byId[String(id)] || editTarget;
      if (!loc) return;
      var label = (loc.code ? '[' + loc.code + '] ' : '') + (loc.path || loc.name || '');
      var busy = '该库位（含子库位）当前有 ' + LC.fmt.quantity(loc.bag_count) + ' 袋 / 数量 ' +
        LC.fmt.quantity(loc.quantity) + '；有库存时停用会被系统拒绝。';
      if (!LC.confirmAction('停用库位 ' + label + '？\n' + busy + '\n停用后不再出现在列表里。')) return;
      LC.status.clear();
      submitDeactivate(loc, btn).then(function (res) {
        onDeactivated(res, loc);
      }).catch(function (err) {
        handleDeactivateError(err, loc, btn);
      });
    });

    if (nodes.filter) {
      nodes.filter.addEventListener('input', LC.debounce(function () { render(); }, 120));
    }

    if (createForm) {
      LC.guard(createForm, function (values, done) {
        var button = createForm.querySelector('button[type="submit"]');
        submitCreate(values, button).then(function (res) {
          done();
          onCreated(res);
        }).catch(function (err) {
          done(err);
          handleCreateError(err, values, button);
        });
      });
    }

    if (moveForm) {
      LC.guard(moveForm, function (values, done) {
        var loc = moveTarget;
        var parentId = LC.parse.int(values.parent_id, null);
        var parent = byId[parentId];
        if (!loc || !values.parent_id || (parentId !== 0 && !parent)) {
          LC.formError(moveForm, 'parent_id', '请选择一个新上级。');
          done();
          return;
        }
        var destination = parent ? parent.path || parent.name : '根级';
        if (!LC.confirmAction('将「' + (loc.path || loc.name) + '」移到「' + destination + '」下？')) {
          done();
          return;
        }
        var spec = specMove(loc.id);
        LC.submit({
          scope: spec.scope, endpoint: spec.endpoint,
          params: { location_id: loc.id, parent_id: parentId || false, update_parent: true },
          button: moveForm.querySelector('button[type="submit"]'), busyLabel: '移动中…'
        }).then(function (res) {
          var moved = res && res.data && res.data.location;
          done();
          closeMove();
          revealId = loc.id;
          LC.status.show({ kind: 'success', message: '已移动至 ' + (moved ? moved.path : destination) });
          load();
        }).catch(function (err) {
          done(err);
          if (err.unknown || isPendingConflict(err)) {
            handleUnknownSubmit(err, spec);
            showMove(loc, true);
            return;
          }
          LC.status.show({ kind: 'error', code: err.code, message: LC.errorText(err) });
          showFieldErrors(moveForm, err);
        });
      });
    }

    if (editForm) {
      LC.guard(editForm, function (values, done) {
        var button = editForm.querySelector('button[type="submit"]');
        if (!values.location_id) {
          done();
          LC.status.show({ kind: 'error', code: 'VALIDATION_ERROR',
                           message: '请先在上面的列表里选择要改名的库位。' });
          return;
        }
        submitRename(values, button).then(function (res) {
          done();
          handleRenameDone(res, button, values);
        }).catch(function (err) {
          done(err);
          handleRenameError(err, values, button);
        });
      });
    }

    // 先恢复"整类"未决（locations/create）：即使列表加载失败也能看到并解除
    refreshLocks();
    load();
  });
})();