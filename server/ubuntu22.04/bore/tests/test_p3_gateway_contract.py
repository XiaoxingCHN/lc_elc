#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 公网网关契约：精确页面 GET/HEAD、业务 JSON-RPC POST、CSRF PDF POST、默认拒绝。

分三层，互不替代：

1. ``P3AllowlistTextTest``
   纯文本断言：模板里到底登记了哪些 ``location``、方法白名单、以及**不该出现**
   的通配/通用入口/高风险端点。不需要 nginx、不需要 Odoo，任何环境都能跑。

2. ``P3AllowlistSourceSyncTest``
   与 ``server/ubuntu22.04/odoo_addons`` 的**实际 @http.route** 交叉核对：
   网关放行的 JSON-RPC 端点集合必须恰好等于"已实现且有 P3 UI"的那一批。
   后端新增端点时这里会失败 —— 这是有意的：新增公网写入口必须先做一次
   Lead 决定，不允许"路由加了网关自动跟着放开"。

3. ``P3RealNginxTest``
   只有提供 ``LC_P3_NGINX_BIN`` 才执行：同一份模板渲染成 HTTP 变体，真跑
   ``nginx -t`` + 启动 nginx + 合成上游，逐条验证"放行的到达上游 / 拒绝的
   不到达上游"。没有 nginx 二进制时**跳过**（跳过不算通过）。
   正向对照一律走**真正的 proxy location**（`/team/lab/bags` 等），不走
   `return`/`redirect` 固定响应路径，否则"到达上游"这类断言会失去意义。
   上游记录器由本文件自带（``_RecordingUpstream``）而不是复用
   ``tests/synthetic_upstream.py``：后者是 P1 共享夹具，不记录
   ``X-Forwarded-Host`` / ``X-Forwarded-Port``，而本轮必须断言"外部端口经
   XFH 原样到达上游 + Forwarded/X-Forwarded-Port 被清空"。共享夹具不在本
   任务写域（其字段被 P1 用例依赖），因此按 ``scripts/verify-local-entry.sh``
   的既有做法，测试自带一个更详细的记录器。

设计红线（与 local/build/p3-web-20261028 的 frontend/backend 契约 + Lead 决定一致）：

* 不用 ``/lab/api/.*`` 通配，也不用前缀 location 包住 ``/lab/``：逐条 ``location =``。
* ``adopt_stock`` / ``legacy_stock`` 无 P3 UI 且写历史库存 → 默认不公开。
* 目录写端点 ``catalog/bind``、``catalog/create_material`` 按 Lead 决定放开，但只到
  "精确 + POST"为止：角色仍由后端 ``lab_catalog`` 权限校验，网关不判断角色。
* 旧 ``/lab/scan`` 只做**站内相对 303** 到 ``/team/scan``（``absolute_redirect off`` +
  ``$is_args$args`` 保 query），location 内**没有** ``proxy_pass``：旧 inline 控制台永不
  可达，``/team/scan`` 未注册时由应用层 404（fail-closed）。方法限制必须写在 rewrite
  阶段的 ``if``——location 内的 ``return`` 先于 ``limit_except`` 的 ``deny`` 执行。
* 旧表单端点 ``/lab/scan/{resolve,submit}``、``/lab/labels/{plan,download}`` 仍不公开。
* location 内不得写 ``add_header``：nginx 只要在 location 里见到一条 add_header，
  就会丢弃 server 级继承的 CSP / X-Frame-Options / nosniff。
