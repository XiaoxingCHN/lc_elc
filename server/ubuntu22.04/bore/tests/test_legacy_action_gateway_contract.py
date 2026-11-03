#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旧菜单动作 GET 兼容层的公网网关契约（13 条固定 xmlid）。

分三层，互不替代：

1. LegacyActionAllowlistTextTest
   纯文本断言：模板里恰好登记 13 条 location = /odoo/action-<xmlid>，
   方法只有 GET/HEAD，代理头走共享 include，location 内无 add_header；
   且没有 /odoo 前缀/正则 location、没有 /odoo/action-* 通配。

2. LegacyActionSourceSyncTest
   与 lab_team_web/controllers/legacy_entries.py 的实际
   @http.route('/odoo/action-<xmlid>') 交叉核对：网关放行的动作集合必须
   恰好等于应用层已迁移的那 13 条；应用层新增/删除动作而网关没跟上时这里失败。
   同时校验每个 303 目标页本身也在白名单里（否则跳过去先被网关 404）。

3. LegacyActionRealNginxTest
   只有提供 LC_P3_NGINX_BIN 才执行：同一份模板渲染成 HTTP 变体，真跑
   nginx -t + nginx + 合成上游，逐条验证「放行的到达上游 / 拒绝的不到达上游」。

设计红线：
* 只放行字面量路径：location = 精确匹配，不用 ~ / ^~ / 前缀。
* 未迁移的 xmlid（request_log / action_lab_move / catalog category / import_run）
  与任意未知 /odoo/action-* 一律 404，不回退旧网页、不转发通用 /odoo。
