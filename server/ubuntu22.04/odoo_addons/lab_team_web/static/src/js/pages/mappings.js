/* ==========================================================================
 * lab_team_web · P3 类别映射页（page_id=mappings，/lab/location-mappings）
 * --------------------------------------------------------------------------
 * 业务语义（backend-contract §3.4 / lead-decisions #4）：
 *   类别 → 库位映射**只参与"扫码上架"的库位推荐排序**（相同器件 → 类别映射 →
 *   同类器件），不写库存、不自动选库位。本页只维护这条配置记录。
 *
 * 端点
 *   mappingList    读  {category_id?, include_inactive?}
 *   mappingSet     写  upsert {category_id, location_id, priority?, note?, active?}
 *   mappingRemove  写  {mapping_id, hard?}  默认软停用，hard=true 才删配置记录
 *   locations      读  只用于"推荐库位"下拉（内部库位）
 *
 * 写操作全部走 LC.submit：结果未知时同一内容 + 同一请求键显式重试，
 * 不自动重试、不换键。没有删除库存/库位/流水的入口。
 * ========================================================================== */
(function () {
  'use strict';

  var LC = window.LC;
  if (!LC) return;

  LC.register('mappings', function (ctx) {
    var root = ctx.root;

    var nodes = {
      rows: LC.qs('[data-lc-rows="mappings"]', root),
      recoRows: LC.qs('[data-lc-rows="reco"]', root),
      recoEmpty: LC.qs('[data-lc-empty="reco"]', root),
      count: LC.qs('[data-lc-count="mappings"]', root),
      empty: LC.qs('[data-lc-empty="mappings"]', root),
      loading: LC.qs('[data-lc-loading="mappings"]', root),
      includeInactive: LC.qs('[data-lc-field="include_inactive"]', root),
      categoryPicks: LC.qs('[data-lc-inv-category-picks]', root),
      locationSelect: LC.qs('#lc-inv-map-location', root),
      locks: LC.qs('[data-lc-inv-locks="mappings"]', root),
      lockRows: LC.qs('[data-lc-rows="locks"]', root)
    };
    var form = LC.qs('[data-lc-form="mapping-set"]', root);
    var locationsLoaded = false;
    var mappings = [];
    var loadSeq = 0;
    // 用户是否动过"启用"开关；没动过就沿用该 (类别,库位) 已有映射的状态，
    // 避免"只想改优先级"却把已停用的映射悄悄启用（backend-contract §3.4）。
    var activeTouched = false;
    var pendingLocks = {};   // lockKey -> {spec, pending}（core v1.2 未决恢复）

    /* ------------------------------------------------- 未决提交（core v1.2）
     * core 按 (user,company,scope,endpoint) 锁住"结果未知"的提交；页面只做三件事：
     *   1. 加载时用 LC.pendingAttempt 恢复横幅（**不自动重发**）；
     *   2. "用原内容重试" → LC.submit 复用原 request_key；
     *   3. 人核对列表后 LC.resolveUnknown({confirmed,verification}) 显式解除。
     * 不允许"清一下就换新 key 重发"。
     */
    var SPEC_SET = { key: 'set', scope: 'mappings/set',
                     endpoint: 'mappingSet', label: '保存映射' };

    function specFor(action, id) {
      var label = action === 'disable' ? '停用映射 #' + id
        : action === 'enable' ? '启用映射 #' + id : '删除映射 #' + id;
      return {
        key: action + ':' + id,
        scope: 'mappings/' + action + '/' + id,
        endpoint: action === 'enable' ? 'mappingSet' : 'mappingRemove',
        label: label
      };
    }

    function lockSpecs() {
      var specs = [SPEC_SET];
      mappings.forEach(function (item) {
        specs.push(specFor('disable', item.id));
        specs.push(specFor('remove', item.id));
        specs.push(specFor('enable', item.id));
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
      if (data.mapping_id) return '映射 #' + data.mapping_id + (data.hard ? '（删除配置）' : '（停用）');
      return '类别 #' + data.category_id + ' → 库位 #' + data.location_id +
        '，优先级 ' + data.priority + '，' + (data.active ? '启用' : '停用') +
        (data.note ? '，备注「' + data.note + '」' : '');
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
      if (form) {
        var button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = !!pendingLocks.set;
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
        LC.status.show({ kind: 'success',
          message: '未决提交已确认生效（' + spec.label + '）' +
            (res && res.replayed ? '；服务端判定为重放，未重复执行' : '') });
        load();
      }).catch(function (err) {
        if (err && (err.unknown || isPendingConflict(err))) {
          refreshLocks();
          LC.status.show({ kind: 'unknown', code: err.code,
            message: '仍未确认结果：未决记录保留，请继续用原内容重试，或核对后显式解除。' });
          return;
        }
        refreshLocks();
        LC.status.show({ kind: 'error', code: err && err.code, message: LC.errorText(err) });
        load();
      });
    }

    function resolveLock(spec, verification, button) {
      var question = verification === 'absent'
        ? '请先刷新映射列表（勾选“显示已停用映射”）核对：确认上次「' + spec.label + '」没有生效，可以重新提交？'
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
      render();     // 行按钮/表单同步为禁用（未决期间不允许再发）
      LC.status.show({
        kind: 'unknown',
        code: err && err.code,
        message: isPendingConflict(err)
          ? '上一次「' + spec.label + '」结果未知：不能修改内容后再次提交。'
          : '「' + spec.label + '」结果未知（网络中断或超时）：本页不会自动重发。',
        detail: '请在上方未决区点「用原内容重试」，或核对映射列表（含已停用）后点「已核对：上次未生效 / 已生效」显式解除。',
        retry: function () { refreshLocks(); }
      });
    }

    /* -------------------------------------------------------------- 渲染 */
    function statusBadge(item) {
      return item.active
        ? LC.el('span', { class: 'lc-badge', 'data-tone': 'ok', text: '启用' })
        : LC.el('span', { class: 'lc-badge', text: '已停用' });
    }

    function actionsCell(item) {
      var toggleLocked = !!(pendingLocks['disable:' + item.id] || pendingLocks['enable:' + item.id]);
      var removeLocked = !!pendingLocks['remove:' + item.id];
      var toggle = item.active
        ? LC.el('button', {
            class: 'lc-btn lc-btn-outline lc-inv-btn-sm', type: 'button',
            'data-lc-action': 'mappings-disable',
            'data-lc-inv-mapping-id': String(item.id),
            title: toggleLocked ? '该映射有未决提交，请先在上方未决区解除' : '',
            disabled: toggleLocked, text: '停用'
          })
        : LC.el('button', {
            class: 'lc-btn lc-btn-outline lc-inv-btn-sm', type: 'button',
            'data-lc-action': 'mappings-enable',
            'data-lc-inv-mapping-id': String(item.id),
            title: toggleLocked ? '该映射有未决提交，请先在上方未决区解除' : '',
            disabled: toggleLocked, text: '启用'
          });
      var remove = LC.el('button', {
        class: 'lc-btn lc-btn-danger lc-inv-btn-sm', type: 'button',
        'data-lc-action': 'mappings-remove',
        'data-lc-inv-mapping-id': String(item.id),
        title: removeLocked ? '该映射有未决提交，请先在上方未决区解除' : '',
        disabled: removeLocked, text: '删除'
      });
      var children = [];
      if (toggle) children.push(toggle);
      children.push(remove);
      return LC.el('td', {}, [LC.el('div', { class: 'lc-inv-actions' }, children)]);
    }

    function row(item) {
      return LC.el('tr', {}, [
        LC.el('td', { text: item.category_path || ('类别 #' + item.category_id) }),
        LC.el('td', { text: item.location_path || ('库位 #' + item.location_id) }),
        LC.el('td', {}, [LC.el('span', { class: 'lc-mono', text: item.location_code || '—' })]),
        LC.el('td', { class: 'lc-inv-num', text: LC.fmt.quantity(item.priority) }),
        LC.el('td', {}, [statusBadge(item)]),
        LC.el('td', { text: item.note || '—' }),
        actionsCell(item)
      ]);
    }

    /** 推荐关系预览：按类别分组、priority 升序 = 入库页的推荐先后。 */
    function renderReco() {
      var groups = {};
      var order = [];
      mappings.filter(function (item) { return item.active; })
        .slice()
        .sort(function (a, b) {
          if (a.category_id !== b.category_id) return a.category_id - b.category_id;
          return a.priority - b.priority;
        })
        .forEach(function (item) {
          var key = String(item.category_id);
          if (!groups[key]) {
            groups[key] = { path: item.category_path || ('类别 #' + item.category_id), items: [] };
            order.push(key);
          }
          groups[key].items.push(item);
        });

      LC.clear(nodes.recoRows);
      order.forEach(function (key) {
        var group = groups[key];
        var chain = [];
        group.items.forEach(function (item, index) {
          if (index) chain.push(LC.el('span', { class: 'lc-inv-arrow', 'aria-hidden': 'true', text: '→' }));
          chain.push(LC.el('span', { class: 'lc-inv-reco-chip' }, [
            LC.el('span', { class: 'lc-mono', text: item.location_code || '' }),
            LC.el('span', { text: ' ' + (item.location_path || '') })
          ]));
        });
        nodes.recoRows.appendChild(LC.el('li', { class: 'lc-inv-reco-item' }, [
          LC.el('p', { class: 'lc-inv-reco-head' }, [
            LC.el('span', { class: 'lc-inv-reco-cat', text: group.path }),
            LC.el('span', { class: 'lc-hint', text: '（类别映射，共 ' + group.items.length + ' 个库位）' })
          ]),
          LC.el('div', { class: 'lc-inv-reco-chain' }, chain)
        ]));
      });
      LC.show(nodes.recoEmpty, order.length === 0);
    }

    function renderCategoryPicks() {
      if (!nodes.categoryPicks) return;
      LC.clear(nodes.categoryPicks);
      var seen = {};
      var added = 0;
      mappings.forEach(function (item) {
        if (seen[String(item.category_id)]) return;
        seen[String(item.category_id)] = true;
        added += 1;
        nodes.categoryPicks.appendChild(LC.el('button', {
          class: 'lc-inv-chip', type: 'button',
          'data-lc-action': 'mappings-pick-category',
          'data-lc-inv-category-id': String(item.category_id),
          'data-lc-inv-category-path': item.category_path || '',
          text: item.category_path || ('类别 #' + item.category_id)
        }));
      });
      if (!added) {
        nodes.categoryPicks.appendChild(LC.el('span', {
          class: 'lc-hint', text: '已有映射的类别会出现在这里，点一下即可填回上面。'
        }));
      }
    }

    function render() {
      LC.renderRows(nodes.rows, mappings, row);
      LC.setText(nodes.count, String(mappings.length));
      LC.show(nodes.empty, mappings.length === 0);
      renderReco();
      renderCategoryPicks();
    }

    /* -------------------------------------------------------------- 读取 */
    function load(button) {
      loadSeq += 1;
      var seq = loadSeq;
      var includeInactive = !!(nodes.includeInactive && nodes.includeInactive.checked);
      LC.show(nodes.loading, true);
      LC.show(nodes.empty, false);
      LC.setBusy(button, true, '刷新中…');
      return LC.rpc('mappingList', { include_inactive: includeInactive }).then(function (data) {
        if (seq !== loadSeq) return;
        mappings = (data && data.mappings) || [];
        refreshLocks();      // 先恢复未决提交（决定按钮/表单是否禁用），再渲染
        render();
        LC.show(nodes.loading, false);
        LC.setBusy(button, false);
      }).catch(function (err) {
        if (seq !== loadSeq) return;
        LC.show(nodes.loading, false);
        LC.setBusy(button, false);
        LC.status.show({
          kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
          code: err.code,
          message: LC.errorText(err),
          retry: function () { load(button); }
        });
      });
    }

    function loadLocations() {
      if (locationsLoaded || !nodes.locationSelect) return Promise.resolve();
      return LC.rpc('locations', {}).then(function (data) {
        var list = (data && data.locations) || [];
        LC.clear(nodes.locationSelect);
        nodes.locationSelect.appendChild(LC.el('option', {
          value: '', text: list.length ? '（选择内部库位）' : '（没有可用的内部库位）'
        }));
        list.forEach(function (loc) {
          nodes.locationSelect.appendChild(LC.el('option', {
            value: String(loc.id),
            text: (loc.code ? '[' + loc.code + '] ' : '') + (loc.path || loc.name || loc.id)
          }));
        });
        locationsLoaded = true;
      }).catch(function (err) {
        LC.status.show({
          kind: 'error',
          code: err.code,
          message: '库位列表加载失败：' + LC.errorText(err),
          detail: '没有库位列表就无法选择推荐库位；可以稍后重试。',
          retry: function () { loadLocations().then(function () {}); }
        });
      });
    }

    /* -------------------------------------------------------------- 写入 */
    function existingForPair(categoryId, locationId) {
      var found = null;
      mappings.forEach(function (item) {
        if (String(item.category_id) === String(categoryId) &&
            String(item.location_id) === String(locationId)) found = item;
      });
      return found;
    }

    function submitSet(values, button) {
      var categoryId = LC.parse.int(values.category_id, null);
      var locationId = LC.parse.int(values.location_id, null);
      var existing = existingForPair(categoryId, locationId);
      var active;
      if (activeTouched) active = !!values.active;            // 用户显式改过 -> 听用户的
      else if (existing) active = !!existing.active;          // 没改过 -> 保留该映射当前状态
      else active = !!values.active;
      var params = {
        category_id: categoryId,
        location_id: locationId,
        priority: LC.parse.int(values.priority, 10),
        active: active
      };
      var note = String(values.note || '').trim();
      if (note) params.note = note;
      return LC.submit({
        scope: SPEC_SET.scope,
        endpoint: SPEC_SET.endpoint,
        params: params,
        button: button,
        busyLabel: '保存中…'
      });
    }

    function onSetDone(res) {
      var data = (res && res.data) || {};
      var mapping = data.mapping || {};
      activeTouched = false;
      LC.status.show({
        kind: 'success',
        message: (data.created ? '已新增映射：' : '已更新映射：') +
          (mapping.category_path || '') + ' → ' + (mapping.location_path || '') +
          '（优先级 ' + LC.fmt.quantity(mapping.priority) + '，' +
          (mapping.active ? '启用' : '已停用') + '）'
      });
      refreshLocks();
      load();
    }

    function handleSetError(err, values, button) {
      if (err.unknown || isPendingConflict(err)) {
        handleUnknownSubmit(err, SPEC_SET);
        return;
      }
      if (err.code === 'FORBIDDEN') {
        LC.status.show({ kind: 'denied', code: err.code, message: LC.errorText(err) });
        return;
      }
      LC.status.show({
        kind: 'error',
        code: err.code,
        message: err.code === 'PRECONDITION_FAILED' || err.code === 'NOT_FOUND'
          ? (err.message || LC.errorText(err))
          : LC.errorText(err),
        detail: err.code === 'INTERNAL_ERROR' && err.fields && err.fields.error_id
          ? '请把错误编号 ' + err.fields.error_id + ' 提供给管理员。' : '',
        retry: err.code === 'CONFLICT' ? function () { load(); } : null
      });
      LC.fieldMessages(err).forEach(function (item) {
        if (item.field === 'category_id' || item.field === 'location_id' ||
            item.field === 'priority' || item.field === 'note') {
          LC.formError(form, item.field, item.message);
        }
      });
    }

    function submitRemove(item, hard, button) {
      return LC.submit({
        scope: 'mappings/' + (hard ? 'remove' : 'disable') + '/' + String(item.id),
        endpoint: 'mappingRemove',
        params: { mapping_id: LC.parse.int(item.id, null), hard: !!hard },
        button: button,
        busyLabel: hard ? '删除中…' : '停用中…'
      });
    }

    function onRemoveDone(res, item, hard) {
      LC.status.show({
        kind: 'success',
        message: (hard ? '已删除映射配置：' : '已停用映射：') +
          (item.category_path || '') + ' → ' + (item.location_path || '') +
          (hard ? '' : '（勾选「显示已停用映射」可以看到它）')
      });
      refreshLocks();
      load();
    }

    function handleRemoveError(err, item, hard, button) {
      if (err.unknown || isPendingConflict(err)) {
        handleUnknownSubmit(err, specFor(hard ? 'remove' : 'disable', item.id));
        return;
      }
      LC.status.show({
        kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
        code: err.code,
        message: LC.errorText(err),
        retry: err.code === 'NOT_FOUND' || err.code === 'CONFLICT'
          ? function () { load(); } : null
      });
    }

    /** 重新启用一条已停用映射（mapping_set 的 upsert，active=true）。 */
    function submitEnable(item, button) {
      var params = {
        category_id: LC.parse.int(item.category_id, null),
        location_id: LC.parse.int(item.location_id, null),
        priority: LC.parse.int(item.priority, 10),
        active: true
      };
      // note 必须带上：mapping_set 不传 note 会把它清空
      if (item.note) params.note = item.note;
      return LC.submit({
        scope: 'mappings/enable/' + String(item.id),
        endpoint: 'mappingSet',
        params: params,
        button: button,
        busyLabel: '启用中…'
      });
    }

    function onEnabled(res, item) {
      LC.status.show({
        kind: 'success',
        message: '已启用映射：' + (item.category_path || '') + ' → ' + (item.location_path || '')
      });
      refreshLocks();
      load();
    }

    function findMapping(id) {
      var found = null;
      mappings.forEach(function (item) {
        if (String(item.id) === String(id)) found = item;
      });
      return found;
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

    LC.on(root, '[data-lc-action="mappings-reload"]', 'click', function (ev, btn) {
      LC.status.clear();
      load(btn);
    });

    LC.on(root, '[data-lc-action="mappings-clear-form"]', 'click', function () {
      if (!form) return;
      LC.clearFormErrors(form);
      LC.setFieldValue(form, 'category_id', '');
      LC.setFieldValue(form, 'location_id', '');
      LC.setFieldValue(form, 'priority', '10');
      LC.setFieldValue(form, 'note', '');
      if (form.elements.active) form.elements.active.checked = true;
      activeTouched = false;
    });

    LC.on(root, '[data-lc-action="mappings-pick-category"]', 'click', function (ev, btn) {
      if (!form) return;
      var categoryId = btn.getAttribute('data-lc-inv-category-id');
      LC.setFieldValue(form, 'category_id', categoryId);
      // 该类别已有映射时把库位/优先级/备注/启用状态一起带出来：
      // 编辑已有映射不该因为表单默认值把它"悄悄启用"。
      var first = null;
      mappings.forEach(function (item) {
        if (String(item.category_id) !== String(categoryId)) return;
        if (!first || item.priority < first.priority) first = item;
      });
      activeTouched = false;
      if (first) {
        LC.setFieldValue(form, 'location_id', first.location_id);
        LC.setFieldValue(form, 'priority', first.priority);
        LC.setFieldValue(form, 'note', first.note || '');
        if (form.elements.active) form.elements.active.checked = !!first.active;
      }
      LC.status.show({
        kind: 'empty',
        message: '已填入类别「' + (btn.getAttribute('data-lc-inv-category-path') || '') + '」' +
          (first ? '（带出已有映射：' + (first.location_path || '') + '，优先级 ' +
            LC.fmt.quantity(first.priority) + '，' + (first.active ? '启用' : '已停用') + '）' : '') +
          '；确认库位后保存即可（同类别 + 同库位会覆盖原记录）。'
      });
    });

    LC.on(root, '[data-lc-action="mappings-enable"]', 'click', function (ev, btn) {
      var item = findMapping(btn.getAttribute('data-lc-inv-mapping-id'));
      if (!item) return;
      if (!LC.confirmAction('重新启用映射「' + (item.category_path || '') + ' → ' +
        (item.location_path || '') + '」？启用后它重新进入入库推荐顺序。')) return;
      LC.status.clear();
      submitEnable(item, btn).then(function (res) {
        onEnabled(res, item);
      }).catch(function (err) {
        handleRemoveError(err, item, false, btn);
      });
    });

    LC.on(root, '[data-lc-action="mappings-disable"]', 'click', function (ev, btn) {
      var item = findMapping(btn.getAttribute('data-lc-inv-mapping-id'));
      if (!item) return;
      if (!LC.confirmAction('停用映射「' + (item.category_path || '') + ' → ' +
        (item.location_path || '') + '」？停用后该库位不再进入入库推荐顺序。')) return;
      LC.status.clear();
      submitRemove(item, false, btn).then(function (res) {
        onRemoveDone(res, item, false);
      }).catch(function (err) {
        handleRemoveError(err, item, false, btn);
      });
    });

    LC.on(root, '[data-lc-action="mappings-remove"]', 'click', function (ev, btn) {
      var item = findMapping(btn.getAttribute('data-lc-inv-mapping-id'));
      if (!item) return;
      if (!LC.confirmAction('删除映射配置「' + (item.category_path || '') + ' → ' +
        (item.location_path || '') + '」？只删除这条配置记录，不会改动任何库存、袋或流水。')) return;
      LC.status.clear();
      submitRemove(item, true, btn).then(function (res) {
        onRemoveDone(res, item, true);
      }).catch(function (err) {
        handleRemoveError(err, item, true, btn);
      });
    });

    if (nodes.includeInactive) {
      nodes.includeInactive.addEventListener('change', function () {
        LC.status.clear();
        load();
      });
    }

    // 只有用户真的动过"启用"开关，保存时才覆盖已有映射的启用状态
    var activeBox = form && form.elements ? form.elements.active : null;
    if (activeBox) {
      activeBox.addEventListener('change', function () { activeTouched = true; });
    }

    if (form) {
      LC.guard(form, function (values, done) {
        var button = form.querySelector('button[type="submit"]');
        if (!LC.has('can_manage_mappings')) {
          done();
          LC.status.show({ kind: 'denied', code: 'FORBIDDEN',
                           message: '当前账号没有类别映射管理权限。' });
          return;
        }
        if (!values.category_id || !values.location_id) {
          done();
          if (!values.category_id) LC.formError(form, 'category_id', '请填写产品分类 ID。');
          if (!values.location_id) LC.formError(form, 'location_id', '请选择推荐库位。');
          return;
        }
        submitSet(values, button).then(function (res) {
          done();
          onSetDone(res);
        }).catch(function (err) {
          done(err);
          handleSetError(err, values, button);
        });
      });
    }

    // 先恢复"整类"未决（mappings/set）：即使列表加载失败也能看到并解除
    refreshLocks();
    load();
    loadLocations();
  });
})();
