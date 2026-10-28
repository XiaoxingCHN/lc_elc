#!/usr/bin/env bash
# ============================================================================
# P3 写业务独立验收运行器（真实隔离 Odoo；不连生产/NAS；不落盘凭据）
#
# 设计（与 P2 一致，不重造）：
#   * 证据助手（results.jsonl / 脱敏）**复用** bore/scripts/run-p2-isolated.sh 的
#     `--print-evidence-helper`，本脚本只负责断言与 summary，避免第二套证据格式。
#   * 不启动 Odoo/PG：实例由 Lead 用既有隔离方式启动（见 local/build/p3-web-20261028/run-all.sh
#     或 lab_workflow/tools/run_isolation_tests.sh），本脚本只打真实 HTTP/JSON-RPC。
#   * 所有账号为**合成账号**；口令只从环境变量读取，经 stdin 传给助手，不进 argv/日志/证据。
#   * 端点缺失（P3 后端路由尚未发布）记 blocked，**不算通过**，退出码 3。
#
# 必填环境变量：
#   ODOO_URL        实例地址，必须 loopback（http://127.0.0.1:<port>）
#   DB_NAME         隔离测试库名（不得指向生产库）
#   P3_USERS        四个合成登录名，冒号分隔：norole:catalog:operator:manager
#   P3_PASS         合成口令（同一口令，仅 env）
#   P3_ADMIN        管理员登录名（建夹具/读数用）
#   P3_ADMIN_PASS   管理员口令（仅 env）
# 可选：
#   PYTHON          默认 python3
#   P3_BASE         证据根目录（默认 <repo>/local/build/p3-web-20261028），必须绝对路径
#   P3_WORK         本轮目录（默认 mktemp 在 P3_BASE/runs；已存在 results.jsonl 则拒绝=4）
#   P3_RUN_ID       本轮标识（默认 p3-<UTC 时间>-<work basename>）
#   P3_SEED         1=自动建合成夹具（默认 1；0=用既有夹具，相关断言 blocked）
#   P3_GATE_URL     公网入口地址（提供时追加 Origin/网关断言，缺省则 blocked）
#   P3_ITEM_MPN     夹具器件 MPN（默认 P3-TEST-MPN-0001）
#   P3_TIMEOUT      HTTP 超时秒数（默认 30）
#   P3_VERIFY_SCRIPT  **仅测试用**：用外部脚本替换内置断言矩阵（须输出同一 JSONL 协议）
#
# 用法：
#   verify-p3-write.sh                    正常跑一轮
#   verify-p3-write.sh --check-evidence <workdir>    从 results.jsonl 重算并核对 summary
#   verify-p3-write.sh --print-verify-helper         输出内置断言助手源码（供单测/审阅）
#   verify-p3-write.sh --selftest                    只跑助手纯逻辑自测（不需要 Odoo）
#
# 退出码：0 全部 pass 且无 blocked；1 有 fail；3 blocked（输入/环境/端点未发布）；4 证据错误
# ============================================================================
set -uo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BORE_DIR/../../.." && pwd)"
PYTHON="${PYTHON:-python3}"
P2_RUNNER="$BORE_DIR/scripts/run-p2-isolated.sh"
P3_BASE="${P3_BASE:-$REPO_ROOT/local/build/p3-web-20261028}"
P3_ITEM_MPN="${P3_ITEM_MPN:-P3-TEST-MPN-0001}"
P3_TIMEOUT="${P3_TIMEOUT:-30}"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy 2>/dev/null || true
export NO_PROXY="*" no_proxy="*"