* ``location / { return 404; }`` 必须仍是最后一个 location。
"""

import http.client
import importlib.util
import json
import os
import pathlib
import re
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "nginx" / "bore-public-allowlist.conf.template").read_text(encoding="utf-8")
#: 与 test_config_contract.py 同一套渲染口径：只替换公开端口占位符。
ALLOW = TEMPLATE.replace("@PUBLIC_PORT@", "9500")
HEADERS = (ROOT / "nginx" / "bore-proxy-headers.conf").read_text(encoding="utf-8")
ODOO_ADDONS = ROOT.parent / "odoo_addons"

#: P3 页面（controllers/workflow_pages.py 注册，规范 /team/** 与根级别成对）。
P3_PAGE_PATHS = (
    "/team/scan", "/scan",
    "/team/account", "/account",
    "/team/lab/receipts", "/lab/receipts",
    "/team/lab/bags", "/lab/bags",
    "/team/lab/labels", "/lab/labels",
    "/team/lab/issues", "/lab/issues",
    "/team/lab/issues/new", "/lab/issues/new",
    "/team/lab/history", "/lab/history",
    "/team/lab/locations", "/lab/locations",
    "/team/lab/location-mappings", "/lab/location-mappings",
    "/team/lab/settings", "/lab/settings",
    "/team/lab/materials", "/lab/materials",
)

#: 动态 bag 详情：单段 + **正整数** + 有界位数（对齐 Odoo <int:bag_id> 与 DB 正整数 id）。
#: 首位非 0，最多 19 位（int8/bigserial 宽度，已覆盖 int4）；超长数字必须被拒绝。
P3_BAG_DETAIL_REGEX = r"^/(?:team/)?lab/bags/[1-9][0-9]{0,18}$"
#: 含 `{0,18}` 的正则必须双引号包裹，否则 nginx 词法把 "{" 当块起始而报语法错。
P3_BAG_DETAIL_LOCATION = 'location ~ "%s"' % P3_BAG_DETAIL_REGEX
P3_BAG_DETAIL_SAMPLES = ("/team/lab/bags/1", "/lab/bags/42",
                         "/lab/bags/9223372036854775807")  # 19 位 = int8 最大值
#: 必须被正则拒绝的输入（含超长数字——不允许为了让样例通过而放宽）。
#: 注意：这是**位数上界**，不是数值上界——正则无法表达 int8 的 9223372036854775807 值域，
#: 因此 19 位数字一律放行（由应用层按 id 是否存在返回 404），只拒绝 20 位及以上。
P3_BAG_DETAIL_REJECTED = (
    "/lab/bags/",             # 空段
    "/lab/bags/abc",          # 非数字
    "/lab/bags/-1",           # 负号
    "/lab/bags/1.5",          # 小数点
    "/lab/bags/1/x",          # 多余段
    "/lab/bags/1/",           # 尾随斜杠
    "/lab/bags/0x10",         # 十六进制
    "/lab/bags/0",            # 非正整数
    "/lab/bags/0123",         # 前导零（非规范 id）
    "/lab/bags/12345678901234567890",   # 20 位：超出位数上界
    "/lab/bags/" + "9" * 20,            # 20 位
    "/lab/bags/" + "9" * 64,            # 超长数字
)

#: P3 业务 JSON-RPC（全部 POST + 统一信封）。共 24 条，逐条精确。
P3_API_PATHS = (
    # lab 角色（只读/引导）
    "/lab/api/inventory/bootstrap",
    "/lab/api/inventory/locations",
    "/lab/api/inventory/resolve_code",
    "/lab/api/inventory/bags",
    "/lab/api/inventory/bag",
    "/lab/api/inventory/issues",
    "/lab/api/inventory/history",
    # operator（写，全部要求 request_key）
    "/lab/api/inventory/pending/list",
    "/lab/api/inventory/pending/create",
    "/lab/api/inventory/pending/update",
    "/lab/api/inventory/pending/resolve",
    "/lab/api/inventory/pending/confirm",
    "/lab/api/inventory/receipt",
    "/lab/api/inventory/issue",
    "/lab/api/inventory/return",
    # manager
    "/lab/api/inventory/location_create",
    "/lab/api/inventory/location_update",
    "/lab/api/inventory/mapping_list",
    "/lab/api/inventory/mapping_set",
    "/lab/api/inventory/mapping_remove",
    "/lab/api/inventory/members",
    "/lab/api/inventory/member_set_role",
    # operator（标签只读）
    "/lab/api/labels/plan",
    "/lab/api/labels/preview",
)

#: 有路由但**不**公开：无 P3 UI / 写历史库存 / 旧控制台表单端点。
P3_NOT_PUBLIC_PATHS = (
    "/lab/api/inventory/adopt_stock",
    "/lab/api/inventory/legacy_stock",
    "/lab/scan/resolve",
    "/lab/scan/submit",
    "/lab/labels/plan",
    "/lab/labels/download",
)

#: 目录 API（lab_catalog，POST + 统一信封）。只读 4 + 写 2 = 6 条，与后端实际路由一一对应。
P3_CATALOG_READ_PATHS = (
    "/lab/api/catalog/search",
    "/lab/api/catalog/detail",
    "/lab/api/catalog/categories",
    "/lab/api/catalog/facets",
)

#: materials 页使用的目录**写**端点（Lead 决定放开；角色仍由后端 catalog 权限校验）。
P3_CATALOG_WRITE_PATHS = (
    "/lab/api/catalog/bind",
    "/lab/api/catalog/create_material",
)

P3_CATALOG_PATHS = P3_CATALOG_READ_PATHS + P3_CATALOG_WRITE_PATHS

#: 旧 /lab/scan：只做站内相对 303 迁移，绝不转发旧控制台（location 内没有 proxy_pass）。
P3_REDIRECT_PATH = "/lab/scan"
P3_REDIRECT_TARGET = "/team/scan"

#: 通用入口：一律不得出现在白名单里。
GENERIC_DENIED_PATHS = (
    "/jsonrpc", "/web/dataset", "/web/dataset/call_kw", "/web/database",
    "/web/database/selector", "/odoo", "/website", "/web/login", "/web/image",
    "/report", "/longpolling", "/websocket",
)

#: 标签 PDF：浏览器表单 POST 直出（非 JSON-RPC）。
P3_PDF_PATH = "/lab/labels/pdf"


# ---------------------------------------------------------------------------
# 纯文本辅助
# ---------------------------------------------------------------------------
def location_lines(text=ALLOW):
    """所有 location 指令行（去缩进），保持文件顺序。"""
    return [line.strip() for line in text.splitlines()
            if line.strip().startswith("location ")]


def location_for(path, text=ALLOW):
    """按**完整路径**取 location 行；不会把 /lab 误配到 /lab/api/...。"""
    pattern = re.compile(r"^location\s+(?:=\s+)?" + re.escape(path) + r"\s")
    for line in location_lines(text):
        if pattern.match(line):
            return line
    return None


def prefix_locations(text=ALLOW):
    """前缀/正则 location（非 `location =`），用于"不得放宽"断言。"""
    return [line for line in location_lines(text) if not line.startswith("location = ")]


def location_block(path, text=ALLOW):
    """取一个 location 的**完整**配置块（多行也支持，按花括号配平）。"""
    lines = text.splitlines()
    pattern = re.compile(r"^\s*location\s+(?:=\s+)?" + re.escape(path) + r"\s")
    for index, line in enumerate(lines):
        if not pattern.match(line):
            continue
        block = []
        depth = 0
        for current in lines[index:]:
            block.append(current)
            depth += current.count("{") - current.count("}")
            if depth <= 0:
                break
        return block
    return None


def location_text(path, text=ALLOW):
    """location 块压成一行（便于断言指令），保留 `;`/`{`/`}` 之间的空格。"""
    block = location_block(path, text)
    if block is None:
        return None
    return " ".join(part.strip() for part in block if part.strip())


def load_render_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TLS_TEXT = "ssl_certificate /test/site.crt;" + chr(10) + "ssl_certificate_key /test/site.key;"


# ---------------------------------------------------------------------------
# 1. 模板文本契约
# ---------------------------------------------------------------------------
class P3AllowlistTextTest(unittest.TestCase):
    def test_every_p3_page_is_exact_get_head_only(self):
        for path in P3_PAGE_PATHS:
            with self.subTest(path=path):
                line = location_for(path)
                self.assertIsNotNone(line, "缺少 P3 页面 location：%s" % path)
                self.assertIn("limit_except GET HEAD", line)
                self.assertIn("include bore-proxy-headers.conf;", line)
                self.assertNotIn("POST", line.split("proxy_pass")[0])
                self.assertNotIn("add_header", line)

    def test_p3_bag_detail_is_bounded_numeric_single_segment(self):
        """bag 详情：单段正整数、有界位数；超长数字与畸形串一律不匹配。"""
        self.assertIn(P3_BAG_DETAIL_REGEX, ALLOW)
        # 含 "{" 的正则必须被引号包裹，否则 nginx 会把 "{" 当块起始
        self.assertIn(P3_BAG_DETAIL_LOCATION, ALLOW)
        compiled = re.compile(P3_BAG_DETAIL_REGEX)
        for sample in P3_BAG_DETAIL_SAMPLES:
            self.assertTrue(compiled.match(sample), sample)
        for bad in P3_BAG_DETAIL_REJECTED:
            self.assertFalse(compiled.match(bad), bad)
        # 位数上限本身要能挡住"再长一位"的合法数字（不是数字字符集变宽）
        self.assertTrue(compiled.match("/lab/bags/" + "9" * 19))
        self.assertFalse(compiled.match("/lab/bags/" + "9" * 20))
        # 不允许用前缀/通配把整个 /lab/bags/ 子树交出去
        self.assertNotIn("location ^~ /lab/bags", ALLOW)
        self.assertNotIn("location /lab/bags", ALLOW)
        # 注意：正则文本里是 `(?:team/)?lab/bags`，没有连续的 "/lab/bags" 子串，
        # 因此这里必须用 `lab/bags` 做筛选（用带前导斜杠的串会永远筛不到）。
        bag_prefixes = [line for line in prefix_locations() if "lab/bags" in line]
        self.assertEqual(len(bag_prefixes), 1, bag_prefixes)
        self.assertTrue(bag_prefixes[0].startswith(P3_BAG_DETAIL_LOCATION),
                        bag_prefixes[0])

    def test_p3_business_jsonrpc_is_exact_post_only(self):
        self.assertEqual(len(P3_API_PATHS), 24)
        self.assertEqual(len(set(P3_API_PATHS)), 24)
        for path in P3_API_PATHS:
            with self.subTest(path=path):
                line = location_for(path)
                self.assertIsNotNone(line, "缺少 P3 JSON-RPC location：%s" % path)
                self.assertIn("limit_except POST { deny all; }", line)
                self.assertIn("include bore-proxy-headers.conf;", line)
                self.assertNotIn("GET", line.split("proxy_pass")[0])
                self.assertNotIn("add_header", line)

    def test_no_lab_api_wildcard_or_prefix_location(self):
        for line in prefix_locations():
            self.assertNotIn("/lab/api", line,
                             "不得用前缀/正则 location 包住 /lab/api：%s" % line)
        # 允许的前缀 location 只有两类静态资源 + 默认拒绝；其余 /lab/** 一律精确登记
        allowed_prefixes = ("location ^~ /lab_team_web/static/",
                            "location ^~ /lab/client/updates/assets/",
                            "location / { return 404; }")
        regex_locations = []
        for line in prefix_locations():
            if line.startswith("location ~ "):
                regex_locations.append(line)
                continue
            self.assertTrue(line.startswith(allowed_prefixes), line)
        # 正则 location 只有两个，且各自有边界断言（items 单段 / bags 十进制单段）
        self.assertEqual(len(regex_locations), 2, regex_locations)
        self.assertTrue(any("lab/items/" in line for line in regex_locations), regex_locations)
        self.assertTrue(any(P3_BAG_DETAIL_REGEX in line for line in regex_locations), regex_locations)
        # 精确 location 里也不得出现正则通配
        for line in location_lines():
            if line.startswith("location = "):
                self.assertNotIn(".*", line, line)
                self.assertNotIn("~", line.split("proxy_pass")[0], line)

    def test_high_risk_and_generic_endpoints_absent(self):
        for path in P3_NOT_PUBLIC_PATHS + GENERIC_DENIED_PATHS:
            with self.subTest(path=path):
                self.assertIsNone(location_for(path),
                                  "不应公开的路径出现在白名单：%s" % path)
        # 也不能通过前缀 location 间接放行
        for line in prefix_locations():
            for path in ("/lab/scan", "/lab/labels", "/web/", "/jsonrpc", "/websocket"):
                self.assertNotIn(path, line, line)

    def test_catalog_apis_are_exact_post_only(self):
        """目录 6 条（只读 4 + 写 2）逐条精确 POST；角色由后端 catalog 权限校验。"""
        self.assertEqual(len(P3_CATALOG_PATHS), 6)
        self.assertEqual(len(set(P3_CATALOG_PATHS)), 6)
        for path in P3_CATALOG_PATHS:
            with self.subTest(path=path):
                line = location_for(path)
                self.assertIsNotNone(line, "缺少目录 API location：%s" % path)
                self.assertIn("limit_except POST { deny all; }", line)
                self.assertIn("include bore-proxy-headers.conf;", line)
                self.assertNotIn("GET", line.split("proxy_pass")[0])
                self.assertNotIn("add_header", line)
        # 目录写端点不得被通配/前缀放开，也不得顺手带出别的目录写接口
        for extra in ("/lab/api/catalog/delete", "/lab/api/catalog/unbind"):
            self.assertIsNone(location_for(extra), extra)

    def test_legacy_scan_is_relative_303_without_legacy_upstream(self):
        """旧 /lab/scan 只做站内相对 303；没有 proxy_pass，旧 inline 控制台不可达。"""
        text = location_text(P3_REDIRECT_PATH)
        self.assertIsNotNone(text, "缺少旧 /lab/scan 兼容 location")
        # 相对 303：保留 query，目标固定为 /team/scan
        self.assertIn("absolute_redirect off;", text)
        self.assertIn("return 303 %s$is_args$args;" % P3_REDIRECT_TARGET, text)
        self.assertNotIn("$scheme", text)
        self.assertNotIn("$http_host", text)
        # 绝不触及旧 upstream
        self.assertNotIn("proxy_pass", text)
        self.assertNotIn("proxy_set_header", text)
        self.assertNotIn("@UPSTREAM@", text)
        self.assertNotIn("include bore-proxy-headers.conf;", text)
        self.assertNotIn("add_header", text)
        # 方法限制必须在 rewrite 阶段（location 内 return 先于 limit_except 的 deny）
        self.assertIn("if ($request_method !~ ^(?:GET|HEAD)$) { return 403; }", text)
        # 旧表单端点仍然一律不公开
        for path in ("/lab/scan/resolve", "/lab/scan/submit"):
            self.assertIsNone(location_for(path), path)
        # 新扫码页必须是精确 GET/HEAD（303 的目标本身不再被网关二次改写）
        self.assertIn("limit_except GET HEAD", location_for("/team/scan") or "")

    def test_pdf_is_post_only(self):
        line = location_for(P3_PDF_PATH)
        self.assertIsNotNone(line, "缺少标签 PDF location")
        self.assertIn("limit_except POST { deny all; }", line)
        self.assertNotIn("GET", line.split("proxy_pass")[0])
        self.assertIn("include bore-proxy-headers.conf;", line)
        # 不得加 add_header（会丢弃继承的 CSP / nosniff）
        self.assertNotIn("add_header", line)
        # no-store 由上游（lab_workflow /lab/labels/pdf）负责，网关不改写缓存头
        self.assertNotIn("proxy_hide_header", ALLOW)
        self.assertNotIn("proxy_cache", ALLOW)

    def test_default_deny_is_last_location(self):
        lines = [line for line in ALLOW.splitlines() if line.strip()]
        tail = [line.strip() for line in lines if line.strip().startswith("location ")]
        self.assertEqual(tail[-1], "location / { return 404; }", tail[-1])
        self.assertEqual(sum(1 for line in tail if line.startswith("location / ")), 1)

    def test_every_proxy_location_uses_shared_headers(self):
        for line in location_lines():
            if line.startswith("location = /web/session/authenticate"):
                continue  # 唯一独立写头的 location（清 DB 头），由 test_config_contract 防漂移
            if "proxy_pass" in line:
                self.assertIn("include bore-proxy-headers.conf;", line, line)
            self.assertNotIn("proxy_set_header", line, line)

    def test_server_level_security_headers_still_inherited(self):
        """P3 新增的 location 不得引入 add_header，否则继承的 CSP 会被整体丢弃。"""
        first = next(index for index, line in enumerate(ALLOW.splitlines())
                     if line.strip().startswith("location "))
        inside = [line for line in ALLOW.splitlines()[first:]
                  if line.strip().startswith("add_header")]
        self.assertEqual(inside, [])
        for header in ('add_header X-Content-Type-Options "nosniff" always;',
                       'add_header X-Frame-Options "DENY" always;',
                       'add_header Content-Security-Policy '):
            self.assertIn(header, ALLOW)


# ---------------------------------------------------------------------------
# 2. 与后端实际路由交叉核对
# ---------------------------------------------------------------------------
ROUTE_RE = re.compile(r"@http\.route\(\s*API\s*\+\s*'([^']+)'")
API_PREFIX_RE = re.compile(r"^API\s*=\s*'([^']+)'", re.MULTILINE)

#: 允许出现在公网白名单的控制器（只有这三个文件承载 P3 业务 JSON-RPC）。
P3_API_CONTROLLERS = ("lab_inventory_api.py", "lab_p3_api.py", "lab_labels_api.py")


@unittest.skipUnless(ODOO_ADDONS.is_dir(), "找不到 odoo_addons（独立部署的 bore 目录）")
class P3AllowlistSourceSyncTest(unittest.TestCase):
    def _api_paths(self, filename):
        path = ODOO_ADDONS / "lab_workflow" / "controllers" / filename
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        match = API_PREFIX_RE.search(text)
        self.assertIsNotNone(match, "%s 未声明 API 前缀" % filename)
        prefix = match.group(1)
        return ["%s%s" % (prefix, found) for found in ROUTE_RE.findall(text)]

    def test_gateway_matches_implemented_p3_endpoints(self):
        discovered = []
        for filename in P3_API_CONTROLLERS:
            discovered.extend(self._api_paths(filename))
        self.assertEqual(len(discovered), len(set(discovered)), discovered)
        published = set(discovered) - set(P3_NOT_PUBLIC_PATHS)
        self.assertEqual(sorted(published), sorted(P3_API_PATHS))

    def test_excluded_endpoints_really_exist_so_the_decision_is_explicit(self):
        discovered = set()
        for filename in P3_API_CONTROLLERS:
            discovered.update(self._api_paths(filename))
        for path in ("/lab/api/inventory/adopt_stock", "/lab/api/inventory/legacy_stock"):
            self.assertIn(path, discovered, path)
            self.assertIsNone(location_for(path), path)

    def test_legacy_form_endpoints_never_reach_legacy_console(self):
        """lab_web.py 的旧表单端点：只能被"无 proxy_pass 的 303"接管，其余一律不公开。"""
        path = ODOO_ADDONS / "lab_workflow" / "controllers" / "lab_web.py"
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        # 旧控制器全部是 @http.route('<literal>', type='http', ... csrf=True)
        legacy = re.findall(r"@http\.route\('([^']+)'", text)
        self.assertTrue(legacy, "lab_web.py 未解析到任何路由")
        self.assertIn(P3_REDIRECT_PATH, legacy)
        self.assertIn("/lab/labels/download", legacy)
        for route in legacy:
            if route == P3_REDIRECT_PATH:
                continue
            with self.subTest(route=route):
                self.assertIsNone(location_for(route),
                                  "旧表单端点不得出现在公网白名单：%s" % route)
        # /lab/scan 只允许"无 proxy_pass 的站内 303"，旧控制台与旧上游永不可达
        redirect = location_text(P3_REDIRECT_PATH)
        self.assertIsNotNone(redirect)
        self.assertNotIn("proxy_pass", redirect)
        self.assertNotIn("@UPSTREAM@", redirect)
        self.assertIn("return 303 %s$is_args$args;" % P3_REDIRECT_TARGET, redirect)

    def test_catalog_paths_match_catalog_controller(self):
        """网关登记的 6 条目录端点必须恰好等于 catalog_api.py 的实际 POST 路由。"""
        path = ODOO_ADDONS / "lab_catalog" / "controllers" / "catalog_api.py"
        if not path.is_file():
            self.skipTest("找不到 lab_catalog/controllers/catalog_api.py")
        text = path.read_text(encoding="utf-8")
        discovered = sorted(re.findall(
            r"@http\.route\('(/lab/api/catalog/[^']+)',\s*type='jsonrpc'[^\n]*methods=\['POST'\]",
            text))
        self.assertEqual(discovered, sorted(P3_CATALOG_PATHS))
        # 每条都必须以"精确 POST"出现在网关里
        for route in discovered:
            with self.subTest(route=route):
                line = location_for(route)
                self.assertIsNotNone(line, route)
                self.assertIn("limit_except POST { deny all; }", line)
        # /lab/api/asset 仍是 GET/HEAD（不在 catalog_api.py，改由 asset_cache.py 提供）
        self.assertIn("limit_except GET HEAD", location_for("/lab/api/asset") or "")

    def test_page_paths_match_workflow_pages_controller(self):
        path = ODOO_ADDONS / "lab_team_web" / "controllers" / "workflow_pages.py"
        if not path.is_file():
            self.skipTest("找不到 workflow_pages.py")
        text = path.read_text(encoding="utf-8")
        routes = []
        for block in re.findall(r"@http\.route\(\[([^\]]*)\]", text):
            routes.extend(re.findall(r"'([^']+)'", block))
        # 去掉动态参数，只比静态路径
        static = sorted(route for route in routes if "<" not in route)
        self.assertEqual(static, sorted(P3_PAGE_PATHS))


# ---------------------------------------------------------------------------
# 3. 渲染器：模板里的 location 必须原样出现在最终 nginx.conf
# ---------------------------------------------------------------------------
class P3GatewayRenderTest(unittest.TestCase):
    def setUp(self):
        self.public = load_render_module("render-public-gateway.py", "p3_public_render")

    def render_public(self):
        return self.public.render(tls_config=TLS_TEXT, output=pathlib.Path("/test/p3"),
                                  public_port=16443, listen_port=18443,
                                  database="TestDB", nginx_version="1.18.0")

    def test_public_render_keeps_every_p3_location(self):
        config, headers = self.render_public()
        for path in (P3_PAGE_PATHS + P3_API_PATHS + P3_CATALOG_PATHS
                     + (P3_PDF_PATH, P3_REDIRECT_PATH)):
            with self.subTest(path=path):
                self.assertIsNotNone(location_for(path, config),
                                     "渲染后丢失 location：%s" % path)
        self.assertIn(P3_BAG_DETAIL_REGEX, config)
        self.assertIsNotNone(location_for("/web/session/authenticate", config))
        self.assertNotIn("@", config + headers)
        self.assertIn("location / { return 404; }", config)
        # 渲染不引入第二个 server 级 CSP / 第二个 authority 校验
        self.assertEqual(config.count("Content-Security-Policy"), 1)
        self.assertEqual(len([line for line in config.splitlines()
                              if "$http_host !~ " in line]), 1)

    def test_public_render_keeps_relative_303_for_legacy_scan(self):
        """渲染后 /lab/scan 仍是"相对 303 + 无 proxy_pass"，未被 @RATE_LIMIT@ 等注入破坏。"""
        config, _ = self.render_public()
        text = location_text(P3_REDIRECT_PATH, config)
        self.assertIsNotNone(text)
        self.assertIn("absolute_redirect off;", text)
        self.assertIn("return 303 %s$is_args$args;" % P3_REDIRECT_TARGET, text)
        self.assertNotIn("proxy_pass", text)
        self.assertNotIn("@UPSTREAM@", text)
        self.assertNotIn("lc_bore_auth", text)

    def test_public_render_keeps_nginx_118_and_shared_rate_limit(self):
        config, _ = self.render_public()
        self.assertIn('proxy_cookie_path / "/; Secure; SameSite=Lax";', config)
        self.assertNotIn("proxy_cookie_flags", config)
        # 认证共享限速仍在，且只挂在三个认证入口上
        self.assertEqual(config.count("limit_req zone=lc_bore_auth"), 3)
        for route in ("/login", "/team/login"):
            line = next(line for line in config.splitlines()
                        if "location = " + route + " " in line)
            self.assertIn("limit_req zone=lc_bore_auth", line)
        auth = next(line for line in config.splitlines()
                    if "location = /web/session/authenticate" in line)
        self.assertNotIn("limit_req", auth)  # 限速在块内独立行，不在首行
        self.assertEqual(config.count("@RATE_LIMIT@"), 0)

    def test_public_render_excludes_high_risk_endpoints(self):
        config, _ = self.render_public()
        for path in P3_NOT_PUBLIC_PATHS + GENERIC_DENIED_PATHS:
            with self.subTest(path=path):
                self.assertIsNone(location_for(path, config), path)

    def test_netlify_render_keeps_p3_surface_and_no_store(self):
        module = load_render_module("render-netlify-gateway.py", "p3_netlify_render")
        config, _headers = module.render(
            tls_config=TLS_TEXT, output=pathlib.Path("/test/p3-netlify"),
            public_port=16444, listen_port=18445, database="TestDB",
            nginx_version="1.18.0", origin_host="origin-team.l-creation.club",
            canonical_host="team.l-creation.club",
            frontend_hosts=("team.l-creation.club", "rad-taffy-56e1ce.netlify.app"))
        for path in (P3_PAGE_PATHS + P3_API_PATHS + P3_CATALOG_PATHS
                     + (P3_PDF_PATH, P3_REDIRECT_PATH)):
            with self.subTest(path=path):
                self.assertIsNotNone(location_for(path, config), path)
        self.assertNotIn("lc_bore_", config)
        for directive in ('proxy_cache off;',
                          'add_header Cache-Control "private, no-store, max-age=0" always;',
                          'add_header Netlify-CDN-Cache-Control "no-store" always;'):
            self.assertIn(directive, config)
        for path in P3_NOT_PUBLIC_PATHS:
            self.assertIsNone(location_for(path, config), path)
        self.assertIn("location / { return 404; }", config)
        # 相对 303 在 Netlify 回源变体里同样保持"无 proxy_pass"
        redirect = location_text(P3_REDIRECT_PATH, config)
        self.assertIsNotNone(redirect)
        self.assertIn("return 303 %s$is_args$args;" % P3_REDIRECT_TARGET, redirect)
        self.assertNotIn("proxy_pass", redirect)


# ---------------------------------------------------------------------------
# 4. 真实 Nginx（需要 LC_P3_NGINX_BIN；没有则跳过）
# ---------------------------------------------------------------------------
NGINX_BIN = os.environ.get("LC_P3_NGINX_BIN", "").strip()
PUBLIC_HOST = "team.l-creation.club"


def _free_port():
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _wait_port(port, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _render_plain_http(upstream, public_port, workdir):
    """把同一份模板渲染成 HTTP 变体（不引 TLS，避免需要证书文件）。"""
    headers = HEADERS.replace("@DB_HEADER@",
                              "proxy_set_header X-Odoo-Database lc_p3_synth;")
    headers_path = workdir / "bore-proxy-headers.conf"
    headers_path.write_text(headers, encoding="utf-8")
    text = "\n".join(line for line in TEMPLATE.splitlines()
                     if not line.strip().startswith("#")) + "\n"
    replacements = {
        "@LISTEN_LINE@": "listen 127.0.0.1:%d;" % public_port,
        "@SSL_LINES@": "",
        "@REALIP_LINES@": "# synthetic: no PROXY protocol",
        "@COOKIE_FLAGS@": "",
        "@PUBLIC_PORT@": str(public_port),
        "@UPSTREAM@": upstream,
        "@RATE_LIMIT@": "",
        "include bore-proxy-headers.conf;": "include %s;" % headers_path.as_posix(),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    leftover = re.search(r"@[A-Z_]+@", text + headers)
    assert leftover is None, "未渲染的占位符：%s" % (leftover and leftover.group(0))
    return text


def _request_raw(port, method, path, host=PUBLIC_HOST, body=None, origin=None,
                 extra_headers=None):
    """发一条请求，返回 (status, headers_lowercase, body)；连接被 444 断开时 status=0。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host)
        if origin is not None:
            conn.putheader("Origin", origin)
        for name, value in (extra_headers or {}).items():
            conn.putheader(name, value)
        if body is not None:
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, headers, response.read()
    except (OSError, http.client.HTTPException):
        return 0, {}, b""
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _request(port, method, path, host=PUBLIC_HOST, body=None, origin=None):
    """发一条请求；连接被 444 断开时返回 (0, b'')。"""
    status, _headers, data = _request_raw(port, method, path, host=host,
                                          body=body, origin=origin)
    return status, data


