#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 写业务浏览器验收（真实 UI + CDP），复用 P2 的 BrowserFlow。

为什么不改 browser_flow.py
--------------------------
P2 的 28 步必需集由 `bore/tests/test_p2_runner_verify.py` 断言，改动会破坏 P2 证据
契约。本文件**导入并继承** P2 的 Chrome 启动、CDP、事件/网络记录、脱敏、profile 清理，
只新增 P3 页面与写业务步骤，输出独立 schema（`lc-elc-p3-browser-flow/1`）。

选择器来源（已发布，非猜测）
--------------------------
`lab_team_web/views/team_templates.xml`（`#workflow-root[data-workflow-page]`）
与 `lab_team_web/views/workflow_{receipt,issue,inventory}.xml` 的 `data-lc-*` 契约。
每个选择器都可用 `P3_SEL_<NAME>` 覆盖，UI 契约变动时不必改代码。

判定原则
--------
* 页面仍是占位（`界面尚未接入`）或缺页面脚本 → `blocked`，**不算通过**（退出码 3）。
* 写业务断言只认"服务端事实"：建袋/确认前后都用真实 JSON-RPC 读 `stock.quant`，
  再和 UI 动作对照；不把前端提示当成功。
* UI 尚未提供可操作入口的动作（跨账号归还、同 key 异 payload、网络中断后的未知重试）
  显式 `blocked` 并写明原因，由 `verify-p3-write.sh` / `test_p3_workflows_http.py` 覆盖，
  不静默消失，也不用 API 写冒充 UI 通过。
* 缺 Python `websockets`（P2 CDP 客户端依赖）属**环境不可用**，在 `env` 步骤直接判 fail
  并退出 2，不再让后续 25 步显示 blocked 掩盖根因。

选择器只用真实页面里已存在的钩子
--------------------------------
`data-lc-*` 来自 `views/workflow_{receipt,issue,inventory}.xml` 的静态标记，或页面脚本
（`settings.js:225` 的 `data-lc-inv-role`、`issue_new.js:392` 的 `add-bag`、
`issues.js:199` 的 `return-open`）在运行时渲染的属性。`P3_SEL_<NAME>` 可覆盖任一默认值。

环境变量
--------
必填：CHROME_BIN  URL  LOGIN  PASSWORD  OUT_DIR
可选：P3_ALLOW_HTTP=1（允许 http 回环隔离实例）
      P3_PYDEPS（本轮 local 依赖目录，冒号或逗号分隔；缺 websockets 时先放这里）
      P3_ITEM_KEY（形如 `lcsc:C123456`，用于建袋与库存对照；缺省相关步骤 blocked）
      P3_PAGES（逗号分隔，默认 12 个业务页）
      P3_MANAGER_LOGIN / P3_MANAGER_PASSWORD（管理域：库位/映射/成员角色/材料）
      P3_NOROLE_LOGIN（默认 p3_norole；成员角色切换的目标账号）
      P3_CATALOG_CODE（合成资料库编号，默认 C990000001；材料页真实建档用）
      P3_CATALOG_FIXTURE=0（跳过材料写；默认 1 = 缺索引行时用当前 manager 账号
                            写一行**合成** `lab.catalog.item` 当夹具：不建档案、不写库存）
stdout 只输出一个 JSON 对象；退出码：0 全 pass；1 fail；2 环境不可用；3 仅 blocked。
"""
import json
import os
import re
import sys
import time
import traceback
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def repo_root():
    """`<repo>/server/ubuntu22.04/bore/tests` → `<repo>`（只用于列出本机依赖候选目录）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))


def pydeps_candidates(repo=None):
    """本轮可用的本机依赖目录候选（P3_PYDEPS 优先，其次 local/build 下约定目录）。"""
    repo = repo or repo_root()
    raw_items = []
    for chunk in (os.environ.get('P3_PYDEPS') or '').split(os.pathsep):
        raw_items.extend(part.strip() for part in chunk.split(','))
    raw_items.extend([
        os.path.join(repo, 'local', 'build', 'p3-web-20261028', 'pydeps'),
        os.path.join(repo, 'local', 'build', 'pydeps'),
    ])
    out = []
    for item in raw_items:
        if not item:
            continue
        path = os.path.abspath(item)
        if path not in out:
            out.append(path)
    return out


def ensure_websockets(candidates=None):
    """把本机依赖目录加进 sys.path 再探 websockets；不复制、不实现 CDP/WebSocket。

    返回值一律是数据（selftest 可断言），失败不抛异常 —— 由 `check_env` 决定这是
    "环境不可用"（退出 2）而不是静默 blocked。
    """
    candidates = pydeps_candidates() if candidates is None else list(candidates)
    added = []
    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
            added.append(path)
    try:
        import websockets  # noqa: F401  （只为探测；实际连接仍由 P2 的 CDP 客户端做）
        return {'ok': True, 'version': str(getattr(websockets, '__version__', '?')),
                'file': str(getattr(websockets, '__file__', '?')),
                'added': added, 'candidates': candidates}
    except Exception as exc:
        return {'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc),
                'added': added, 'candidates': candidates}


PYDEPS = ensure_websockets()

import browser_flow as p2  # noqa: E402  （复用 P2 实现，不复制）

SCHEMA = 'lc-elc-p3-browser-flow/1'

DEFAULT_PAGES = (
    'receipts', 'scan', 'bags', 'labels', 'issue_new', 'issues',
    'locations', 'mappings', 'settings', 'history', 'materials', 'account',
)

PAGE_PATHS = {
    'receipts': '/team/lab/receipts',
    'scan': '/team/scan',
    'bags': '/team/lab/bags',
    'labels': '/team/lab/labels',
    'issue_new': '/team/lab/issues/new',
    'issues': '/team/lab/issues',
    'locations': '/team/lab/locations',
    'mappings': '/team/lab/location-mappings',
    'settings': '/team/lab/settings',
    'history': '/team/lab/history',
    'materials': '/team/lab/materials',
    'account': '/team/account',
}

#: 只有 manager 能看的页面（以操作员巡检时必须 403）
MANAGER_ONLY_PAGES = ('mappings', 'settings')

#: 占位页正文特征（views/team_templates.xml:85-107）
PLACEHOLDER_TEXT = '界面尚未接入'

DEFAULT_SELECTORS = {
    'page_marker': '#workflow-root',
    'placeholder': '[data-lc-placeholder]',
    'receipt_item_key': '[data-lc-panel="prepare"] [data-lc-field="item_key"]',
    'receipt_resolve_item': '[data-lc-action="resolve-item"]',
    'receipt_selected': '[data-lc-selected="material"]',
    'receipt_qty': '[data-lc-form="pending-create"] [data-lc-field="quantity"]',
    'receipt_count': '[data-lc-form="pending-create"] [data-lc-field="count"]',
    'receipt_create': '[data-lc-form="pending-create"] button[type="submit"]',
    'receipt_pending_rows': '[data-lc-rows="pending"]',
    'receipt_tab_shelve': '[data-lc-action="tab"][data-tab="shelve"]',
    'receipt_scan': '[data-lc-scan="shelve"]',
    'receipt_resolve_pending': '[data-lc-action="resolve-pending"]',
    'receipt_confirm_form': '[data-lc-form="pending-confirm"]',
    'receipt_location': '[data-lc-form="pending-confirm"] [data-lc-field="location_id"]',
    'receipt_confirm_qty': '[data-lc-form="pending-confirm"] [data-lc-field="quantity"]',
    'receipt_confirm': '[data-lc-form="pending-confirm"] button[type="submit"]',
    'pdf_form': '[data-lc-pdf-form="labels"]',
    # issue_new（views/workflow_issue.xml:28-149 + pages/issue_new.js:281-476）
    'issue_scan': '[data-lc-scan]',
    'issue_resolve': '[data-lc-action="resolve"]',
    'issue_add_bag': '[data-lc-action="add-bag"]',
    'issue_cart_qty': '[data-lc-cart-qty]',
    'issue_borrower': '[data-lc-form="issue"] [data-lc-field="borrower_id"]',
    'issue_project': '[data-lc-form="issue"] [data-lc-field="project"]',
    'issue_submit': '[data-lc-action="submit-issue"]',
    'issue_success': '[data-lc-panel="success"]',
    # issues（views/workflow_issue.xml:233-340 + pages/issues.js:199,603-620）
    'issues_return_open': '[data-lc-rows="issues"] [data-lc-action="return-open"]',
    'issues_filter_query': '[data-lc-form="issues-filter"] [data-lc-field="query"]',
    'issues_filter_outstanding': '[data-lc-form="issues-filter"] [data-lc-field="outstanding_only"]',
    'issues_filter_search': '[data-lc-action="search"]',
    'issues_return_form': '[data-lc-form="return"]',
    'issues_return_qty': '[data-lc-form="return"] [data-lc-field="quantity"]',
    'issues_return_submit': '[data-lc-action="submit-return"]',
    # 入库成功/未决锁（views/workflow_receipt.xml:411、77-92）
    'receipt_success': '[data-lc-success="shelve"]',
    'receipt_lock_box': '[data-lc-lock="create"]',
    'receipt_lock_retry': '[data-lc-lock="create"] [data-lc-action="lock-retry"]',
    # 管理域（views/workflow_inventory.xml，contract v1.2）
    'loc_toggle_create': '[data-lc-action="locations-toggle-create"]',
    'loc_create_form': '[data-lc-form="location-create"]',
    'loc_name': '[data-lc-form="location-create"] [data-lc-field="name"]',
    'loc_submit': '[data-lc-form="location-create"] button[type="submit"]',
    'loc_rows': '[data-lc-rows="locations"]',
    'map_form': '[data-lc-form="mapping-set"]',
    'map_category': '[data-lc-form="mapping-set"] [data-lc-field="category_id"]',
    'map_location': '[data-lc-form="mapping-set"] [data-lc-field="location_id"]',
    'map_priority': '[data-lc-form="mapping-set"] [data-lc-field="priority"]',
    'map_submit': '[data-lc-form="mapping-set"] button[type="submit"]',
    # settings（views/workflow_inventory.xml:370-378 + pages/settings.js:221-233,454）
    'members_query': '#lc-inv-mem-query',
    'members_search': '[data-lc-action="members-search"]',
    'members_rows': '[data-lc-rows="members"]',
    'role_checkbox': '[data-lc-rows="members"] [data-lc-inv-role="lab_user"]',
    # materials（views/workflow_inventory.xml:445-560 + pages/materials.js:129-146,559-578）
    'material_form': '[data-lc-form="material-bind"]',
    'material_query': '[data-lc-form="material-search"] [data-lc-field="query"]',
    'material_search': '[data-lc-form="material-search"] button[type="submit"]',
    'material_rows': '[data-lc-rows="materials"]',
}

#: 页面按角色门槛：账号没有对应组时服务端 403，属"该账号无此角色"，不是页面缺陷。
ROLE_GATED_PAGES = {'materials': 'catalog'}   # frontend-contract §3：materials 需 catalog 角色

#: 有意触发的 4xx（角色门槛探针），不算网络失败。
#: 键为 (path, status, method, resource_type)：**逐条精确**，不做前缀/模式匹配，
#: 避免把真实 API 403（例如写端点被拒）也一起忽略。
EXPECTED_4XX = {
    ('/team/lab/settings', 403, 'GET', 'Document'),
    ('/team/lab/location-mappings', 403, 'GET', 'Document'),
    ('/team/lab/materials', 403, 'GET', 'Document'),   # 无 catalog 角色时
}


def expected_4xx_match(item):
    """只认精确的 (path, status, method, type)；其余 4xx 一律算失败。"""
    key = (item.get('path'), item.get('status'),
           (item.get('method') or '').upper(), item.get('type'))
    return key in EXPECTED_4XX


