/* ==========================================================================
 * lab_team_web · 我的账号（page_id: account，domain: account）
 * --------------------------------------------------------------------------
 * 只读页面：身份、权限位、会话状态全部来自既有 /api/team/session，通过
 * window.LC.session() / LC.refreshSession() 取得（与导航、权限位同源）。
 *
 * 边界（frontend-contract.md §5 / backend-contract.md §5）：
 * 1. 不新增接口、不新增认证：密码变更不在本页，走管理员复位或 Odoo 原生流程；
 * 2. 不缓存凭据：本文件不读写 localStorage/sessionStorage，不接触 cookie/token；
 * 3. 不接管退出：退出是模板里的原生 POST 表单 + CSRF 隐藏域，浏览器自己跟随
 *    303。用 fetch 代提交会吞掉 303 并硬编码跳转目标，绕过 CSRF 语义；
 * 4. 渲染只用 LC.el / textContent（无 innerHTML、无字符串拼 DOM）；
 * 5. 无写操作，因此不需要 request_key / LC.submit；读取失败按 error.code 分支，
 *    "结果未知"给显式重试（不自动重试、不在加载时自动提交任何东西）；
 * 6. 所有链接都来自服务端下发的站内相对路径（LC.urls / session.urls），
 *    页面不拼绝对 origin。
 * ========================================================================== */
(function () {
  'use strict';

  if (!window.LC) return;

  LC.register('account', function (ctx) {
    var root = ctx.root || document;

    var loadingEl = LC.qs('[data-lc-loading]', root);
    var sessionBadge = LC.qs('[data-account-badge="session"]', root);
    var refreshBtn = LC.qs('[data-lc-action="refresh-session"]', root);
    var permNodes = LC.qsa('[data-account-perm]', root);
    var entryNodes = LC.qsa('[data-account-entry]', root);

    var busy = false;

    /* ---------------------------------------------------------------- 小工具 */
    function fieldNode(name) {
      return LC.qs('[data-account-field="' + name + '"]', root);
    }

    function setField(name, value) {
      var node = fieldNode(name);
      if (!node) return;
      var text = value === null || value === undefined ? '' : String(value);
      LC.setText(node, text === '' ? '—' : text);
    }

    function setBadge(node, text, tone) {
      if (!node) return;
      LC.setText(node, text);
      if (tone) node.setAttribute('data-tone', tone);
      else node.removeAttribute('data-tone');
    }

    /** 只接受站内相对路径：拒绝 //host、scheme、反斜杠与控制字符。 */
    function siteRelative(url) {
      var text = typeof url === 'string' ? url.trim() : '';
      if (!text || text.charAt(0) !== '/') return '';
      if (text.charAt(1) === '/') return '';
      if (text.indexOf('://') !== -1) return '';
      if (text.indexOf('\\') !== -1) return '';
      if (/[\u0000-\u001f\u007f]/.test(text)) return '';
      return text;
    }

    function applyEntryUrls(urls) {
      var map = urls || {};
      entryNodes.forEach(function (node) {
        var key = node.getAttribute('data-account-entry') || '';
        var target = siteRelative(map[key]);
        if (target) node.setAttribute('href', target);
      });
    }

    function setEntryVisible(key, visible) {
      entryNodes.forEach(function (node) {
        if (node.getAttribute('data-account-entry') !== key) return;
        LC.show(node, !!visible);
      });
    }

    /* ---------------------------------------------------------------- 渲染 */
    function render(data) {
      var payload = data || {};
      var perms = payload.permissions || ctx.permissions || {};
      var company = payload.company || {};
      var authenticated = payload.authenticated !== false;

      setField('name', payload.name);
      setField('login', payload.login);
      setField('uid', payload.uid);
      setField('company', company.name);
      setField('session', authenticated ? '已登录（会话有效）' : '会话已失效');
      setBadge(sessionBadge, authenticated ? '会话有效' : '会话已失效',
        authenticated ? 'ok' : 'bad');

      permNodes.forEach(function (node) {
        var key = node.getAttribute('data-account-perm') || '';
        var granted = !!perms[key];
        setBadge(node, granted ? '已授予' : '未授予', granted ? 'ok' : 'warn');
      });

      // 「我的领用」需要 lab 角色（/lab/issues 服务端同样是 lab 门槛）
      setEntryVisible('issues', !!perms.can_lab);
      applyEntryUrls(payload.urls);
      LC.show(loadingEl, false);
    }

    /* ---------------------------------------------------------------- 错误 */
    function showFailure(error) {
      LC.show(loadingEl, false);
      setBadge(sessionBadge, '会话读取失败', 'bad');

      // 结果未知（断网/超时/5xx/非 JSON）：只提示并给显式重试，不自动重试
      if (error && error.unknown) {
        LC.status.show({
          kind: 'unknown',
          code: 'INTERNAL_ERROR',
          message: '读取会话结果未知（网络中断或超时），可以安全重试。',
          retry: function () { load(true); }
        });
        return;
      }

      var code = (error && error.code) || 'INTERNAL_ERROR';
      if (code === 'UNAUTHORIZED') {
        // core 已把 401/403/HTML 响应收敛成 UNAUTHORIZED 并附「重新登录」入口
        LC.status.show({
          kind: 'denied',
          code: code,
          message: LC.errorText(error),
          relogin: true
        });
        return;
      }
      if (code === 'FORBIDDEN') {
        LC.status.show({
          kind: 'denied',
          code: code,
          message: '当前账号没有读取会话信息的权限，请联系库存管理员。'
        });
        return;
      }
      // 其余按 code 分支：文案统一取 LC.errorText（INTERNAL_ERROR 已带错误编号）
      LC.status.show({
        kind: 'error',
        code: code,
        message: LC.errorText(error),
        retry: function () { load(true); }
      });
    }

    /* ---------------------------------------------------------------- 读取 */
    function load(force) {
      if (busy) return;
      busy = true;
      LC.status.clear();
      LC.show(loadingEl, true);
      LC.setBusy(refreshBtn, true, '读取中…');

      var request = force ? LC.refreshSession() : LC.session();

      request.then(function (data) {
        render(data);
        if (force) {
          // 只有用户显式点「重新读取会话」才提示成功，首次加载不弹
          LC.status.show({ kind: 'success', message: '会话信息已更新。' });
        }
      }).catch(function (error) {
        showFailure(error);
      }).then(function () {
        busy = false;
        LC.setBusy(refreshBtn, false);
      });
    }

    /* ---------------------------------------------------------------- 事件 */
    LC.on(root, '[data-lc-action="refresh-session"]', 'click', function (event) {
      event.preventDefault();
      load(true);
    });

    // 退出刻意不接管：原生 POST + CSRF 隐藏域由浏览器提交并跟随 303。
    load(false);
  });
})();