* 代理层不判断角色：鉴权与 303 在应用层（legacy_entries.py）。
* 不得引入 add_header（会丢弃 server 级继承的 CSP / nosniff）。
"""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "nginx" / "bore-public-allowlist.conf.template").read_text(encoding="utf-8")
ALLOW = TEMPLATE.replace("@PUBLIC_PORT@", "9500")
ODOO_ADDONS = ROOT.parent / "odoo_addons"
LEGACY_CONTROLLER = ODOO_ADDONS / "lab_team_web" / "controllers" / "legacy_entries.py"
TLS_TEXT = "ssl_certificate /test/site.crt;\nssl_certificate_key /test/site.key;"

#: 迁移类入口（与 LEGACY_ACTIONS 一一对应）。刻意不含 request_log /
#: action_lab_move / catalog category / import_run —— 这些仍保留原生后台入口。
LEGACY_ACTION_XMLIDS = (
    "lab_workflow.action_lab_scan_console",
    "lab_workflow.action_lab_bag",
    "lab_workflow.action_lab_issue_line",
    "lab_workflow.action_lab_return_wizard",
    "lab_workflow.action_lab_label_open",
    "lab_workflow.action_lab_location",
    "lab_workflow.action_lab_operation",
    "lab_catalog.action_lab_unified_catalog_client",
    "lab_catalog.view_lab_catalog_item_action",
    "lab_catalog.view_lab_catalog_binding_action",
    "lab_inventory.action_lab_product",
    "lab_inventory.action_lab_location",
    "lab_inventory.action_lab_mapping",
)
LEGACY_ACTION_PATHS = tuple("/odoo/action-" + xmlid for xmlid in LEGACY_ACTION_XMLIDS)

#: 必须被网关拒绝（404，且不进上游）：未迁移动作、通用 Odoo 入口、伪造形态。
LEGACY_DENIED_PATHS = (
    "/odoo",
    "/odoo/",
    "/odoo/action-",
    "/odoo/action-lab_workflow.action_lab_request_log",
    "/odoo/action-lab_inventory.action_lab_move",
    "/odoo/action-lab_catalog.view_lab_catalog_category_action",
    "/odoo/action-lab_catalog.view_lab_catalog_import_run_action",
    "/odoo/action-lab_workflow.action_lab_bag/1",
    "/odoo/action-lab_workflow.action_lab_bag-extra",
    "/odoo/action-LAB_WORKFLOW.ACTION_LAB_BAG",
    "/odoo/lab.issue.line",
    "/odoo/lab.bag/1",
    "/web/dataset/call_kw",
    "/jsonrpc",
    "/web/login",
    "/website",
    "/report",
    "/web/image",
    "/websocket",
    "/longpolling",
)


def _load(filename, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 复用 P3 契约测试的纯文本辅助（同一份模板、同一套"完整路径"匹配语义）。
P3 = _load("test_p3_gateway_contract.py", "lc_p3_contract_for_legacy")


def location_lines(text=None):
    return P3.location_lines(ALLOW if text is None else text)


def location_for(path, text=None):
    return P3.location_for(path, ALLOW if text is None else text)


def location_text(path, text=None):
    return P3.location_text(path, ALLOW if text is None else text)


def prefix_locations(text=None):
    return P3.prefix_locations(ALLOW if text is None else text)


def controller_text():
    if not LEGACY_CONTROLLER.is_file():
        return None
    return LEGACY_CONTROLLER.read_text(encoding="utf-8")


def controller_route_paths():
    """legacy_entries.py 里所有 @http.route 的路径字面量（按出现顺序去重）。"""
    text = controller_text()
    if text is None:
        return None
    seen = []
    for path in re.findall(r"@http\.route\('([^']+)'", text):
        if path not in seen:
            seen.append(path)
    return seen


def controller_route_options(path):
    text = controller_text()
    index = text.find("@http.route('%s'" % path)
    if index < 0:
        return None
    # 装饰器参数里没有括号，所以第一个 ")" 就是收尾；不要用 ")\n"
    # （仓库里是 CRLF，按行尾找会落空并退化成截断窗口）。
    end = text.find(")", index)
    chunk = text[index:end + 1] if end > 0 else text[index:index + 800]
    return " ".join(chunk.split())


def controller_targets():
    """TARGET_* 常量（303 目标页），用于"目标页必须也在白名单"的跨层断言。"""
    text = controller_text()
    if text is None:
        return None
    return sorted(set(re.findall(r"TARGET_[A-Z_]+ = '(/team[^']*)'", text)))


class LegacyActionAllowlistTextTest(unittest.TestCase):
    def test_exactly_thirteen_exact_literal_locations(self):
        found = [line for line in location_lines() if "/odoo" in line]
        self.assertEqual(len(found), len(LEGACY_ACTION_PATHS), found)
        registered = sorted(re.findall(r"location = (/odoo/action-\S+) ", ALLOW))
        self.assertEqual(registered, sorted(LEGACY_ACTION_PATHS))
        for path in LEGACY_ACTION_PATHS:
            with self.subTest(path=path):
                line = location_for(path)
                self.assertIsNotNone(line, "缺少旧动作 location：%s" % path)
                self.assertTrue(line.startswith("location = " + path + " "), line)
                self.assertIn("limit_except GET HEAD", line)
                self.assertIn("include bore-proxy-headers.conf;", line)
                self.assertIn("proxy_pass @UPSTREAM@;", line)
                self.assertNotIn("POST", line)
                self.assertNotIn("add_header", line)
                self.assertNotIn("proxy_set_header", line)
                self.assertNotIn("return ", line)

    def test_no_odoo_wildcard_or_prefix_location(self):
        for line in location_lines():
            if line.startswith("location = "):
                self.assertNotIn(".*", line, line)
                self.assertNotIn("~", line.split("proxy_pass")[0], line)
            else:
                self.assertNotIn("/odoo", line,
                                 "不得用前缀/正则 location 包住 /odoo：%s" % line)
        for banned in ("location ^~ /odoo", "location /odoo", "location ~ /odoo",
                       "location ~* /odoo"):
            self.assertNotIn(banned, ALLOW)

    def test_unknown_and_non_migrated_paths_are_not_registered(self):
        for path in LEGACY_DENIED_PATHS:
            with self.subTest(path=path):
                self.assertIsNone(location_for(path),
                                  "不应公开的路径出现在白名单：%s" % path)

    def test_default_deny_still_last_location(self):
        locations = location_lines()
        self.assertEqual(locations[-1], "location / { return 404; }", locations[-1])

    def test_security_headers_not_shadowed(self):
        lines = ALLOW.splitlines()
        first = next(index for index, line in enumerate(lines)
                     if line.strip().startswith("location "))
        inside = [line.strip() for line in lines[first:]
                  if line.strip().startswith("add_header")]
        self.assertEqual(inside, [])

    def test_legacy_scan_redirect_still_relative_and_upstream_free(self):
        text = location_text("/lab/scan")
        self.assertIsNotNone(text)
        self.assertIn("return 303 /team/scan$is_args$args;", text)
        self.assertIn("absolute_redirect off;", text)
        self.assertNotIn("proxy_pass", text)


class LegacyActionSourceSyncTest(unittest.TestCase):
    def test_gateway_matches_migrated_controller_routes(self):
        routes = controller_route_paths()
        if routes is None:
            self.skipTest("找不到 lab_team_web/controllers/legacy_entries.py")
        self.assertEqual(sorted(routes), sorted(LEGACY_ACTION_PATHS))
        self.assertEqual(len(routes), len(LEGACY_ACTION_PATHS))
        # 应用层不得注册 /odoo 通配或其它非 /odoo/action-<xmlid> 的入口。
        for path in routes:
            self.assertTrue(path.startswith("/odoo/action-"), path)
            self.assertNotIn("<", path)

    def test_controller_routes_are_public_http(self):
        routes = controller_route_paths()
        if routes is None:
            self.skipTest("找不到 legacy_entries.py")
        for path in routes:
            with self.subTest(path=path):
                options = controller_route_options(path)
                self.assertIsNotNone(options, path)
                self.assertIn("auth='public'", options)
                self.assertIn("type='http'", options)
                self.assertIn("website=False", options)
                self.assertIn("sitemap=False", options)

    def test_controller_routes_declare_get_and_guard_other_methods(self):
        """应用层也必须拒绝非 GET（纵深防御，不只靠网关 limit_except）。

        legacy_entries.py 每条旧入口是一条路由、方法集合显式列出
        ["GET", "POST", "PUT", "PATCH", "DELETE"]：GET/HEAD 走 303 跳到自有页面，
        其余方法落到同一个 handler，由 _legacy_redirect 里的
        request.httprequest.method 判断返回 405 + Allow: GET, HEAD（不重放写请求）。

        为什么不是两条路由（先 methods=['GET']，再写方法一条）：同一路径声明两条
       规则时，非 GET 请求会先命中 GET 规则的路径、方法不匹配，然后落回 Odoo 核心的
        /odoo/<path> 兜底（csrf=True），实测返回 400 而不是我们想要的 405；
        合并成一条规则后 handler 才能真正拿到请求并返回 405。
        """
        routes = controller_route_paths()
        if routes is None:
            self.skipTest("找不到 legacy_entries.py")
        missing = []
        for path in routes:
            options = controller_route_options(path) or ""
            if "methods=['GET'" not in options:
                missing.append(path)
            elif "csrf=False" not in options:
                missing.append(path)
        self.assertEqual(missing, [],
                         "这些旧动作路由未声明 GET 且 csrf=False（写方法要进 handler 才能 405）：%s"
                         % missing)

    def test_every_redirect_target_is_reachable_through_gateway(self):
        """旧链接 303 到 /team/... 之后，浏览器还要再过一次网关。

        目标页不在白名单里 = 旧链接"能跳但跳过去 404"，属于本层最容易漏的接缝。
        """
        targets = controller_targets()
        if targets is None:
            self.skipTest("找不到 legacy_entries.py")
        self.assertTrue(targets)
        # prefix_locations() 里既有 location ~ "正则" 也有无引号的
        # "location / { return 404; }" / ^~ 行，取正则前必须先确认有引号。
        regexes = [re.compile(line.split('"')[1]) for line in prefix_locations()
                   if line.startswith("location ~ ") and '"' in line]
        for target in targets:
            with self.subTest(target=target):
                if location_for(target) is not None:
                    continue
                self.assertTrue(any(pattern.match(target) for pattern in regexes),
                                "303 目标页不在网关白名单：%s" % target)


class LegacyActionRenderTest(unittest.TestCase):
    def test_public_render_keeps_every_legacy_action(self):
        module = P3.load_render_module("render-public-gateway.py", "legacy_public_render")
        config, _headers = module.render(TLS_TEXT, pathlib.Path("/test/legacy-public"),
                                         16443, 18443, "TestDB", "1.18.0")
        for path in LEGACY_ACTION_PATHS:
            with self.subTest(path=path):
                line = location_for(path, config)
                self.assertIsNotNone(line, "渲染后丢失 location：%s" % path)
                self.assertIn("limit_except GET HEAD", line)
                self.assertIn("proxy_pass http://127.0.0.1:8069;", line)
        self.assertIn("location / { return 404; }", config)
        self.assertIsNone(re.search(r"@[A-Z_]+@", config))
        for path in LEGACY_DENIED_PATHS:
            with self.subTest(path=path):
                self.assertIsNone(location_for(path, config), path)

    def test_netlify_render_keeps_every_legacy_action_and_no_store(self):
        module = P3.load_render_module("render-netlify-gateway.py", "legacy_netlify_render")
        config, _headers = module.render(
            TLS_TEXT, pathlib.Path("/test/legacy-netlify"), 16444, 18445,
            "TestDB", "1.18.0", "origin-team.l-creation.club", "team.l-creation.club",
            ("team.l-creation.club", "rad-taffy-56e1ce.netlify.app"))
        for path in LEGACY_ACTION_PATHS:
            with self.subTest(path=path):
                self.assertIsNotNone(location_for(path, config), path)
        self.assertIn('add_header Cache-Control "private, no-store, max-age=0" always;', config)
        self.assertIn("location / { return 404; }", config)
        for path in LEGACY_DENIED_PATHS:
            with self.subTest(path=path):
                self.assertIsNone(location_for(path, config), path)


NGINX_BIN = P3.NGINX_BIN
PUBLIC_HOST = P3.PUBLIC_HOST


@unittest.skipUnless(NGINX_BIN and pathlib.Path(NGINX_BIN).exists(),
                     "设置 LC_P3_NGINX_BIN 指向 nginx 可执行文件才跑真实链路")
class LegacyActionRealNginxTest(P3.P3RealNginxTest):
    """复用 P3 的真实 Nginx 夹具（同一模板、同一合成上游、同一转发头记录器）。

    只覆盖旧动作矩阵，不重复跑 P3 自己的用例（见文件末尾把继承来的 test_* 置 None）。
    """

    def test_legacy_action_get_and_head_reach_upstream(self):
        for path in LEGACY_ACTION_PATHS:
            with self.subTest(method="GET", path=path):
                self.assert_reached("GET", path)
            with self.subTest(method="HEAD", path=path):
                self.assert_reached("HEAD", path)

    def test_forwarding_headers_still_overwritten_on_legacy_action(self):
        _status, record = self.assert_reached("GET", LEGACY_ACTION_PATHS[0])
        self.assertEqual(record.get("xf_host"), PUBLIC_HOST)
        self.assertEqual(record.get("xff"), "127.0.0.1")
        self.assertEqual(record.get("forwarded"), "")
        self.assertEqual(record.get("xf_port"), "")
        self.assertEqual(record.get("x_odoo_database"), "lc_p3_synth")

    def test_legacy_action_post_is_denied_without_upstream(self):
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {}}).encode("utf-8")
        for path in LEGACY_ACTION_PATHS:
            with self.subTest(path=path):
                self.assert_blocked("POST", path, body=body, want=403)

    def test_other_methods_are_denied_without_upstream(self):
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method=method):
                self.assert_blocked(method, LEGACY_ACTION_PATHS[0], want=403)

    def test_unknown_and_non_migrated_paths_are_404_without_upstream(self):
        for path in LEGACY_DENIED_PATHS:
            with self.subTest(path=path):
                self.assert_blocked("GET", path, want=404)

    def test_legacy_scan_redirect_unaffected(self):
        status, headers, _body = P3._request_raw(self.public_port, "GET",
                                                 "/lab/scan?raw=LABB%3A1")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("location"), "/team/scan?raw=LABB%3A1")
        self.assert_blocked("POST", "/lab/scan", want=403)

    def test_p3_pages_still_reach_upstream(self):
        for path in ("/team/scan", "/team/lab/receipts", "/team/lab/bags/42"):
            with self.subTest(path=path):
                self.assert_reached("GET", path)


# 只保留本文件自己的用例：把从 P3RealNginxTest 继承来的 test_* 遮蔽为不可调用。
for _inherited in [name for name in dir(P3.P3RealNginxTest) if name.startswith("test_")]:
    setattr(LegacyActionRealNginxTest, _inherited, None)


if __name__ == "__main__":
    unittest.main()