def expected_4xx_paths():
    return sorted({key[0] for key in EXPECTED_4XX})

P3_STEPS = (
    'env',
    'chrome-launch',
    'cdp-connect',
    'login-page',
    'login-ui-submit',
    'lab-authenticated',
    'p3-pages-nav',
    'p3-page-receipts',
    'p3-receipt-resolve-local-key',
    'p3-receipt-item-resolve',
    'p3-receipt-create-no-stock',
    'p3-receipt-shelve-resolve',
    'p3-receipt-confirm',
    'p3-receipt-confirm-replay',
    'p3-receipt-same-key-conflict',
    'p3-issue-submit',
    'p3-return-partial',
    'p3-cross-user-denied',
    'p3-readonly-role-denied',
    'p3-unknown-outcome-retry',
    'p3-label-pdf',
    'p3-anon-redirect',
    'p3-manager-login',
    'p3-location-create',
    'p3-mapping-set',
    'p3-member-role-toggle',
    'p3-material-write',
    'console-clean',
    'network-clean',
    'evidence-redaction',
    'profile-cleanup',
)

PAGE_STATE_JS = """(() => {
  const sel = %s;
  const q = function (s) { try { return document.querySelector(s); } catch (e) { return null; } };
  const marker = q(sel.page_marker);
  const main = q('#lc-main') || document.body;
  const text = main && main.innerText ? main.innerText.slice(0, 1500) : '';
  const pageId = marker ? (marker.getAttribute('data-workflow-page') || '') : '';
  const js = pageId ? document.querySelector('script[src*="/pages/' + pageId + '.js"]') : null;
  return {
    path: location.pathname,
    title: document.title || '',
    auth: document.body ? document.body.getAttribute('data-authenticated') : null,
    main: !!q('#lc-main'),
    marker: !!marker,
    page_id: pageId,
    page_js: !!js,
    placeholder: !!q(sel.placeholder) || (!!marker && text.indexOf(sel.placeholder_text) >= 0),
    error_page: !!q('.lc-error-page'),
    login_form: !!q('#lc-login-form'),
    text: text
  };
})()"""


#: 页面内只读 instrumentation：给 fetch 包一层，**只记录元数据**
#: （path/status/业务 ok/code/返回 data 的键名），不记录请求体、cookie、token、响应全文。
#: 用途：解析/写操作失败时定位"到底是网络、HTTP 还是业务 code"。
RPC_TRACE_JS = """(() => {
  if (window.__LC_RPC_TRACE) return;
  window.__LC_RPC_TRACE = [];
  const orig = window.fetch;
  if (!orig) return;
  window.fetch = function (input, init) {
    const url = (typeof input === 'string') ? input : ((input && input.url) || '');
    return orig.apply(this, arguments).then(function (resp) {
      try {
        const copy = resp.clone();
        copy.text().then(function (text) {
          let payload = null;
          try { payload = JSON.parse(text); } catch (e) { payload = null; }
          const result = payload && payload.result;
          const jrpcError = payload && payload.error;
          let path = url;
          try { path = new URL(url, location.href).pathname; } catch (e) {}
          const entry = {
            path: path,
            status: resp.status,
            ok: result ? !!result.ok : null,
            code: result ? (result.code || '') : '',
            keys: (result && result.data && typeof result.data === 'object')
              ? Object.keys(result.data).sort() : [],
            fields: (jrpcError && jrpcError.data && jrpcError.data.fields)
              ? Object.keys(jrpcError.data.fields).sort() : [],
            error: jrpcError ? 'jsonrpc-error' : ''
          };
          window.__LC_RPC_TRACE.push(entry);
          if (window.__LC_RPC_TRACE.length > 40) window.__LC_RPC_TRACE.shift();
        }).catch(function () {});
      } catch (e) {}
      return resp;
    });
  };
})()"""


def js_str(value):
    return json.dumps(value, ensure_ascii=False)


def parse_pages(raw):
    """把逗号分隔的页面名收敛成已知页面列表（未知名忽略并回报）。"""
    if not (raw or '').strip():
        return list(DEFAULT_PAGES), []
    wanted, unknown = [], []
    for part in (item.strip() for item in raw.split(',')):
        if not part:
            continue
        if part in PAGE_PATHS:
            if part not in wanted:
                wanted.append(part)
        else:
            unknown.append(part)
    if not wanted:
        return list(DEFAULT_PAGES), unknown
    return wanted, unknown


def classify_page_state(state, expect_page=None):
    """把页面状态分类成 (result, detail)。纯函数，selftest 覆盖。

    blocked 只用于"UI 还没发布"，绝不用于"UI 有错"。
    """
    if not isinstance(state, dict):
        return 'fail', '页面状态不可读'
    if state.get('error_page'):
        return 'fail', '渲染了错误页'
    if state.get('login_form'):
        return 'blocked', '被重定向到登录页（会话未保持）'
    if state.get('placeholder'):
        return 'blocked', '占位模板（界面尚未接入）'
    if not state.get('marker'):
        return 'blocked', '缺少页面标记 %s' % DEFAULT_SELECTORS['page_marker']
    if not state.get('page_js'):
        return 'blocked', '页面脚本未发布（static/src/js/pages/<page>.js）'
    page_id = state.get('page_id') or ''
    if expect_page and page_id and page_id != expect_page:
        return 'fail', '页面标记不符 %s != %s' % (page_id, expect_page)
    return 'pass', 'page=%s path=%s' % (page_id or expect_page or '?', state.get('path') or '?')


def selector_for(name):
    return (os.environ.get('P3_SEL_' + name.upper()) or '').strip() \
        or DEFAULT_SELECTORS[name]


def item_key_code(item_key):
    """`lcsc:C123` -> `C123`；用于按本地档案查库存。"""
    if not item_key or ':' not in item_key:
        return ''
    return item_key.split(':', 1)[1].strip()


class P3Config(p2.Config):
    #: 本项目其它脚本用 ODOO_URL/P3_* 命名；P2 的 Config 要 URL/LOGIN/PASSWORD/...
    _ENV_ALIASES = (
        ('URL', ('ODOO_URL',)),
        ('LOGIN', ('P3_LOGIN',)),
        ('PASSWORD', ('P3_PASS',)),
        ('CHROME_BIN', ('P3_CHROME_BIN',)),
        ('OUT_DIR', ('P3_OUT_DIR',)),
    )

    def __init__(self):
        for target, sources in self._ENV_ALIASES:
            if (os.environ.get(target) or '').strip():
                continue
            for source in sources:
                value = (os.environ.get(source) or '').strip()
                if value:
                    os.environ[target] = value
                    break
        p2.Config.__init__(self)
        self.allow_http = (os.environ.get('P3_ALLOW_HTTP') or '').strip() == '1'
        self.pages, self.unknown_pages = parse_pages(os.environ.get('P3_PAGES') or '')
        self.manager_login = (os.environ.get('P3_MANAGER_LOGIN') or '').strip()
        self.manager_password = (os.environ.get('P3_MANAGER_PASSWORD') or '').strip()
        self.norole_login = (os.environ.get('P3_NOROLE_LOGIN') or 'p3_norole').strip()
        self.item_key = (os.environ.get('P3_ITEM_KEY') or '').strip()
        self.item_code = item_key_code(self.item_key)
        self.catalog_code = (os.environ.get('P3_CATALOG_CODE') or 'C990000001').strip().upper()
        self.catalog_fixture = (os.environ.get('P3_CATALOG_FIXTURE') or '1').strip() != '0'

    def secrets(self):
        values = p2.Config.secrets(self)
        if self.manager_password:
            values.append(('manager-password', self.manager_password))
        return values


