/* ==========================================================================
 * lab_team_web · P3 器件档案页（page_id=materials，/lab/materials）
 * --------------------------------------------------------------------------
 * 能力（ui-audit §4.10 + backend-contract §2 #18）：
 *   * 检索本地档案与资料库器件（catalog/search）；
 *   * 给本地档案绑定同立创编号（catalog/bind）；
 *   * 按资料库器件建立本地档案（catalog/create_material）；
 *   * 同一立创编号下有多个本地档案时**必须让用户选 SN**（AMBIGUOUS_MATERIAL），
 *     绝不默认取第一个。
 *
 * 不显示、不接受供应商可售数量（catalog_stock）；不暴露通用 ORM 入口；
 * 建档不复制任何库存（期初数量只能走入库流程）。
 *
 * 写入的特殊性：lab_catalog 的 bind / create_material **没有 request_key**
 * （控制器只读 product_template_id / catalog_code / item_key），所以这两个动作
 * 用 LC.rpc 发原始 payload，不塞 request_key、不自动重发：
 *   * bind：服务端按（编号, 档案）唯一约束去重 -> 结果未知时允许显式重试同一内容；
 *   * create：没有幂等键 -> 结果未知时**锁定建档入口**，要求先检索核对再显式解锁，
 *     绝不伪造成功、绝不静默再发请求。
 * 其余读取用 LC.rpc，错误一律按 code 分支。
 * ========================================================================== */
