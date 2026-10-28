/* ==========================================================================
 * lab_team_web · P3 扫码页（page_id = scan）
 * --------------------------------------------------------------------------
 * 扫一次 → resolve_code → 按 kind 分派（frontend-contract.md §7.1、ui-audit §4.4）：
 *   bag      → 袋摘要 + 袋追溯 / 领用 / 归还有未还行
 *   location → 库位摘要 + 该库位实物袋
 *   lcsc/jlc/sn → 器件摘要；同一 C 多档案给候选，**绝不取 first**
 *   unknown  → 中性提示 + 可识别前缀说明（不猜成袋）
 *
 * 摄像头：只做能力检测（BarcodeDetector），不加载任何第三方识码库、不用 CDN；
 * 不支持/被拒绝时明确提示，扫码枪（键盘回车）与手工粘贴始终可用。
 * 本页只读：所有写动作都在别的页面完成，这里只给站内链接。
 * ========================================================================== */
(function () {
  'use strict';

  if (!window.LC) return;

  var KIND_TEXT = {
    bag: '本系统袋追溯码（LABB:）',
    location: '库位库码（LABL:）',
    sn: '物料 SN',
    lcsc: '立创 C 编号',
    jlc: '立创原厂物料袋二维码',
    unknown: '未识别'
  };

  var camera = {
    supported: null,
    stream: null,
    detector: null,
    running: false,
    timer: 0
  };

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

  function showError(err, retryFn) {
    if (!err) return;
    if (err.unknown) {
      LC.status.show({
        kind: 'unknown',
        code: err.code,
        message: '结果未知（网络中断或超时）。核对网络后再扫一次；本页不写库存，不会产生重复记账。',
        retry: retryFn
      });
      return;
    }
    if (err.code === 'UNAUTHORIZED') return;
    LC.status.show({
      kind: err.code === 'FORBIDDEN' ? 'denied' : 'error',
      code: err.code,
      message: LC.errorText(err),
      retry: retryFn
    });
  }

  function scanInput() {
    return LC.qs('[data-lc-scan="scan"]');
  }

  function readRaw() {
    var input = scanInput();
    return input ? String(input.value || '').trim() : '';
  }

  /* ------------------------------------------------------------------ 结果渲染 */
  function clearResultAreas() {
    LC.show(q('data-lc-result', 'scan'), false);
    LC.show(q('data-lc-candidates', 'scan'), false);
    LC.show(q('data-lc-location-bags', 'scan'), false);
    LC.show(q('data-lc-item-bags', 'scan'), false);
    LC.clear(q('data-lc-actions', 'scan'));
  }

  function setKindBadge(kind) {
    var badge = slot('kind-badge');
    if (!badge) return;
    badge.textContent = KIND_TEXT[kind] || kind || '—';
    badge.setAttribute('data-tone', kind === 'unknown' ? 'warn' : 'ok');
  }

  function addAction(node) {
    var holder = q('data-lc-actions', 'scan');
    if (holder && node) holder.appendChild(node);
  }

  function addLink(text, href, outline) {
    if (!href) return;
    addAction(LC.el('a', {
      class: 'lc-btn ' + (outline ? 'lc-btn-outline' : 'lc-btn-ghost'),
      href: href,
      text: text
    }));
  }

  function bagsTable(rows, container) {
    var tbody = q('data-lc-rows', container);
    LC.renderRows(tbody, rows || [], function (bag) {
      var tr = LC.el('tr');
      tr.appendChild(LC.el('td', { class: 'lc-mono' }, [
        LC.el('a', { href: LC.urls.bag + bag.id, text: bag.trace_code })
      ]));
      tr.appendChild(LC.el('td', {
        text: [bag.name, bag.mpn, bag.package].filter(Boolean).join(' · ') || '—'
      }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(bag.quantity) }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(bag.available_quantity) }));
      tr.appendChild(LC.el('td', { text: LC.fmt.quantity(bag.outstanding_quantity) }));
      return tr;
    });
    LC.show(q('data-lc-empty', container), !(rows && rows.length));
  }

  function renderBag(data) {
    var bag = data.bag || {};
    setKindBadge('bag');
    setSlot('summary', '袋 ' + bag.trace_code + '：' + (bag.name || '—') +
      '，库位 ' + (bag.location_path || bag.location_code || '—') +
      '，在库 ' + LC.fmt.quantity(bag.quantity) +
      '，可用 ' + LC.fmt.quantity(bag.available_quantity) +
      '，未还 ' + LC.fmt.quantity(bag.outstanding_quantity));
    addLink('打开袋追溯', LC.urls.bag + bag.id, true);
    if (LC.has('can_issue')) {
      addLink('按袋领用', LC.base + '/lab/issues/new?bag_id=' + bag.id);
    }
    if (LC.has('can_return') && Number(bag.outstanding_quantity) > 0) {
      addLink('归还该袋', LC.base + '/lab/issues?q=' + encodeURIComponent(bag.trace_code || ''));
    }
    if (LC.has('can_issue')) {
      addLink('再建一条同料号待入库', LC.urls.receipts + '?tab=prepare&item_key=' +
        encodeURIComponent(bag.item_key || ''));
    }
  }

  function renderLocation(data) {
    var location = data.location || {};
    setKindBadge('location');
    setSlot('summary', '库位 ' + (location.code || '—') + '：' +
      (location.path || location.name || '—') + '。下面是该库位（含子库位）的在库袋。');
    addLink('看库位管理页', LC.urls.locations, true);
    LC.show(q('data-lc-location-bags', 'scan'), true);
    areaLoading('location-bags', true);
    LC.rpc('bags', {
      location_id: location.id,
      has_stock: true,
      limit: LC.limits.pageSize
    }).then(function (result) {
      areaLoading('location-bags', false);
      var rows = (result && result.bags) || [];
      bagsTable(rows, 'location-bags');
      var count = q('data-lc-count', 'location-bags');
      if (count) count.textContent = '本页 ' + rows.length + ' 个袋';
    }).catch(function (err) {
      areaLoading('location-bags', false);
      LC.show(q('data-lc-location-bags', 'scan'), false);
      showError(err, function () { resolve(readRaw()); });
    });
  }

  function renderCandidates(candidates, itemKey) {
    LC.show(q('data-lc-candidates', 'scan'), true);
    var tbody = q('data-lc-rows', 'candidates');
    LC.renderRows(tbody, candidates, function (candidate) {
      var tr = LC.el('tr');
      var radio = LC.el('input', {
        type: 'radio',
        name: 'candidate',
        value: String(candidate.product_template_id),
        'aria-label': '选择档案 ' + candidate.product_template_id
      });
      radio.addEventListener('change', function () {
        var target = q('data-lc-action', 'candidate-receipt');
        if (!target) return;
        target.disabled = false;
        target.setAttribute('data-template-id', String(candidate.product_template_id));
      });
      tr.appendChild(LC.el('td', {}, [radio]));
      tr.appendChild(LC.el('td', { class: 'lc-mono', text: candidate.sn || '—' }));
      tr.appendChild(LC.el('td', { text: candidate.name || '—' }));
      tr.appendChild(LC.el('td', { text: candidate.mpn || '—' }));
      tr.appendChild(LC.el('td', { text: candidate.package || '—' }));
      return tr;
    });
    var button = q('data-lc-action', 'candidate-receipt');
    if (button) {
      button.setAttribute('data-item-key', itemKey || '');
      button.disabled = true;
    }
    setSlot('summary', '同一编号在本地有 ' + candidates.length + ' 个档案：必须在下方表格里选一个，' +
      '系统不会自动选择，避免把新袋绑错档案。');
  }

  function renderItem(data) {
    var material = data.material || {};
    var supplier = data.supplier_metadata || {};
    var kind = data.kind || (supplier.order_no ? 'jlc' : 'lcsc');
    setKindBadge(kind);
    var lines = [];
    lines.push((material.item_key || data.item_key || '—'));
    if (material.name) lines.push(material.name);
    if (material.mpn) lines.push('型号 ' + material.mpn);
    if (material.package) lines.push('封装 ' + material.package);
    if (material.sn) lines.push('SN ' + material.sn);
    lines.push('实验室库存 ' + LC.fmt.quantity(material.lab_quantity) +
      '（袋 ' + (material.bag_count === undefined ? '—' : material.bag_count) + ' 个）');
    if (supplier.order_no || supplier.mpn) {
      lines.push('原厂袋：订单 ' + (supplier.order_no || '—') +
        ' · 型号 ' + (supplier.mpn || '—') +
        ' · 数量 ' + (supplier.quantity === undefined || supplier.quantity === null ? '—' : supplier.quantity));
      if (supplier.is_valid === false) {
        lines.push('原厂袋二维码缺少立创编号，无法直接对应本地档案；请补扫 C 编号标签。');
      }
    }
    setSlot('summary', lines.join('；'));

    if (data.item_key) {
      addLink('去建待入库袋', LC.urls.receipts + '?tab=prepare&item_key=' +
        encodeURIComponent(data.item_key), true);
    }
    if (material.product_template_id) {
      addLink('看该器件实物袋', LC.urls.bags + '?q=' +
        encodeURIComponent(material.mpn || material.name || ''));
    }

    var bags = data.bags || [];
    LC.show(q('data-lc-item-bags', 'scan'), true);
    bagsTable(bags, 'item-bags');
  }

  /* ------------------------------------------------------------------ 解析 */
  function resolve(raw) {
    var value = raw === undefined ? readRaw() : String(raw || '').trim();
    if (!value) {
      areaError('resolve', '请先扫码或粘贴编码。');
      return;
    }
    areaError('resolve', '');
    areaLoading('resolve', true);
    LC.rpc('resolve', { raw: value }).then(function (data) {
      areaLoading('resolve', false);
      clearResultAreas();
      LC.show(q('data-lc-result', 'scan'), true);
      LC.show(q('data-lc-empty', 'result'), false);
      setSlot('raw', data.raw || value);
      setSlot('normalized', data.normalized || '—');
      var kind = data.kind || 'unknown';

      if (kind === 'bag' && data.bag) {
        renderBag(data);
        return;
      }
      if (kind === 'location' && data.location) {
        renderLocation(data);
        return;
      }
      if (data.candidates && data.candidates.length > 1) {
        setKindBadge(kind);
        renderCandidates(data.candidates, data.item_key);
        return;
      }
      if (data.material) {
        renderItem(data);
        return;
      }
      setKindBadge(kind);
      setSlot('summary', '已识别为' + (KIND_TEXT[kind] || kind) + '，但没有对应的本地记录。');
      if (data.item_key) {
        addLink('去建待入库袋', LC.urls.receipts + '?tab=prepare&item_key=' +
          encodeURIComponent(data.item_key), true);
      }
    }).catch(function (err) {
      areaLoading('resolve', false);
      var fields = (err && err.fields) || {};
      if (err && err.code === 'VALIDATION_ERROR' && fields.raw === 'unknown') {
        clearResultAreas();
        LC.show(q('data-lc-empty', 'result'), true);
        areaError('resolve', '');
        notify('无法识别该编码：可识别 LABB: 袋追溯码、LABL: 库位库码、C 开头的立创编号、' +
          '物料 SN（形如 LAB-000123）或立创原厂物料袋二维码。系统不会猜成某个袋。', 'empty');
        return;
      }
      clearResultAreas();
      if (err && err.code === 'PRECONDITION_FAILED') {
        // 典型：扫到本人待入库袋（尚未入库）——明确引导去「扫码上架」
        areaError('resolve', '');
        LC.status.show({
          kind: 'error',
          code: err.code,
          message: err.message || LC.errorText(err)
        });
        LC.show(q('data-lc-result', 'scan'), true);
        setKindBadge('bag');
        setSlot('raw', value);
        setSlot('normalized', '—');
        setSlot('summary', '这是尚未入库（或已取消）的待入库袋：需要到「采购入库 → 扫码上架」确认入库。');
        addLink('去扫码上架', LC.urls.receipts + '?tab=shelve&scan=' +
          encodeURIComponent(value), true);
        return;
      }
      if (err && err.code === 'NOT_FOUND') {
        areaError('resolve', '找不到对应记录：可能已删除或不属于当前公司。');
        return;
      }
      areaError('resolve', '解析失败：' + LC.errorText(err));
      showError(err, function () { resolve(value); });
    });
  }

  /* ------------------------------------------------------------------ 摄像头 */
  function cameraNote(message, kind) {
    var node = q('data-lc-camera-note', 'scan');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('lc-alert-error', kind === 'error');
  }

  function cameraStatus(message) {
    var node = q('data-lc-camera-status', 'scan');
    if (node) node.textContent = message || '';
  }

  function stopCamera() {
    camera.running = false;
    if (camera.timer) {
      window.clearTimeout(camera.timer);
      camera.timer = 0;
    }
    var video = LC.qs('.lc-camera-video');
    if (video) {
      try { video.pause(); } catch (error) { /* 忽略 */ }
      video.srcObject = null;
    }
    if (camera.stream) {
      try {
        camera.stream.getTracks().forEach(function (track) { track.stop(); });
      } catch (error) { /* 忽略 */ }
      camera.stream = null;
    }
    LC.show(q('data-lc-camera', 'scan'), false);
    var toggle = q('data-lc-action', 'camera-toggle');
    if (toggle) toggle.textContent = '打开摄像头';
  }

  function detectSupported() {
    if (camera.supported !== null) return Promise.resolve(camera.supported);
    if (typeof window.BarcodeDetector !== 'function') {
      camera.supported = false;
      return Promise.resolve(false);
    }
    var formats = window.BarcodeDetector.getSupportedFormats;
    if (typeof formats !== 'function') {
      camera.supported = true;
      return Promise.resolve(true);
    }
    return window.BarcodeDetector.getSupportedFormats().then(function (list) {
      var values = list || [];
      camera.supported = values.indexOf('qr_code') !== -1;
      return camera.supported;
    }).catch(function () {
      camera.supported = false;
      return false;
    });
  }

  function tick() {
    if (!camera.running) return;
    var video = LC.qs('.lc-camera-video');
    if (!video || !camera.detector) return;
    if (video.readyState < 2) {
      camera.timer = window.setTimeout(tick, 300);
      return;
    }
    camera.detector.detect(video).then(function (codes) {
      if (!camera.running) return;
      if (codes && codes.length && codes[0].rawValue) {
        var value = String(codes[0].rawValue).trim();
        stopCamera();
        var input = scanInput();
        if (input && value) input.value = value;
        cameraStatus('已识别：' + value);
        resolve(value);
        return;
      }
      camera.timer = window.setTimeout(tick, 400);
    }).catch(function () {
      if (!camera.running) return;
      camera.timer = window.setTimeout(tick, 800);
    });
  }

  function startCamera() {
    detectSupported().then(function (supported) {
      if (!supported) {
        cameraNote('当前浏览器不支持 BarcodeDetector（或缺少 qr_code 格式），无法用摄像头识码。' +
          '请用扫码枪（键盘输入 + 回车）或手工粘贴编码；也可以到「扫码枪」模式继续。', 'error');
        cameraStatus('');
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        cameraNote('当前页面不是安全来源（需 https 或 localhost），浏览器不提供摄像头能力。' +
          '请用扫码枪或手工粘贴编码。', 'error');
        return;
      }
      LC.show(q('data-lc-camera', 'scan'), true);
      cameraStatus('正在打开摄像头…');
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
        .then(function (stream) {
          camera.stream = stream;
          var video = LC.qs('.lc-camera-video');
          if (!video) return;
          video.srcObject = stream;
          var played = video.play();
          if (played && typeof played.catch === 'function') {
            played.catch(function () { /* 自动播放被拒绝时用户仍可手工输入 */ });
          }
          camera.detector = new window.BarcodeDetector({
            formats: ['qr_code', 'code_128', 'ean_13']
          });
          camera.running = true;
          cameraStatus('已打开摄像头，对准二维码；识别到内容会自动解析。');
          var toggle = q('data-lc-action', 'camera-toggle');
          if (toggle) toggle.textContent = '关闭摄像头';
          tick();
        })
        .catch(function (error) {
          LC.show(q('data-lc-camera', 'scan'), false);
          var name = error && error.name ? error.name : '';
          if (name === 'NotAllowedError' || name === 'SecurityError') {
            cameraNote('摄像头权限被拒绝：请在浏览器地址栏重新允许本站使用摄像头，' +
              '或改用扫码枪 / 手工粘贴编码。', 'error');
          } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
            cameraNote('没有找到可用摄像头；请改用扫码枪或手工粘贴编码。', 'error');
          } else {
            cameraNote('摄像头打开失败（' + (name || '未知错误') + '）；请改用扫码枪或手工粘贴编码。', 'error');
          }
          cameraStatus('');
        });
    });
  }

  function toggleCamera() {
    if (camera.running) stopCamera();
    else startCamera();
  }

  /* ------------------------------------------------------------------ 事件 */
  function wireActions(root) {
    LC.on(root, '[data-lc-action]', 'click', function (ev, node) {
      var action = node.getAttribute('data-lc-action');
      if (action === 'resolve') {
        ev.preventDefault();
        resolve(readRaw());
        return;
      }
      if (action === 'camera-toggle') { ev.preventDefault(); toggleCamera(); return; }
      if (action === 'camera-stop') { ev.preventDefault(); stopCamera(); return; }
      if (action === 'candidate-receipt') {
        ev.preventDefault();
        var itemKey = node.getAttribute('data-item-key') || '';
        var templateId = node.getAttribute('data-template-id') || '';
        if (!templateId) {
          notify('请先在表格里选择一个本地档案。');
          return;
        }
        LC.navigate(LC.urls.receipts + '?tab=prepare&item_key=' +
          encodeURIComponent(itemKey) + '&product_template_id=' + encodeURIComponent(templateId));
        return;
      }
    });
  }

  function wireScanInput(root) {
    LC.on(root, '[data-lc-scan]', 'keydown', function (ev) {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      resolve(readRaw());
    });
  }

  /* ------------------------------------------------------------------ 初始化 */
  LC.register('scan', function (ctx) {
    var root = ctx.root;
    wireActions(root);
    wireScanInput(root);

    LC.show(q('data-lc-empty', 'result'), true);
    LC.show(q('data-lc-result', 'scan'), false);

    detectSupported().then(function (supported) {
      var toggle = q('data-lc-action', 'camera-toggle');
      if (!supported) {
        if (toggle) {
          toggle.disabled = true;
          toggle.setAttribute('aria-disabled', 'true');
          toggle.textContent = '摄像头不可用';
        }
        cameraNote('当前浏览器不支持 BarcodeDetector，摄像头识码不可用；' +
          '扫码枪（键盘输入 + 回车）与手工粘贴编码可以正常使用。', 'error');
        return;
      }
      cameraNote('摄像头识码已就绪：点「打开摄像头」后对准二维码。' +
        '也可以随时改用扫码枪或手工粘贴（回车即解析）。');
    });

    window.addEventListener('focus', function () {
      var input = scanInput();
      if (input && !camera.running && !input.value) input.focus();
    }, { once: true });

    var raw = ctx.page.query.get('raw') || ctx.page.query.get('scan') || readRaw();
    if (raw) resolve(raw);
  });
})();