class P3Flow(p2.BrowserFlow):
    def __init__(self, cfg):
        p2.BrowserFlow.__init__(self, cfg)
        self.selectors = {name: selector_for(name) for name in DEFAULT_SELECTORS}
        self.pydeps = dict(PYDEPS)
        self.page_states = {}
        self.trace_code = ''
        self.pending_before = None
        self.expected_4xx = []
        # P2 的 verify_events()/counts() 直接调 recorder.status_failures()，
        # 所以白名单必须在 recorder 这一层生效（只放行 EXPECTED_4XX 里逐条登记的项）。
        _base_status_failures = self.recorder.status_failures

        def _status_failures():
            out = []
            seen = {item.get('request_id') for item in self.expected_4xx}
            for item in _base_status_failures():
                if expected_4xx_match(item):
                    if item.get('request_id') not in seen:
                        self.expected_4xx.append(item)
                        seen.add(item.get('request_id'))
                    continue
                out.append(item)
            return out

        self.recorder.status_failures = _status_failures

    # -- 环境（允许本机 http 回环隔离实例） -----------------------------
    def check_env(self):
        problems = []
        if not os.path.isfile(self.cfg.chrome):
            problems.append('CHROME_BIN 不存在')
        if self.cfg.scheme != 'https':
            if not self.cfg.allow_http:
                problems.append('URL 必须是 https（隔离实例可设 P3_ALLOW_HTTP=1）')
            elif self.cfg.host not in ('127.0.0.1', 'localhost', '::1', '[::1]'):
                problems.append('P3_ALLOW_HTTP 只允许回环地址')
        try:
            os.makedirs(self.cfg.out_dir, exist_ok=True)
        except OSError as exc:
            problems.append('OUT_DIR 不可创建: ' + p2.truncate(exc, 60))
        if not problems and p2.contains_link_component(self.cfg.out_dir):
            problems.append('OUT_DIR 路径链含 symlink/junction')
        # CDP 客户端（P2 browser_flow.py:1722）依赖 websockets 同步客户端。
        # 缺包是环境不可用，不是页面缺陷：这里显式判 fail + 退出 2，禁止让 25 步 blocked 掩盖根因。
        if not self.pydeps.get('ok'):
            problems.append(
                '缺 Python 依赖 websockets（CDP 必需；%s）。'
                '把装有 websockets 的解释器设为 PYTHON，或用 pip install --target 装到本轮 '
                'local 依赖目录并设 P3_PYDEPS。候选目录：%s'
                % (p2.truncate(self.pydeps.get('error'), 90),
                   ','.join(self.pydeps.get('candidates') or []) or '(none)'))
        if problems:
            self.hard_env_failure = True
            self.step('env', 'fail', '; '.join(problems))
            raise p2.FlowAbort('env: ' + '; '.join(problems))
        tls = ('ca-file' if self.cfg.ca_file
               else ('spki-pin' if self.cfg.spki else 'unset'))
        self.step('env', 'pass', 'tls=%s scheme=%s entry=%s pages=%d item_key=%s '
                                'websockets=%s pydeps=%s'
                  % (tls, self.cfg.scheme, self.cfg.origin, len(self.cfg.pages),
                     'set' if self.cfg.item_key else 'missing',
                     self.pydeps.get('version') or '?',
                     ','.join(self.pydeps.get('added') or []) or '(sys.path/default)'))
        if self.cfg.unknown_pages:
            self.note('忽略未知页面名: ' + ','.join(self.cfg.unknown_pages))

    # -- 页面读取/等待 ---------------------------------------------------
    def read_page_state(self, context_id=None):
        expression = PAGE_STATE_JS % js_str({
            'page_marker': self.selectors['page_marker'],
            'placeholder': self.selectors['placeholder'],
            'placeholder_text': PLACEHOLDER_TEXT})
        try:
            return self.cdp.evaluate(expression, context_id=context_id) or {}
        except Exception as exc:
            self.note('read_page_state failed: ' + p2.truncate(exc, 120))
            return {}

    def nav(self, path, label, ready_expr=None, match_path=None):
        """真实导航。`path` 可带查询串；`match_path` 只用于比较 location.pathname。"""
        url = self.cfg.url + path
        ready = ready_expr or ("document.readyState !== 'loading' && !!document.body")
        expected = match_path or path
        self.prepare_navigation('p3 navigate ' + label, path=expected)

        def action():
            return self.cdp.call('Page.navigate', url=url)

        return self.cdp.expect_navigation(
            action, lambda target: p2.url_path(target) == expected, ready, label=label)

    def has(self, selector):
        try:
            return bool(self.cdp.evaluate(
                "(() => { try { return !!document.querySelector(%s); }"
                " catch (e) { return false; } })()" % js_str(selector)))
        except Exception:
            return False

    def visible(self, selector):
        try:
            return bool(self.cdp.evaluate(
                "(() => { const el = document.querySelector(%s);"
                " return !!(el && !el.hidden && el.offsetParent !== null); })()"
                % js_str(selector)))
        except Exception:
            return False

    def wait_js(self, expression, label, timeout=25):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.cdp.evaluate(expression):
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        raise p2.FlowAbort('等待超时: ' + label)

    def wait_js_soft(self, expression, timeout=15):
        """软等待：超时返回 False，由调用方用服务端事实判定（不把超时当 blocked）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.cdp.evaluate(expression):
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    # -- 服务端事实（页面内同源 JSON-RPC） -------------------------------
    def _api(self, path, params):
        expression = """(async () => {
          const response = await fetch(%s, {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: %s})
          });
          const text = await response.text();
          let payload = null;
          try { payload = JSON.parse(text); } catch (e) { payload = null; }
          return {status: response.status, payload: payload};
        })()""" % (js_str(self.cfg.url + path), js_str(params or {}))
        try:
            return self.cdp.evaluate(expression, await_promise=True) or {}
        except Exception as exc:
            self.note('api failed: ' + p2.truncate(exc, 120))
            return {}

    def _template_id(self):
        if not self.cfg.item_code:
            return None
        state = self._api('/web/dataset/call_kw', {
            'model': 'product.template', 'method': 'search_read',
            'args': [[['lab_lcsc_code', '=', self.cfg.item_code]], ['id']],
            'kwargs': {'limit': 1}})
        payload = state.get('payload') or {}
        rows = payload.get('result')
        if isinstance(rows, list):
            return rows[0].get('id') if rows else None
        error = payload.get('error') or {}
        self.details['template_diag'] = {
            'item_code': self.cfg.item_code,
            'http_status': state.get('status'),
            'keys': sorted(payload.keys()),
            'error': p2.truncate(
                (error.get('message') if isinstance(error, dict) else error) or 'no-result', 120),
        }
        return None

    def quant_total(self):
        """内部/在途库位的实时库存合计（stock.quant 唯一权威，不读缓存）。

        口径与后端 `lab_assert_not_negative` 一致：只统计
        `location_id.usage in ('internal','transit')`。R6 之后暴露的工具缺陷：原来的
        domain 只有 product tmpl，把 supplier/客户等虚拟库位也加进来，入库移动
        （supplier −N ／ internal +N）会互相抵消成"恒 0"，导致后续断言假失败。

        读不到或 API 报错返回 None，并在 `details.quant_diag` 记 code/keys/status；
        **绝不**把错误 dict 当 0 或当成功。
        """
        template_id = self._template_id()
        if not template_id:
            self.details['quant_diag'] = {
                'error': 'template_not_found', 'item_code': self.cfg.item_code}
            return None
        state = self._api('/web/dataset/call_kw', {
            'model': 'stock.quant', 'method': 'search_read',
            'args': [[['product_id.product_tmpl_id', '=', template_id],
                      ('location_id.usage', 'in', ['internal', 'transit'])],
                     ['quantity', 'location_id', 'lot_id']],
            'kwargs': {}})
        payload = state.get('payload') or {}
        rows = payload.get('result')
        if not isinstance(rows, list):
            error = payload.get('error') or {}
            data = error.get('data') if isinstance(error, dict) else {}
            diag = {
                'error': 'api',
                'item_code': self.cfg.item_code,
                'template_id': template_id,
                'http_status': state.get('status'),
                'keys': sorted(payload.keys()),
                'code': (data or {}).get('code') if isinstance(data, dict) else '',
                'message': p2.truncate(
                    (error.get('message') if isinstance(error, dict) else str(error)), 120),
            }
            self.details['quant_diag'] = diag
            self.note('quant_total API error: '
                      + p2.truncate(json.dumps(diag, ensure_ascii=False), 200))
            return None
        total = 0.0
        for row in rows:
            try:
                total += float(row.get('quantity') or 0)
            except (TypeError, ValueError):
                continue
        total = round(total, 6)
        self.details['quant_diag'] = {
            'item_code': self.cfg.item_code, 'template_id': template_id,
            'rows': len(rows), 'total': total}
        return total

    def quant_error_detail(self):
        return p2.truncate(json.dumps(self.details.get('quant_diag')
                                      or self.details.get('template_diag') or {},
                                      ensure_ascii=False), 200)

    # -- 页面巡检 --------------------------------------------------------
    def flow_pages(self):
        results = {}
        published = 0
        for page in self.cfg.pages:
            path = PAGE_PATHS[page]
            try:
                nav = self.nav(path, 'p3 page ' + page)
                state = self.read_page_state(nav.get('context_id'))
            except p2.FlowAbort:
                raise
            except Exception as exc:
                results[page] = ('fail', '导航失败: ' + p2.truncate(exc, 120))
                continue
            result, detail = classify_page_state(state, expect_page=page)
            if page in MANAGER_ONLY_PAGES and self.cfg.login != self.cfg.manager_login:
                if state.get('error_page'):
                    result, detail = 'pass', 'manager-only 页面按预期 403'
                else:
                    result, detail = 'fail', '非管理员未被拒绝（期望 403 错误页）'
            elif page in ROLE_GATED_PAGES and state.get('error_page'):
                result, detail = 'blocked', (
                    '%s 页需 %s 角色，本账号服务端 403（角色未授予，不代表页面缺陷）'
                    % (page, ROLE_GATED_PAGES[page]))
            if result == 'pass':
                published += 1
                if page in ('receipts', 'scan', 'issue_new', 'issues', 'materials'):
                    self.shot('p3-' + page)      # 真实页面截图（非 API 写后补拍）
            results[page] = (result, detail)
            self.page_states[page] = state
        self.details['p3_pages'] = {
            name: {'result': value[0], 'detail': value[1]}
            for name, value in results.items()}
        failures = [name for name, value in results.items() if value[0] == 'fail']
        blocked = [name for name, value in results.items() if value[0] == 'blocked']
        manager_ready = bool(self.cfg.manager_login and self.cfg.manager_password)
        deferred = [name for name in blocked
                    if name in ROLE_GATED_PAGES and manager_ready]
        blocked = [name for name in blocked if name not in deferred]
        if failures:
            self.step('p3-pages-nav', 'fail', 'fail=%s' % ','.join(failures))
        elif blocked:
            self.step('p3-pages-nav', 'blocked',
                      'published=%d blocked=%s' % (published, ','.join(blocked)))
        else:
            self.step('p3-pages-nav', 'pass',
                      'published=%d/%d%s'
                      % (published, len(results),
                         ('（role-gated 延后到 manager 套件：%s）' % ','.join(deferred))
                         if deferred else ''))

    def _block(self, name, detail):
        """幂等登记 blocked：已登记的步骤不再重复写（step 遇到重名会抛错）。"""
        if name in self.steps:
            return
        self.step(name, 'blocked', detail)

    def _status_for(self, exc, blocked_hints=('库位', '夹具', '角色')):
        """FlowAbort 分两类：缺环境夹具 → blocked；已交付控件上的超时 → fail。"""
        if isinstance(exc, p2.FlowAbort):
            text = str(exc)
            if any(hint in text for hint in blocked_hints):
                return 'blocked'
            return 'fail'
        return 'fail'

    def row_count(self, selector):
        expression = ("(() => { try { return document.querySelectorAll(%s + ' tr').length; }"
                      " catch (e) { return -1; } })()" % js_str(selector))
        try:
            return int(self.cdp.evaluate(expression))
        except Exception:
            return -1

    def _poll(self, fn, predicate, timeout=10, interval=0.4):
        """轮询只读事实（写操作落库有短暂延迟），返回最后一次取值。"""
        deadline = time.time() + timeout
        value = None
        while time.time() < deadline:
            try:
                value = fn()
            except Exception:
                value = None
            if predicate(value):
                return value
            time.sleep(interval)
        return value

    def dispatch_change(self, selector):
        """对真实控件补发 change（等价于用户离开输入框），页面监听器据此更新购物车/表单状态。"""
        expression = """(() => {
          const el = document.querySelector(%s);
          if (!el) return false;
          el.dispatchEvent(new Event('change', {bubbles: true}));
          return true;
        })()""" % js_str(selector)
        return bool(self.cdp.evaluate(expression))

    # -- 诊断（失败现场；只取元数据，不含凭据/响应全文） --------------------
    def install_rpc_trace(self):
        """在每个新文档注入 fetch 元数据记录器（只在页面内存里，不落盘原文）。"""
        try:
            self.cdp.call('Page.addScriptToEvaluateOnNewDocument', source=RPC_TRACE_JS)
            return True
        except Exception as exc:
            self.note('install_rpc_trace failed: ' + p2.truncate(exc, 120))
            return False

    def read_rpc_trace(self, limit=8):
        try:
            rows = self.cdp.evaluate(
                "(() => (window.__LC_RPC_TRACE || []).slice(-%d))()" % int(limit)) or []
        except Exception:
            rows = []
        return rows if isinstance(rows, list) else []

    def last_rpc(self, path_suffix, rows=None):
        rows = self.read_rpc_trace() if rows is None else rows
        for row in reversed(rows):
            if str(row.get('path') or '').endswith(path_suffix):
                return row
        return {}

    def resolve_diagnostics(self):
        """解析失败现场：输入值、错误文案、已选卡片的 hidden/aria、下拉、状态区。"""
        expression = """(() => {
          const q = function (s) { try { return document.querySelector(s); } catch (e) { return null; } };
          const card = q('[data-lc-selected="material"]');
          const err = q('[data-lc-error="resolve"]');
          const load = q('[data-lc-loading="resolve"]');
          const input = q('[data-lc-field="item_key"]');
          const select = q('[data-slot="material-select"]');
          const status = q('[data-lc-status]');
          return {
            input_value: input ? String(input.value || '') : null,
            card_present: !!card,
            card_hidden: card ? card.hasAttribute('hidden') : null,
            card_aria_hidden: card ? card.getAttribute('aria-hidden') : null,
            card_text: card ? String(card.innerText || '').slice(0, 200) : '',
            error_hidden: err ? err.hasAttribute('hidden') : null,
            error_text: err ? String(err.innerText || '').slice(0, 240) : '',
            loading_hidden: load ? load.hasAttribute('hidden') : null,
            select_options: select
              ? Array.from(select.options || []).map(function (o) { return String(o.value); })
              : [],
            status_text: status ? String(status.innerText || '').slice(0, 240) : ''
          };
        })()"""
        try:
            return self.cdp.evaluate(expression) or {}
        except Exception as exc:
            return {'probe_error': p2.truncate(exc, 120)}

    def wait_for_resolve(self, timeout=25):
        """等「已选物料卡可见」或「解析错误文案出现」；两者任一即返回。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            facts = self.resolve_diagnostics()
            if facts.get('card_present') and facts.get('card_hidden') is False:
                return 'card', facts
            if facts.get('error_text'):
                return 'error', facts
            time.sleep(0.25)
        return 'timeout', self.resolve_diagnostics()

    def wait_page_runtime(self, timeout=20):
        """等页面脚本真正初始化完（window.LC + 权限位 + 写区可见性）。

        `nav()` 只等 `document.readyState`；`LC.register` 在脚本执行后才接事件，
        R6 的"点击无反应 → 25s 超时"就可能是这个竞态。这里等运行时就绪再操作。
        """
        return self.wait_js_soft(
            "(() => { const w = document.querySelector('[data-lc-write=\"prepare\"]');"
            " return !!(window.LC && window.LC.permissions && document.getElementById('workflow-root')"
            " && (!w || !w.hasAttribute('hidden'))); })()", timeout)

    def receipt_fixture_facts(self):
        """只读：P3_ITEM_KEY 在当前账号可见的本地档案候选（核对 seed 快照，不写业务数据）。"""
        code = self.cfg.item_code
        if not code:
            return {'candidates': None}
        state = self._api('/web/dataset/call_kw', {
            'model': 'product.template', 'method': 'search_read',
            'args': [[['lab_lcsc_code', '=', code]], ['id', 'name', 'lab_sn']],
            'kwargs': {'limit': 5}})
        payload = state.get('payload') or {}
        rows = payload.get('result')
        return {
            'code': code,
            'candidates': len(rows) if isinstance(rows, list) else None,
            'ids': [row.get('id') for row in rows] if isinstance(rows, list) else [],
            'catalog_index': bool(self._catalog_item(code)),
            'http_status': state.get('status'),
        }

    def flow_resolve_local_key(self):
        """`lab:<id>` 真实解析回归（跑在 `lcsc:` 主链之前，证明本地档案 key 也能被识别）。

        只读事实保证：解析本身不产生库存、也不产生待入库袋（quant 与 pending 行数不变）。
        """
        local_id = self._template_id()
        if not local_id:
            self._block('p3-receipt-resolve-local-key',
                        '取不到本地档案 id（夹具/权限缺口；quant_diag 见详情）')
            return
        key = 'lab:%d' % int(local_id)
        quant_before = self.quant_total()
        rows_before = max(self.row_count(self.selectors['receipt_pending_rows']), 0)
        try:
            self.type_into(self.selectors['receipt_item_key'], key)
            self.cdp.click(self.selectors['receipt_resolve_item'], label='resolve-item-local')
        except Exception as exc:
            self.step('p3-receipt-resolve-local-key', self._status_for(exc),
                      '本地 key 解析控件不可用: ' + p2.truncate(exc, 160))
            return
        outcome, facts = self.wait_for_resolve()
        trace = self.read_rpc_trace()
        rpc = self.last_rpc('/resolve_code', trace)
        quant_after = self.quant_total()
        rows_after = max(self.row_count(self.selectors['receipt_pending_rows']), 0)
        card = self.cdp.evaluate("""(() => {
          const slot = document.querySelector('[data-slot="material-key"]');
          const select = document.querySelector('[data-slot="material-select"]');
          return {
            card_key: slot ? String(slot.innerText || '').trim() : '',
            select_value: select ? String(select.value || '') : '',
            select_options: select
              ? Array.from(select.options || []).map(function (o) { return String(o.value); })
              : []
          };
        })()""") or {}
        canonical = 'lcsc:%s' % self.cfg.item_code if self.cfg.item_code else ''
        matched = (str(local_id) in (card.get('select_options') or [])
                   or card.get('select_value') == str(local_id)
                   or card.get('card_key') in (key, canonical))
        self.details['receipt_resolve_local'] = {
            'key': key, 'outcome': outcome, 'match': bool(matched),
            'dom': facts, 'card': card, 'rpc': rpc,
            'quant': [quant_before, quant_after],
            'pending_rows': [rows_before, rows_after]}

        def reset_selection():
            # 用页面自己的「重新选择」清空，避免污染随后 lcsc: 主链
            if self.has('[data-lc-action="clear-item"]'):
                self.cdp.click('[data-lc-action="clear-item"]', label='clear-item-local')

        ok = (outcome == 'card' and matched and quant_after == quant_before
              and rows_after == rows_before)
        if ok:
            self.step('p3-receipt-resolve-local-key', 'pass',
                      'key=%s 卡片匹配=%s（%s）quant %s 未变 待入库行 %d 未变'
                      % (key, matched, card.get('card_key') or '-', quant_before, rows_before))
        else:
            self.shot('p3-receipt-resolve-local-failure')
            self.step('p3-receipt-resolve-local-key', 'fail',
                      '本地 key 解析未通过 outcome=%s matched=%s quant %s->%s rows %s->%s '
                      'rpc=%s/%s%s'
                      % (outcome, matched, quant_before, quant_after, rows_before, rows_after,
                         rpc.get('status'), rpc.get('code') or rpc.get('error') or '-',
                         (' keys=' + ','.join(rpc.get('keys') or [])) if rpc.get('keys') else ''))
        reset_selection()

    def _block_receipt_chain(self, detail):
        for name in ('p3-receipt-resolve-local-key', 'p3-receipt-item-resolve',
                     'p3-receipt-create-no-stock',
                     'p3-receipt-shelve-resolve', 'p3-receipt-confirm',
                     'p3-receipt-confirm-replay', 'p3-receipt-same-key-conflict',
                     'p3-issue-submit', 'p3-return-partial',
                     'p3-cross-user-denied', 'p3-unknown-outcome-retry',
                     'p3-label-pdf'):
            if name not in self.steps:
                self._block(name, detail)

    # -- 两阶段入库：建袋 → 不增库存 → 扫码上架 → 增库存 → 重放 -------------
    def flow_receipts(self):
        page_result = (self.details.get('p3_pages', {}).get('receipts') or {}).get('result')
        if page_result != 'pass':
            self._block('p3-page-receipts', 'receipts 页面未发布')
            self._block_receipt_chain('依赖 receipts 页面，未执行')
            return
        # 页面巡检最后停在别的页；R5 的"缺建袋控件"就是没回到 receipts 页导致的假象。
        # 这里先真实导航回来，再按当前页面事实判定。
        try:
            nav = self.nav(PAGE_PATHS['receipts'], 'p3 receipts page')
            state = self.read_page_state(nav.get('context_id'))
        except Exception as exc:
            self.step('p3-page-receipts', self._status_for(exc),
                      '打开 receipts 页失败: ' + p2.truncate(exc, 140))
            self._block_receipt_chain('receipts 页打不开，后续未执行')
            return
        if state.get('login_form'):
            self.step('p3-page-receipts', 'fail', '回到 receipts 页时已掉登录')
            self._block_receipt_chain('掉登录，后续未执行')
            return
        if state.get('placeholder') or not state.get('marker'):
            self.step('p3-page-receipts', 'fail',
                      'receipts 页未渲染业务页面（placeholder=%s marker=%s）'
                      % (state.get('placeholder'), state.get('marker')))
            self._block_receipt_chain('receipts 页未就绪，后续未执行')
            return
        self.step('p3-page-receipts', 'pass', 'path=%s' % PAGE_PATHS['receipts'])
        runtime_ready = self.wait_page_runtime()
        if not runtime_ready:
            self.note('receipts 页面脚本 20s 内未就绪（window.LC/权限位/写区）')
        if not self.cfg.item_key:
            self._block_receipt_chain('缺 P3_ITEM_KEY（形如 lcsc:C123456）')
            return
        if not self.has(self.selectors['receipt_item_key']):
            # 页面已交付（上面已确认 marker/脚本在），控件缺失属真实缺陷 → fail
            self.step('p3-receipt-item-resolve', 'fail',
                      'receipts 页已发布但缺建袋控件 %s' % self.selectors['receipt_item_key'])
            self._block_receipt_chain('建袋控件缺失（真实缺陷，已判 fail）')
            return

        # ⓪ 夹具事实（只读核对 seed 快照：该 C 编号有没有本地档案；不写业务数据）
        fixture = self.receipt_fixture_facts()
        self.details['receipt_fixture'] = fixture
        if fixture.get('candidates') == 0:
            self._block('p3-receipt-item-resolve',
                        'seed 快照缺本地档案：lab_lcsc_code=%s 无候选（夹具缺口，非产品缺陷）'
                        % self.cfg.item_code)
            self._block_receipt_chain('夹具缺本地档案绑定，后续未执行')
            return

        # ①-a 本地档案 key（lab:<id>）真实解析回归：先证明它也能被识别，再走 lcsc: 主链
        self.flow_resolve_local_key()

        # ① 解析料号（真实输入 + 真实点击；失败时抓现场，而不是断言选择器）
        try:
            self.type_into(self.selectors['receipt_item_key'], self.cfg.item_key)
            self.cdp.click(self.selectors['receipt_resolve_item'], label='resolve-item')
        except Exception as exc:
            self.step('p3-receipt-item-resolve', self._status_for(exc),
                      '解析控件不可用: ' + p2.truncate(exc, 160))
            self._block_receipt_chain('解析控件不可用，后续未执行')
            return
        outcome, facts = self.wait_for_resolve()
        trace = self.read_rpc_trace()
        rpc = self.last_rpc('/resolve_code', trace)
        self.details['receipt_resolve'] = {
            'outcome': outcome, 'runtime_ready': runtime_ready,
            'dom': facts, 'rpc': rpc, 'rpc_tail': trace[-4:]}
        if outcome == 'card':
            self.step('p3-receipt-item-resolve', 'pass',
                      'item_key=%s 已选物料卡=%s'
                      % (self.cfg.item_key, p2.truncate(facts.get('card_text'), 80)))
        else:
            self.shot('p3-receipt-resolve-failure')
            self.step('p3-receipt-item-resolve', 'fail',
                      '解析未成功 outcome=%s rpc=%s/%s%s dom=%s'
                      % (outcome, rpc.get('status'),
                         rpc.get('code') or rpc.get('error') or '-',
                         (' keys=' + ','.join(rpc.get('keys') or [])) if rpc.get('keys') else '',
                         p2.truncate(json.dumps(facts, ensure_ascii=False), 260)))
            self._block_receipt_chain('料号解析未成功（现场见 receipt_resolve）')
            return

        # ② 建待入库袋：确认前库存不得变化
        before = self.quant_total()
        if before is None:
            self._block_receipt_chain('读不到库存（内部/在途 stock.quant 只读失败）diag='
                                      + self.quant_error_detail())
            return
        rows_before = max(self.row_count(self.selectors['receipt_pending_rows']), 0)
        self.pending_before = rows_before
        pending_ids_before = self.cdp.evaluate(
            "Array.from(document.querySelectorAll(%s + ' tr')).map(r => r.getAttribute('data-id'))"
            % js_str(self.selectors['receipt_pending_rows'])) or []
        try:
            self.type_into(self.selectors['receipt_qty'], '2')
            if self.has(self.selectors['receipt_count']):
                self.type_into(self.selectors['receipt_count'], '1')
            self.prepare_navigation('p3 pending create',
                                    path='/lab/api/inventory/pending/create')
            self.cdp.click(self.selectors['receipt_create'], label='pending-create')
            self.wait_js(
                "(() => { const rows = document.querySelectorAll(%s + ' tr');"
                " return rows.length > %d; })()"
                % (js_str(self.selectors['receipt_pending_rows']), rows_before),
                'pending row')
            after = self.quant_total()
            self.step('p3-receipt-create-no-stock',
                      'pass' if after == before else 'fail',
                      'quant %s -> %s（建袋不得增库存）rows %d -> %d'
                      % (before, after, rows_before,
                         self.row_count(self.selectors['receipt_pending_rows'])))
            self.shot('p3-receipt-pending')
            trace_dom = self.cdp.evaluate(
                "(() => { const prior = %s;"
                " const rows = Array.from(document.querySelectorAll(%s + ' tr'))"
                " .filter(r => !prior.includes(r.getAttribute('data-id')));"
                " if (rows.length !== 1) return {new_rows: rows.length};"
                " return {row_id: rows[0].getAttribute('data-id'),"
                " trace: (rows[0].cells[1].textContent || '').trim()}; })()"
                % (json.dumps(pending_ids_before), js_str(self.selectors['receipt_pending_rows']))) or {}
            self.details['receipt_pending_dom'] = trace_dom
            self.trace_code = trace_dom.get('trace') or ''
        except Exception as exc:
            self.step('p3-receipt-create-no-stock', self._status_for(exc),
                      '建袋未完成: ' + p2.truncate(exc, 160))
            self._block_receipt_chain('建袋未完成，后续未执行')
            return
        if not self.trace_code:
            self._block_receipt_chain('建袋后无法从唯一新增DOM行读取原始追溯码')
            return

        # ③ 扫码上架（shelve tab）→ 确认入库
        try:
            if self.has(self.selectors['receipt_tab_shelve']):
                self.cdp.click(self.selectors['receipt_tab_shelve'], label='tab-shelve')
            self.type_into(self.selectors['receipt_scan'], 'LABB:' + self.trace_code)
            self.cdp.click(self.selectors['receipt_resolve_pending'], label='resolve-pending')
            self.wait_js(
                "(() => { const el = document.querySelector(%s);"
                " return !!(el && !el.hidden && el.offsetParent !== null); })()"
                % js_str(self.selectors['receipt_confirm_form']),
                'confirm form')
            self.step('p3-receipt-shelve-resolve', 'pass', 'trace=%s' % self.trace_code)
        except Exception as exc:
            self.step('p3-receipt-shelve-resolve', self._status_for(exc),
                      '扫码上架未就绪: ' + p2.truncate(exc, 160))
            for name in ('p3-receipt-confirm', 'p3-receipt-confirm-replay',
                         'p3-issue-submit', 'p3-return-partial',
                         'p3-cross-user-denied', 'p3-unknown-outcome-retry',
                         'p3-label-pdf'):
                if name not in self.steps:
                    self._block(name, '扫码上架未就绪，后续未执行')
            return

        try:
            self._select_first_location()
            if self.has(self.selectors['receipt_confirm_qty']):
                self.type_into(self.selectors['receipt_confirm_qty'], '2')
            self.prepare_navigation('p3 pending confirm',
                                    path='/lab/api/inventory/pending/confirm')
            self.cdp.click(self.selectors['receipt_confirm'], label='pending-confirm')
            success = self.wait_js_soft(
                "(() => { const el = document.querySelector(%s);"
                " return !!(el && !el.hidden); })()"
                % js_str(self.selectors['receipt_success']), 20)
            after = self._poll(self.quant_total,
                               lambda value: value is not None and value == round(before + 2, 6),
                               timeout=12)
            ok = bool(success) and after == round(before + 2, 6)
            self.step('p3-receipt-confirm',
                      'pass' if ok else 'fail',
                      'success_banner=%s quant %s -> %s（期望 +2）' % (bool(success), before, after))
            if ok:
                self.shot('p3-receipt-confirmed')
        except Exception as exc:
            self.step('p3-receipt-confirm', self._status_for(exc),
                      '确认未完成: ' + p2.truncate(exc, 160))
            after = self.quant_total()
        # ④ 真实重复尝试：同一袋再扫一次上架，页面必须回"已入库"且库存不再变化
        settled = self.quant_total()
        try:
            if self.has(self.selectors['receipt_tab_shelve']):
                self.cdp.click(self.selectors['receipt_tab_shelve'], label='tab-shelve-again')
            self.type_into(self.selectors['receipt_scan'], 'LABB:' + self.trace_code)
            self.cdp.click(self.selectors['receipt_resolve_pending'], label='resolve-again')
            again = self.wait_js_soft(
                "(() => { const el = document.querySelector(%s);"
                " return !!(el && !el.hidden); })()"
                % js_str(self.selectors['receipt_success']), 15)
            replay = self.quant_total()
            ok = bool(again) and settled is not None and replay == settled
            self.step('p3-receipt-confirm-replay', 'pass' if ok else 'fail',
                      '重复扫码已入库袋：banner=%s quant %s -> %s（不得重复入库）'
                      % (bool(again), settled, replay))
        except Exception as exc:
            self.step('p3-receipt-confirm-replay', self._status_for(exc),
                      '重复扫码未完成: ' + p2.truncate(exc, 160))

        self._block('p3-receipt-same-key-conflict',
                    '同 key 异 payload 由 verify-p3-write.sh 覆盖（UI 无该入口）')
        self.flow_issue()
        self.flow_return()
        self._block('p3-cross-user-denied',
                    '跨账号归还需第二个浏览器会话；由 verify-p3-write.sh 与 HttpCase 独立覆盖')
        self._block('p3-unknown-outcome-retry',
                    '未知结果重试需用 CDP 断网注入 + 精确网络失败白名单，本轮未实现；'
                    '同 payload 同 request_key 的重试语义由 verify-p3-write.sh 与 '
                    'test_workflow_core.mjs 覆盖，这里不冒充已测')
        self.flow_pdf()

    def _select_first_location(self):
        """在确认表单里选第一个可用库位（真实 select 变更事件）。"""
        expression = """(() => {
          const sel = document.querySelector(%s);
          if (!sel) return '';
          const option = Array.from(sel.options || []).find(function (o) {
            return o.value && !o.disabled;
          });
          if (!option) return '';
          sel.value = option.value;
          sel.dispatchEvent(new Event('change', {bubbles: true}));
          return option.value;
        })()""" % js_str(self.selectors['receipt_location'])
        value = self.cdp.evaluate(expression)
        if not value:
            raise p2.FlowAbort('确认表单没有可选库位')
        return value

    # -- 领用（真实页面填表/点击 → 写请求），只读 API 核对未还余额 ----------
    def flow_issue(self):
        page_result = (self.details.get('p3_pages', {}).get('issue_new') or {}).get('result')
        if page_result != 'pass':
            self._block('p3-issue-submit', 'issue_new 页面未发布')
            return
        if not self.trace_code:
            self._block('p3-issue-submit', '没有上一步入库得到的袋码，无法领用')
            return
        # 当前还在 receipts 页：先真实导航到领用页，再检查控件
        try:
            nav = self.nav(PAGE_PATHS['issue_new'], 'p3 issue new page')
            state = self.read_page_state(nav.get('context_id'))
            if state.get('error_page') or state.get('login_form'):
                self.step('p3-issue-submit', 'fail',
                          'issue_new 页不可用（error_page=%s login=%s）'
                          % (state.get('error_page'), state.get('login_form')))
                return
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-issue-submit', status,
                      '打开领用页失败: ' + p2.truncate(exc, 160))
            return
        self.wait_page_runtime(15)
        if not self.has(self.selectors['issue_scan']):
            self.step('p3-issue-submit', 'fail',
                      'issue_new 页已发布但缺扫码框 %s' % self.selectors['issue_scan'])
            return
        before = self.quant_total()
        if before is None:
            self._block('p3-issue-submit', '读不到库存（内部/在途 stock.quant 只读失败）diag='
                        + self.quant_error_detail())
            return
        try:
            self.type_into(self.selectors['issue_scan'], 'LABB:' + self.trace_code)
            self.cdp.click(self.selectors['issue_resolve'], label='issue-resolve')
            self.wait_js(
                "(() => !!document.querySelector(%s))()"
                % js_str(self.selectors['issue_add_bag']), 'issue add-bag', timeout=20)
            self.cdp.click(self.selectors['issue_add_bag'], label='issue-add-bag')
            self.wait_js(
                "(() => !!document.querySelector(%s))()"
                % js_str(self.selectors['issue_cart_qty']), 'issue cart row', timeout=15)
            self.type_into(self.selectors['issue_cart_qty'], '2')
            self.dispatch_change(self.selectors['issue_cart_qty'])
            self._select_borrower_self()
            self.type_into(self.selectors['issue_project'], 'P3-DOM-验收')
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-issue-submit', status,
                      '领用表单未就绪: ' + p2.truncate(exc, 160))
            return
        try:
            self.prepare_navigation('p3 issue submit', path='/lab/api/inventory/issue')
            self.cdp.click(self.selectors['issue_submit'], label='submit-issue')
            banner = self.wait_js_soft(
                "(() => { const el = document.querySelector(%s);"
                " return !!(el && !el.hidden); })()" % js_str(self.selectors['issue_success']),
                25)
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-issue-submit', status,
                      '领用提交未完成: ' + p2.truncate(exc, 160))
            return
        after = self._poll(self.quant_total,
                          lambda value: value is not None and value == round(before - 2, 6),
                          timeout=15)
        outstanding = self._poll(lambda: self.outstanding_for(self.trace_code),
                                 lambda value: value == 2, timeout=15)
        ok = (after == round(before - 2, 6) and outstanding == 2)
        self.step('p3-issue-submit', 'pass' if ok else 'fail',
                  'success_panel=%s quant %s -> %s outstanding=%s（页面提交产生真实领用）'
                  % (bool(banner), before, after, outstanding))
        if ok:
            self.shot('p3-issue-done')

    def _select_borrower_self(self):
        """领用人下拉选本人（can_issue_for_others=false 时通常只有一个有效项）。"""
        expression = """(() => {
          const sel = document.querySelector(%s);
          if (!sel) return '';
          const options = Array.from(sel.options || []).filter(function (o) {
            return o.value;
          });
          if (!options.length) return '';
          sel.value = options[0].value;
          sel.dispatchEvent(new Event('change', {bubbles: true}));
          return sel.value;
        })()""" % js_str(self.selectors['issue_borrower'])
        value = self.cdp.evaluate(expression)
        if not value:
            raise p2.FlowAbort('领用人下拉没有可选项')

    # -- 部分归还（真实页面）→ 只读 API 核对未还余额 ----------------------
    def flow_return(self):
        page_result = (self.details.get('p3_pages', {}).get('issues') or {}).get('result')
        if page_result != 'pass':
            self._block('p3-return-partial', 'issues 页面未发布')
            return
        base = PAGE_PATHS['issues']
        trace = self.trace_code
        if not trace:
            self._block('p3-return-partial', '没有袋码，无法定位领用行')
            return
        try:
            # 真实导航：先用页面自己的筛选（q=trace_code + 只看未还）缩小到本次领用行
            nav = self.nav(base + '?q=' + quote(trace) + '&outstanding_only=1',
                           'p3 issues page', match_path=base)
            state = self.read_page_state(nav.get('context_id'))
            if state.get('error_page'):
                self.step('p3-return-partial', 'fail',
                          'issues 页已交付但渲染错误页（服务端 4xx/5xx）')
                return
            ready = self.wait_js_soft(
                "(() => !!document.querySelector(%s))()"
                % js_str(self.selectors['issues_return_open']), 12)
            if not ready and self.has(self.selectors['issues_filter_query']):
                # 兜底：URL 过滤未生效时，用页面表单筛选（仍是真实 UI 操作）
                self.type_into(self.selectors['issues_filter_query'], trace)
                if self.has(self.selectors['issues_filter_outstanding']):
                    # 该控件是 <select>（1=只看未归还 / 0=全部），不是 checkbox
                    self.cdp.evaluate(
                        "(() => { const el = document.querySelector(%s);"
                        " if (el) { el.value = '1';"
                        " el.dispatchEvent(new Event('change', {bubbles: true})); }"
                        " return true; })()"
                        % js_str(self.selectors['issues_filter_outstanding']))
                self.cdp.click(self.selectors['issues_filter_search'], label='issues-search')
                ready = self.wait_js_soft(
                    "(() => !!document.querySelector(%s))()"
                    % js_str(self.selectors['issues_return_open']), 15)
            if not ready:
                raise p2.FlowAbort('issues 列表没有可归还行（bag=%s）' % trace)
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-return-partial', status,
                      '归还列表未就绪: ' + p2.truncate(exc, 160))
            return
        before_outstanding = self.outstanding_for(trace)
        before_quant = self.quant_total()
        try:
            index = self._return_row_index(trace)
            if index < 0:
                raise p2.FlowAbort('列表里找不到该袋的归还入口（bag=%s）' % trace)
            self.cdp.click(self.selectors['issues_return_open'], index=index, label='return-open')
            self.wait_js(
                "(() => { const el = document.querySelector(%s);"
                " return !!(el && el.offsetParent !== null); })()"
                % js_str(self.selectors['issues_return_form']), 'return form', timeout=15)
            self.type_into(self.selectors['issues_return_qty'], '1')
            self.dispatch_change(self.selectors['issues_return_qty'])
            self.prepare_navigation('p3 return submit', path='/lab/api/inventory/return')
            self.cdp.click(self.selectors['issues_return_submit'], label='submit-return')
            self.wait_js_soft("(() => true)()", 3)
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-return-partial', status,
                      '归还未完成: ' + p2.truncate(exc, 160))
            return
        after_outstanding = self._poll(lambda: self.outstanding_for(trace),
                                       lambda value: value == 1, timeout=15)
        after_quant = self._poll(self.quant_total,
                                 lambda value: (before_quant is not None
                                                and value == round(before_quant + 1, 6)),
                                 timeout=15)
        ok = (after_outstanding == 1 and before_quant is not None
              and after_quant == round(before_quant + 1, 6))
        self.step('p3-return-partial', 'pass' if ok else 'fail',
                  'outstanding %s -> %s quant %s -> %s（部分归还 1/2，页面提交）'
                  % (before_outstanding, after_outstanding, before_quant, after_quant))
        if ok:
            self.shot('p3-return-done')

    def _return_row_index(self, trace):
        """在 issues 行里定位属于该袋的「归还」按钮序号（避免点到别人的领用行）。"""
        expression = """(() => {
          const nodes = Array.from(document.querySelectorAll(%s));
          for (let i = 0; i < nodes.length; i++) {
            const tr = nodes[i].closest('tr');
            if (tr && (tr.innerText || '').indexOf(%s) >= 0) { return i; }
          }
          return -1;
        })()""" % (js_str(self.selectors['issues_return_open']), js_str(trace))
        try:
            return int(self.cdp.evaluate(expression))
        except Exception:
            return -1

    def outstanding_for(self, trace_code):
        """只读 API：按袋码查未归还余额（issues 端点，非写操作）。"""
        if not trace_code:
            return None
        state = self._api('/lab/api/inventory/issues', {
            'query': trace_code, 'outstanding_only': True, 'limit': 50})
        payload = state.get('payload') or {}
        result = payload.get('result') or {}
        if not result.get('ok'):
            return None
        rows = (result.get('data') or {}).get('issues') or []
        for row in rows if isinstance(rows, list) else []:
            code = row.get('trace_code') or ((row.get('bag') or {}).get('trace_code'))
            if code == trace_code:
                return row.get('outstanding_quantity')
        return None

    def flow_pdf(self):
        """断言 PDF 入口是"真实表单 POST + CSRF + 新窗口"，响应头由脚本侧校验。"""
        # 标签页才有 PDF 表单；先真实导航过去
        try:
            self.nav(PAGE_PATHS['labels'], 'p3 labels page')
        except Exception as exc:
            self.step('p3-label-pdf', self._status_for(exc),
                      '打开标签页失败: ' + p2.truncate(exc, 140))
            return
        if not self.has(self.selectors['pdf_form']):
            self.step('p3-label-pdf', 'fail',
                      'labels 页已发布但缺 PDF 表单 %s' % self.selectors['pdf_form'])
            return
        info = self.cdp.evaluate("""(() => {
          const form = document.querySelector(%s);
          if (!form) return null;
          const hidden = {};
          Array.from(form.querySelectorAll('input[type="hidden"]')).forEach(function (el) {
            hidden[el.getAttribute('name') || ''] = String(el.value || '');
          });
          return {
            action: form.getAttribute('action') || '',
            method: (form.getAttribute('method') || '').toUpperCase(),
            target: form.getAttribute('target') || '',
            csrf: String(hidden.csrf_token || '').length > 0,
            fields: Object.keys(hidden).filter(function (key) {
              return key && key !== 'csrf_token';
            }).sort()
          };
        })()""" % js_str(self.selectors['pdf_form'])) or {}
        required = ['copies', 'fields', 'gap_mm', 'height_mm', 'ids', 'kind',
                    'margin_mm', 'width_mm']
        ok = (info.get('action') or '').endswith('/lab/labels/pdf') \
            and info.get('method') == 'POST' and info.get('csrf') is True \
            and info.get('target') == '_blank' \
            and list(info.get('fields') or []) == required
        self.step('p3-label-pdf', 'pass' if ok else 'fail',
                  'action_tail=%s method=%s csrf=%s target=%s fields=%s（内联脚本/iframe 都不用）'
                  % ((info.get('action') or '')[-24:], info.get('method'),
                     info.get('csrf'), info.get('target'),
                     ','.join(info.get('fields') or [])))
        self.shot('p3-labels-pdf')

    # -- 角色/匿名 -------------------------------------------------------
    def flow_role(self):
        path = PAGE_PATHS['settings']
        if self.cfg.manager_login and self.cfg.login == self.cfg.manager_login:
            self._block('p3-readonly-role-denied',
                        '巡检账号就是管理员账号（LOGIN == P3_MANAGER_LOGIN）；'
                        '角色门槛由另一次非管理员账号运行覆盖')
            return
        try:
            nav = self.nav(path, 'p3 settings as operator')
            state = self.read_page_state(nav.get('context_id'))
        except Exception as exc:
            self.step('p3-readonly-role-denied', self._status_for(exc),
                      '导航失败: ' + p2.truncate(exc, 140))
            return
        denied = bool(state.get('error_page')) or '403' in (state.get('title') or '')
        self.step('p3-readonly-role-denied', 'pass' if denied else 'fail',
                  'error_page=%s title=%s（非管理员访问 manager 页）'
                  % (state.get('error_page'), p2.truncate(state.get('title'), 40)))
        try:
            self.nav(PAGE_PATHS['receipts'], 'p3 restore page')
        except Exception:
            pass

    # -- 管理域（库位 / 映射 / 成员角色 / 材料）：真实 DOM 写交互 -------------
    def _ui_login_as(self, login, password, label):
        """在当前浏览器里真实登出+登录（不登记重复步骤）。"""
        self.cdp.call('Network.clearBrowserCookies')
        url = self.cfg.url + '/team/login?next=' + PAGE_PATHS['receipts']
        self.prepare_navigation('p3 login as ' + label)
        self.cdp.call('Page.navigate', url=url)
        self.wait_js(
            "(() => { const f = document.getElementById('lc-login-form');"
            " return !!(f && f.querySelector('input[name=login]')); })()",
            'login form for ' + label, 25)
        self.type_into('#lc-login-form input[name=login]', login)
        self.type_into('#lc-login-form input[name=password]', password)
        self.prepare_navigation('p3 submit login ' + label)
        self.cdp.click('#lc-login-form button[type=submit]', label='login-' + label)
        self.wait_js(
            "(() => document.body.getAttribute('data-authenticated') === '1')()",
            'authenticated as ' + label, 30)

    def flow_manager_suite(self):
        if not (self.cfg.manager_login and self.cfg.manager_password):
            for name in ('p3-manager-login', 'p3-location-create', 'p3-mapping-set',
                         'p3-member-role-toggle', 'p3-material-write'):
                self._block(name, '未提供 P3_MANAGER_LOGIN/P3_MANAGER_PASSWORD，管理域未执行')
            return
        try:
            self._ui_login_as(self.cfg.manager_login, self.cfg.manager_password, 'manager')
            self.step('p3-manager-login', 'pass', 'manager=%s' % self.cfg.manager_login)
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-manager-login', status, '管理员登录失败: ' + p2.truncate(exc, 160))
            for name in ('p3-location-create', 'p3-mapping-set',
                         'p3-member-role-toggle', 'p3-material-write'):
                self._block(name, '管理员登录失败，未执行')
            return
        self._flow_location_create()
        self._flow_mapping_set()
        self._flow_member_role()
        self._flow_material_write()

    def _flow_location_create(self):
        stamp = time.strftime('%H%M%S')
        name = 'P3-DOM-LOC-%s' % stamp
        try:
            self.nav(PAGE_PATHS['locations'], 'p3 locations page')
            if not self.has(self.selectors['loc_toggle_create']):
                self.step('p3-location-create', 'fail',
                          'locations 页已发布但缺「新建库位」按钮')
                return
            self.cdp.click(self.selectors['loc_toggle_create'], label='locations-create')
            self.wait_js(
                "(() => { const f = document.querySelector(%s);"
                " return !!(f && f.offsetParent !== null); })()"
                % js_str(self.selectors['loc_create_form']), 'location create form', 15)
            self.type_into(self.selectors['loc_name'], name)
            self.prepare_navigation('p3 location create', path='/lab/api/inventory/location_create')
            self.cdp.click(self.selectors['loc_submit'], label='location-create-submit')
            self.wait_js(
                "(() => { const rows = document.querySelector(%s);"
                " return !!(rows && rows.innerText && rows.innerText.indexOf(%s) >= 0); })()"
                % (js_str(self.selectors['loc_rows']), js_str(name)),
                'location row %s' % name, 20)
            found = self._poll(
                lambda: self._api_find('/lab/api/inventory/locations', {}, 'locations',
                                       'name', name),
                lambda value: bool(value), timeout=15)
            self.step('p3-location-create', 'pass' if found else 'fail',
                      'name=%s 只读API可见=%s（页面表单创建）' % (name, bool(found)))
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-location-create', status,
                      '库位创建未完成: ' + p2.truncate(exc, 160))

    def _flow_mapping_set(self):
        try:
            category = self._first_category()
            location_id = self._last_location_id()
            if not category or not location_id:
                self._block('p3-mapping-set', '缺少类别或库位夹具（无法安全构造映射）')
                return
            self.nav(PAGE_PATHS['mappings'], 'p3 mappings page')
            if not self.has(self.selectors['map_form']):
                self.step('p3-mapping-set', 'fail',
                          'mappings 页已发布但缺映射表单 %s' % self.selectors['map_form'])
                return
            self.type_into(self.selectors['map_category'], str(category))
            self._select_option_value(self.selectors['map_location'], str(location_id))
            if self.has(self.selectors['map_priority']):
                self.type_into(self.selectors['map_priority'], '10')
            self.prepare_navigation('p3 mapping set', path='/lab/api/inventory/mapping_set')
            self.cdp.click(self.selectors['map_submit'], label='mapping-submit')
            hit = self._poll(lambda: self._mapping_hit(category, location_id),
                             lambda value: bool(value), timeout=15)
            self.step('p3-mapping-set', 'pass' if hit else 'fail',
                      'category=%s location=%s 只读API可见=%s（页面表单保存）'
                      % (category, location_id, bool(hit)))
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-mapping-set', status,
                      '映射保存未完成: ' + p2.truncate(exc, 160))

    def _mapping_hit(self, category, location_id):
        rows = self._api_post('/lab/api/inventory/mapping_list', {})
        for mapping in rows.get('mappings') or []:
            if (int(mapping.get('category_id') or 0) == int(category)
                    and int(mapping.get('location_id') or 0) == int(location_id)):
                return mapping
        return None

    def _flow_member_role(self):
        login = self.cfg.norole_login
        try:
            self.nav(PAGE_PATHS['settings'], 'p3 settings page')
            if not self.has(self.selectors['members_query']):
                self.step('p3-member-role-toggle', 'fail',
                          'settings 页已发布但缺成员搜索框 %s'
                          % self.selectors['members_query'])
                return
            self.type_into(self.selectors['members_query'], login)
            self.cdp.click(self.selectors['members_search'], label='members-search')
            self.wait_js(
                "(() => { const rows = document.querySelector(%s);"
                " return !!(rows && rows.innerText && rows.innerText.indexOf(%s) >= 0); })()"
                % (js_str(self.selectors['members_rows']), js_str(login)),
                'member row %s' % login, 20)
            before = self._member_role(login)
            if before is None:
                self._block('p3-member-role-toggle',
                            '隔离库里没有成员 %s（夹具缺失，无法做真实角色切换）' % login)
                return
            index = self._role_checkbox_index(login)
            if index < 0:
                self.step('p3-member-role-toggle', 'fail',
                          '成员行已渲染但找不到 %s 的 lab_user 勾选框' % login)
                return
            trail = [before]
            if before:
                # 先把状态归零，避免把"本来就是操作员"误判成勾选生效
                trail.append(self._toggle_role(index, login, False))
            trail.append(self._toggle_role(index, login, True))
            trail.append(self._toggle_role(index, login, False))
            ok = trail[-1] is False and True in trail
            self.step('p3-member-role-toggle', 'pass' if ok else 'fail',
                      'lab_user %s（勾选/取消即提交，逐次读服务端事实）'
                      % '→'.join('?' if item is None else str(item) for item in trail))
        except Exception as exc:
            status = self._status_for(exc)
            self.step('p3-member-role-toggle', status,
                      '成员角色切换未完成: ' + p2.truncate(exc, 160))

    def _toggle_role(self, index, login, expected):
        """真实点击角色勾选框，并轮询服务端角色事实到期望值；返回实际值。"""
        self.cdp.click(self.selectors['role_checkbox'], index=index,
                       label='role-lab_user-%s' % ('on' if expected else 'off'))
        return self._poll(lambda: self._member_role(login),
                          lambda value: value is expected, timeout=15)

    def _flow_material_write(self):
        """材料写交互：合成索引行当夹具 + 真实"按资料库建档"（断言不复制库存）。"""
        code = self.cfg.catalog_code
        if not self.cfg.catalog_fixture or not code:
            self._block('p3-material-write', 'P3_CATALOG_FIXTURE=0：材料写未执行（未冒充）')
            return
        try:
            nav = self.nav(PAGE_PATHS['materials'], 'p3 materials page')
            state = self.read_page_state(nav.get('context_id'))
            if state.get('error_page'):
                self._block('p3-material-write',
                            'materials 页 403：当前账号无 catalog 角色，材料写未执行')
                return
        except Exception as exc:
            self.step('p3-material-write', self._status_for(exc),
                      '材料页未打开: ' + p2.truncate(exc, 140))
            return
        if not self.has(self.selectors['material_query']):
            self.step('p3-material-write', 'fail',
                      'materials 页已发布但缺资料库检索框 %s'
                      % self.selectors['material_query'])
            return
        fixture, fixture_detail = self._ensure_catalog_fixture(code)
        if not fixture:
            self._block('p3-material-write',
                        '合成资料库夹具 %s 不可用（%s）；材料建档未执行（未用 API 写冒充 UI）'
                        % (code, fixture_detail))
            return
        before = len(self._templates_for_code(code))
        expected = before + 1 if before == 0 else before   # 已有档案时服务端复用，不得重复建
        try:
            self.type_into(self.selectors['material_query'], code)
            self.cdp.click(self.selectors['material_search'], label='material-search')
            row = '[data-lc-action="materials-create-row"][data-lc-inv-item-key="lcsc:%s"]' % code
            self.wait_js("(() => !!document.querySelector(%s))()" % js_str(row),
                         'material row %s' % code, 20)
            self.cdp.click(row, label='material-create-row')
            after = self._poll(lambda: len(self._templates_for_code(code)),
                               lambda value: value == expected, timeout=20)
            templates = self._templates_for_code(code)
            stock_rows = self._quant_rows_for_template(
                templates[0].get('id')) if templates else None
            ok = (after == expected and stock_rows == 0)
            self.step('p3-material-write', 'pass' if ok else 'fail',
                      'code=%s 本地档案 %d->%d（期望 %d，%s）stock_rows=%s'
                      % (code, before, after, expected,
                         '首次建档' if before == 0 else '服务端复用', stock_rows))
        except Exception as exc:
            self.step('p3-material-write', self._status_for(exc),
                      '材料建档未完成: ' + p2.truncate(exc, 160))

    # -- 只读辅助 --------------------------------------------------------
    def _api_post(self, path, params):
        state = self._api(path, params)
        result = (state.get('payload') or {}).get('result') or {}
        if not result.get('ok'):
            return {}
        return result.get('data') or {}

    def _api_find(self, path, params, key, field, value):
        data = self._api_post(path, params)
        for item in data.get(key) or []:
            if item.get(field) == value:
                return item
        return None

    def _first_category(self):
        state = self._api('/web/dataset/call_kw', {
            'model': 'product.category', 'method': 'search_read',
            'args': [[], ['id']], 'kwargs': {'limit': 1}})
        rows = ((state.get('payload') or {}).get('result') or [])
        return rows[0].get('id') if rows else None

    def _catalog_item(self, code):
        """只读：合成资料库索引行是否存在。"""
        state = self._api('/web/dataset/call_kw', {
            'model': 'lab.catalog.item', 'method': 'search_read',
            'args': [[['catalog_code', '=', code], ['market', '=', 'cn']],
                     ['id', 'catalog_code', 'name', 'mpn']],
            'kwargs': {'limit': 1}})
        rows = ((state.get('payload') or {}).get('result') or [])
        return rows[0] if isinstance(rows, list) and rows else None

    def _ensure_catalog_fixture(self, code):
        """夹具（不是被测功能）：隔离库里补一行**合成**资料库索引，供材料页真实建档。

        * 只写 `lab.catalog.item`（不建档案、不写库存、不连爬虫/生产）；
        * 幂等：已存在就不再写；
        * 结果写进 `details['material_fixture']`，证据里能看出这是夹具而非业务动作。
        """
        existing = self._catalog_item(code)
        if existing:
            info = {'status': 'exists', 'id': existing.get('id')}
            self.details['material_fixture'] = info
            return True, 'exists id=%s' % existing.get('id')
        state = self._api('/web/dataset/call_kw', {
            'model': 'lab.catalog.item', 'method': 'create',
            'args': [[{
                'catalog_code': code, 'market': 'cn',
                'name': 'P3 浏览器验收合成器件', 'mpn': 'P3-DOM-MPN',
                'brand': 'P3-SYNTH', 'brand_code': 'P3SYN', 'package': '0603',
                'search_text': '%s P3 浏览器验收合成器件 P3-DOM-MPN' % code,
            }]],
            'kwargs': {}})
        payload = state.get('payload') or {}
        created = payload.get('result')
        if isinstance(created, list) and created:
            info = {'status': 'created', 'id': created[0]}
            self.details['material_fixture'] = info
            return True, 'created id=%s' % created[0]
        error = payload.get('error') or {}
        data = error.get('data') if isinstance(error, dict) else {}
        message = (data or {}).get('message') if isinstance(data, dict) else ''
        info = {'status': 'failed', 'error': p2.truncate(message or str(error), 160)}
        self.details['material_fixture'] = info
        return False, info['error']

    def _templates_for_code(self, code):
        """只读：该 C 编号下当前账号可见的本地档案（建档前后对比的唯一事实来源）。"""
        state = self._api('/web/dataset/call_kw', {
            'model': 'product.template', 'method': 'search_read',
            'args': [[['lab_lcsc_code', '=', code]], ['id', 'lab_sn', 'name']],
            'kwargs': {'order': 'id'}})
        rows = ((state.get('payload') or {}).get('result') or [])
        return rows if isinstance(rows, list) else []

    def _quant_rows_for_template(self, template_id):
        """只读：新档案在内部/在途库位的库存行数；建档不得复制任何库存（应为 0）。"""
        if not template_id:
            return None
        state = self._api('/web/dataset/call_kw', {
            'model': 'stock.quant', 'method': 'search_read',
            'args': [[['product_id.product_tmpl_id', '=', template_id],
                      ('location_id.usage', 'in', ['internal', 'transit'])], ['id']],
            'kwargs': {'limit': 20}})
        payload = state.get('payload') or {}
        rows = payload.get('result')
        if not isinstance(rows, list):
            self.note('quant_rows API error: http=%s keys=%s'
                      % (state.get('status'), ','.join(sorted(payload.keys()))))
            return None
        return len(rows)

    def _last_location_id(self):
        data = self._api_post('/lab/api/inventory/locations', {})
        rows = data.get('locations') or []
        names = [r.get('name') for r in rows if str(r.get('name') or '').startswith('P3-DOM-LOC-')]
        if not names:
            return None
        for row in rows:
            if row.get('name') == sorted(names)[-1]:
                return row.get('id')
        return None

    def _member_role(self, login):
        data = self._api_post('/lab/api/inventory/members', {'query': login, 'limit': 20})
        for member in data.get('members') or []:
            if member.get('login') == login:
                return bool((member.get('roles') or {}).get('lab_user'))
        return None

    def _role_checkbox_index(self, login):
        """在成员表里定位属于该登录名的 lab_user 勾选框序号（避免点错行）。"""
        expression = """(() => {
          const boxes = Array.from(document.querySelectorAll(%s));
          for (var i = 0; i < boxes.length; i++) {
            const tr = boxes[i].closest('tr');
            if (tr && (tr.innerText || '').indexOf(%s) >= 0) { return i; }
          }
          return -1;
        })()""" % (js_str(self.selectors['role_checkbox']), js_str(login))
        try:
            return int(self.cdp.evaluate(expression))
        except Exception:
            return -1

    def _select_option_value(self, selector, value, timeout=20):
        """等页面异步渲染出目标 <option> 再选；不盲等固定 sleep。

        超时抛 FlowAbort 并带上**当前真实选项值**，便于区分"页面没加载库位"与"值语义不对"。
        """
        wanted = str(value)
        state = self.cdp.evaluate("""(() => {
          const sel = document.querySelector(%s);
          if (!sel) return {found: false, values: []};
          return {found: true,
                  values: Array.from(sel.options || []).map(function (o) { return String(o.value); })};
        })()""" % js_str(selector))
        values = (state or {}).get('values') if isinstance(state, dict) else []
        if len(values or []) <= 1 and self.has('[data-lc-action="mappings-reload"]'):
            # 首次进入页面时库位列表可能还在异步加载/加载失败：用页面自己的「刷新」再拉一次
            self.cdp.click('[data-lc-action="mappings-reload"]', label='mappings-reload')
        deadline = time.time() + timeout
        while time.time() < deadline:
            picked = self.cdp.evaluate("""(() => {
              const sel = document.querySelector(%s);
              if (!sel) return '';
              const option = Array.from(sel.options || []).find(function (o) {
                return String(o.value) === %s;
              });
              if (!option) return '';
              sel.value = option.value;
              sel.dispatchEvent(new Event('change', {bubbles: true}));
              return String(option.value);
            })()""" % (js_str(selector), js_str(wanted)))
            if picked:
                return picked
            time.sleep(0.25)
        current = self.cdp.evaluate("""(() => {
          const sel = document.querySelector(%s);
          if (!sel) return [];
          return Array.from(sel.options || []).map(function (o) { return String(o.value); });
        })()""" % js_str(selector)) or []
        raise p2.FlowAbort('下拉里没有目标选项 value=%s（当前选项=%s）'
                           % (wanted, p2.truncate(','.join(current), 120)))

    # -- 主页网络判定：放行有意触发的 4xx（过滤在 recorder 层完成） --------
    def status_failures(self):
        return self.recorder.status_failures()

    def ignore_expected_4xx_console(self):
        """角色门槛页的 403 会被 Chrome 记成 Log network error，只精确放行白名单 URL。

        三重收窄：kind=log-error + 文本含 403/FORBIDDEN + URL 命中 EXPECTED_4XX 的精确 path。
        其它 console/log 错误仍然失败（不放松 P2 的零容忍口径）。
        """
        ignored = 0
        paths = expected_4xx_paths()
        for entry in self.sink.entries:
            if entry.get('kind') != 'log-error':
                continue
            text = entry.get('text') or ''
            if '403' not in text and 'FORBIDDEN' not in text.upper():
                continue
            for path in paths:
                if path in text:
                    entry['kind'] = 'log-ignored-expected-403'
                    ignored += 1
                    break
        if ignored:
            self.details['expected_403_console'] = ignored
        return ignored

    def flow_anon(self):
        """清 Cookie 后访问业务页：必须落到本站登录页。"""
        try:
            self.cdp.call('Network.clearBrowserCookies')
            self.prepare_navigation('p3 anon receipts')
            self.cdp.call('Page.navigate', url=self.cfg.url + PAGE_PATHS['receipts'])
            deadline = time.time() + 20
            path = ''
            while time.time() < deadline:
                try:
                    path = self.cdp.evaluate('location.pathname') or ''
                except Exception:
                    path = ''
                if path and path != PAGE_PATHS['receipts']:
                    break
                time.sleep(0.2)
            state = self.read_page_state()
            ok = '/login' in path or bool(state.get('login_form'))
            self.step('p3-anon-redirect', 'pass' if ok else 'fail',
                      'path=%s login_form=%s' % (path, state.get('login_form')))
        except Exception as exc:
            self.step('p3-anon-redirect', 'fail',
                      '匿名跳转断言失败: ' + p2.truncate(exc, 140))

    # -- 主流程 ----------------------------------------------------------
    def run(self):
        try:
            self.check_env()
            self.launch_chrome()
            self.connect_cdp()
            self.install_rpc_trace()   # 只在页面内存记录 RPC 元数据（无凭据/无全文）
            self.flow_login()          # 复用 P2：登录 + /lab 已认证
            self.flow_pages()
            self.flow_receipts()
            self.flow_role()
            self.flow_anon()
            self.flow_manager_suite()
        except p2.FlowAbort as exc:
            self.abort_reason = p2.redact(p2.truncate(exc, 240),
                                          [('password', self.cfg.password)])
        except Exception as exc:
            self.abort_reason = 'unexpected: ' + p2.redact(
                p2.truncate('%s: %s' % (type(exc).__name__, exc), 240),
                [('password', self.cfg.password)])
            self.note('traceback: ' + p2.truncate(traceback.format_exc(limit=3), 500))
        finally:
            try:
                self.ignore_expected_4xx_console()
            except Exception as exc:
                self.note('ignore_expected_4xx_console failed: ' + p2.truncate(exc, 120))
            try:
                self.verify_events()
            except Exception as exc:
                self.note('verify_events failed: ' + p2.truncate(exc, 160))
            try:
                self.cleanup()
            except Exception as exc:
                self.note('cleanup failed: ' + p2.truncate(exc, 160))
        return 0

    # -- 结果 ------------------------------------------------------------
    def ordered_steps(self):
        executed = {item['name'] for item in self.steps.values()}
        out = [self.steps[name] for name in P3_STEPS if name in executed]
        for name in sorted(self.steps):
            if name not in P3_STEPS:
                out.append(self.steps[name])
        return out

    def build_result(self):
        self.recorder.finish()
        steps = self.ordered_steps()
        counts = {'pass': 0, 'fail': 0, 'blocked': 0}
        for item in steps:
            counts[item['status']] = counts.get(item['status'], 0) + 1
        executed = {item['name'] for item in steps}
        unreached = [name for name in P3_STEPS if name not in executed]
        for name in unreached:
            steps.append({'name': name, 'status': 'blocked', 'ok': False,
                          'detail': '未执行（前置步骤失败）'})
            counts['blocked'] += 1
        ok = (counts['fail'] == 0 and counts['blocked'] == 0
              and not self.abort_reason)
        if ok:
            exit_code = 0
        elif self.hard_env_failure:
            exit_code = 2
        elif counts['fail'] == 0:
            exit_code = 3
        else:
            exit_code = 1
        return {
            'schema': SCHEMA,
            'ok': ok,
            'exit_code': exit_code,
            'abort_reason': self.abort_reason,
            'counts': {
                'steps': len(steps),
                'pass': counts['pass'],
                'fail': counts['fail'],
                'blocked': counts['blocked'],
                'planned_total': len(P3_STEPS),
                'unreached': len(unreached),
            },
            'unreached_steps': unreached,
            'steps': steps,
            'p3_pages': self.details.get('p3_pages', {}),
            'expected_4xx': self.expected_4xx,
            'expected_403_console': self.details.get('expected_403_console', 0),
            'material_fixture': self.details.get('material_fixture'),
            'receipt_fixture': self.details.get('receipt_fixture'),
            'receipt_resolve': self.details.get('receipt_resolve'),
            'quant_diag': self.details.get('quant_diag'),
            'template_diag': self.details.get('template_diag'),
            'item_key': 'set' if self.cfg.item_key else 'missing',
            'trace_code_seen': bool(self.trace_code),
            'console': {
                'summary': self.sink.summary(),
                'errors': self.sink.error_entries(),
                'ignored': self.sink.ignored_entries(),
            },
            'network': {
                'counts': self.recorder.counts(),
                'failures': self.recorder.failures,
                'status_failures': self.recorder.status_failures(),
                'ignored': self.recorder.ignored,
            },
            'screenshots': self.screenshots,
            'notes': self.notes,
        }