def _recorder_handler(recorder):
    """构造记录转发头的 HTTP handler（GET/POST/HEAD/PUT/DELETE/PATCH 都记录）。"""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            recorder.record(self.command, self.path.split("?")[0], self.headers)
            body = b'{"synthetic":true,"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = do_HEAD = _handle
        do_PUT = do_DELETE = do_PATCH = _handle

        def log_message(self, *args):
            return

    return Handler


class _RecordingUpstream(object):
    """记录 nginx 实际发出的转发头，供"头是否丢失/是否被伪造值污染"的断言使用。

    字段与 ``scripts/verify-local-entry.sh`` 的内联记录器一致：多出
    ``xf_host`` / ``xf_port`` 两个 key，正是本轮"外部端口是否经 XFH 原样到达上游"
    与"伪造 X-Forwarded-Port 是否被清空"所必需。共享夹具
    ``tests/synthetic_upstream.py`` 不含这两个字段，且不在本任务写域。
    """

    HEADERS = (("host", "Host"), ("xff", "X-Forwarded-For"),
               ("x_real_ip", "X-Real-IP"), ("xf_proto", "X-Forwarded-Proto"),
               ("xf_host", "X-Forwarded-Host"), ("xf_port", "X-Forwarded-Port"),
               ("forwarded", "Forwarded"), ("x_odoo_database", "X-Odoo-Database"))

    def __init__(self, log_path):
        self.log_path = log_path
        self._lock = threading.Lock()

    def record(self, method, path, headers):
        entry = {"method": method, "path": path}
        for key, header in self.HEADERS:
            entry[key] = headers.get(header, "")
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


