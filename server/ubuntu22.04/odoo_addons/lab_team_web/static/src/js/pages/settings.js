/* ==========================================================================
 * lab_team_web · P3 管理页（page_id=settings，/lab/settings）
 * --------------------------------------------------------------------------
 * 只维护三个库存组（backend-contract §3.5 / lead-decisions #7）：
 *   lab_user / lab_operator / lab_manager  ->  就这三个，别的组一律不碰。
 * * 不出现 base.group_system、ERP 管理员或器件目录角色的授权入口；
 * * 每次变更只发一个组的 (user_id, role, enabled)，服务端只对这一组做
 *   (4, group) / (3, group)，账号的其他组保持不变；
 * * "最后一名管理员"与"隐含层级"保护在服务端（PRECONDITION_FAILED），
 *   本页只负责显示原因并回退界面状态，不假装成功。
 *
 * 端点：members（manager，分页 next_cursor）、memberSetRole（manager）。
 * 写操作走 LC.submit：结果未知时同一内容 + 同一请求键显式重试。
 * ========================================================================== */
(function () {
  'use strict';

  var LC = window.LC;
  if (!LC) return;

  var ROLE_LABELS = {
    lab_user: '库存用户',
    lab_operator: '操作员',
    lab_manager: '管理员'
  };
  var ROLES = ['lab_user', 'lab_operator', 'lab_manager'];
  var PAGE_LIMIT = 50;

  LC.register('settings', function (ctx) {
    var root = ctx.root;

    var nodes = {
      rows: LC.qs('[data-lc-rows="members"]', root),
      count: LC.qs('[data-lc-count="members"]', root),
      empty: LC.qs('[data-lc-empty="members"]', root),
      loading: LC.qs('[data-lc-loading="members"]', root),
      query: LC.qs('[data-lc-field="query"]', root),
      onlyWithRole: LC.qs('[data-lc-field="only_with_role"]', root),
      more: LC.qs('[data-lc-action="members-more"]', root),
      locks: LC.qs('[data-lc-inv-locks="settings"]', root),
      lockRows: LC.qs('[data-lc-rows="locks"]', root)
    };

    var members = [];
    var cursor = null;
    var loadSeq = 0;
    var pendingLocks = {};   // lockKey -> {spec, pending}（core v1.2 未决恢复）

    /* ------------------------------------------------- 未决提交（core v1.2）
     * 角色变更 scope 稳定为 settings/role/<uid>/<role>（按对象拆分，锁影响面最小）。
     * 页面只做：加载时恢复横幅（不自动重发）、用原内容重试、核对成员列表后显式解除。
     */
    function specFor(userId, role) {
      return {
        key: userId + ':' + role,
        scope: 'settings/role/' + userId + '/' + role,
        endpoint: 'memberSetRole',
        label: '角色变更 · ' + (memberLabel(userId) || ('#' + userId)) + ' · ' + ROLE_LABELS[role]
      };
    }

    function memberLabel(userId) {
      var member = findMember(userId);
      return member ? (member.name || member.login || '') : '';
    }

    function lockSpecs() {
      var specs = [];
      members.forEach(function (member) {
        ROLES.forEach(function (role) { specs.push(specFor(member.id, role)); });
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
      return '账号 #' + data.user_id + ' · ' + (ROLE_LABELS[data.role] || data.role) +
        ' → ' + (data.enabled ? '授予' : '撤销');
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
      return items.length;
    }

    function retryLock(spec, pending, button) {
      if (!pending || !pending.payload) {
        LC.status.show({
          kind: 'error',
          message: '浏览器没有保存原提交内容（sessionStorage 不可用），无法安全重试；请核对成员列表后显式解除。'
        });
        return;
      }
      LC.submit({
        scope: spec.scope, endpoint: spec.endpoint,
        params: pending.payload, button: button, busyLabel: '重试中…'
      }).then(function (res) {
        var data = (res && res.data) || {};
        replaceMember(data.member);
        refreshLocks();
        render();
        LC.status.show({
          kind: 'success',
          message: '未决角色变更已确认生效（' + spec.label + '）' +
            (res && res.replayed ? '；系统判定为重复提交，未重复执行' : '')
        });
      }).catch(function (err) {
        var payload = pending.payload || {};
        var member = findMember(payload.user_id) || { id: payload.user_id, name: '' };
        if (err && (err.unknown || isPendingConflict(err))) {
          refreshLocks();
          LC.status.show({ kind: 'unknown', code: err.code,
            message: '仍未确认结果：未决记录保留，请继续用原内容重试，或核对成员列表后显式解除。' });
          return;
        }
        refreshLocks();
        handleRoleError(err, member, payload.role || 'lab_user', !!payload.enabled, null);
      });
    }

    function resolveLock(spec, verification, button) {
      var question = verification === 'absent'
        ? '请先刷新成员列表核对：确认上次「' + spec.label + '」没有生效，可以重新提交？'
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
        load(null, false);
      }).catch(function (err) {
        LC.setBusy(button, false);
        LC.status.show({ kind: 'error', code: err && err.code, message: LC.errorText(err) });
      });
    }

    function handleUnknownSubmit(err, spec) {
      refreshLocks();
      render();     // 对应角色 checkbox 同步为禁用
      LC.status.show({
        kind: 'unknown',
        code: err && err.code,
        message: isPendingConflict(err)
          ? '上一次「' + spec.label + '」结果未知：不能改内容后再次提交。'
          : '「' + spec.label + '」结果未知（网络中断或超时）：本页不会自动重发。',
        detail: '请在上方未决区点「用原内容重试」，或核对成员列表里的角色现状后点「已核对：上次未生效 / 已生效」显式解除。',
        retry: function () { refreshLocks(); }
      });
    }

    /* -------------------------------------------------------------- 渲染 */
    function roleCell(member, role) {
      var locked = !!pendingLocks[String(member.id) + ':' + role];
      var box = LC.el('input', {
        type: 'checkbox',
        'data-lc-inv-role': role,
        'data-lc-inv-user-id': String(member.id),
        'aria-label': (member.name || member.login || member.id) + ' 的' + ROLE_LABELS[role] + '角色',
        title: locked ? '该角色有未决提交，请先在上方未决区解除' : '',
        checked: !!(member.roles && member.roles[role])
      });
      if (locked) box.disabled = true;
      /* 图形仍 18/22px，但真实可点击区域由 label 撑到 ≥44×44（触屏/鼠标都好点） */
      var hit = LC.el('label', {
        class: 'lc-inv-role-hit',
        title: box.title || ''
      }, [box]);
      return LC.el('td', { class: 'lc-inv-role-cell' }, [hit]);
    }

    /* 窄屏卡片化：把表头文案复制到每个单元格的 data-label，
     * CSS 在 ≤760px 用 ::before 显示（操作按钮不用横向滚动找）。 */
    function labelCells() {
      var table = root.querySelector('[data-lc-table="members"]');
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

    function row(member) {
      var nameCell = LC.el('td', {}, [
        LC.el('span', { text: member.name || member.login || ('#' + member.id) }),
        member.is_self
          ? LC.el('span', { class: 'lc-badge lc-inv-self', text: '本人' })
          : null
      ]);
      var state = member.active
        ? LC.el('span', { class: 'lc-badge', 'data-tone': 'ok', text: '启用' })
        : LC.el('span', { class: 'lc-badge', text: '已停用' });
      var cells = [
        nameCell,
        LC.el('td', {}, [LC.el('span', { class: 'lc-mono', text: member.login || '—' })])
      ];
      ROLES.forEach(function (role) { cells.push(roleCell(member, role)); });
      cells.push(LC.el('td', {}, [state]));
      return LC.el('tr', { 'data-lc-inv-member': String(member.id) }, cells);
    }

    function render() {
      LC.renderRows(nodes.rows, members, row);
      labelCells();
      LC.setText(nodes.count, String(members.length));
      LC.show(nodes.empty, members.length === 0);
      LC.show(nodes.more, !!cursor);
    }

    function findMember(userId) {
      var found = null;
      members.forEach(function (member) {
        if (String(member.id) === String(userId)) found = member;
      });
      return found;
    }

    function replaceMember(updated) {
      if (!updated) return;
      members = members.map(function (member) {
        return String(member.id) === String(updated.id) ? updated : member;
      });
    }

    /* -------------------------------------------------------------- 读取 */
    function load(button, append) {
      loadSeq += 1;
      var seq = loadSeq;
      var params = {
        limit: PAGE_LIMIT,
        only_with_role: !!(nodes.onlyWithRole && nodes.onlyWithRole.checked)
      };
      var query = nodes.query ? String(nodes.query.value || '').trim() : '';
      if (query) params.query = query;
      if (append && cursor) params.cursor = cursor;

      LC.show(nodes.loading, true);
      if (!append) LC.show(nodes.empty, false);
      LC.setBusy(button, true, '加载中…');
      return LC.rpc('members', params).then(function (data) {
        if (seq !== loadSeq) return;
        var list = (data && data.members) || [];
        members = append ? members.concat(list) : list;
        cursor = (data && data.next_cursor) || null;
        refreshLocks();      // 先恢复未决提交（决定 checkbox 是否禁用），再渲染
        render();
        // 账号维护区的目标下拉框跟着成员列表走：列表变了，可选项也要变。
        fillAdminTargets();
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
          retry: function () { load(button, append); }
        });
      });
    }

    /* -------------------------------------------------------------- 写角色 */
    function submitRole(member, role, enabled, box) {
      var spec = specFor(member.id, role);
      return LC.submit({
        scope: spec.scope,
        endpoint: spec.endpoint,
        params: {
          user_id: LC.parse.int(member.id, null),
          role: role,
          enabled: !!enabled
        },
        busyLabel: '保存角色…'
      });
    }

    function onRoleDone(res, member, role, enabled) {
      var data = (res && res.data) || {};
      replaceMember(data.member);
      refreshLocks();
      render();
      var changed = data.changed !== false;
      LC.status.show({
        kind: 'success',
        message: (changed ? (enabled ? '已授予' : '已撤销') : '无需变更：') +
          '「' + (member.name || member.login || '') + '」的' +
          ROLE_LABELS[role] + '角色' + (changed ? '' : '本来就是该状态')
      });
    }

    function handleRoleError(err, member, role, enabled, box) {
      if (err.unknown || isPendingConflict(err)) {
        handleUnknownSubmit(err, specFor(member && member.id, role));
        render();   // 回退到服务端已知状态（checkbox 恢复），锁定横幅已渲染
        return;
      }
      render();   // 回退到服务端已知状态（checkbox 恢复）
      if (err.code === 'PRECONDITION_FAILED') {
        // 服务端 p3_rules.RuleError.fields() = {role: 'last_manager'|'implied_role'}
        var fields = err.fields || {};
        var reason = fields.role || fields.reason || '';
        var detail = '';
        if (reason === 'last_manager') {
          detail = '该公司至少需要保留一名启用中的库存管理员；请先给其他账号授予管理员角色。';
        } else if (reason === 'implied_role') {
          detail = '操作员隐含库存用户、管理员隐含操作员；请先撤销更高角色再撤销低角色。';
        } else if (fields.user_id === 'inactive') {
          detail = '账号已停用，不能变更角色。';
        }
        LC.status.show({
          kind: 'error',
          code: err.code,
          message: err.message || LC.errorText(err),
          detail: detail
        });
        return;
      }
      LC.status.show({
        kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
        code: err.code,
        message: err.message || LC.errorText(err),
        detail: err.code === 'INTERNAL_ERROR' && err.fields && err.fields.error_id
          ? '请把错误编号 ' + err.fields.error_id + ' 提供给管理员。' : '',
        retry: err.code === 'CONFLICT' || err.code === 'NOT_FOUND'
          ? function () { load(); } : null
      });
    }

    function markBusy(box, busy) {
      if (!box) return;
      box.disabled = !!busy;
      if (busy) box.setAttribute('aria-busy', 'true');
      else box.removeAttribute('aria-busy');
    }

    function toggleRole(box) {
      var member = findMember(box.getAttribute('data-lc-inv-user-id'));
      var role = box.getAttribute('data-lc-inv-role');
      if (!member || !role) return;
      if (!LC.has('can_manage_members')) {
        render();
        LC.status.show({ kind: 'denied', code: 'FORBIDDEN',
                         message: '当前账号没有成员角色管理权限。' });
        return;
      }
      var enabled = !!box.checked;
      if (member.is_self && role === 'lab_manager' && !enabled) {
        if (!LC.confirmAction('撤销自己的库存管理员角色？若本公司没有其他管理员，系统会拒绝。')) {
          render();
          return;
        }
      }
      LC.status.clear();
      markBusy(box, true);
      submitRole(member, role, enabled, box).then(function (res) {
        markBusy(box, false);
        onRoleDone(res, member, role, enabled);
      }).catch(function (err) {
        markBusy(box, false);
        handleRoleError(err, member, role, enabled, box);
      });
    }

    /* -------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action="locks-retry"]', 'click', function (ev, btn) {
      var item = pendingLocks[btn.getAttribute('data-lc-inv-lock-key')];
      if (!item) {
        refreshLocks();
        LC.status.show({ kind: 'error', message: '未决记录已不存在（可能已过期），请刷新页面后核对成员列表。' });
        return;
      }
      LC.status.clear();
      retryLock(item.spec, item.pending, btn);
    });

    LC.on(root, '[data-lc-action="locks-resolve"]', 'click', function (ev, btn) {
      var item = pendingLocks[btn.getAttribute('data-lc-inv-lock-key')];
      if (!item) {
        refreshLocks();
        LC.status.show({ kind: 'error', message: '未决记录已不存在（可能已过期），请刷新页面后核对成员列表。' });
        return;
      }
      var verification = btn.hasAttribute('data-lc-inv-lock-resolve-absent') ? 'absent' : 'present';
      LC.status.clear();
      resolveLock(item.spec, verification, btn);
    });

    LC.on(root, '[data-lc-action="members-reload"]', 'click', function (ev, btn) {
      LC.status.clear();
      load(btn, false);
    });

    LC.on(root, '[data-lc-action="members-search"]', 'click', function (ev, btn) {
      LC.status.clear();
      load(btn, false);
    });

    LC.on(root, '[data-lc-action="members-more"]', 'click', function (ev, btn) {
      LC.status.clear();
      load(btn, true);
    });

    LC.on(root, '[data-lc-inv-role]', 'change', function (ev, box) {
      toggleRole(box);
    });

    if (nodes.query) {
      nodes.query.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter') return;
        ev.preventDefault();
        load(nodes.query, false);
      });
    }

    if (nodes.onlyWithRole) {
      nodes.onlyWithRole.addEventListener('change', function () {
        LC.status.clear();
        load(null, false);
      });
    }

    /* ================================================================
     * 账号维护：建号 / 重置密码 / 停用 / 系统管理员
     *
     * 这些操作以前只能在 Odoo 原生后台完成。前端只做转发与展示，
     * 安全边界全部在服务端：
     *   - 全部要 manager 门禁；
     *   - 授予 base.group_system 额外要求操作者是系统管理员；
     *   - 不能停用自己、不能停用最后一个管理员。
     * ================================================================ */
    var adminNodes = {
      newLogin: LC.qs('[data-lc-field="new_login"]', root),
      newName: LC.qs('[data-lc-field="new_name"]', root),
      newPassword: LC.qs('[data-lc-field="new_password"]', root),
      newRole: LC.qs('[data-lc-field="new_role"]', root),
      target: LC.qs('[data-lc-field="admin_target"]', root),
      newPw: LC.qs('[data-lc-field="admin_password"]', root),
      sysTarget: LC.qs('[data-lc-field="system_target"]', root),
      edaTarget: LC.qs('[data-lc-field="eda_target"]', root),
      edaName: LC.qs('[data-lc-field="eda_name"]', root),
      edaDays: LC.qs('[data-lc-field="eda_days"]', root),
      edaRows: LC.qs('[data-lc-rows="eda_tokens"]', root),
      edaNew: LC.qs('[data-lc-inv-eda-result="new"]', root),
      edaNewToken: LC.qs('[data-lc-eda="token"]', root),
      edaError: LC.qs('[data-lc-inv-eda-result="error"]', root),
      edaErrorText: LC.qs('[data-lc-eda="error"]', root),
      lcscName: LC.qs('[data-lc-field="lcsc_name"]', root),
      lcscAppId: LC.qs('[data-lc-field="lcsc_app_id"]', root),
      lcscAk: LC.qs('[data-lc-field="lcsc_access_key"]', root),
      lcscSk: LC.qs('[data-lc-field="lcsc_secret_key"]', root),
      lcscRows: LC.qs('[data-lc-rows="lcsc_keys"]', root),
      lcscError: LC.qs('[data-lc-inv-lcsc-result="error"]', root),
      lcscErrorText: LC.qs('[data-lc-lcsc="error"]', root)
    };

    /// 目标下拉框跟随成员列表刷新（用当前已加载的 members）。
    function fillAdminTargets() {
      [adminNodes.target, adminNodes.sysTarget, adminNodes.edaTarget].forEach(function (select) {
        if (!select) return;
        var keep = select.value;
        select.innerHTML = '<option value="">（先在上方列表里搜索，再选择）</option>';
        members.forEach(function (member) {
          var option = document.createElement('option');
          option.value = String(member.id);
          option.textContent = (member.name || member.login || ('#' + member.id)) +
            ' · ' + (member.login || '');
          select.appendChild(option);
        });
        if (keep && members.some(function (m) { return String(m.id) === keep; })) {
          select.value = keep;
        }
      });
    }

    function adminValue(node) {
      return node && node.value ? String(node.value).trim() : '';
    }

    function adminError(err) {
      var message = (err && err.message) || '操作失败。';
      LC.status.show({ kind: 'error', code: err && err.code, message: message });
    }

    function adminDone(message) {
      LC.status.show({ kind: 'success', message: message });
    }

    LC.on(root, '[data-lc-action="admin-create-user"]', 'click', function (ev, btn) {
      var login = adminValue(adminNodes.newLogin);
      var name = adminValue(adminNodes.newName);
      var password = adminNodes.newPassword ? adminNodes.newPassword.value : '';
      var role = adminValue(adminNodes.newRole);
      if (!login || !name || !password) {
        LC.status.show({ kind: 'error', message: '请填写登录名、姓名和初始密码。' });
        return;
      }
      btn.disabled = true;
      LC.rpc('adminUserCreate', {
        login: login, name: name, password: password,
        role: role || undefined
      }).then(function (res) {
        var user = (res && res.data && res.data.user) || {};
        adminDone('已创建账号「' + (user.name || name) + '」（' + (user.login || login) + '）');
        if (adminNodes.newLogin) adminNodes.newLogin.value = '';
        if (adminNodes.newName) adminNodes.newName.value = '';
        if (adminNodes.newPassword) adminNodes.newPassword.value = '';
        if (adminNodes.newRole) adminNodes.newRole.value = '';
        load(null, false);
      }).catch(adminError).then(function () { btn.disabled = false; });
    });

    LC.on(root, '[data-lc-action="admin-set-password"]', 'click', function (ev, btn) {
      var userId = adminValue(adminNodes.target);
      var password = adminNodes.newPw ? adminNodes.newPw.value : '';
      if (!userId || !password) {
        LC.status.show({ kind: 'error', message: '请选择目标账号并填写新密码。' });
        return;
      }
      btn.disabled = true;
      LC.rpc('adminUserSetPassword', {
        user_id: LC.parse.int(userId, null), password: password
      }).then(function (res) {
        var user = (res && res.data && res.data.user) || {};
        adminDone('已重置「' + (user.name || user.login || userId) + '」的密码');
        if (adminNodes.newPw) adminNodes.newPw.value = '';
      }).catch(adminError).then(function () { btn.disabled = false; });
    });

    LC.on(root, '[data-lc-action="admin-toggle-active"]', 'click', function (ev, btn) {
      var userId = adminValue(adminNodes.target);
      if (!userId) {
        LC.status.show({ kind: 'error', message: '请先选择目标账号。' });
        return;
      }
      var current = members.filter(function (m) { return String(m.id) === userId; })[0];
      var nextActive = !(current && current.active === false);
      btn.disabled = true;
      LC.rpc('adminUserToggleActive', {
        user_id: LC.parse.int(userId, null), active: nextActive
      }).then(function (res) {
        var user = (res && res.data && res.data.user) || {};
        adminDone((user.active ? '已启用' : '已停用') +
          '「' + (user.name || user.login || userId) + '」');
        load(null, false);
      }).catch(adminError).then(function () { btn.disabled = false; });
    });

    LC.on(root, '[data-lc-action="admin-grant-system"]', 'click', function (ev, btn) {
      var userId = adminValue(adminNodes.sysTarget);
      if (!userId) {
        LC.status.show({ kind: 'error', message: '请先选择目标账号。' });
        return;
      }
      btn.disabled = true;
      LC.rpc('adminUserSetSystemGroup', {
        user_id: LC.parse.int(userId, null), enabled: true
      }).then(function (res) {
        var user = (res && res.data && res.data.user) || {};
        adminDone('已授予「' + (user.name || user.login || userId) + '」系统管理员');
        load(null, false);
      }).catch(adminError).then(function () { btn.disabled = false; });
    });

    LC.on(root, '[data-lc-action="admin-revoke-system"]', 'click', function (ev, btn) {
      var userId = adminValue(adminNodes.sysTarget);
      if (!userId) {
        LC.status.show({ kind: 'error', message: '请先选择目标账号。' });
        return;
      }
      btn.disabled = true;
      LC.rpc('adminUserSetSystemGroup', {
        user_id: LC.parse.int(userId, null), enabled: false
      }).then(function (res) {
        var user = (res && res.data && res.data.user) || {};
        adminDone('已撤销「' + (user.name || user.login || userId) + '」系统管理员');
        load(null, false);
      }).catch(adminError).then(function () { btn.disabled = false; });
    });

    /* ================================================================
     * EDA 插件密钥
     *
     * 只有库存管理员能发放/吊销（服务端强制）。明文只在发放响应里出现一次，
     * 列表永远不含明文或哈希。
     * ================================================================ */
    function showEdaNew(token) {
      if (!adminNodes.edaNew) return;
      adminNodes.edaNew.hidden = false;
      if (adminNodes.edaNewToken) adminNodes.edaNewToken.textContent = token;
    }

    function hideEdaNew() {
      if (adminNodes.edaNew) adminNodes.edaNew.hidden = true;
      if (adminNodes.edaNewToken) adminNodes.edaNewToken.textContent = '';
    }

    function showEdaError(message) {
      if (!adminNodes.edaError) return;
      adminNodes.edaError.hidden = false;
      if (adminNodes.edaErrorText) adminNodes.edaErrorText.textContent = message || '操作失败。';
    }

    function fmtWhen(value) {
      if (!value) return '—';
      return String(value).replace(' ', ' · ');
    }

    function renderEdaTokens(tokens) {
      var body = adminNodes.edaRows;
      if (!body) return;
      body.innerHTML = '';
      (tokens || []).forEach(function (token) {
        var tr = document.createElement('tr');
        [token.user_name || token.user_login || '—',
         token.name || '—',
         token.expires_at ? fmtWhen(token.expires_at) : '永不过期',
         fmtWhen(token.last_used_at),
         token.active ? '有效' : '已吊销'
        ].forEach(function (text) {
          var td = document.createElement('td');
          td.textContent = text;
          tr.appendChild(td);
        });
        var action = document.createElement('td');
        if (token.active) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'lc-btn lc-btn-outline';
          btn.textContent = '吊销';
          btn.setAttribute('data-lc-action', 'eda-revoke');
          btn.setAttribute('data-lc-eda-id', String(token.id));
          btn.addEventListener('click', function () { revokeEdaToken(btn); });
          action.appendChild(btn);
        }
        tr.appendChild(action);
        body.appendChild(tr);
      });
    }

    function loadEdaTokens() {
      if (!adminNodes.edaRows) return;
      // LC.rpc 已经把 result.data 解包出来了；再取 .data 会得到 undefined。
      // （LC.submit 不同，它返回 {data, replayed, requestKey}。）
      LC.rpc('edaTokens', {}).then(function (data) {
        renderEdaTokens((data && data.tokens) || []);
      }).catch(function (err) {
        showEdaError((err && err.message) || '读取密钥列表失败。');
      });
    }

    function revokeEdaToken(btn) {
      var id = btn && btn.getAttribute('data-lc-eda-id');
      if (!id) return;
      btn.disabled = true;
      LC.rpc('edaRevoke', { id: LC.parse.int(id, null) }).then(function () {
        adminDone('已吊销该密钥，对应插件将立即无法访问。');
        loadEdaTokens();
      }).catch(function (err) {
        btn.disabled = false;
        showEdaError((err && err.message) || '吊销失败。');
      });
    }

    LC.on(root, '[data-lc-action="eda-issue"]', 'click', function (ev, btn) {
      var userId = adminValue(adminNodes.edaTarget);
      if (!userId) {
        LC.status.show({ kind: 'error', message: '请先选择要发放给谁。' });
        return;
      }
      hideEdaNew();
      if (adminNodes.edaError) adminNodes.edaError.hidden = true;
      btn.disabled = true;
      LC.rpc('edaIssue', {
        user_id: LC.parse.int(userId, null),
        name: adminValue(adminNodes.edaName) || undefined,
        days: adminNodes.edaDays && adminNodes.edaDays.value !== ''
          ? LC.parse.int(adminNodes.edaDays.value, null) : undefined
      }).then(function (data) {
        showEdaNew((data && data.token) || '');
        adminDone('已为「' + ((data && data.user_name) || userId) + '」发放 EDA 密钥。');
        loadEdaTokens();
      }).catch(function (err) {
        showEdaError((err && err.message) || '发放失败。');
      }).then(function () { btn.disabled = false; });
    });

    if (adminNodes.edaRows) loadEdaTokens();

    /* ================================================================
     * 立创开放平台密钥池
     *
     * 日额度按 AppId 算，多套轮询能叠加。SecretKey 只写不读——
     * 列表里只显示 AppId，保存后无法再查看。
     * ================================================================ */
    function showLcscError(message) {
      if (!adminNodes.lcscError) return;
      adminNodes.lcscError.hidden = false;
      if (adminNodes.lcscErrorText) adminNodes.lcscErrorText.textContent = message;
    }

    function hideLcscError() {
      if (adminNodes.lcscError) adminNodes.lcscError.hidden = true;
    }

    function renderLcscKeys(keys) {
      var body = adminNodes.lcscRows;
      if (!body) return;
      body.innerHTML = '';
      (keys || []).forEach(function (item) {
        var tr = document.createElement('tr');
        [item.name || '—',
         item.app_id || '—',
         fmtWhen(item.last_used_at),
         fmtWhen(item.rate_limited_at),
         item.active ? '启用' : '停用'
        ].forEach(function (text) {
          var td = document.createElement('td');
          td.textContent = text;
          tr.appendChild(td);
        });
        var action = document.createElement('td');
        var toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'lc-btn lc-btn-outline';
        toggle.textContent = item.active ? '停用' : '启用';
        toggle.addEventListener('click', function () {
          toggle.disabled = true;
          LC.rpc('lcscKeyToggle', { id: item.id, active: !item.active })
            .then(loadLcscKeys)
            .catch(function (err) {
              toggle.disabled = false;
              showLcscError((err && err.message) || '操作失败。');
            });
        });
        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'lc-btn lc-btn-outline';
        remove.textContent = '删除';
        remove.style.marginLeft = '6px';
        remove.addEventListener('click', function () {
          remove.disabled = true;
          LC.rpc('lcscKeyRemove', { id: item.id })
            .then(loadLcscKeys)
            .catch(function (err) {
              remove.disabled = false;
              showLcscError((err && err.message) || '删除失败。');
            });
        });
        action.appendChild(toggle);
        action.appendChild(remove);
        tr.appendChild(action);
        body.appendChild(tr);
      });
    }

    function loadLcscKeys() {
      if (!adminNodes.lcscRows) return;
      LC.rpc('lcscKeys', {}).then(function (data) {
        renderLcscKeys((data && data.keys) || []);
      }).catch(function (err) {
        showLcscError((err && err.message) || '读取密钥列表失败。');
      });
    }

    LC.on(root, '[data-lc-action="lcsc-add"]', 'click', function (ev, btn) {
      var payload = {
        name: adminValue(adminNodes.lcscName),
        app_id: adminValue(adminNodes.lcscAppId),
        access_key: adminValue(adminNodes.lcscAk),
        secret_key: adminNodes.lcscSk ? adminNodes.lcscSk.value : ''
      };
      if (!payload.name || !payload.app_id || !payload.access_key || !payload.secret_key) {
        showLcscError('备注、AppId、AccessKey、SecretKey 都要填。');
        return;
      }
      hideLcscError();
      btn.disabled = true;
      LC.rpc('lcscKeyCreate', payload).then(function () {
        adminDone('已添加立创密钥「' + payload.name + '」。');
        if (adminNodes.lcscName) adminNodes.lcscName.value = '';
        if (adminNodes.lcscAppId) adminNodes.lcscAppId.value = '';
        if (adminNodes.lcscAk) adminNodes.lcscAk.value = '';
        if (adminNodes.lcscSk) adminNodes.lcscSk.value = '';
        loadLcscKeys();
      }).catch(function (err) {
        showLcscError((err && err.message) || '添加失败。');
      }).then(function () { btn.disabled = false; });
    });

    LC.on(root, '[data-lc-action="lcsc-reset"]', 'click', function (ev, btn) {
      btn.disabled = true;
      LC.rpc('lcscKeyReset', {}).then(function () {
        adminDone('已重置所有密钥的超限标记。');
        loadLcscKeys();
      }).catch(function (err) {
        showLcscError((err && err.message) || '重置失败。');
      }).then(function () { btn.disabled = false; });
    });

    if (adminNodes.lcscRows) loadLcscKeys();

    // 角色未决按成员 id 记账：先扫一遍（成员加载失败时列表为空，仅保持状态一致）
    refreshLocks();
    load(null, false);
  });
})();