# ---------------------------------------------------------------------------
# selftest（纯逻辑，不需要 Chrome/Odoo）
# ---------------------------------------------------------------------------
def selftest():
    checks = []

    def expect(name, condition):
        checks.append((name, bool(condition)))

    pages, unknown = parse_pages('receipts,issues,nope')
    expect('pages-known', pages == ['receipts', 'issues'])
    expect('pages-unknown', unknown == ['nope'])
    expect('pages-default', parse_pages('')[0] == list(DEFAULT_PAGES))
    expect('pages-empty-fallback', parse_pages(',,')[0] == list(DEFAULT_PAGES))
    expect('classify-pass', classify_page_state(
        {'marker': True, 'page_js': True, 'page_id': 'receipts',
         'path': '/team/lab/receipts'}, 'receipts')[0] == 'pass')
    expect('classify-no-js', classify_page_state(
        {'marker': True, 'page_js': False, 'page_id': 'receipts'})[0] == 'blocked')
    expect('classify-placeholder', classify_page_state(
        {'marker': True, 'page_js': True, 'placeholder': True})[0] == 'blocked')
    expect('classify-login', classify_page_state({'login_form': True})[0] == 'blocked')
    expect('classify-error', classify_page_state({'error_page': True})[0] == 'fail')
    expect('classify-wrong-page', classify_page_state(
        {'marker': True, 'page_js': True, 'page_id': 'bags'}, 'receipts')[0] == 'fail')
    expect('classify-not-dict', classify_page_state(None)[0] == 'fail')
    expect('item-key-code', item_key_code('lcsc:C123') == 'C123')
    expect('item-key-bad', item_key_code('junk') == '')
    expect('selector-create',
           selector_for('receipt_create') ==
           '[data-lc-form="pending-create"] button[type="submit"]')
    expect('selector-role-real', 'data-lc-inv-role' in DEFAULT_SELECTORS['role_checkbox'])
    expect('selector-return-rows',
           DEFAULT_SELECTORS['issues_return_open'].startswith('[data-lc-rows="issues"]'))
    expect('selector-material-search',
           'material-search' in DEFAULT_SELECTORS['material_query']
           and 'material-search' in DEFAULT_SELECTORS['material_search'])
    expect('pydeps-dedup', len(pydeps_candidates('/r')) == len(set(pydeps_candidates('/r'))))
    expect('pydeps-has-round-dir',
           any(path.endswith(os.path.join('p3-web-20261028', 'pydeps'))
               for path in pydeps_candidates('/r')))
    probe = ensure_websockets(['/nonexistent-pydeps-for-selftest'])
    expect('pydeps-probe-shape',
           set(['ok', 'added', 'candidates']).issubset(set(probe)) and probe['ok'] is bool(PYDEPS['ok']))
    expect('status-for-fixture',
           P3Flow._status_for(None, p2.FlowAbort('确认表单没有可选库位')) == 'blocked')
    expect('status-for-timeout',
           P3Flow._status_for(None, p2.FlowAbort('等待超时: pending row')) == 'fail')
    expect('status-for-plain',
           P3Flow._status_for(None, ValueError('boom')) == 'fail')
    expect('4xx-exact-match', expected_4xx_match({
        'path': '/team/lab/settings', 'status': 403,
        'method': 'GET', 'type': 'Document'}))
    expect('4xx-reject-wrong-method', not expected_4xx_match({
        'path': '/team/lab/settings', 'status': 403,
        'method': 'POST', 'type': 'Document'}))
    expect('4xx-reject-jsonrpc-path', not expected_4xx_match({
        'path': '/lab/api/inventory/mapping_set', 'status': 403,
        'method': 'POST', 'type': 'XHR'}))
    expect('4xx-paths', expected_4xx_paths() == sorted(
        ['/team/lab/settings', '/team/lab/location-mappings', '/team/lab/materials']))
    expect('steps-ordered', P3_STEPS.index('login-page') < P3_STEPS.index('p3-pages-nav'))
    expect('steps-local-before-lcsc',
           P3_STEPS.index('p3-receipt-resolve-local-key')
           < P3_STEPS.index('p3-receipt-item-resolve'))
    expect('steps-has-cleanup', 'profile-cleanup' in P3_STEPS)
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        sys.stdout.write('%s %s\n' % ('ok  ' if ok else 'FAIL', name))
    sys.stdout.write('SELFTEST %d/%d\n' % (len(checks) - len(failed), len(checks)))
    return 0 if not failed else 1