# ---------------------------------------------------------------------------
# 内置断言助手（单一定义处；--print-verify-helper 输出同一份源码）
# ---------------------------------------------------------------------------
p3_helper_source() {
  cat <<'P3VERIFY'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 断言助手（仅标准库；只对隔离实例发请求；不保存 Cookie/口令）。

协议：stdout 每行一个 JSON 对象
  {"id":"p3-...","result":"pass|fail|blocked","detail":"..."}   一条断言
  {"fatal":3,"message":"..."}                                    致命输入错误（随后退出 3）
退出码：0 全部 pass 且无 blocked；1 有 fail；3 有 blocked 或输入错误；4 内部错误
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

CODES = ("VALIDATION_ERROR", "UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND", "CONFLICT",
         "PRECONDITION_FAILED", "DUPLICATE_REQUEST", "INTERNAL_ERROR",
         "AMBIGUOUS_MATERIAL")

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")

#: 实验室库存只看**内部库位**的真实 quant。供应商/客户/盘点等虚拟库位上的
#: quant 是一次移动的镜像（收货时供应商侧 -N、客户侧 +N），把全库 quant 相加
#: 恒等于 0；用它做断言会让 confirm/issue 的库存变化永远不可见（HTTP R3 根因）。
INTERNAL_USAGES = ('internal', 'transit')


def internal_stock_domain(template_id):
    """某物料档案「内部库存」的 stock.quant 域（与后端负库存校验同一口径）。"""
    return [('product_id.product_tmpl_id', '=', template_id),
            ('location_id.usage', 'in', list(INTERNAL_USAGES))]


# ---------------------------------------------------------------------------
# 纯逻辑（selftest 覆盖，不触网）
# ---------------------------------------------------------------------------
def is_loopback(url):
    match = re.match(r'^(https?)://([^/?#]+)(?:[/?#]|$)', (url or '').strip())
    if not match:
        return False
    authority = match.group(2)
    if authority.startswith('['):
        host = authority.split(']')[0] + ']'
    else:
        host = authority.split(':')[0]
    return host.lower() in LOOPBACK_HOSTS


def parse_users(raw):
    parts = [item.strip() for item in (raw or '').split(':')]
    if len(parts) != 4 or any(not item for item in parts):
        return None
    return {"norole": parts[0], "catalog": parts[1],
            "operator": parts[2], "manager": parts[3]}


def redact_detail(text, limit=300):
    text = re.sub(r'(session_id|csrf_token|password)=[^&\s;]+', r'\1=<redacted>', str(text))
    text = re.sub(r'[A-Za-z0-9]{32,}', '<id>', text)
    return text[:limit]


def envelope(payload):
    """把 JSON-RPC 响应归一成 (ok, code, fields, data)。"""
    if not isinstance(payload, dict):
        return (None, None, {}, None)
    result = payload.get('result')
    if isinstance(result, dict) and 'ok' in result:
        error = result.get('error') or {}
        if not isinstance(error, dict):
            error = {}
        return (bool(result.get('ok')), error.get('code'), error.get('fields') or {},
                result.get('data') or {})
    error = payload.get('error')
    if isinstance(error, dict):
        # Odoo 原生 JSON-RPC 错误（例如未登录、路由不存在时不会走到这里）
        return (False, 'TRANSPORT_%s' % error.get('code'), {}, None)
    return (None, None, {}, None)


def is_ok(status, payload):
    ok, code, fields, data = envelope(payload)
    return status == 200 and ok is True


def error_code(status, payload):
    ok, code, fields, data = envelope(payload)
    if status == 404:
        return 'ROUTE_NOT_PUBLISHED'
    if status >= 500:
        return 'HTTP_%d' % status
    return code


def has_error_id(payload):
    ok, code, fields, data = envelope(payload)
    return isinstance(fields, dict) and 'error_id' in fields


# ---------------------------------------------------------------------------
# HTTP 客户端（每个逻辑动作一个独立会话，避免 Cookie 串场）
# ---------------------------------------------------------------------------
class Api(object):
    def __init__(self, base, db, timeout=30):
        self.base = (base or '').rstrip('/')
        self.db = db
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.uid = None

    def raw(self, path, body=None, headers=None, method=None):
        request = urllib.request.Request(
            self.base + path, data=body, method=method or ('POST' if body else 'GET'))
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read()
        except Exception as exc:  # 连接失败/超时
            return 0, {}, ('%s: %s' % (type(exc).__name__, exc)).encode('utf-8')

    def rpc(self, path, params):
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": params or {}}).encode('utf-8')
        status, headers, raw = self.raw(
            path, body, {"Content-Type": "application/json",
                         "Accept": "application/json"})
        try:
            payload = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            payload = {"_raw_len": len(raw)}
        return status, payload

    def login(self, login, password):
        status, payload = self.rpc('/web/session/authenticate',
                                   {"db": self.db, "login": login, "password": password})
        info = payload.get('result') if isinstance(payload, dict) else None
        if isinstance(info, dict) and info.get('uid'):
            self.uid = info.get('uid')
            return True
        return False

    def kw(self, model, method, args=None, kwargs=None):
        status, payload = self.rpc('/web/dataset/call_kw', {
            "model": model, "method": method,
            "args": args or [], "kwargs": kwargs or {}})
        if isinstance(payload, dict) and 'error' in payload:
            return status, None, payload.get('error')
        if isinstance(payload, dict):
            return status, payload.get('result'), None
        return status, None, 'bad payload'

    def api(self, path, params):
        return self.rpc(path, params)


def session_api(url, db, login, password, timeout=30):
    client = Api(url, db, timeout)
    ok = client.login(login, password)
    return client, ok


# ---------------------------------------------------------------------------
# 断言收集
# ---------------------------------------------------------------------------
class Collector(object):
    def __init__(self):
        self.counts = {"pass": 0, "fail": 0, "blocked": 0}
        self.seen = set()

    def emit(self, ident, result, detail=''):
        self.counts[result] = self.counts.get(result, 0) + 1
        self.seen.add(ident)
        sys.stdout.write(json.dumps(
            {"id": ident, "result": result,
             "detail": redact_detail(detail)}, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def ok(self, ident, detail=''):
        self.emit(ident, 'pass', detail)

    def bad(self, ident, detail=''):
        self.emit(ident, 'fail', detail)

    def block(self, ident, detail=''):
        self.emit(ident, 'blocked', detail)

    def check(self, ident, condition, detail='', fail_detail=''):
        if condition:
            self.ok(ident, detail)
        else:
            self.bad(ident, fail_detail or detail)

    def block_rest(self, idents, detail):
        """把尚未登记的步骤统一记 blocked（前置未就绪时不得静默消失）。"""
        for ident in idents:
            if ident not in self.seen:
                self.block(ident, detail)


#: 本矩阵的全部断言 id（顺序即报告顺序）；用于"前置未就绪时显式 blocked"
ALL_STEPS = (
    'p3-env-url', 'p3-seed-fixtures',
    'p3-anon-rejected',
    'p3-auth-norole', 'p3-auth-catalog', 'p3-auth-operator',
    'p3-auth-manager', 'p3-auth-operator_b',
    'p3-bootstrap-operator', 'p3-bootstrap-manager',
    'p3-norole-no-lab-forbidden', 'p3-catalog-no-lab-forbidden',
    'p3-api-pending-create', 'p3-api-pending-confirm', 'p3-api-receipt',
    'p3-api-issue', 'p3-api-return', 'p3-api-labels-plan',
    'p3-pending-create', 'p3-two-stage-no-stock-before-confirm',
    'p3-pending-resolve', 'p3-two-stage-confirm-stock',
    'p3-confirm-creates-bag', 'p3-confirm-replay-idempotent',
    'p3-same-key-different-payload', 'p3-pending-resolve-after-confirm',
    'p3-issue-decrements', 'p3-return-partial', 'p3-return-over-limit',
    'p3-return-cross-user', 'p3-return-by-manager',
    'p3-malformed-location', 'p3-malformed-issue-line', 'p3-malformed-limit',
    'p3-malformed-label-copies', 'p3-location-disable',
    'p3-inactive-location-receipt', 'p3-adopt-atomic-rollback',
    'p3-unknown-outcome-retry-same-key',
    'p3-label-bounds', 'p3-label-location-plan', 'p3-label-preview-safe',
    'p3-label-cross-company', 'p3-label-pdf-csrf', 'p3-label-pdf-download',
    'p3-origin-cross-site',
    'p3-api-bags', 'p3-api-bag', 'p3-api-location-update',
    'p3-api-mapping-list', 'p3-api-mapping-set', 'p3-api-members',
    'p3-api-mapping-operator-forbidden', 'p3-api-member-role-whitelist',
    'p3-readonly-role-receipt-forbidden',
)


# ---------------------------------------------------------------------------
# 夹具（只在隔离库；全部合成）
# ---------------------------------------------------------------------------
GROUP_XMLIDS = (
    ('base', 'group_user'),
    ('lab_catalog', 'group_lab_catalog_user'),
    ('lab_workflow', 'group_lab_user'),
    ('lab_workflow', 'group_lab_operator'),
    ('lab_workflow', 'group_lab_manager'),
)

#: 夹具器件的立创编号（浏览器验收用 P3_ITEM_KEY=lcsc:<这个值>）
P3_LCSC_CODE = 'C9990001'


def group_id(admin, module, name):
    status, result, error = admin.kw(
        'ir.model.data', 'search_read',
        [[('module', '=', module), ('name', '=', name)], ['res_id']],
        {'limit': 1})
    if error or not result:
        return None
    return result[0].get('res_id')


def ensure_user(admin, login, group_xmlids, password, company_id):
    status, ids, error = admin.kw('res.users', 'search', [[('login', '=', login)]])
    if error:
        return None
    if ids:
        return ids[0]
    group_ids = []
    for module, name in group_xmlids:
        value = group_id(admin, module, name)
        if value:
            group_ids.append(value)
    values = {'name': login, 'login': login, 'password': password,
              'email': '%s@example.invalid' % login,
              'group_ids': [(6, 0, group_ids)],
              'company_ids': [(6, 0, [company_id])],
              'company_id': company_id}
    status, result, error = admin.kw(
        'res.users', 'create', [values], {'context': {'no_reset_password': True}})
    if error:
        return None
    return result


def ensure_company(admin, name):
    status, ids, error = admin.kw('res.company', 'search', [[('name', '=', name)]])
    if error:
        return None
    if ids:
        return ids[0]
    status, result, error = admin.kw('res.company', 'create', [{'name': name}])
    return None if error else result


def ensure_category(admin, name):
    status, ids, error = admin.kw('product.category', 'search', [[('name', '=', name)]])
    if error:
        return None
    if ids:
        return ids[0]
    status, result, error = admin.kw('product.category', 'create', [{'name': name}])
    return None if error else result


def ensure_location(admin, name, company_id, parent_id=None):
    status, ids, error = admin.kw(
        'stock.location', 'search',
        [[('name', '=', name), ('company_id', '=', company_id)]])
    if error:
        return None
    if ids:
        return ids[0]
    values = {'name': name, 'usage': 'internal', 'company_id': company_id}
    if parent_id:
        values['location_id'] = parent_id
    status, result, error = admin.kw('stock.location', 'create', [values])
    return None if error else result


def ensure_item(admin, name, mpn, company_id, lcsc_code=None):
    """夹具器件：带 lab_lcsc_code，使浏览器验收可用 P3_ITEM_KEY=lcsc:<code>。"""
    status, ids, error = admin.kw(
        'product.template', 'search', [[('name', '=', name)]])
    if error:
        return None
    if ids:
        template_id = ids[0]
        # 既有夹具可能缺立创编号：补齐（只改夹具字段，不碰库存）
        if lcsc_code:
            status, rows, read_error = admin.kw(
                'product.template', 'read', [[template_id], ['lab_lcsc_code']])
            current = None
            if not read_error and rows:
                current = rows[0].get('lab_lcsc_code')
            if not current:
                admin.kw('product.template', 'write',
                         [[template_id], {'lab_lcsc_code': lcsc_code}])
        return template_id
    values = {'name': name, 'type': 'consu', 'is_storable': True,
              'tracking': 'lot', 'lab_mpn': mpn, 'company_id': company_id}
    if lcsc_code:
        values['lab_lcsc_code'] = lcsc_code
    status, result, error = admin.kw('product.template', 'create', [values])
    if error:
        # 可选字段兜底：保留 lab_lcsc_code（浏览器验收要用），其余逐个去掉重试
        for key in ('is_storable', 'tracking', 'lab_mpn'):
            values.pop(key, None)
        status, result, error = admin.kw('product.template', 'create', [values])
    return None if error else result


def stock_state(admin, template_id):
    """内部库存合计（stock.quant 是唯一权威，不读 lab.bag 缓存）。"""
    status, rows, error = admin.kw(
        'stock.quant', 'search_read',
        [internal_stock_domain(template_id), ['quantity', 'location_id']])
    if error or not isinstance(rows, list):
        return None
    total = 0.0
    for row in rows:
        try:
            total += float(row.get('quantity') or 0)
        except (TypeError, ValueError):
            pass
    return round(total, 6)


def count_of(admin, model, domain=None):
    status, result, error = admin.kw(model, 'search_count', [domain or []])
    if error:
        return None
    return result


# ---------------------------------------------------------------------------
# 断言矩阵
# ---------------------------------------------------------------------------
class Verify(object):
    def __init__(self, cfg, collector):
        self.cfg = cfg
        self.c = collector
        self.ids = {}
        self.state = {}

    # -- 基础 -----------------------------------------------------------
    def client(self, role, timeout=None):
        login = self.ids['users'].get(role)
        if not login:
            return None
        client = Api(self.cfg['url'], self.cfg['db'],
                     timeout or self.cfg['timeout'])
        if not client.login(login, self.cfg['pass']):
            return None
        return client

    def admin(self):
        client = Api(self.cfg['url'], self.cfg['db'], self.cfg['timeout'])
        if not client.login(self.cfg['admin'], self.cfg['admin_pass']):
            return None
        return client

    # -- 0. 输入/环境 ----------------------------------------------------
    def step_env(self):
        if not is_loopback(self.cfg['url']):
            self.c.block('p3-env-url', 'ODOO_URL 必须是 loopback（隔离实例）')
            return False
        if not self.cfg['db'] or self.cfg['db'].lower().startswith('lchardware'):
            self.c.block('p3-env-db', 'DB_NAME 缺失或疑似生产库名')
            return False
        self.c.ok('p3-env-url', 'loopback=%s db=%s' % (self.cfg['url'], self.cfg['db']))
        return True

    # -- 1. 夹具 ---------------------------------------------------------
    def step_seed(self):
        admin = self.admin()
        if admin is None:
            self.c.block('p3-seed-admin', '管理员登录失败（检查 P3_ADMIN/P3_ADMIN_PASS）')
            return False
        status, companies, error = admin.kw('res.company', 'search', [[('id', '>', 0)]],
                                           {'limit': 1})
        company_id = companies[0] if companies else None
        if not company_id:
            self.c.block('p3-seed-company', '取不到公司 id')
            return False
        users = {}
        for role in ('norole', 'catalog', 'operator', 'manager'):
            login = self.cfg['users'][role]
            groups = [('base', 'group_user')]
            if role == 'catalog':
                groups.append(('lab_catalog', 'group_lab_catalog_user'))
            elif role == 'operator':
                groups += [('lab_catalog', 'group_lab_catalog_user'),
                           ('lab_workflow', 'group_lab_user'),
                           ('lab_workflow', 'group_lab_operator')]
            elif role == 'manager':
                groups += [('lab_catalog', 'group_lab_catalog_user'),
                           ('lab_workflow', 'group_lab_user'),
                           ('lab_workflow', 'group_lab_operator'),
                           ('lab_workflow', 'group_lab_manager')]
            uid = ensure_user(admin, login, groups, self.cfg['pass'], company_id)
            if not uid:
                self.c.block('p3-seed-user-%s' % role, '创建/查找合成账号失败')
                return False
            users[role] = login
        # 第二个操作员：跨账号归还用例（非 manager）
        other = self.cfg['users']['operator'] + '-b'
        other_uid = ensure_user(admin, other,
                                [('base', 'group_user'),
                                 ('lab_catalog', 'group_lab_catalog_user'),
                                 ('lab_workflow', 'group_lab_user'),
                                 ('lab_workflow', 'group_lab_operator')],
                                self.cfg['pass'], company_id)
        if not other_uid:
            self.c.block('p3-seed-user-operator-b', '创建第二操作员失败')
            return False
        users['operator_b'] = other
        self.ids['users'] = users

        parent_status, parents, parent_error = admin.kw(
            'stock.location', 'search',
            [[('usage', '=', 'internal'), ('company_id', '=', company_id)]],
            {'limit': 1})
        parent_id = parents[0] if parents else None
        loc_a = ensure_location(admin, 'P3-A-01', company_id, parent_id)
        loc_b = ensure_location(admin, 'P3-A-02', company_id, parent_id)
        if not loc_a or not loc_b:
            self.c.block('p3-seed-locations', '创建内部库位失败')
            return False
        template_id = ensure_item(admin, 'P3 验收器件', self.cfg['mpn'],
                                  company_id, P3_LCSC_CODE)
        if not template_id:
            self.c.block('p3-seed-item', '创建器件夹具失败')
            return False
        category_id = ensure_category(admin, 'P3 验收类别')
        other_company = ensure_company(admin, 'P3-Other-Company')
        other_loc = ensure_location(admin, 'P3-B-01', other_company, None) \
            if other_company else None
        self.ids.update({'company': company_id, 'locations': [loc_a, loc_b],
                         'template': template_id, 'category': category_id,
                         'other_company': other_company, 'other_location': other_loc})
        self.c.ok('p3-seed-fixtures',
                  'users=5 locations=2 item=%s category=%s other_company=%s item_key=lcsc:%s'
                  % (template_id, category_id, other_company, P3_LCSC_CODE))
        return True

    # -- 2. 认证/权限 ----------------------------------------------------
    def step_auth(self):
        anon = Api(self.cfg['url'], self.cfg['db'], self.cfg['timeout'])
        status, payload = anon.api('/lab/api/inventory/bootstrap', {})
        ok, code, fields, data = envelope(payload)
        self.c.check('p3-anon-rejected', status == 200 and ok is False,
                     'anon ok=False code=%s' % code,
                     'anon 未被拒绝 status=%s code=%s' % (status, code))
        for role in ('norole', 'catalog', 'operator', 'manager', 'operator_b'):
            client = self.client(role)
            if client is None:
                self.c.bad('p3-auth-%s' % role, '登录失败')
                continue
            self.c.ok('p3-auth-%s' % role, 'uid=%s' % client.uid)
        # bootstrap 权限位
        client = self.client('operator')
        if client is not None:
            status, payload = client.api('/lab/api/inventory/bootstrap', {})
            ok, code, fields, data = envelope(payload)
            perms = (data or {}).get('permissions') or {}
            self.c.check('p3-bootstrap-operator',
                         ok and perms.get('can_receipt') and perms.get('can_issue')
                         and not perms.get('is_manager'),
                         'can_receipt=%s can_issue=%s is_manager=%s'
                         % (perms.get('can_receipt'), perms.get('can_issue'),
                            perms.get('is_manager')),
                         'bootstrap 权限位不符 code=%s' % code)
        manager = self.client('manager')
        if manager is not None:
            status, payload = manager.api('/lab/api/inventory/bootstrap', {})
            ok, code, fields, data = envelope(payload)
            perms = (data or {}).get('permissions') or {}
            self.c.check('p3-bootstrap-manager', ok and perms.get('is_manager') is True,
                         'is_manager=%s' % perms.get('is_manager'),
                         '管理员权限位不符 code=%s' % code)
        for role in ('norole', 'catalog'):
            client = self.client(role)
            if client is None:
                continue
            status, payload = client.api('/lab/api/inventory/bootstrap', {})
            ok, code, fields, data = envelope(payload)
            self.c.check('p3-%s-no-lab-forbidden' % role,
                         ok is False and code == 'FORBIDDEN',
                         'code=%s' % code, '期望 FORBIDDEN，实际 %s' % code)
        return True

    # -- 2b. 端点发布探针（未发布 → blocked，不是 fail） ------------------
    def step_probe(self):
        operator = self.client('operator')
        if operator is None:
            self.c.block('p3-api-pending-create', '缺少操作员会话')
            return False
        core = (
            ('p3-api-pending-create', '/lab/api/inventory/pending/create'),
            ('p3-api-pending-confirm', '/lab/api/inventory/pending/confirm'),
            ('p3-api-receipt', '/lab/api/inventory/receipt'),
            ('p3-api-issue', '/lab/api/inventory/issue'),
            ('p3-api-return', '/lab/api/inventory/return'),
            ('p3-api-labels-plan', '/lab/api/labels/plan'),
        )
        missing = []
        for ident, path in core:
            status, payload = operator.api(path, {})
            if status == 404:
                self.c.block(ident, '端点未发布 %s' % path)
                missing.append(path)
            elif status == 0:
                self.c.block(ident, '连接失败 %s' % path)
                missing.append(path)
            else:
                self.c.ok(ident, 'published status=%s' % status)
        return not missing

    # -- 3. 两阶段入库 ---------------------------------------------------
    def step_two_stage(self):
        admin = self.admin()
        operator = self.client('operator')
        if admin is None or operator is None:
            self.c.block('p3-two-stage', '缺少管理员或操作员会话')
            return False
        template = self.ids['template']
        location = self.ids['locations'][0]
        before = stock_state(admin, template)
        if before is None:
            self.c.block('p3-two-stage-state', '读库存失败')
            return False
        key_create = 'p3-create-0001'
        # pending/create 的器件来源是 item_key（或 material{name}）；
        # 只传 product_template_id 会落到"新建器件必须填写名称"→VALIDATION_ERROR。
        item_key = 'lcsc:%s' % P3_LCSC_CODE
        status, payload = operator.api('/lab/api/inventory/pending/create', {
            'request_key': key_create, 'item_key': item_key,
            'product_template_id': template,
            'quantity': 5, 'count': 1, 'note': 'p3 validation'})
        ok, code, fields, data = envelope(payload)
        if not ok:
            self.c.bad('p3-pending-create',
                       'code=%s fields=%s item_key=%s'
                       % (code, json.dumps(fields, ensure_ascii=False), item_key))
            return False
        records = (data or {}).get('records') or []
        if not records:
            self.c.bad('p3-pending-create', '未返回 records')
            return False
        record = records[0]
        pending_id = record.get('id') or record.get('pending_id')
        trace_code = record.get('trace_code') or ''
        self.c.ok('p3-pending-create', 'records=%d pending_id=%s trace=%s'
                  % (len(records), pending_id, 'yes' if trace_code else 'no'))

        # 确认前不得有库存变化（两阶段语义）
        mid = stock_state(admin, template)
        self.c.check('p3-two-stage-no-stock-before-confirm', mid == before,
                     'quant=%s（未变）' % mid,
                     '确认前库存变化 %s -> %s' % (before, mid))

        # 扫码解析：真实扫码枪给的是袋负载（LABB:<code>），没有负载时退回裸追溯码。
        # 此刻还没有任何内部库存袋，推荐列表必须为空——推荐只能来自已有库存。
        scan_raw = record.get('payload') or trace_code
        status, payload = operator.api('/lab/api/inventory/pending/resolve',
                                       {'raw': scan_raw})
        ok, code, fields, data = envelope(payload)
        resolved = (data or {}).get('record') or {}
        recs = (data or {}).get('recommendations')
        recs = recs if isinstance(recs, list) else []
        self.c.check(
            'p3-pending-resolve',
            ok and resolved.get('id') == pending_id
            and resolved.get('trace_code') == trace_code
            and resolved.get('state') == 'pending' and not recs,
            'record=%s state=%s recommendations=%d'
            % (resolved.get('id'), resolved.get('state'), len(recs)),
            'resolve 未按待入库袋返回 record/空推荐 code=%s record=%s state=%s recs=%d'
            % (code, resolved.get('id'), resolved.get('state'), len(recs)))

        key_confirm = 'p3-confirm-0001'
        confirm_params = {'request_key': key_confirm, 'pending_id': pending_id,
                          'quantity': 5, 'location_id': location}
        status, payload = operator.api('/lab/api/inventory/pending/confirm',
                                       confirm_params)
        ok, code, fields, data = envelope(payload)
        after = stock_state(admin, template)
        self.c.check('p3-two-stage-confirm-stock',
                     ok and after == round(before + 5, 6),
                     'quant %s -> %s' % (before, after),
                     '确认失败 code=%s quant %s -> %s' % (code, before, after))
        bag = (data or {}).get('bag') or {}
        bag_id = bag.get('id')
        self.c.check('p3-confirm-creates-bag', bool(bag_id), 'bag_id=%s' % bag_id,
                     '确认未返回 bag id')

        # 同 key 同 payload 重放：幂等
        status, payload = operator.api('/lab/api/inventory/pending/confirm',
                                       confirm_params)
        ok, code, fields, data = envelope(payload)
        replayed = bool((data or {}).get('replayed'))
        after2 = stock_state(admin, template)
        self.c.check('p3-confirm-replay-idempotent',
                     ok and replayed and after2 == after,
                     'replayed=%s quant=%s' % (replayed, after2),
                     '重放不幂等 ok=%s replayed=%s quant %s -> %s'
                     % (ok, replayed, after, after2))

        # 同 key 不同 payload：CONFLICT
        changed = dict(confirm_params)
        changed['quantity'] = 6
        status, payload = operator.api('/lab/api/inventory/pending/confirm', changed)
        ok, code, fields, data = envelope(payload)
        self.c.check('p3-same-key-different-payload',
                     ok is False and code == 'CONFLICT',
                     'code=%s' % code, '期望 CONFLICT，实际 %s' % code)

        # 入库完成后用同一个追溯码再扫一次：刚入库的库位必须作为推荐出现
        # （推荐顺序：相同器件 → 类别映射 → 同类器件；此处只有本袋，故是「相同器件」）
        status, payload = operator.api('/lab/api/inventory/pending/resolve',
                                       {'raw': scan_raw})
        ok, code, fields, data = envelope(payload)
        resolved = (data or {}).get('record') or {}
        recs = (data or {}).get('recommendations')
        recs = recs if isinstance(recs, list) else []
        first = recs[0] if recs else {}
        self.c.check(
            'p3-pending-resolve-after-confirm',
            ok and resolved.get('state') == 'done'
            and bool(recs) and first.get('id') == location
            and first.get('reason') in ('相同器件', '类别映射', '同类器件'),
            'state=%s recommendations=%d first=%s/%s'
            % (resolved.get('state'), len(recs), first.get('id'),
               first.get('reason')),
            '入库后扫码推荐未包含刚入库库位 code=%s state=%s recs=%d first=%s/%s'
            % (code, resolved.get('state'), len(recs), first.get('id'),
               first.get('reason')))

        self.ids.update({'bag': bag_id, 'template_state': after})
        return True

    # -- 4. 领用/归还 ----------------------------------------------------
    def step_issue_return(self):
        admin = self.admin()
        operator = self.client('operator')
        if admin is None or operator is None:
            self.c.block('p3-issue', '缺少会话')
            return False
        template = self.ids['template']
        bag_id = self.ids.get('bag')
        before = stock_state(admin, template)
        status, payload = operator.api('/lab/api/inventory/issue', {
            'request_key': 'p3-issue-0001', 'borrower_id': operator.uid,
            'project': 'P3 验收', 'lines': [{'bag_id': bag_id, 'quantity': 2}]})
        ok, code, fields, data = envelope(payload)
        lines = (data or {}).get('lines') or []
        issue_line_id = lines[0].get('issue_line_id') if lines else None
        after = stock_state(admin, template)
        self.c.check('p3-issue-decrements',
                     ok and after == round(before - 2, 6) and bool(issue_line_id),
                     'quant %s -> %s issue_line=%s' % (before, after, issue_line_id),
                     '领用失败 code=%s quant %s -> %s' % (code, before, after))
        if not issue_line_id:
            self.c.block('p3-return-partial', '没有 issue_line_id')
            return False

        status, payload = operator.api('/lab/api/inventory/return', {
            'request_key': 'p3-return-0001', 'issue_line_id': issue_line_id,
            'quantity': 1})
        ok, code, fields, data = envelope(payload)
        outstanding = (data or {}).get('outstanding_quantity')
        self.c.check('p3-return-partial',
                     ok and outstanding == 1,
                     'outstanding=%s' % outstanding,
                     '部分归还失败 code=%s outstanding=%s' % (code, outstanding))

        status, payload = operator.api('/lab/api/inventory/return', {
            'request_key': 'p3-return-0002', 'issue_line_id': issue_line_id,
            'quantity': 99})
        ok, code, fields, data = envelope(payload)
        self.c.check('p3-return-over-limit',
                     ok is False and code == 'PRECONDITION_FAILED',
                     'code=%s' % code, '期望 PRECONDITION_FAILED，实际 %s' % code)

        # 跨账号归还：第二操作员归还他人领用行 → FORBIDDEN
        other = self.client('operator_b')
        if other is None:
            self.c.block('p3-return-cross-user', '第二操作员会话不可用')
        else:
            status, payload = other.api('/lab/api/inventory/return', {
                'request_key': 'p3-return-x0001', 'issue_line_id': issue_line_id,
                'quantity': 1})
            ok, code, fields, data = envelope(payload)
            self.c.check('p3-return-cross-user',
                         ok is False and code == 'FORBIDDEN',
                         'code=%s fields=%s' % (code, json.dumps(fields, ensure_ascii=False)),
                         '期望 FORBIDDEN/not_owner，实际 code=%s' % code)

        # 管理员代还：允许，actor/borrower 分离
        manager = self.client('manager')
        if manager is None:
            self.c.block('p3-return-by-manager', '管理员会话不可用')
        else:
            status, payload = manager.api('/lab/api/inventory/return', {
                'request_key': 'p3-return-m0001', 'issue_line_id': issue_line_id,
                'quantity': 1})
            ok, code, fields, data = envelope(payload)
            outstanding = (data or {}).get('outstanding_quantity')
            self.c.check('p3-return-by-manager',
                         ok and outstanding == 0,
                         'outstanding=%s' % outstanding,
                         '管理员代还失败 code=%s outstanding=%s' % (code, outstanding))
        return True

    # -- 5. 失败语义/原子性 ----------------------------------------------
    def step_failures(self):
        admin = self.admin()
        operator = self.client('operator')
        manager = self.client('manager')
        if admin is None or operator is None or manager is None:
            self.c.block('p3-failure-semantics', '缺少会话')
            return False
        template = self.ids['template']
        location = self.ids['locations'][0]

        malformed = (
            ('p3-malformed-location', '/lab/api/inventory/receipt',
             {'request_key': 'p3-bad-0001', 'item_key': 'lcsc:%s' % P3_LCSC_CODE,
              'quantity': 1, 'location_id': 'abc'}),
            ('p3-malformed-issue-line', '/lab/api/inventory/return',
             {'request_key': 'p3-bad-0002', 'issue_line_id': 'abc', 'quantity': 1}),
            ('p3-malformed-limit', '/lab/api/inventory/issues', {'limit': 'abc'}),
            ('p3-malformed-label-copies', '/lab/api/labels/plan',
             {'kind': 'location', 'ids': [location], 'copies': 'x'}),
        )
        for ident, path, params in malformed:
            status, payload = operator.api(path, params)
            ok, code, fields, data = envelope(payload)
            if status == 404:
                self.c.block(ident, '端点未发布 %s' % path)
                continue
            self.c.check(ident,
                         ok is False and code in ('VALIDATION_ERROR', 'NOT_FOUND')
                         and not has_error_id(payload),
                         'code=%s fields=%s' % (code, json.dumps(fields, ensure_ascii=False)),
                         '畸形入参未按业务错误码返回 code=%s error_id=%s'
                         % (code, has_error_id(payload)))

        # 停用库位不能入库（A5）
        status, payload = manager.api('/lab/api/inventory/location_update',
                                      {'location_id': self.ids['locations'][1],
                                       'active': False})
        ok, code, fields, data = envelope(payload)
        if status == 404:
            self.c.block('p3-inactive-location-receipt', 'location_update 未发布')
        else:
            self.c.check('p3-location-disable', ok, 'ok=%s code=%s' % (ok, code),
                         '停用库位失败 code=%s' % code)
            status, payload = operator.api('/lab/api/inventory/receipt', {
                'request_key': 'p3-inactive-0001',
                'item_key': 'lcsc:%s' % P3_LCSC_CODE,
                'quantity': 1, 'location_id': self.ids['locations'][1]})
            ok, code, fields, data = envelope(payload)
            self.c.check('p3-inactive-location-receipt',
                         ok is False and code == 'VALIDATION_ERROR'
                         and (fields or {}).get('location_id') == 'inactive',
                         'code=%s fields=%s' % (code, json.dumps(fields, ensure_ascii=False)),
                         '停用库位仍可入库 code=%s' % code)

        # adopt_stock 失败整体回滚（S3）
        bags_before = count_of(admin, 'lab.bag')
        quant_before = stock_state(admin, template)
        status, payload = manager.api('/lab/api/inventory/adopt_stock', {
            'item_key': 'lcsc:C999001',
            'bags': [{'location_id': location, 'quantity': 3,
                      'trace_code': 'P3ADOPT0001'},
                     {'location_id': location, 'quantity': 4,
                      'trace_code': 'P3ADOPT0001'}],
            'note': 'p3 rollback probe'})
        ok, code, fields, data = envelope(payload)
        bags_after = count_of(admin, 'lab.bag')
        quant_after = stock_state(admin, template)
        self.c.check('p3-adopt-atomic-rollback',
                     ok is False and bags_after == bags_before and quant_after == quant_before,
                     'bags %s->%s quant %s->%s code=%s'
                     % (bags_before, bags_after, quant_before, quant_after, code),
                     'adopt_stock 失败有残留 bags %s->%s quant %s->%s'
                     % (bags_before, bags_after, quant_before, quant_after))

        # 传输不确定 → 同 key 同 payload 重发（不得重复记账）
        bags0 = count_of(admin, 'lab.bag')
        params = {'request_key': 'p3-retry-0001',
                  'item_key': 'lcsc:%s' % P3_LCSC_CODE,
                  'quantity': 1, 'location_id': location}
        status, payload = operator.api('/lab/api/inventory/receipt', params)
        ok1 = is_ok(status, payload)
        status, payload = operator.api('/lab/api/inventory/receipt', params)
        ok2, code, fields, data = envelope(payload)
        replayed = bool((data or {}).get('replayed'))
        bags1 = count_of(admin, 'lab.bag')
        self.c.check('p3-unknown-outcome-retry-same-key',
                     ok1 and ok2 and replayed and bags1 == bags0 + 1,
                     'replayed=%s bags %s->%s' % (replayed, bags0, bags1),
                     '同 key 重发不幂等 ok1=%s ok2=%s replayed=%s bags %s->%s'
                     % (ok1, ok2, replayed, bags0, bags1))
        return True

    # -- 6. 标签/PDF -----------------------------------------------------
    def step_labels(self):
        operator = self.client('operator')
        if operator is None:
            self.c.block('p3-labels', '缺少操作员会话')
            return False
        bag_id = self.ids.get('bag')
        location = self.ids['locations'][0]

        status, payload = operator.api('/lab/api/labels/plan', {
            'kind': 'bag', 'ids': [bag_id], 'width_mm': 5, 'height_mm': 5})
        ok, code, fields, data = envelope(payload)
        if status == 404:
            self.c.block('p3-label-bounds', 'labels/plan 未发布')
        else:
            self.c.check('p3-label-bounds',
                         ok is False and code == 'VALIDATION_ERROR',
                         'code=%s' % code,
                         '过小尺寸未按契约返回 VALIDATION_ERROR code=%s fields=%s'
                         % (code, json.dumps(fields, ensure_ascii=False)))

        status, payload = operator.api('/lab/api/labels/plan', {
            'kind': 'location', 'ids': [location]})
        ok, code, fields, data = envelope(payload)
        self.c.check('p3-label-location-plan', ok, 'ok=%s code=%s' % (ok, code),
                     '库位标签 plan 失败 code=%s' % code)

        status, payload = operator.api('/lab/api/labels/preview', {
            'kind': 'bag', 'ids': [bag_id]})
        ok, code, fields, data = envelope(payload)
        if status == 404:
            self.c.block('p3-label-preview-safe', 'labels/preview 未发布')
        else:
            data = data or {}
            self.c.check('p3-label-preview-safe',
                         ok and 'font_path' not in data
                         and data.get('qr_per_label') == 1,
                         'qr_per_label=%s font_path=%s'
                         % (data.get('qr_per_label'), 'font_path' in data),
                         'preview 泄漏 font_path 或 qr_per_label!=1')

        # 跨公司标签 id → NOT_FOUND（S4）
        other_loc = self.ids.get('other_location')
        if other_loc:
            status, payload = operator.api('/lab/api/labels/plan', {
                'kind': 'location', 'ids': [other_loc]})
            ok, code, fields, data = envelope(payload)
            self.c.check('p3-label-cross-company',
                         ok is False and code == 'NOT_FOUND',
                         'code=%s' % code, '跨公司库位未被拒 code=%s' % code)
        else:
            self.c.block('p3-label-cross-company', '第二公司库位未建立')

        # 浏览器 PDF：无 CSRF 拒绝；带 CSRF 返回 application/pdf
        status, headers, body = operator.raw('/lab/labels/pdf', b'kind=bag&ids=%d' % (bag_id or 0),
                                            {'Content-Type': 'application/x-www-form-urlencoded'})
        if status == 404:
            self.c.block('p3-label-pdf-csrf', '/lab/labels/pdf 未发布')
            self.c.block('p3-label-pdf-download', '/lab/labels/pdf 未发布')
        else:
            self.c.check('p3-label-pdf-csrf', status in (400, 403),
                         'status=%s' % status, '缺 CSRF 未被拒 status=%s' % status)
            status_page, page_headers, page_body = operator.raw('/team/lab/labels')
            token = b''
            match = re.search(br'name="csrf_token"[^>]*value="([^"]+)"',
                              page_body or b'')
            if match:
                token = match.group(1)
            form = urllib.parse.urlencode({
                'csrf_token': token.decode('ascii', 'replace'),
                'kind': 'bag', 'ids': str(bag_id or 0)}).encode('ascii')
            status, headers, body = operator.raw(
                '/lab/labels/pdf', form,
                {'Content-Type': 'application/x-www-form-urlencoded'})
            ctype = (headers.get('Content-Type') or '').lower()
            self.c.check('p3-label-pdf-download',
                         status == 200 and 'application/pdf' in ctype
                         and (body or b'')[:4] == b'%PDF'
                         and (headers.get('X-Content-Type-Options') or '').lower() == 'nosniff'
                         and 'no-store' in (headers.get('Cache-Control') or '').lower(),
                         'status=%s ctype=%s bytes=%d' % (status, ctype, len(body or b'')),
                         'PDF 响应不合规 status=%s ctype=%s' % (status, ctype))
        return True

    # -- 7. Origin / 网关 -------------------------------------------------
    def step_origin(self):
        gate = self.cfg.get('gate_url')
        if not gate:
            self.c.block('p3-origin-cross-site',
                         '未提供 P3_GATE_URL（仅公网入口校验 Origin）；'
                         'Nginx 1.26.2/1.30.6 各 34 项配置契约另有独立证据'
                         '（real-nginx-r2-results.json），不能替本项记 pass')
            return True
        if not is_loopback(gate):
            self.c.block('p3-origin-cross-site', 'P3_GATE_URL 必须是本机回环入口')
            return True
        client = Api(gate, self.cfg['db'], self.cfg['timeout'])
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {}}).encode('utf-8')
        status, headers, raw = client.raw(
            '/lab/api/inventory/bootstrap', body,
            {'Content-Type': 'application/json',
             'Origin': 'https://evil.example'})
        self.c.check('p3-origin-cross-site', status == 403,
                     'status=%s' % status, '跨站 Origin 未被拒 status=%s' % status)
        return True

    # -- 8. 管理 API（P3 新增，候选） ------------------------------------
    def step_management(self):
        operator = self.client('operator')
        manager = self.client('manager')
        if operator is None or manager is None:
            self.c.block('p3-management', '缺少会话')
            return False
        location = self.ids['locations'][0]
        category = self.ids.get('category')
        probes = (
            ('p3-api-bags', '/lab/api/inventory/bags', {'limit': 1}),
            ('p3-api-bag', '/lab/api/inventory/bag', {'bag_id': self.ids.get('bag')}),
            ('p3-api-location-update', '/lab/api/inventory/location_update',
             {'location_id': location, 'note': 'p3'}),
            ('p3-api-mapping-list', '/lab/api/inventory/mapping_list', {}),
            ('p3-api-mapping-set', '/lab/api/inventory/mapping_set',
             {'category_id': category, 'location_id': location, 'priority': 10}),
            ('p3-api-members', '/lab/api/inventory/members', {'limit': 5}),
        )
        published = {}
        for ident, path, params in probes:
            status, payload = manager.api(path, params)
            ok, code, fields, data = envelope(payload)
            published[ident] = (status != 404 and status != 0)
            if not published[ident]:
                self.c.block(ident, '端点未发布（P3 后端路由待登记）')
            else:
                self.c.check(ident, status == 200, 'code=%s' % code,
                             'HTTP %s code=%s' % (status, code))
        # 角色门槛：operator 调管理写端点必须 FORBIDDEN
        if published.get('p3-api-mapping-set'):
            status, payload = operator.api('/lab/api/inventory/mapping_set', {
                'category_id': category, 'location_id': location})
            ok, code, fields, data = envelope(payload)
            self.c.check('p3-api-mapping-operator-forbidden',
                         ok is False and code == 'FORBIDDEN',
                         'code=%s' % code, '操作员可写映射 code=%s' % code)
        else:
            self.c.block('p3-api-mapping-operator-forbidden', '端点未发布')
        # 成员角色白名单：不得授予系统组
        if published.get('p3-api-members'):
            users = self.ids.get('users') or {}
            target = users.get('norole')
            status, payload = manager.api('/lab/api/inventory/members',
                                          {'query': target, 'limit': 5})
            ok, code, fields, data = envelope(payload)
            members = (data or {}).get('members') or []
            target_id = members[0].get('id') if members else None
            if target_id:
                status, payload = manager.api(
                    '/lab/api/inventory/member_set_role',
                    {'user_id': target_id, 'role': 'base.group_system',
                     'enabled': True})
                ok, code, fields, data = envelope(payload)
                self.c.check('p3-api-member-role-whitelist',
                             ok is False and code == 'FORBIDDEN',
                             'code=%s' % code, '系统组未被拒 code=%s' % code)
            else:
                self.c.block('p3-api-member-role-whitelist', '取不到目标成员')
        else:
            self.c.block('p3-api-member-role-whitelist', 'members 端点未发布')
        return True

    # -- 9. 只读角色/页面 ------------------------------------------------
    def step_readonly_role(self):
        catalog = self.client('catalog')
        if catalog is None:
            self.c.block('p3-readonly-role', '缺少目录角色会话')
            return False
        status, payload = catalog.api('/lab/api/inventory/receipt', {
            'request_key': 'p3-ro-0001',
            'product_template_id': self.ids['template'], 'quantity': 1,
            'location_id': self.ids['locations'][0]})
        ok, code, fields, data = envelope(payload)
        self.c.check('p3-readonly-role-receipt-forbidden',
                     ok is False and code == 'FORBIDDEN',
                     'code=%s' % code, '只读角色可入库 code=%s' % code)
        return True

    # -- 主流程 ----------------------------------------------------------
    def run(self):
        if not self.step_env():
            self.c.block_rest(ALL_STEPS, '环境不满足，未执行')
            return 3
        if not self.cfg['seed']:
            self.c.block('p3-seed-fixtures', 'P3_SEED=0：使用既有夹具，本轮未建')
            self.c.block_rest(ALL_STEPS, '未建夹具，未执行')
            return 3
        if not self.step_seed():
            self.c.block_rest(ALL_STEPS, '夹具未就绪，未执行')
            return 3
        self.step_auth()
        if not self.step_probe():
            self.c.block_rest(ALL_STEPS, '核心端点未发布，写业务断言未执行')
            return 3
        if not self.step_two_stage():
            self.c.block_rest(ALL_STEPS, '两阶段入库未完成，后续断言未执行')
            return 1
        self.step_issue_return()
        self.step_failures()
        self.step_labels()
        self.step_origin()
        self.step_management()
        self.step_readonly_role()
        self.c.block_rest(ALL_STEPS, '未执行（前置步骤未覆盖到该断言）')
        if self.c.counts.get('fail'):
            return 1
        if self.c.counts.get('blocked'):
            return 3
        return 0


# ---------------------------------------------------------------------------
# selftest：纯逻辑，不需要 Odoo
# ---------------------------------------------------------------------------
def selftest():
    checks = []

    def expect(name, condition):
        checks.append((name, bool(condition)))

    expect('loopback-127', is_loopback('http://127.0.0.1:18069'))
    expect('loopback-localhost', is_loopback('http://localhost:8069'))
    expect('not-loopback', not is_loopback('https://team.example.com'))
    expect('not-loopback-host-spoof',
           not is_loopback('http://127.0.0.1.evil.example:8069'))
    expect('users-parse', parse_users('a:b:c:d') == {
        'norole': 'a', 'catalog': 'b', 'operator': 'c', 'manager': 'd'})
    expect('users-parse-bad', parse_users('a:b:c') is None)
    expect('redact-session', 'session_id=<redacted>' in
           redact_detail('session_id=abcdef&x=1'))
    expect('redact-long-id', '<id>' in redact_detail('a' * 40))
    expect('envelope-ok', envelope({'result': {'ok': True, 'data': {'a': 1}}})[0] is True)
    expect('envelope-error',
           envelope({'result': {'ok': False, 'error': {'code': 'CONFLICT'}}})[1] == 'CONFLICT')
    expect('envelope-native',
           envelope({'error': {'code': 100}})[1] == 'TRANSPORT_100')
    expect('error-id', has_error_id({'result': {'ok': False,
                                                'error': {'fields': {'error_id': 'x'}}}}))
    expect('no-error-id', not has_error_id({'result': {'ok': False, 'error': {'fields': {}}}}))
    # 库存断言口径：必须限定内部库位，否则收发/领用会因虚拟库位镜像而恒为 0
    expect('stock-domain-internal',
           ('location_id.usage', 'in', list(INTERNAL_USAGES))
           in internal_stock_domain(7))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        sys.stdout.write('%s %s\n' % ('ok  ' if ok else 'FAIL', name))
    sys.stdout.write('SELFTEST %d/%d\n' % (len(checks) - len(failed), len(checks)))
    return 0 if not failed else 1


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def build_config(argv):
    if not argv:
        return None, 'usage: verify helper --url ... --db ...'
    values = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith('--'):
            return None, 'unexpected argument: %s' % token
        key = token[2:]
        if key == 'pass-stdin':
            # 无值开关：口令经 stdin 传入（不进 argv，避免 ps/审计日志泄漏）
            values[key] = '1'
            index += 1
            continue
        if index + 1 >= len(argv):
            return None, 'missing value for --%s' % key
        values[key] = argv[index + 1]
        index += 2
    if values.get('pass-stdin'):
        lines = sys.stdin.read().splitlines()
        if len(lines) < 2:
            return None, '--pass-stdin 需要 stdin 两行：账号口令 / 管理员口令'
        values.setdefault('pass', lines[0].strip())
        values.setdefault('admin-pass', lines[1].strip())
    required = ('url', 'db', 'users', 'pass', 'admin', 'admin-pass')
    for key in required:
        if not values.get(key):
            return None, 'missing --%s' % key
    users = parse_users(values['users'])
    if users is None:
        return None, '--users 需要 4 个冒号分隔登录名'
    return {
        'url': values['url'].rstrip('/'),
        'db': values['db'],
        'users': users,
        'pass': values['pass'],
        'admin': values['admin'],
        'admin_pass': values['admin-pass'],
        'seed': values.get('seed', '1') != '0',
        'gate_url': (values.get('gate-url') or '').strip(),
        'mpn': values.get('mpn') or 'P3-TEST-MPN-0001',
        'timeout': int(values.get('timeout') or 30),
    }, None


def main(argv):
    if not argv:
        sys.stderr.write('usage: p3_verify.py verify|selftest [options]\n')
        return 2
    if argv[0] == 'selftest':
        return selftest()
    if argv[0] != 'verify':
        sys.stderr.write('unknown command: %s\n' % argv[0])
        return 2
    cfg, error = build_config(argv[1:])
    if error:
        sys.stdout.write(json.dumps({'fatal': 3, 'message': error}) + '\n')
        return 3
    collector = Collector()
    try:
        verify = Verify(cfg, collector)
        code = verify.run()
    except Exception as exc:
        sys.stdout.write(json.dumps(
            {'fatal': 4, 'message': '%s: %s' % (type(exc).__name__, exc)},
            ensure_ascii=False) + '\n')
        return 4
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
P3VERIFY
}

# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
case "${1:-}" in
  --print-verify-helper)
    p3_helper_source
    exit 0
    ;;
  --selftest)
    _tmp="$(mktemp -d)" || exit 4
    p3_helper_source > "$_tmp/p3_verify.py" || { rm -rf "$_tmp"; exit 4; }
    "$PYTHON" "$_tmp/p3_verify.py" selftest
    _rc=$?
    rm -rf "$_tmp"
    exit $_rc
    ;;
  --check-evidence)
    _work="${2:-}"
    [ -n "$_work" ] || { echo "usage: $0 --check-evidence <workdir>"; exit 2; }
    _results="$_work/results.jsonl"
    _summary="$_work/verify-summary.json"
    [ -f "$_results" ] || { echo "BLOCKED 缺少 results.jsonl"; exit 3; }
    [ -f "$_summary" ] || { echo "BLOCKED 缺少 verify-summary.json"; exit 3; }
    "$PYTHON" - "$_results" "$_summary" <<'PY'
import json, sys
results_path, summary_path = sys.argv[1], sys.argv[2]
counts = {'pass': 0, 'fail': 0, 'blocked': 0}
bad = []
with open(results_path, 'rb') as handle:
    for number, line in enumerate(handle.read().decode('utf-8', 'replace').splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            bad.append(number)
            continue
        if record.get('result') not in counts or not record.get('id'):
            bad.append(number)
            continue
        counts[record['result']] += 1
with open(summary_path, 'r', encoding='utf-8') as handle:
    summary = json.load(handle)
recorded = summary.get('counts') or {}
mismatch = [key for key in counts if int(recorded.get(key) or 0) != counts[key]]
total = sum(counts.values())
if bad or mismatch:
    print('EVIDENCE-MISMATCH badlines=%s mismatch=%s' % (bad[:5], mismatch))
    sys.exit(1)
print('EVIDENCE-OK pass=%d fail=%d blocked=%d total=%d'
      % (counts['pass'], counts['fail'], counts['blocked'], total))
sys.exit(0)
PY
    exit $?
    ;;
esac

# ---------------------------------------------------------------------------
# 正常一轮
# ---------------------------------------------------------------------------
for name in ODOO_URL DB_NAME P3_USERS P3_PASS P3_ADMIN P3_ADMIN_PASS; do
  if [ -z "${!name:-}" ]; then
    echo "BLOCKED 缺少环境变量 $name"
    exit 3
  fi
done
case "$P3_BASE" in
  /*) ;;
  *) echo "BLOCKED P3_BASE 必须是绝对路径"; exit 3 ;;
esac

if [ -n "${P3_WORK:-}" ]; then
  WORK="$P3_WORK"
  if [ -f "$WORK/results.jsonl" ]; then
    echo "BLOCKED P3_WORK 已有本轮证据，拒绝复用：$WORK"
    exit 4
  fi
  mkdir -p "$WORK" || { echo "BLOCKED 无法创建 P3_WORK"; exit 3; }
else
  mkdir -p "$P3_BASE/runs" || { echo "BLOCKED 无法创建 runs"; exit 3; }
  WORK="$(mktemp -d "$P3_BASE/runs/run.XXXXXX")" || { echo "BLOCKED mktemp 失败"; exit 3; }
fi
chmod 700 "$WORK" 2>/dev/null || true
RUN_ID="${P3_RUN_ID:-p3-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$WORK")}"
export P3_RUN_ID="$RUN_ID"
# 复用 P2 证据助手时让 run_id 与本轮一致（助手优先读 P2_RUN_ID）
export P2_RUN_ID="$RUN_ID" P2_WORK="$WORK"
RESULTS="$WORK/results.jsonl"
: > "$RESULTS" || { echo "BLOCKED results.jsonl 不可写"; exit 4; }

# 证据助手复用 P2 单一实现
EV="$WORK/.p3_evidence.py"
if ! bash "$P2_RUNNER" --print-evidence-helper > "$EV" 2>/dev/null; then
  echo "BLOCKED 证据助手不可用（$P2_RUNNER）"
  exit 3
fi
chmod 600 "$EV" 2>/dev/null || true
HELPER="$WORK/.p3_verify.py"
p3_helper_source > "$HELPER" || { echo "BLOCKED 断言助手写入失败"; exit 4; }
chmod 600 "$HELPER" 2>/dev/null || true

echo "=== P3 写业务独立验收 ==="
echo "实例: $ODOO_URL  库: $DB_NAME  账号: $P3_USERS"
echo "证据: $WORK  run_id: $RUN_ID"
echo "seed=${P3_SEED:-1} gate=${P3_GATE_URL:-none}"

if [ -n "${P3_VERIFY_SCRIPT:-}" ]; then
  echo "（测试模式：使用外部断言脚本 $P3_VERIFY_SCRIPT）"
  P3_URL="$ODOO_URL" P3_DB="$DB_NAME" P3_USERS_ENV="$P3_USERS" \
    P3_PASS_ENV="$P3_PASS" P3_ADMIN_ENV="$P3_ADMIN" \
    P3_ADMIN_PASS_ENV="$P3_ADMIN_PASS" P3_WORK="$WORK" P3_RUN_ID="$RUN_ID" \
    P3_HELPER="$HELPER" P3_EVIDENCE_PY="$EV" \
    bash "$P3_VERIFY_SCRIPT"
  VERIFY_RC=$?
  if [ ! -s "$RESULTS" ]; then
    echo "BLOCKED 外部断言脚本未产生 results.jsonl"
    exit 4
  fi
else
  printf '%s\n%s\n' "$P3_PASS" "$P3_ADMIN_PASS" \
    | "$PYTHON" "$HELPER" verify \
      --url "$ODOO_URL" --db "$DB_NAME" --users "$P3_USERS" \
      --admin "$P3_ADMIN" --pass-stdin \
      --seed "${P3_SEED:-1}" --gate-url "${P3_GATE_URL:-}" \
      --mpn "$P3_ITEM_MPN" --timeout "$P3_TIMEOUT" \
      > "$WORK/verify.out" 2>"$WORK/verify.err"
  VERIFY_RC=$?
fi

# 逐条登记证据（不打印明细中的敏感值）
PASS=0; FAIL=0; BLOCKED=0; FATAL=0
"$PYTHON" - "$WORK/verify.out" > "$WORK/verify.tsv" <<'PY'
import json, sys
try:
    with open(sys.argv[1], 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if 'fatal' in record:
                print('FATAL\t%s\t%s' % ('p3-fatal',
                                         str(record.get('message'))[:300]))
                continue
            ident = record.get('id') or ''
            result = record.get('result') or ''
            if not ident or result not in ('pass', 'fail', 'blocked', 'skip'):
                continue
            detail = (record.get('detail') or '').replace('\t', ' ').replace('\n', ' ')
            print('%s\t%s\t%s' % (result, ident, detail[:400]))
except OSError:
    pass
PY
while IFS=$'\t' read -r result ident detail; do
  [ -n "${result:-}" ] || continue
  if [ "$result" = "FATAL" ]; then
    FATAL=1
    printf 'BLOCKED %s :: %s\n' "$ident" "${detail:-}"
    continue
  fi
  case "$result" in
    pass) PASS=$((PASS + 1)) ;;
    fail) FAIL=$((FAIL + 1)) ;;
    blocked) BLOCKED=$((BLOCKED + 1)) ;;
  esac
  "$PYTHON" "$EV" add "$RESULTS" "$ident" "$result" "${detail:-}" >/dev/null 2>&1 \
    || { echo "EVIDENCE-WRITE-FAILED $ident"; FATAL=1; }
  printf '%-9s %s :: %s\n' "$(echo "$result" | tr '[:lower:]' '[:upper:]')" "$ident" "${detail:-}"
done < "$WORK/verify.tsv"

# 以 results.jsonl 为准重算计数（外部断言脚本模式也适用，避免两套计数漂移）
RECOUNT="$("$PYTHON" - "$RESULTS" <<'PY'
import json, sys
counts = {'pass': 0, 'fail': 0, 'blocked': 0, 'skip': 0}
bad = 0
try:
    with open(sys.argv[1], 'rb') as handle:
        for line in handle.read().decode('utf-8', 'replace').splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if record.get('result') in counts:
                counts[record['result']] += 1
            else:
                bad += 1
except OSError:
    bad += 1
print('%d %d %d %d' % (counts['pass'], counts['fail'], counts['blocked'], bad))
PY
)"
read -r PASS FAIL BLOCKED BADLINES <<< "${RECOUNT:-0 0 0 1}"
[ "${BADLINES:-1}" -gt 0 ] && { echo "EVIDENCE-BADLINES $BADLINES"; FATAL=1; }

TOTAL=$((PASS + FAIL + BLOCKED))
EXIT_CODE=0
if [ "$FATAL" = "1" ]; then EXIT_CODE=4; fi
if [ "$VERIFY_RC" -ne 0 ] && [ "$EXIT_CODE" = "0" ]; then EXIT_CODE="$VERIFY_RC"; fi
if [ "$FAIL" -gt 0 ]; then EXIT_CODE=1; fi
if [ "$EXIT_CODE" = "0" ] && [ "$BLOCKED" -gt 0 ]; then EXIT_CODE=3; fi

# summary（schema 独立于 P2，便于并存）
"$PYTHON" - "$WORK/verify-summary.json" "$RUN_ID" "$WORK" "$EXIT_CODE" \
  "$PASS" "$FAIL" "$BLOCKED" "$VERIFY_RC" <<'PY'
import datetime, json, os, sys
path, run_id, work, code, p, f, b, verify_rc = sys.argv[1:9]
data = {
    "schema": "p3-verify-summary-1",
    "run_id": run_id,
    "work": work,
    "counts": {"pass": int(p), "fail": int(f), "blocked": int(b)},
    "total": int(p) + int(f) + int(b),
    "verify_rc": int(verify_rc),
    "exit_code": int(code),
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"),
}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(tmp, path)
print("VERIFY_SUMMARY " + json.dumps(data, ensure_ascii=False, sort_keys=True))
PY

echo
echo "SUMMARY PASS=$PASS FAIL=$FAIL BLOCKED=$BLOCKED total=$TOTAL verify_rc=$VERIFY_RC exit_code=$EXIT_CODE"
echo "证据目录：$WORK"
if [ "$FAIL" -gt 0 ] && [ -f "$WORK/verify.err" ]; then
  echo "--- verify.err tail ---"
  tail -n 20 "$WORK/verify.err"
fi
exit "$EXIT_CODE"