@unittest.skipUnless(NGINX_BIN and pathlib.Path(NGINX_BIN).exists(),
                     "设置 LC_P3_NGINX_BIN 指向 nginx 可执行文件才跑真实链路")
class P3RealNginxTest(unittest.TestCase):
    """真跑 nginx：放行的到达合成上游，拒绝的不到达上游（fail-closed）。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="lc-p3-gw-")
        work = pathlib.Path(cls._tmp.name)
        cls.work = work
        for name in ("body", "proxy", "fcgi", "uwsgi", "scgi", "logs"):
            (work / name).mkdir()
        cls.public_port = _free_port()
        cls.upstream_port = _free_port()
        while cls.upstream_port == cls.public_port:
            cls.upstream_port = _free_port()
        cls.upstream_log = work / "logs" / "upstream.jsonl"
        cls.upstream_log.write_text("", encoding="utf-8")
        cls.gateway = work / "gateway.conf"
        cls.gateway.write_text(
            _render_plain_http("http://127.0.0.1:%d" % cls.upstream_port,
                               cls.public_port, work), encoding="utf-8")
        cls.nginx_conf = work / "nginx.conf"
        cls.nginx_conf.write_text("\n".join([
            "worker_processes 1;",
            "pid %s;" % (work / "nginx.pid").as_posix(),
            "error_log %s warn;" % (work / "logs" / "error.log").as_posix(),
            "events { worker_connections 128; }",
            "http {",
            '    map $http_origin $p2_origin_ok { default 0; "" 1; "https://%s" 1; }' % PUBLIC_HOST,
            '    map "$request_method:$p2_origin_ok" $p2_reject_post { default 0; "POST:0" 1; }',
            "    access_log %s;" % (work / "logs" / "access.log").as_posix(),
            "    client_body_temp_path %s;" % (work / "body").as_posix(),
            "    proxy_temp_path %s;" % (work / "proxy").as_posix(),
            "    fastcgi_temp_path %s;" % (work / "fcgi").as_posix(),
            "    uwsgi_temp_path %s;" % (work / "uwsgi").as_posix(),
            "    scgi_temp_path %s;" % (work / "scgi").as_posix(),
            "    include %s;" % cls.gateway.as_posix(),
            "}",
            "",
        ]), encoding="utf-8")
        cls.upstream = None
        cls.nginx = None
        cls.server = None
        cls._start_upstream()
        try:
            check = subprocess.run(
                [NGINX_BIN, "-p", str(work), "-c", str(cls.nginx_conf), "-t"],
                capture_output=True, text=True, timeout=60)
            assert check.returncode == 0, "nginx -t 失败：%s" % (check.stderr or check.stdout)
            cls.nginx = subprocess.Popen(
                [NGINX_BIN, "-p", str(work), "-c", str(cls.nginx_conf),
                 "-g", "daemon off;"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert _wait_port(cls.public_port), "nginx 未在预期端口监听"
        except Exception:
            cls._stop_all()
            cls._tmp.cleanup()
            raise

    @classmethod
    def _start_upstream(cls):
        """进程内记录器：比共享夹具多记 XFH/XFPort，且不依赖外部脚本。"""
        recorder = _RecordingUpstream(cls.upstream_log)
        server = ThreadingHTTPServer(("127.0.0.1", cls.upstream_port),
                                     _recorder_handler(recorder))
        server.daemon_threads = True
        cls.server = server
        cls.upstream = threading.Thread(target=server.serve_forever, daemon=True)
        cls.upstream.start()
        assert _wait_port(cls.upstream_port), "合成上游未启动"

    @classmethod
    def _stop_all(cls):
        if cls.nginx is not None:
            try:
                cls.nginx.terminate()
                cls.nginx.wait(timeout=15)
            except Exception:
                try:
                    cls.nginx.kill()
                except Exception:
                    pass
            cls.nginx = None
        if cls.server is not None:
            try:
                cls.server.shutdown()
                cls.server.server_close()
            except Exception:
                pass
            cls.server = None
        cls.upstream = None

    @classmethod
    def tearDownClass(cls):
        cls._stop_all()
        try:
            cls._tmp.cleanup()
        except Exception:
            pass

    # -- 辅助 ---------------------------------------------------------
    def upstream_records(self):
        text = self.upstream_log.read_text(encoding="utf-8")
        records = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return records

    def reached(self, method, path):
        return any(record.get("method") == method and record.get("path") == path
                   for record in self.upstream_records())

    def assert_reached(self, method, path, host=PUBLIC_HOST, body=None):
        before = len(self.upstream_records())
        status, _data = _request(self.public_port, method, path, host=host, body=body)
        self.assertNotEqual(status, 0, "%s %s 连接被断开" % (method, path))
        after = self.upstream_records()
        self.assertGreater(len(after), before,
                           "%s %s 未到达上游（status=%s）" % (method, path, status))
        last = after[-1]
        self.assertEqual(last.get("method"), method, last)
        self.assertEqual(last.get("path"), path, last)
        return status, last

    def assert_blocked(self, method, path, host=PUBLIC_HOST, body=None, want=None):
        before = len(self.upstream_records())
        status, _data = _request(self.public_port, method, path, host=host, body=body)
        after = len(self.upstream_records())
        self.assertEqual(after, before,
                         "%s %s 被拒绝了却仍到达上游" % (method, path))
        if want is not None:
            self.assertEqual(status, want, "%s %s 期望 %s 实际 %s"
                             % (method, path, want, status))
        else:
            self.assertNotEqual(status, 0, "%s %s 应返回拒绝码而不是断开" % (method, path))
        return status

    # -- 断言 ---------------------------------------------------------
    def test_nginx_test_passes_on_rendered_template(self):
        check = subprocess.run(
            [NGINX_BIN, "-p", str(self.work), "-c", str(self.nginx_conf), "-t"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(check.returncode, 0, check.stderr or check.stdout)

    def test_p3_pages_reach_upstream(self):
        for path in P3_PAGE_PATHS:
            with self.subTest(path=path):
                self.assert_reached("GET", path)
        for path in P3_BAG_DETAIL_SAMPLES:
            with self.subTest(path=path):
                self.assert_reached("GET", path)

    def test_bag_detail_out_of_range_ids_are_404_without_upstream(self):
        """超长/非规范 bag_id 必须在网关就 404，且不进上游（DB 正整数 id 有界）。"""
        for path in ("/lab/bags/" + "9" * 20,      # 20 位，超 int8
                     "/lab/bags/" + "9" * 64,      # 超长数字
                     "/lab/bags/0123",             # 前导零，非规范 id
                     "/lab/bags/0",                # 非正整数
                     "/lab/bags/-1",
                     "/lab/bags/abc",
                     "/lab/bags/1/x"):
            with self.subTest(path=path):
                self.assert_blocked("GET", path, want=404)

    def test_p3_jsonrpc_post_reaches_upstream(self):
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {}}).encode("utf-8")
        for path in P3_API_PATHS:
            with self.subTest(path=path):
                self.assert_reached("POST", path, body=body)

    def test_pdf_post_reaches_upstream(self):
        body = b"csrf_token=x&kind=bag&ids=1"
        self.assert_reached("POST", P3_PDF_PATH, body=body)

    def test_catalog_post_reaches_upstream(self):
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {}}).encode("utf-8")
        for path in P3_CATALOG_PATHS:
            with self.subTest(path=path):
                self.assert_reached("POST", path, body=body)

    def test_legacy_scan_redirects_relatively_without_upstream(self):
        """旧 /lab/scan：303 + 相对 Location + 保留 query + 零上游。"""
        before = len(self.upstream_records())
        status, headers, _body = _request_raw(self.public_port, "GET",
                                              "/lab/scan?raw=ABC123")
        self.assertEqual(status, 303)
        location = headers.get("location", "")
        self.assertEqual(location, P3_REDIRECT_TARGET + "?raw=ABC123")
        # 必须是相对 Location：不得带 scheme/host（否则非标准端口下丢 origin）
        self.assertFalse(location.startswith("http"), location)
        self.assertNotIn("://", location)
        self.assertTrue(location.startswith("/"), location)
        self.assertEqual(len(self.upstream_records()), before, "303 不得触达上游")

        # 无 query 时不得凭空补 "?"
        status, headers, _body = _request_raw(self.public_port, "GET", "/lab/scan")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("location", ""), P3_REDIRECT_TARGET)
        self.assertEqual(len(self.upstream_records()), before)

        # HEAD 同样放行且保留 query
        status, headers, _body = _request_raw(self.public_port, "HEAD",
                                              "/lab/scan?scan=lab:3")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("location", ""),
                         P3_REDIRECT_TARGET + "?scan=lab:3")
        self.assertEqual(len(self.upstream_records()), before)

    def test_legacy_scan_illegal_methods_are_denied_without_upstream(self):
        """非 GET/HEAD 一律 403，且不触达上游（rewrite 阶段 if 先于 return）。"""
        before = len(self.upstream_records())
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            with self.subTest(method=method):
                status, headers, _body = _request_raw(
                    self.public_port, method, "/lab/scan", body=b"x=1")
                self.assertEqual(status, 403)
                self.assertNotIn("location", headers,
                                 "%s 被 303 了（方法限制写在了 limit_except 里？）" % method)
        self.assertEqual(len(self.upstream_records()), before, "被拒方法不得触达上游")

    def test_method_confusion_is_denied_without_upstream(self):
        for method, path in (("GET", P3_PDF_PATH),
                             ("POST", "/team/lab/bags"),
                             ("POST", "/lab/labels"),
                             ("POST", "/lab"),
                             ("GET", "/web/session/authenticate"),
                             ("GET", "/lab/api/inventory/bootstrap"),
                             ("PUT", "/lab/api/inventory/receipt"),
                             ("GET", "/lab/api/catalog/bind"),
                             ("GET", "/lab/api/catalog/create_material")):
            with self.subTest(method=method, path=path):
                self.assert_blocked(method, path, want=403)

    def test_high_risk_and_generic_paths_are_404_without_upstream(self):
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {}}).encode("utf-8")
        for method, path in (("POST", "/lab/api/inventory/adopt_stock"),
                             ("POST", "/lab/api/inventory/legacy_stock"),
                             ("POST", "/web/dataset/call_kw"),
                             ("POST", "/jsonrpc"),
                             ("POST", "/web/database/selector"),
                             ("GET", "/websocket"),
                             ("POST", "/lab/scan/submit"),
                             ("POST", "/lab/labels/download"),
                             ("GET", "/lab/scan/resolve"),
                             ("GET", "/lab/labels/plan")):
            with self.subTest(method=method, path=path):
                self.assert_blocked(method, path, want=404,
                                    body=body if method == "POST" else None)

    def test_cross_site_origin_post_is_forbidden_before_upstream(self):
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {}}).encode("utf-8")
        before = len(self.upstream_records())
        status, _data = _request(self.public_port, "POST",
                                 "/lab/api/inventory/bootstrap",
                                 body=body, origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(len(self.upstream_records()), before)
        # 同源 Origin 必须放行（证明不是一律 403）
        before = len(self.upstream_records())
        status, _data = _request(self.public_port, "POST",
                                 "/lab/api/inventory/bootstrap", body=body,
                                 origin="https://" + PUBLIC_HOST)
        self.assertNotEqual(status, 403)
        after = self.upstream_records()
        self.assertGreater(len(after), before)
        self.assertEqual(after[-1].get("method"), "POST")
        self.assertEqual(after[-1].get("path"), "/lab/api/inventory/bootstrap")

    def test_unknown_authority_is_dropped_before_upstream(self):
        # 正向对照必须走**真正的 proxy location**（有 proxy_pass），否则请求被
        # `return`/`redirect` 固定响应接走，"到达上游"的断言就失去意义。
        probe = "/team/lab/bags"
        probe_line = location_for(probe, ALLOW)
        self.assertIsNotNone(probe_line, probe)
        self.assertIn("proxy_pass @UPSTREAM@;", probe_line,
                      "正向对照路径必须是代理location，不能是 return/redirect 路径")
        self.assertNotIn("return ", probe_line)

        before = len(self.upstream_records())
        status, _data = _request(self.public_port, "GET", probe,
                                 host="evil.example")
        self.assertIn(status, (0, 400))
        self.assertEqual(len(self.upstream_records()), before,
                         "非法 Host 不得触达上游")

        # 带显式公开端口的 authority 必须被接受，且外部端口经 Host/XFH 原样到达上游
        authority = "%s:%d" % (PUBLIC_HOST, self.public_port)
        status, last = self.assert_reached("GET", probe, host=authority)
        self.assertEqual(last.get("host"), authority)
        self.assertEqual(last.get("xf_host"), authority)
        # 伪造/多余转发头必须被清空或重写（证明转发头链路没有丢）
        self.assertEqual(last.get("forwarded"), "")
        self.assertEqual(last.get("xf_port"), "")
        # 共享头文件的其余字段确实生效：证明确实 include 了 bore-proxy-headers.conf
        self.assertEqual(last.get("xff"), "127.0.0.1")
        self.assertEqual(last.get("x_real_ip"), "127.0.0.1")
        self.assertEqual(last.get("xf_proto"), "https")
        self.assertEqual(last.get("x_odoo_database"), "lc_p3_synth")

    def test_forwarding_headers_are_overwritten_not_passed_through(self):
        """带伪造转发头请求：上游只看得到被覆盖/清空后的值（源侧没有丢头）。"""
        authority = "%s:%d" % (PUBLIC_HOST, self.public_port)
        forged = {"X-Forwarded-For": "9.9.9.9",
                  "X-Real-IP": "9.9.9.9",
                  "X-Forwarded-Host": "evil.example:1234",
                  "X-Forwarded-Port": "1234",
                  "Forwarded": "for=9.9.9.9"}
        before = len(self.upstream_records())
        status, _headers, _body = _request_raw(self.public_port, "GET",
                                               "/team/lab/bags", host=authority,
                                               extra_headers=forged)
        self.assertNotEqual(status, 0)
        self.assertEqual(len(self.upstream_records()), before + 1)
        last = self.upstream_records()[-1]
        self.assertEqual(last.get("method"), "GET")
        self.assertEqual(last.get("path"), "/team/lab/bags")
        # 伪造值必须被覆盖/清空，且 Host/XFH 保留已校验的 authority（含端口）
        self.assertEqual(last.get("host"), authority)
        self.assertEqual(last.get("xf_host"), authority)
        self.assertEqual(last.get("xff"), "127.0.0.1")
        self.assertEqual(last.get("x_real_ip"), "127.0.0.1")
        self.assertEqual(last.get("forwarded"), "")
        self.assertEqual(last.get("xf_port"), "")
        # 伪造值不得以任何形式渗透（端口那一路由 xf_port=="" + xf_host==authority 覆盖）
        for value in ("9.9.9.9", "evil.example"):
            self.assertNotIn(value, json.dumps(last, ensure_ascii=False),
                             "伪造转发头值渗透到上游：%s" % value)


if __name__ == "__main__":
    unittest.main()