def fallback_result(message):
    names = list(P3_STEPS)
    return {
        'schema': SCHEMA,
        'ok': False,
        'exit_code': 2,
        'abort_reason': p2.truncate(message, 240),
        'counts': {'steps': len(names), 'pass': 0, 'fail': 0,
                   'blocked': len(names), 'planned_total': len(names),
                   'unreached': len(names)},
        'unreached_steps': names,
        'steps': [{'name': name, 'status': 'blocked', 'ok': False,
                   'detail': 'environment unavailable'} for name in names],
        'p3_pages': {},
        'item_key': 'unknown',
        'trace_code_seen': False,
        'screenshots': [],
        'notes': [p2.truncate(message, 240)],
    }


def write_result(out_dir, payload):
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'browser-p3.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path
    except Exception as exc:
        sys.stderr.write('browser-p3.json write failed: %s\n'
                         % p2.truncate(exc, 140))
        return ''


def main(argv):
    if '--selftest' in argv:
        return selftest()
    out_dir = os.environ.get('OUT_DIR') or os.getcwd()
    try:
        cfg = P3Config()
        out_dir = cfg.out_dir
        flow = P3Flow(cfg)
        flow.run()
        payload = flow.build_result()
    except KeyError as exc:
        payload = fallback_result('missing env: ' + str(exc))
    except Exception as exc:
        payload = fallback_result('%s: %s' % (type(exc).__name__, exc))
    write_result(out_dir, payload)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()
    return int(payload.get('exit_code') or 0)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
