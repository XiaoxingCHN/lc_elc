/* ==========================================================================
 * lab_team_web · 客户端脚本（原生 ES2019，无框架）
 * --------------------------------------------------------------------------
 * 本文件不依赖 Odoo WebClient / OWL / jQuery，只读取 body 上的 data-* 契约：
 *   data-base         挂载前缀（"" 或 "/team"）
 *   data-authenticated "1" | "0"
 *   data-api-search   /lab/api/catalog/search
 *
 * 关键决策：
 * 1. 登录只调用 Odoo 原生 /web/session/authenticate（或模板给出的 endpoint），
 *    不自己保存任何凭据，也不写浏览器持久存储。
 * 2. 仓库检索采用"序号 + AbortController"双重防竞态：旧的响应即使回来也会被
 *    序号丢弃；新请求会主动中止旧请求，避免慢响应覆盖新结果。
 * 3. 检索失败时只显示 .lc-alert-error，**不清空**已有卡片；只有成功响应才替换
 *    或追加列表，这样网络抖动不会让用户丢掉当前结果。
 * 4. URL 在检索成功后才同步（q / category_id / stock_only）：地址栏始终对应
 *    屏幕上真实可见的结果。打字触发的自动检索用 replaceState，避免每个字符
 *    都生成一条历史记录；表单提交、分类、只看库存用 pushState。
 * 5. 渲染一律使用 createElement + textContent，不拼接 HTML 字符串，服务端
 *    返回的文本不会被当作 HTML 执行。
 * 6. 图片加载失败时替换为 .lc-item-noimg 占位，不伪造图片。
 * ========================================================================== */