(function () {
  'use strict';

  var LC = window.LC;
  if (!LC) return;

  var SEARCH_LIMIT = 24;

  LC.register('materials', function (ctx) {
    var root = ctx.root;

    var nodes = {
      rows: LC.qs('[data-lc-rows="materials"]', root),
      count: LC.qs('[data-lc-count="materials"]', root),
      empty: LC.qs('[data-lc-empty="materials"]', root),
      loading: LC.qs('[data-lc-loading="materials"]', root),
      more: LC.qs('[data-lc-action="materials-more"]', root),
      target: LC.qs('[data-lc-inv-material-target]', root),
      detailEmpty: LC.qs('[data-lc-empty="material-detail"]', root),
      detailLoading: LC.qs('[data-lc-loading="material-detail"]', root),
      facts: LC.qs('[data-lc-inv-material-facts]', root),
      candidates: LC.qs('[data-lc-inv-candidates]', root),
      candidateRows: LC.qs('[data-lc-rows="candidates"]', root),
      candidatesNote: LC.qs('[data-lc-inv-candidates-note]', root),
      createLock: LC.qs('[data-lc-inv-create-lock]', root)
    };
    var searchForm = LC.qs('[data-lc-form="material-search"]', root);
    var bindForm = LC.qs('[data-lc-form="material-bind"]', root);

    var items = [];
    var cursor = null;
    var selected = null;        // 当前选中的检索行
    var candidates = [];        // AMBIGUOUS_MATERIAL 候选档案
    var pendingItemKey = '';    // 建档歧义时待提交的 item_key
    var searchSeq = 0;

    /* --------------------------------------- 建档"结果未知"持久锁（无幂等键）
     * lab_catalog/create_material 没有 request_key，core 的未决锁帮不上：
     * 所以把"上一次建档结果未知"的 payload 按当前用户+公司写进 sessionStorage
     * （与 core attempt 同前缀），刷新/重开页面仍锁定，避免重复建出第二个档案。
     * 解除只能由人核对后显式选择：仍未建档（absent）/ 已经建档（present）。
     */
    var createUnknown = null;   // {at,item_key,product_template_id}

    function storeKey() {
      var identity = (typeof LC.identity === 'object' && LC.identity) || {};
      var uid = (identity.uid === null || identity.uid === undefined || identity.uid === '')
        ? 'anon' : String(identity.uid);
      var company = (identity.company_id === null || identity.company_id === undefined ||
        identity.company_id === '') ? '0' : String(identity.company_id);
      var prefix = (LC.config && LC.config.attempt && LC.config.attempt.prefix) || 'lc-wf-attempt:';
      return prefix + 'nokey:materials:create:' + uid + ':' + company;
    }

    function readUnknown() {
      try {
        var raw = window.sessionStorage.getItem(storeKey());
        if (!raw) return null;
        var parsed = JSON.parse(raw);
        if (!parsed || typeof parsed.at !== 'number') return null;
        return parsed;
      } catch (error) {
        return null;
      }
    }

    function writeUnknown(record) {
      createUnknown = record;
      try {
        window.sessionStorage.setItem(storeKey(), JSON.stringify(record));
      } catch (error) {
        // sessionStorage 不可用：本页仍锁定，只是刷新后无法恢复
      }
    }

    function clearUnknown() {
      createUnknown = null;
      try {
        window.sessionStorage.removeItem(storeKey());
      } catch (error) {
        // 忽略
      }
    }

    function isCreateLocked() {
      return !!createUnknown;
    }

    /* -------------------------------------------------------------- 渲染 */
    function localProfileText(item) {
      var sns = (item.sn_codes || []).filter(function (sn) { return !!sn; });
      if (sns.length) return sns.join(' / ');
      var ids = item.lab_template_ids || [];
      if (!ids.length) return '—';
      return ids.map(function (id) { return '#' + id; }).join(' / ');
    }

    function actionButton(label, action, item, extraClass) {
      return LC.el('button', {
        class: 'lc-btn ' + (extraClass || 'lc-btn-outline') + ' lc-inv-btn-sm',
        type: 'button',
        'data-lc-action': action,
        'data-lc-inv-item-key': item.item_key || '',
        text: label
      });
    }

    function row(item) {
      var isCatalog = String(item.item_key || '').indexOf('lcsc:') === 0;
      var actions = [actionButton('详情', 'materials-detail', item)];
      if (!isCatalog) actions.push(actionButton('绑定', 'materials-bind', item));
      if (isCatalog) actions.push(actionButton('建档', 'materials-create-row', item, 'lc-btn-primary'));
      return LC.el('tr', {}, [
        LC.el('td', {}, [
          LC.el('span', { text: item.name || '—' }),
          item.category_name ? LC.el('span', { class: 'lc-hint', text: ' ' + item.category_name }) : null
        ]),
        LC.el('td', {}, [LC.el('span', { class: 'lc-mono', text: item.mpn || '—' })]),
        LC.el('td', { text: item.package || '—' }),
        LC.el('td', {}, [LC.el('span', { class: 'lc-mono', text: item.catalog_code || '—' })]),
        LC.el('td', {}, [LC.el('span', { class: 'lc-mono', text: localProfileText(item) })]),
        LC.el('td', { class: 'lc-inv-num', text: LC.fmt.quantity(item.lab_quantity) }),
        LC.el('td', {}, [LC.el('div', { class: 'lc-inv-actions' }, actions)])
      ]);
    }

    function render() {
      LC.renderRows(nodes.rows, items, row);
      LC.setText(nodes.count, String(items.length));
      LC.show(nodes.empty, items.length === 0);
      LC.show(nodes.more, !!cursor);
    }

    function kv(term, value) {
      var body = value instanceof Node ? value : LC.el('span', { text: value });
      return [LC.el('dt', { text: term }), LC.el('dd', {}, [body])];
    }

    function renderDetail(data) {
      var item = (data && data.item) || {};
      var templates = (data && data.lab_templates) || [];
      LC.clear(nodes.facts);

      [
        ['名称', item.name || '—'],
        ['立创编号', item.catalog_code || '—'],
        ['MPN', item.mpn || '—'],
        ['品牌', item.brand || '—'],
        ['封装', item.package || '—'],
        ['分类', item.category_name || '—'],
        ['本地档案数', String((item.lab_template_ids || []).length)],
        ['本地在库', LC.fmt.quantity(item.lab_quantity)],
        ['可用数量', LC.fmt.quantity(item.lab_available_quantity)]
      ].forEach(function (pair) {
        kv(pair[0], pair[1]).forEach(function (node) { nodes.facts.appendChild(node); });
      });

      if (templates.length) {
        nodes.facts.appendChild(LC.el('dt', { text: '本地档案明细' }));
        nodes.facts.appendChild(LC.el('dd', {}, templates.map(function (tmpl) {
          return LC.el('p', { class: 'lc-inv-tmpl' }, [
            LC.el('span', { class: 'lc-mono', text: '#' + tmpl.id }),
            LC.el('span', { text: ' SN ' + (tmpl.sn || '—') }),
            LC.el('span', { text: ' 在库 ' + LC.fmt.quantity(tmpl.quantity) })
          ]);
        })));
      }

      var params = (data && data.parameters) || [];
      if (params.length) {
        nodes.facts.appendChild(LC.el('dt', { text: '参数' }));
        nodes.facts.appendChild(LC.el('dd', {}, params.slice(0, 12).map(function (param) {
          return LC.el('p', { class: 'lc-inv-tmpl' }, [
            LC.el('span', { class: 'lc-hint', text: (param.name || param.code || '') + '：' }),
            LC.el('span', { text: param.value || '' })
          ]);
        })));
      }

      LC.show(nodes.detailEmpty, false);
      LC.show(nodes.facts, true);
    }

    function renderCandidates(note) {
      if (!nodes.candidates) return;
      LC.clear(nodes.candidateRows);
      candidates.forEach(function (candidate, index) {
        var radio = LC.el('input', {
          type: 'radio',
          name: 'lc-inv-candidate',
          value: String(candidate.product_template_id),
          'data-lc-inv-candidate': String(candidate.product_template_id),
          checked: index === 0
        });
        nodes.candidateRows.appendChild(LC.el('li', { class: 'lc-inv-candidate' }, [
          LC.el('label', { class: 'lc-inline' }, [
            radio,
            LC.el('span', { class: 'lc-mono', text: '#' + candidate.product_template_id }),
            LC.el('span', { text: ' SN ' + (candidate.sn || '—') }),
            LC.el('span', { class: 'lc-hint', text: ' ' + (candidate.name || '') })
          ])
        ]));
      });
      if (nodes.candidatesNote) {
        LC.setText(nodes.candidatesNote, note || '同一立创编号下有多个本地档案，请选择要归属的 SN：');
      }
      LC.show(nodes.candidates, candidates.length > 0);
    }

    /** 把选中行的本地档案填进"本地档案（SN）"下拉；多档案时不预选，强制用户选。 */
    function fillTemplateSelect(item) {
      var select = bindForm && bindForm.elements ? bindForm.elements.product_template_id : null;
      if (!select) return;
      var ids = (item && item.lab_template_ids) || [];
      var sns = (item && item.sn_codes) || [];
      LC.clear(select);
      select.appendChild(LC.el('option', {
        value: '',
        text: ids.length > 1 ? '（多个档案：请选择具体 SN）' : '（选择本地档案）'
      }));
      ids.forEach(function (id, index) {
        var sn = ids.length === sns.length ? sns[index] : '';
        select.appendChild(LC.el('option', {
          value: String(id),
          text: '#' + id + (sn ? ' SN ' + sn : '')
        }));
      });
      select.value = ids.length === 1 ? String(ids[0]) : '';
    }

    function selectItem(item) {
      selected = item;
      LC.setText(nodes.target, item ? (item.item_key || '') : '未选择');
      if (bindForm) {
        fillTemplateSelect(item);
        // 必须每次覆盖：否则上一行的编号会留在输入框里被绑到新行
        LC.setFieldValue(bindForm, 'catalog_code', (item && item.catalog_code) || '');
      }
    }

    function findItem(itemKey) {
      var found = null;
      items.forEach(function (item) {
        if (String(item.item_key) === String(itemKey)) found = item;
      });
      return found;
    }

    /* -------------------------------------------------------------- 检索 */
    function search(button, append) {
      searchSeq += 1;
      var seq = searchSeq;
      var params = { limit: SEARCH_LIMIT };
      var query = searchForm ? String(searchForm.elements.query.value || '').trim() : '';
      if (query) params.query = query;
      if (append && cursor) params.cursor = cursor;

      LC.show(nodes.loading, true);
      if (!append) LC.show(nodes.empty, false);
      LC.setBusy(button, true, '检索中…');
      return LC.rpc('catalogSearch', params).then(function (data) {
        if (seq !== searchSeq) return;
        var list = (data && data.items) || [];
        items = append ? items.concat(list) : list;
        cursor = (data && data.next_cursor) || null;
        render();
        LC.show(nodes.loading, false);
        LC.setBusy(button, false);
        if (!items.length) {
          LC.status.show({ kind: 'empty', message: '没有匹配的器件。' });
        } else {
          LC.status.clear();
        }
      }).catch(function (err) {
        if (seq !== searchSeq) return;
        LC.show(nodes.loading, false);
        LC.setBusy(button, false);
        LC.status.show({
          kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
          code: err.code,
          message: LC.errorText(err),
          detail: err.code === 'FORBIDDEN'
            ? '器件档案需要器件库读取角色（lab_catalog.group_lab_catalog_user）。' : '',
          retry: function () { search(button, append); }
        });
      });
    }

    function loadDetail(item, button) {
      if (!item) return;
      LC.show(nodes.detailLoading, true);
      LC.show(nodes.detailEmpty, false);
      LC.show(nodes.facts, false);      // 先收起上一行的档案事实，避免张冠李戴
      LC.setBusy(button, true, '加载中…');
      LC.rpc('catalogDetail', { item_key: item.item_key }).then(function (data) {
        LC.show(nodes.detailLoading, false);
        LC.setBusy(button, false);
        renderDetail(data);
      }).catch(function (err) {
        LC.show(nodes.detailLoading, false);
        LC.setBusy(button, false);
        LC.show(nodes.facts, false);
        LC.show(nodes.detailEmpty, true);
        LC.status.show({
          kind: err.code === 'NOT_FOUND' ? 'empty' : 'error',
          code: err.code,
          message: err.code === 'NOT_FOUND'
            ? '找不到该器件的详情（可能尚未导入资料库）。'
            : LC.errorText(err),
          retry: function () { loadDetail(item, button); }
        });
      });
    }

    /* -------------------------------------------------------------- 写入 */
    /* lab_catalog 的两个写端点（bind / create_material）**没有 request_key**
     * （控制器只读 product_template_id / catalog_code / item_key，见
     *  lab_catalog/controllers/catalog_api.py）：因此这里不走 LC.submit（它会
     *  自动塞 request_key），改用 LC.rpc 发同一份 payload，并且**从不自动重发**。
     *  网络结果未知时：bind 由服务端 (catalog_code, product_template_id) 唯一约束
     *  去重，可显式重试同一 body；create 没有幂等键 -> 锁定建档入口，要求先核对。 */
    function catalogWrite(endpoint, params, button, busyLabel) {
      LC.setBusy(button, true, busyLabel);
      LC.status.busy(true, busyLabel);
      return LC.rpc(endpoint, params, {
        timeoutMs: (LC.config.timeouts && LC.config.timeouts.submitMs) || 30000
      }).then(function (data) {
        LC.setBusy(button, false);
        LC.status.busy(false);
        return data || {};
      }).catch(function (err) {
        LC.setBusy(button, false);
        LC.status.busy(false);
        throw err;
      });
    }

    function submitBind(values, button) {
      return catalogWrite('catalogBind', {
        product_template_id: LC.parse.int(values.product_template_id, null),
        catalog_code: String(values.catalog_code || '').trim().toUpperCase()
      }, button, '绑定中…');
    }

    function submitCreate(itemKey, templateId, button) {
      var params = { item_key: itemKey };
      if (templateId) params.product_template_id = LC.parse.int(templateId, null);
      return catalogWrite('catalogCreateMaterial', params, button, '建档中…');
    }

    function renderLock() {
      LC.show(nodes.createLock, isCreateLocked());
      if (!nodes.createLock) return;
      var meta = LC.qs('[data-lc-inv-create-lock-meta]', nodes.createLock);
      if (!meta) return;
      if (!createUnknown) {
        LC.setText(meta, '—');
        return;
      }
      var ageSec = Math.max(0, Math.round((Date.now() - (createUnknown.at || Date.now())) / 1000));
      LC.setText(meta,
        '未决建档：' + (createUnknown.item_key || '—') +
        (createUnknown.product_template_id ? ' → 档案 #' + createUnknown.product_template_id : '') +
        ' · ' + ageSec + ' 秒前提交（记录在浏览器，刷新后仍在）');
    }

    function onBindDone(data, values) {
      LC.status.show({
        kind: 'success',
        message: '已绑定：档案 #' + (data.product_template_id || values.product_template_id) +
          ' → ' + (data.item_key || values.catalog_code)
      });
      if (bindForm) LC.clearFormErrors(bindForm);
      search();
    }

    function handleBindError(err, values, button) {
      if (err.unknown) {
        LC.status.show({
          kind: 'unknown',
          code: err.code,
          message: '结果未知：绑定可能已保存，也可能没有。',
          detail: '绑定接口没有幂等键；服务端按（档案, 立创编号）唯一约束去重，'
            + '重试同一内容不会产生第二条绑定。也可以先重新检索核对。',
          retryLabel: '重试同一内容',
          retry: function () {
            submitBind(values, button).then(function (data) {
              onBindDone(data, values);
            }).catch(function (again) { handleBindError(again, values, button); });
          }
        });
        return;
      }
      LC.status.show({
        kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
        code: err.code,
        message: err.message || LC.errorText(err),
        detail: err.code === 'VALIDATION_ERROR'
          ? '立创编号必须是 C 加十进制数字，例如 C12345。' : '',
        retry: err.code === 'CONFLICT' ? function () { search(); } : null
      });
      if (bindForm) {
        LC.fieldMessages(err).forEach(function (item) {
          if (item.field === 'catalog_code') LC.formError(bindForm, 'catalog_code', item.message);
          if (item.field === 'product_template_id') {
            LC.formError(bindForm, 'product_template_id',
              '请选择要绑定的本地档案；同 C 多档案时必须选具体 SN。');
          }
        });
      }
    }

    function onCreated(data, itemKey) {
      clearUnknown();     // 已确认成功：未决记录作废
      renderLock();
      candidates = [];
      renderCandidates('');
      LC.status.show({
        kind: 'success',
        message: (data.reused_existing ? '已复用本地档案 #' : '已建立本地档案 #') +
          (data.product_template_id || '') + '（' + (data.item_key || itemKey) + '）',
        detail: '建档不会生成库存；期初数量请走「采购入库」流程。'
      });
      search();
    }

    function handleCreateError(err, itemKey, templateId, button) {
      if (err.unknown) {
        // 建档没有幂等键、也没有 request_key：绝不自动重发，也不假装成功。
        // 把未决 payload 落到 sessionStorage（按用户+公司），刷新后仍然锁定。
        writeUnknown({
          at: Date.now(),
          item_key: itemKey,
          product_template_id: templateId || null
        });
        renderLock();
        LC.status.show({
          kind: 'unknown',
          code: err.code,
          message: '结果未知：本地档案可能已建立，也可能没有；建档入口已锁定（刷新后仍保留）。',
          detail: '请先按立创编号 / 统一料号 / SN 重新检索核对，再点上方的'
            + '「已核对：仍未建档」或「已核对：已经建档」。本页不会自动重发请求。'
        });
        return;
      }
      if (err.code === 'AMBIGUOUS_MATERIAL') {
        // 服务端在"已有多档案"分支直接返回，未创建任何东西 -> 未决记录可以清掉
        clearUnknown();
        renderLock();
        candidates = (err.fields && err.fields.candidates) || [];
        pendingItemKey = itemKey;
        renderCandidates('立创编号 ' + itemKey + ' 下有 ' + candidates.length +
          ' 个本地档案，请选择要归属的 SN：');
        LC.status.show({
          kind: 'error',
          code: err.code,
          message: err.message || LC.errorText(err),
          detail: '选好档案后点「用选中档案建档」；不会默认取第一个。'
        });
        return;
      }
      if (err.code === 'VALIDATION_ERROR' || err.code === 'FORBIDDEN' ||
          err.code === 'NOT_FOUND' || err.code === 'CONFLICT') {
        // 服务端明确拒绝（写入前失败）-> 未决记录作废，下次是新的建档操作
        clearUnknown();
        renderLock();
      }
      LC.status.show({
        kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
        code: err.code,
        message: err.message || LC.errorText(err),
        detail: err.code === 'NOT_FOUND'
          ? '资料库里还没有该立创编号，请先在器件库导入。' : '',
        retry: err.code === 'CONFLICT' ? function () { search(); } : null
      });
    }

    function createFor(item, button) {
      // 权限用实际器件库权限判断（can_catalog），不拿库存 manager 位推断
      if (!LC.has('can_catalog')) {
        LC.status.show({ kind: 'denied', code: 'FORBIDDEN',
                         message: '当前账号没有器件库权限，无法建档。' });
        return;
      }
      if (!item || String(item.item_key || '').indexOf('lcsc:') !== 0) {
        LC.status.show({
          kind: 'error',
          code: 'VALIDATION_ERROR',
          message: '只能对有立创编号的器件建档；本地档案请用「绑定」给它补一个编号。'
        });
        return;
      }
      if (isCreateLocked()) {
        LC.status.show({
          kind: 'unknown',
          code: 'PRECONDITION_FAILED',
          message: '上一次建档结果未知，建档入口仍锁定（记录在浏览器里，刷新不会消失）。',
          detail: '请先检索核对，再点「已核对：仍未建档」或「已核对：已经建档」。'
        });
        return;
      }
      submitCreate(item.item_key, null, button).then(function (data) {
        onCreated(data, item.item_key);
      }).catch(function (err) {
        handleCreateError(err, item.item_key, null, button);
      });
    }

    /* -------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action="materials-more"]', 'click', function (ev, btn) {
      search(btn, true);
    });

    LC.on(root, '[data-lc-action="materials-detail"]', 'click', function (ev, btn) {
      var item = findItem(btn.getAttribute('data-lc-inv-item-key'));
      if (!item) return;
      LC.status.clear();
      selectItem(item);
      loadDetail(item, btn);
    });

    LC.on(root, '[data-lc-action="materials-bind"]', 'click', function (ev, btn) {
      var item = findItem(btn.getAttribute('data-lc-inv-item-key'));
      if (!item) return;
      LC.status.clear();
      selectItem(item);
      if (bindForm) {
        var control = bindForm.elements.catalog_code;
        if (control) control.focus();
      }
      LC.status.show({
        kind: 'empty',
        message: '已选档案 ' + ((item.sn_codes || []).join('/') || localProfileText(item)) +
          '；在右侧选择具体本地档案、填好立创编号后点「保存绑定」。'
      });
    });

    LC.on(root, '[data-lc-action="materials-create-row"]', 'click', function (ev, btn) {
      var item = findItem(btn.getAttribute('data-lc-inv-item-key'));
      if (!item) return;
      LC.status.clear();
      selectItem(item);
      createFor(item, btn);
    });

    LC.on(root, '[data-lc-action="materials-create"]', 'click', function (ev, btn) {
      if (!selected) {
        LC.status.show({
          kind: 'error',
          code: 'VALIDATION_ERROR',
          message: '请先在左侧结果里选择一行器件，再按资料库建档。'
        });
        return;
      }
      LC.status.clear();
      createFor(selected, btn);
    });

    LC.on(root, '[data-lc-action="materials-create-selected"]', 'click', function (ev, btn) {
      var chosen = LC.qs('[data-lc-inv-candidate]:checked', root);
      var templateId = chosen ? chosen.getAttribute('data-lc-inv-candidate') : '';
      if (!templateId) {
        LC.status.show({
          kind: 'error',
          code: 'VALIDATION_ERROR',
          message: '请先选择一个本地档案（SN）。'
        });
        return;
      }
      if (isCreateLocked()) {
        LC.status.show({
          kind: 'unknown',
          code: 'PRECONDITION_FAILED',
          message: '上一次建档结果未知，建档入口仍锁定（记录在浏览器里，刷新不会消失）。',
          detail: '请先检索核对，再点「已核对：仍未建档」或「已核对：已经建档」。'
        });
        return;
      }
      LC.status.clear();
      submitCreate(pendingItemKey, templateId, btn).then(function (data) {
        onCreated(data, pendingItemKey);
      }).catch(function (err) {
        handleCreateError(err, pendingItemKey, templateId, btn);
      });
    });

    LC.on(root, '[data-lc-action="materials-verify"]', 'click', function (ev, btn) {
      // 只读核对：按未决记录的立创编号重新检索，不改锁定状态
      var record = createUnknown || {};
      var code = String(record.item_key || '').replace(/^lcsc:/i, '');
      if (searchForm && searchForm.elements.query) {
        searchForm.elements.query.value = code;
      }
      LC.status.show({
        kind: 'empty',
        message: '正在按 ' + (code || '原编号') + ' 重新检索：'
          + '列表里看不到不等于没提交（可能尚未刷新或被其他档案占用），请按统一料号 / SN 再确认。'
      });
      cursor = null;
      search(btn, false);
    });

    LC.on(root, '[data-lc-action="materials-unlock-absent"]', 'click', function () {
      if (!LC.confirmAction(
        '请先确认已按立创编号 / 统一料号 / SN 核对过：该器件确实还没有成功建档？\n'
        + '解除后再次建档会产生一条新的本地档案；本页不会自动重发。')) {
        return;
      }
      clearUnknown();
      renderLock();
      LC.status.show({
        kind: 'success',
        message: '已解除建档锁定（确认上次未建档）。请重新确认器件后再提交；这次提交会是一条新请求。'
      });
    });

    LC.on(root, '[data-lc-action="materials-unlock-present"]', 'click', function () {
      if (!LC.confirmAction(
        '确认上次建档已经生效、并在左侧列表里能看到该档案？\n'
        + '解除后请直接使用现有档案（绑定 / 入库），不要再重复建档。')) {
        return;
      }
      clearUnknown();
      renderLock();
      LC.status.show({
        kind: 'success',
        message: '已解除建档锁定（确认上次已建档）。请在左侧选择现有档案继续操作，不要重复建档。'
      });
    });

    LC.on(root, '[data-lc-action="materials-clear-candidates"]', 'click', function () {
      candidates = [];
      pendingItemKey = '';
      renderCandidates('');
    });

    if (searchForm) {
      LC.guard(searchForm, function (values, done) {
        var button = searchForm.querySelector('button[type="submit"]');
        done();
        cursor = null;
        if (!String(values.query || '').trim()) {
          LC.status.show({ kind: 'error', code: 'VALIDATION_ERROR', message: '请输入检索关键词。' });
          return;
        }
        search(button, false);
      });
    }

    if (bindForm) {
      LC.guard(bindForm, function (values, done) {
        var button = bindForm.querySelector('button[type="submit"]');
        if (!LC.has('can_catalog')) {
          done();
          LC.status.show({ kind: 'denied', code: 'FORBIDDEN',
                           message: '当前账号没有器件库权限。' });
          return;
        }
        if (!values.product_template_id) {
          done();
          LC.formError(bindForm, 'product_template_id',
            '请选择要绑定的本地档案；同一立创编号有多个档案时必须选具体 SN。');
          return;
        }
        if (!String(values.catalog_code || '').trim()) {
          done();
          LC.formError(bindForm, 'catalog_code', '请填写立创编号，例如 C12345。');
          return;
        }
        submitBind(values, button).then(function (data) {
          done();
          onBindDone(data, values);
        }).catch(function (err) {
          done(err);
          handleBindError(err, values, button);
        });
      });
    }

    // 首屏不自动提交：先恢复"上一次建档结果未知"的持久锁（跨刷新），再给操作提示
    createUnknown = readUnknown();
    renderLock();
    LC.setText(nodes.target, '未选择');
    LC.status.show({
      kind: 'empty',
      message: '输入名称、MPN、C 编号或 SN 开始检索；建档不会写入任何库存。'
    });
  });
})();