(function () {
  'use strict';

  var body = document.body;
  if (!body || !body.classList.contains('lc-body')) return;

  var BASE = normalizeBase(body.getAttribute('data-base'));
  var AUTHENTICATED = body.getAttribute('data-authenticated') === '1';
  var SEARCH_ENDPOINT = body.getAttribute('data-api-search') || '/lab/api/catalog/search';
  var PAGE_SIZE = 24;

  // ------------------------------------------------------------------ 基础工具
  function normalizeBase(value) {
    var base = typeof value === 'string' ? value.trim() : '';
    if (!base) return '';
    while (base.length > 1 && base.charAt(base.length - 1) === '/') {
      base = base.slice(0, -1);
    }
    if (base.charAt(0) !== '/') base = '/' + base;
    return base === '/' ? '' : base;
  }

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function setHidden(element, hidden) {
    if (!element) return;
    if (hidden) element.setAttribute('hidden', '');
    else element.removeAttribute('hidden');
  }

  function requestError(message) {
    var error = new Error(message);
    error.userMessage = message;
    return error;
  }

  /**
   * 深链接回跳安全校验：与后端 tools/paths.normalize_next 同一套判定。
   *
   * 历史缺陷：旧实现用 value.split('?')[0].indexOf(':') 拒绝任何冒号，
   * 导致 /lab/items/lcsc:C123 这类合法业务路径被改写成仓库首页，登录后回不到详情。
   * 现在只做同源判断：单斜杠开头、非协议相对、无反斜杠/控制字符，
   * 并对百分号编码最多解码 3 轮后再校验，拦截 %2f%2f、%5C 这类绕过。
   */
  function safeNext(raw) {
    var fallback = BASE + '/lab';
    var value = typeof raw === 'string' ? raw.trim() : '';
    if (!value || value.charAt(0) !== '/') return fallback;

    function safeShape(text) {
      if (!text || text.charAt(0) !== '/') return false;
      if (text.charAt(1) === '/') return false;
      if (text.indexOf('\\') !== -1) return false;
      if (/[\u0000-\u001f\u007f]/.test(text)) return false;
      if (text.indexOf('://') !== -1) return false;
      return true;
    }

    function decodeOnce(text) {
      try {
        return decodeURIComponent(text);
      } catch (error) {
        return null;
      }
    }

    var probe = value;
    for (var i = 0; i < 3; i += 1) {
      if (!safeShape(probe)) return fallback;
      var decoded = decodeOnce(probe);
      if (decoded === null) return fallback;
      if (decoded === probe) break;
      probe = decoded;
    }
    if (!safeShape(probe)) return fallback;
    return value;
  }

  function itemHref(itemKey) {
    // 与后端 quote_item_key 对齐：保留 [A-Za-z0-9:._-]，其余百分号编码，
    // 这样地址栏是 /lab/items/lcsc:C123，而不是 lcsc%3AC123。
    var raw = String(itemKey == null ? '' : itemKey);
    var out = '';
    for (var i = 0; i < raw.length; i += 1) {
      var ch = raw.charAt(i);
      if (/[A-Za-z0-9:._-]/.test(ch)) out += ch;
      else out += encodeURIComponent(ch);
    }
    return BASE + '/lab/items/' + out;
  }

  /** 图片走 lab_catalog 既有的缓存代理；已经是站内路径的直接使用。 */
  function imageSrc(url) {
    var value = typeof url === 'string' ? url.trim() : '';
    if (!value) return '';
    if (value.charAt(0) === '/' && value.charAt(1) !== '/') return value;
    return '/lab/api/asset?url=' + encodeURIComponent(value);
  }

  function formatQuantity(value) {
    if (value === null || value === undefined || value === '') return '—';
    var number = Number(value);
    if (!isFinite(number)) return '—';
    if (Number.isInteger(number)) return String(number);
    return number.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  }

  function formatPrice(item) {
    var raw = item.price;
    if (raw === null || raw === undefined || raw === '') return '价格待询';
    var number = Number(raw);
    if (!isFinite(number)) return '价格待询';
    var currency = (item.currency || 'CNY').toUpperCase();
    var symbols = { CNY: '¥', RMB: '¥', USD: '$', EUR: '€' };
    var text = Number.isInteger(number) ? String(number) : number.toFixed(2);
    return (symbols[currency] || currency + ' ') + text;
  }

  /**
   * 统一的 JSON-RPC POST。
   * Odoo 的 /web/session/authenticate 与 /lab/api/* 都使用同一套会话 cookie，
   * 因此必须带 credentials: same-origin；不手工塞任何 token 到 URL 或日志。
   */
  async function postJson(url, params, signal) {
    var options = {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'call',
        params: params || {},
      }),
    };
    if (signal) options.signal = signal;

    var response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (error && error.name === 'AbortError') throw error;
      throw requestError('网络异常，请重试');
    }

    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        throw requestError('登录状态已失效，请重新登录。');
      }
      throw requestError('请求失败（' + response.status + '），请稍后重试。');
    }

    var contentType = response.headers.get('Content-Type') || '';
    if (contentType.indexOf('json') === -1) {
      // 会话过期时 Odoo 可能 303 到登录页，fetch 跟随重定向后拿到的是 HTML。
      throw requestError('登录状态已失效，请重新登录。');
    }

    try {
      return await response.json();
    } catch (error) {
      throw requestError('服务器返回异常，请稍后重试。');
    }
  }

  // ------------------------------------------------------------------ 登录页
  function initLogin() {
    var form = document.getElementById('lc-login-form');
    if (!form) return;

    var errorEl = $('.lc-form-error', form);
    var button = $('button[type="submit"]', form) || $('button', form);
    var defaultLabel = button ? button.textContent : '登录';
    var busy = false;

    function showError(message) {
      if (!errorEl) return;
      if (message) {
        errorEl.textContent = message;
        setHidden(errorEl, false);
      } else {
        errorEl.textContent = '';
        setHidden(errorEl, true);
      }
    }

    function setBusy(on) {
      busy = on;
      form.setAttribute('aria-busy', on ? 'true' : 'false');
      if (button) {
        button.disabled = on;
        button.textContent = on ? '登录中…' : defaultLabel;
      }
    }

    /** Odoo 认证失败通常包在 error.data.message；AccessDenied 为英文时转中文。 */
    function loginErrorMessage(payload) {
      var error = payload && payload.error;
      var message = '';
      if (error && error.data && typeof error.data.message === 'string') {
        message = error.data.message.trim();
      }
      if (!message && error && typeof error.message === 'string') {
        message = error.message.trim();
      }
      if (!message) return '账号或密码不正确，请重试。';
      if (/access\s*denied|accessdenied|invalid\s+credentials|odoo\s+server\s+error/i.test(message)) {
        return '账号或密码不正确，请重试。';
      }
      return message;
    }

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if (busy) return;

      var loginInput = $('input[name="login"]', form);
      var passwordInput = $('input[name="password"]', form);
      var login = loginInput ? loginInput.value.trim() : '';
      var password = passwordInput ? passwordInput.value : '';
      var db = form.getAttribute('data-db') || '';
      var endpoint = form.getAttribute('data-endpoint') || '/web/session/authenticate';
      var next = safeNext(form.getAttribute('data-next'));

      showError('');
      if (!login) {
        showError('请输入用户名。');
        if (loginInput) loginInput.focus();
        return;
      }
      if (!password) {
        showError('请输入密码。');
        if (passwordInput) passwordInput.focus();
        return;
      }

      setBusy(true);
      try {
        var payload = await postJson(endpoint, {
          db: db,
          login: login,
          password: password,
        });

        if (payload && payload.error) {
          showError(loginErrorMessage(payload));
          if (passwordInput) {
            passwordInput.value = '';
            passwordInput.focus();
          }
          return;
        }

        var result = payload && payload.result;
        if (result && result.uid) {
          // 成功密码立即从 DOM 清掉，再跳转；不需要也不允许保存凭据。
          if (passwordInput) passwordInput.value = '';
          window.location.assign(next);
          return;
        }

        showError('账号或密码不正确，请重试。');
        if (passwordInput) {
          passwordInput.value = '';
          passwordInput.focus();
        }
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        showError(error && error.userMessage ? error.userMessage : '网络异常，请重试');
      } finally {
        setBusy(false);
      }
    });
  }

  // ------------------------------------------------------------------ 图片失败占位
  function makeImagePlaceholder() {
    var placeholder = document.createElement('div');
    placeholder.className = 'lc-item-noimg';
    placeholder.textContent = '无图';
    placeholder.setAttribute('role', 'img');
    placeholder.setAttribute('aria-label', '无图');
    return placeholder;
  }

  function isTrackedImage(image) {
    if (!image || image.tagName !== 'IMG') return false;
    if (image.classList.contains('lc-item-img')) return true;
    return !!image.closest('.lc-detail-media');
  }

  function replaceBrokenImage(image) {
    if (!image || !image.parentNode) return;
    var holder = image.closest('.lc-item-media, .lc-detail-media');
    if (!holder) return;
    if (holder.querySelector('.lc-item-noimg')) {
      image.parentNode.removeChild(image);
      return;
    }
    holder.replaceChild(makeImagePlaceholder(), image);
  }

  function initImageFallbacks() {
    // 资源加载失败不会冒泡，但可以在捕获阶段到达 document。
    document.addEventListener('error', function (event) {
      if (isTrackedImage(event.target)) replaceBrokenImage(event.target);
    }, true);

    // 处理脚本执行前就已经加载失败（命中缓存）的图片。
    $all('img.lc-item-img, .lc-detail-media img').forEach(function (image) {
      if (image.complete && image.naturalWidth === 0) replaceBrokenImage(image);
    });
  }

  // ------------------------------------------------------------------ 仓库页
  function initWarehouse() {
    if (!AUTHENTICATED) return; // 未登录绝不发检索请求

    var form = document.getElementById('lc-search-form');
    var input = document.getElementById('lc-q');
    var stockOnlyInput = document.getElementById('lc-stock-only');
    var results = document.getElementById('lc-results');
    var grid = document.getElementById('lc-grid');
    if (!results || !grid) return;

    // 实际 QWeb 模板把检索表单放在 .lc-results 内部、分类侧栏之后。
    // 增强模式下把它提升到 .lc-lab 的第一个子元素，既符合"检索优先"的
    // 视觉顺序，也让键盘 Tab 顺序与视觉顺序一致；无 JS 时仍按模板顺序可用。
    if (form && form.parentNode === results) {
      var labWrapper = results.parentNode;
      if (labWrapper && labWrapper.classList.contains('lc-lab')) {
        labWrapper.insertBefore(form, labWrapper.firstChild);
      }
    }

    var more = document.getElementById('lc-more');
    var metaEl = $('.lc-results-meta', results);
    var moreLabel = more && more.textContent.trim() ? more.textContent.trim() : '加载更多';
    var pagePath = window.location.pathname;

    var state = {
      categoryId: '',
      nextCursor: null,
      total: 0,
      loading: false,
      sequence: 0,
      controller: null,
      lastKey: '',
      lastFilters: null,
    };

    var initialParams = new URLSearchParams(window.location.search);
    var initialCategory = (initialParams.get('category_id') || '').trim();
    if (!initialCategory) {
      var initialActive = $('.lc-cats a.lc-cat.is-active');
      initialCategory = initialActive ? (initialActive.getAttribute('data-category-id') || '').trim() : '';
    }
    state.categoryId = initialCategory;
    state.nextCursor = more ? (more.getAttribute('data-cursor') || '').trim() || null : null;

    // ---------------------------------------------------------- 状态区元素
    function insertBeforeGrid(element) {
      if (grid.parentNode === results) results.insertBefore(element, grid);
      else results.appendChild(element);
    }

    function ensureAlert() {
      var element = $('.lc-alert.lc-alert-error', results);
      if (!element) {
        element = document.createElement('div');
        element.className = 'lc-alert lc-alert-error';
        element.setAttribute('role', 'alert');
        element.setAttribute('aria-live', 'assertive');
        setHidden(element, true);
        insertBeforeGrid(element);
      }
      return element;
    }

    function ensureLoading() {
      var element = $('.lc-loading', results);
      if (!element) {
        element = document.createElement('div');
        element.className = 'lc-loading';
        element.textContent = '加载中…';
        element.setAttribute('role', 'status');
        element.setAttribute('aria-live', 'polite');
        setHidden(element, true);
        insertBeforeGrid(element);
      }
      return element;
    }

    function ensureEmpty() {
      var element = $('.lc-empty', results);
      if (!element) {
        element = document.createElement('div');
        element.className = 'lc-empty';
        element.textContent = '没有匹配的器件，试试其他关键词或调整筛选条件。';
        setHidden(element, true);
        results.appendChild(element);
      }
      return element;
    }

    function bindMoreButton(button) {
      if (!button || button.getAttribute('data-lc-bound') === '1') return;
      button.setAttribute('data-lc-bound', '1');
      button.addEventListener('click', function () {
        if (state.loading || !state.nextCursor) return;
        performSearch(false, 'none', false);
      });
    }

    /**
     * 服务端模板只在初始检索有下一页时才渲染 #lc-more。若初始为空、
     * JS 重新检索后才有 next_cursor，就需要在这里补一个按钮，
     * 否则"加载更多"能力只对首屏恰好有多页的情况生效。
     */
    function ensureMoreButton() {
      if (more) return more;
      more = document.createElement('button');
      more.type = 'button';
      more.id = 'lc-more';
      more.className = 'lc-btn lc-load-more';
      more.textContent = moreLabel;
      setHidden(more, true);
      var empty = $('.lc-empty', results);
      if (empty && empty.parentNode === results) results.insertBefore(more, empty);
      else results.appendChild(more);
      bindMoreButton(more);
      return more;
    }

    var alertEl = ensureAlert();
    var loadingEl = ensureLoading();
    var emptyEl = ensureEmpty();
    setHidden(loadingEl, true);
    // 服务端首次检索失败时会直接渲染 .lc-alert-error。有内容时必须保留，
    // 否则会把"真实错误"显示成"空结果"；用户发起新请求时再清掉。
    var hasServerAlert = !!(alertEl && alertEl.textContent.trim());
    if (!hasServerAlert) setHidden(alertEl, true);
    // 有服务端错误时不要再叠加"没有匹配"的空状态，两者互相矛盾。
    setHidden(emptyEl, hasServerAlert || grid.children.length > 0);

    // ---------------------------------------------------------- 读 / 写界面
    function readFilters() {
      var query = input ? input.value.trim() : '';
      var categoryId = state.categoryId;
      if (!categoryId) {
        var active = $('.lc-cats a.lc-cat.is-active');
        categoryId = active ? (active.getAttribute('data-category-id') || '').trim() : '';
      }
      return {
        query: query,
        categoryId: categoryId,
        stockOnly: !!(stockOnlyInput && stockOnlyInput.checked),
      };
    }

    function filtersKey(filters) {
      return JSON.stringify([filters.query, filters.categoryId, filters.stockOnly ? '1' : '0']);
    }

    function setActiveCategory(categoryId) {
      var target = String(categoryId || '').trim();
      $all('.lc-cats a.lc-cat').forEach(function (link) {
        var value = (link.getAttribute('data-category-id') || '').trim();
        var active = value === target;
        link.classList.toggle('is-active', active);
        if (active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
    }

    // 服务端只给 .is-active，这里补齐 aria-current，屏幕阅读器可识别当前分类。
    setActiveCategory(state.categoryId);

    /**
     * 服务端模板的 .lc-results-meta 还带「只看有库存 / 关键词」后缀，
     * 只改 <b> 会让筛选条件变化后仍显示旧后缀。这里按当前 filters 重建，
     * 全部用 textContent，避免把用户输入当 HTML。
     */
    /** 分类链接保持与当前筛选一致，支持 Ctrl/中键新标签打开。 */
    function categoryHref(categoryId, filters) {
      var params = new URLSearchParams();
      if (filters.query) params.set('q', filters.query);
      if (categoryId) params.set('category_id', String(categoryId));
      if (filters.stockOnly) params.set('stock_only', '1');
      var queryString = params.toString();
      return BASE + '/lab' + (queryString ? '?' + queryString : '');
    }

    function syncCategoryLinks(filters) {
      $all('.lc-cats a.lc-cat').forEach(function (link) {
        var categoryId = (link.getAttribute('data-category-id') || '').trim();
        link.href = categoryHref(categoryId, filters);
      });
    }

    function setMetaTotal(total, filters) {
      if (!metaEl) return;
      metaEl.textContent = '';

      metaEl.appendChild(document.createTextNode('共 '));
      var bold = document.createElement('b');
      bold.textContent = String(total);
      metaEl.appendChild(bold);
      metaEl.appendChild(document.createTextNode(' 件'));

      if (filters && filters.stockOnly) {
        var stockMeta = document.createElement('span');
        stockMeta.textContent = ' · 只看有库存';
        metaEl.appendChild(stockMeta);
      }
      if (filters && filters.query) {
        var queryMeta = document.createElement('span');
        queryMeta.textContent = ' · 关键词：' + filters.query;
        metaEl.appendChild(queryMeta);
      }
    }

    function showAlert(message) {
      alertEl.textContent = message;
      setHidden(alertEl, false);
    }

    function hideAlert() {
      alertEl.textContent = '';
      setHidden(alertEl, true);
    }

    function setBusy(on, isMore) {
      results.classList.toggle('is-loading', on);
      results.setAttribute('aria-busy', on ? 'true' : 'false');
      setHidden(loadingEl, !on);
      if (more) {
        more.disabled = !!on;
        more.textContent = on && isMore ? '加载中…' : moreLabel;
      }
    }

    // ---------------------------------------------------------- 卡片渲染
    function buildCard(item) {
      if (!item || !item.item_key) return null;
      var key = String(item.item_key);

      var card = document.createElement('article');
      card.className = 'lc-item';
      card.setAttribute('data-item-key', key);

      var link = document.createElement('a');
      link.className = 'lc-item-link';
      link.href = itemHref(key);

      var media = document.createElement('div');
      media.className = 'lc-item-media';
      var imageUrl = typeof item.image_url === 'string' ? item.image_url.trim() : '';
      if (imageUrl) {
        var image = document.createElement('img');
        image.className = 'lc-item-img';
        image.src = imageSrc(imageUrl);
        image.alt = item.name ? String(item.name) : '器件图片';
        image.loading = 'lazy';
        image.decoding = 'async';
        media.appendChild(image);
      } else {
        media.appendChild(makeImagePlaceholder());
      }

      var bodyEl = document.createElement('div');
      bodyEl.className = 'lc-item-body';

      var code = document.createElement('div');
      code.className = 'lc-item-code';
      // 与服务端模板一致：没有 C 编号时直接显示 item_key（lab:<id>）。
      code.textContent = item.catalog_code ? String(item.catalog_code) : key;

      var name = document.createElement('h3');
      name.className = 'lc-item-name';
      name.textContent = item.name ? String(item.name) : '未命名器件';

      var meta = document.createElement('div');
      meta.className = 'lc-item-meta';
      var metaParts = [];
      // 顺序与服务端模板保持一致：MPN、品牌、封装。
      if (item.mpn) metaParts.push(String(item.mpn));
      if (item.brand) metaParts.push(String(item.brand));
      if (item.package) metaParts.push(String(item.package));
      if (!metaParts.length && item.category_name) metaParts.push(String(item.category_name));
      meta.textContent = metaParts.length ? metaParts.join(' · ') : '—';

      var foot = document.createElement('div');
      foot.className = 'lc-item-foot';

      var quantity = Number(item.lab_quantity);
      var hasStock = !!item.has_stock || (isFinite(quantity) && quantity > 0);

      var stock = document.createElement('span');
      stock.className = 'lc-stock ' + (hasStock ? 'lc-in-stock' : 'lc-no-stock');
      // 与服务端模板一致：显示实验室总库存；可用量放在 title 里，
      // 避免初次渲染和 JS 追加卡片出现两套措辞。
      stock.textContent = hasStock
        ? '库存 ' + formatQuantity(item.lab_quantity)
        : '无库存';
      stock.title = '实验室库存 ' + formatQuantity(item.lab_quantity) +
        '，可用 ' + formatQuantity(item.lab_available_quantity);

      foot.appendChild(stock);

      // 契约要求卡片脚注带 .lc-item-price。当前 pages.xml 的服务端卡片
      // 还没有价格节点，建议模板同步补上；JS 追加卡片先按契约输出，
      // 价格缺失时显示"价格待询"，不伪造数值。
      var price = document.createElement('span');
      price.className = 'lc-item-price';
      price.textContent = formatPrice(item);
      foot.appendChild(price);

      bodyEl.appendChild(code);
      bodyEl.appendChild(name);
      bodyEl.appendChild(meta);
      bodyEl.appendChild(foot);

      link.appendChild(media);
      link.appendChild(bodyEl);
      card.appendChild(link);
      return card;
    }

    /** reset=true 时替换整个列表；false 时按 item_key 去重后追加。 */
    function appendItems(items, reset) {
      var seen = Object.create(null);
      if (!reset) {
        $all('.lc-item', grid).forEach(function (card) {
          var key = card.getAttribute('data-item-key');
          if (key) seen[key] = true;
        });
      } else {
        grid.textContent = '';
      }

      var fragment = document.createDocumentFragment();
      (items || []).forEach(function (item) {
        var key = item && item.item_key ? String(item.item_key) : '';
        if (!key || seen[key]) return;
        seen[key] = true;
        var card = buildCard(item);
        if (card) fragment.appendChild(card);
      });
      grid.appendChild(fragment);
    }

    // ---------------------------------------------------------- URL 同步
    function syncUrl(mode, filters) {
      if (mode !== 'push' && mode !== 'replace') return;
      try {
        var url = new URL(window.location.href);
        if (filters.query) url.searchParams.set('q', filters.query);
        else url.searchParams.delete('q');
        if (filters.categoryId) url.searchParams.set('category_id', String(filters.categoryId));
        else url.searchParams.delete('category_id');
        if (filters.stockOnly) url.searchParams.set('stock_only', '1');
        else url.searchParams.delete('stock_only');
        // 游标属于"加载更多"的内部状态，不写进地址栏。
        url.searchParams.delete('cursor');

        var target = url.pathname + url.search + url.hash;
        var current = window.location.pathname + window.location.search + window.location.hash;
        if (target === current) return;

        var historyState = { lcTeamSearch: true };
        if (mode === 'replace') window.history.replaceState(historyState, '', target);
        else window.history.pushState(historyState, '', target);
      } catch (error) {
        // 地址栏同步失败不影响检索本身（例如受限的嵌入环境）。
      }
    }

    // ---------------------------------------------------------- 检索主流程
    async function performSearch(reset, historyMode, force) {
      if (!AUTHENTICATED) return;

      var filters = !reset && state.lastFilters ? state.lastFilters : readFilters();
      var requestKey = filtersKey(filters);

      // 打字触发的重复检索直接跳过；显式提交 / 分类切换 / popstate 则强制刷新。
      if (reset && !force && requestKey === state.lastKey && !state.nextCursor) return;

      var cursor = reset ? null : state.nextCursor;
      if (!reset && !cursor) return;

      var categoryNumber = parseInt(filters.categoryId, 10);
      if (!isFinite(categoryNumber)) categoryNumber = null;

      var sequence = ++state.sequence;
      if (state.controller) {
        try {
          state.controller.abort();
        } catch (error) {
          // 某些旧实现没有 abort，忽略即可；序号校验仍然兜底。
        }
      }
      var controller = typeof AbortController === 'function' ? new AbortController() : null;
      state.controller = controller;
      state.loading = true;
      setBusy(true, !reset);
      hideAlert();

      try {
        var payload = await postJson(SEARCH_ENDPOINT, {
          query: filters.query,
          category_id: categoryNumber,
          stock_only: filters.stockOnly,
          cursor: cursor,
          limit: PAGE_SIZE,
        }, controller ? controller.signal : undefined);

        // 只有最新一次请求能改界面；旧请求即使没被中止也不能覆盖新结果。
        if (sequence !== state.sequence) return;

        var result = payload && payload.result;
        var data = null;
        if (result && result.ok === true) {
          data = result.data || {};
        } else if (result && Array.isArray(result.items)) {
          data = result; // 兼容直接返回 data 的旧实现
        } else {
          var message = '';
          if (result && result.error && typeof result.error.message === 'string') {
            message = result.error.message;
          }
          if (!message && payload && payload.error && payload.error.data &&
              typeof payload.error.data.message === 'string') {
            message = payload.error.data.message;
          }
          if (!message && payload && payload.error && typeof payload.error.message === 'string') {
            message = payload.error.message;
          }
          if (!message || /odoo\s+server\s+error/i.test(message)) {
            message = '检索失败，请稍后重试。';
          }
          showAlert(message);
          // 关键：失败时保留旧结果，只在旧结果为空时隐藏"无结果"提示。
          if (!grid.children.length) setHidden(emptyEl, true);
          return;
        }

        var items = Array.isArray(data.items) ? data.items : [];
        appendItems(items, reset);
        state.nextCursor = data.next_cursor ? String(data.next_cursor) : null;
        state.total = Number(data.total) || 0;
        state.lastKey = requestKey;
        state.lastFilters = filters;

        setMetaTotal(state.total, filters);
        results.setAttribute('data-total', String(state.total));
        setHidden(emptyEl, grid.children.length > 0);
        hideAlert();

        if (state.nextCursor) {
          var moreButton = ensureMoreButton();
          moreButton.setAttribute('data-cursor', state.nextCursor);
          setHidden(moreButton, false);
        } else if (more) {
          more.removeAttribute('data-cursor');
          setHidden(more, true);
        }

        syncCategoryLinks(filters);
        syncUrl(historyMode, filters);
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        if (sequence !== state.sequence) return;
        showAlert(error && error.userMessage ? error.userMessage : '网络异常，请重试。');
        if (!grid.children.length) setHidden(emptyEl, true);
      } finally {
        // 旧请求不能清掉新请求的加载态，所以只在序号仍是最新时收尾。
        if (sequence === state.sequence) {
          state.loading = false;
          state.controller = null;
          setBusy(false, false);
        }
      }
    }

    // ---------------------------------------------------------- 事件绑定
    var debounceTimer = 0;
    var composing = false;

    function cancelDebounce() {
      if (debounceTimer) {
        window.clearTimeout(debounceTimer);
        debounceTimer = 0;
      }
    }

    function queueDebouncedSearch() {
      cancelDebounce();
      debounceTimer = window.setTimeout(function () {
        debounceTimer = 0;
        var filters = readFilters();
        if (filtersKey(filters) === state.lastKey && !state.nextCursor) return;
        performSearch(true, 'replace', false);
      }, 450);
    }

    if (form) {
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        cancelDebounce();
        performSearch(true, 'push', true);
      });
    }

    if (input) {
      input.addEventListener('compositionstart', function () {
        composing = true;
      });
      input.addEventListener('compositionend', function () {
        composing = false;
        queueDebouncedSearch(); // 中文输入法组合结束后再检索
      });
      input.addEventListener('input', function () {
        if (composing) return;
        queueDebouncedSearch();
      });
    }

    if (stockOnlyInput) {
      stockOnlyInput.addEventListener('change', function () {
        cancelDebounce();
        performSearch(true, 'push', true);
      });
    }

    var cats = $('.lc-cats');
    if (cats) {
      cats.addEventListener('click', function (event) {
        var link = event.target && event.target.closest ? event.target.closest('a.lc-cat') : null;
        if (!link || !cats.contains(link)) return;
        if (link.getAttribute('href')) event.preventDefault();

        var categoryId = (link.getAttribute('data-category-id') || '').trim();
        state.categoryId = categoryId;
        setActiveCategory(categoryId);
        cancelDebounce();
        performSearch(true, 'push', true);
      });
    }

    bindMoreButton(more);

    window.addEventListener('popstate', function () {
      // 只有仍停留在仓库页时才按 URL 重新检索；跨文档导航交给浏览器。
      if (window.location.pathname !== pagePath) return;

      var params = new URLSearchParams(window.location.search);
      var query = params.get('q') || '';
      var categoryId = (params.get('category_id') || '').trim();
      var stockFlag = (params.get('stock_only') || '').toLowerCase();
      var onlyStock = stockFlag === '1' || stockFlag === 'true' ||
        stockFlag === 'on' || stockFlag === 'yes';

      if (input) input.value = query;
      if (stockOnlyInput) stockOnlyInput.checked = onlyStock;
      state.categoryId = categoryId;
      setActiveCategory(categoryId);

      // popstate 是"地址栏已经变了"，必须按 URL 重查，不做相同参数短路。
      state.lastKey = '';
      state.lastFilters = null;
      performSearch(true, 'none', true);
    });
  }

  // ------------------------------------------------------------------ 启动
  function init() {
    var main = document.getElementById('lc-main');
    if (main && !main.hasAttribute('tabindex')) {
      // 让 skip link 跳到正文后，键盘焦点真正落在 main 上。
      main.setAttribute('tabindex', '-1');
    }
    initImageFallbacks();
    initLogin();
    // 退出刻意不接管：表单是原生 POST + CSRF 隐藏域（模板 t-att-action 已带基址），
    // 浏览器自己完成 303 跳转。用 fetch 代提交会吞掉 303/网络错误并硬编码跳转目标，
    // 既绕过 CSRF 语义，也会掩盖服务端 origin 问题。
    initWarehouse();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
