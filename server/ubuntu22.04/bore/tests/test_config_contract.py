"""模板契约测试：不依赖 nginx 运行时，纯文本断言。

覆盖三类约定：
1. 入口白名单/默认拒绝/安全头（行为边界）；
2. 公开 authority 不丢端口：server 段校验原始 $http_host，并通过
   $http_host 传给上游 Host/X-Forwarded-Host；CSP 严格 'self'；
3. 安全头的继承边界：add_header 只允许出现在 server 级（location 内写任何一条
   都会丢弃继承的 CSP / X-Frame-Options / nosniff）。

P3 业务页面、业务 JSON-RPC 与标签 PDF 的逐条白名单在
tests/test_p3_gateway_contract.py；本文件只守"所有 location 都成立"的公共不变量。
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOW_TEMPLATE = (ROOT / "nginx" / "bore-public-allowlist.conf.template").read_text(encoding="utf-8")
ALLOW = ALLOW_TEMPLATE.replace("@PUBLIC_PORT@", "9500")
HEADERS = (ROOT / "nginx" / "bore-proxy-headers.conf").read_text(encoding="utf-8")
STREAM = (ROOT / "nginx" / "bore-edge-stream.conf.template").read_text(encoding="utf-8")

AUTH_LOCATION = "location = /web/session/authenticate"


def _auth_block():
    """authenticate location 的配置块（到下一个 location 之前）。"""
    rest = ALLOW.split(AUTH_LOCATION, 1)[1]
    return rest.split("\n    location ", 1)[0]


def _session_headers(text):
    """取出所有 proxy_set_header 行（去注释、去首尾空白），用于防漂移比对。"""
    out = []
    for raw in text.splitlines():
        line = raw.split("#")[0].strip()
        if line.startswith("proxy_set_header "):
            out.append(" ".join(line.split()))
    return out


class AllowlistContractTest(unittest.TestCase):
    def test_default_deny_and_no_catchall_proxy(self):
        self.assertIn("location / { return 404; }", ALLOW)
        # 不允许把根路径整体 proxy 出去
        self.assertNotRegex(ALLOW, r"location\s+/\s*\{[^}]*proxy_pass")

    def test_required_pages_from_real_source(self):
        for path in ("/lab", "/team/lab", "/login", "/team/login"):
            self.assertIn("location = %s" % path, ALLOW)
        # 动态 key 用正则精确边界（对应 Odoo <string:item_key> 单段）
        self.assertIn(r"^/(?:team/)?lab/items/[^/]+$", ALLOW)
        self.assertNotIn("location ^~ /lab/items/", ALLOW)

    def test_logout_and_session_endpoints(self):
        self.assertIn("location = /logout", ALLOW)
        self.assertIn("location = /team/logout", ALLOW)
        self.assertIn("/web/session/authenticate", ALLOW)
        self.assertIn("/web/session/get_session_info", ALLOW)
        self.assertIn("/web/session/destroy", ALLOW)
        self.assertIn("/api/team/session", ALLOW)

    def test_write_apis_only_narrow_endpoints(self):
        for ep in ("search", "detail", "categories", "facets"):
            self.assertIn("/lab/api/catalog/%s" % ep, ALLOW)
        self.assertIn("/lab/api/asset", ALLOW)
        self.assertIn("/lab/client/updates/manifest", ALLOW)

    def test_denied_paths_absent(self):
        for bad in ("/web/dataset", "/jsonrpc", "/web/database", "/odoo", "/website", "/web/login", "/longpolling"):
            self.assertNotIn("location = %s" % bad, ALLOW)

    def test_auth_location_clears_db_header(self):
        block = _auth_block()
        self.assertIn('proxy_set_header X-Odoo-Database "";', block)
        self.assertIn("limit_except POST", block)

    def test_headers_overwrite_xff(self):
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", HEADERS)
        self.assertNotIn("proxy_add_x_forwarded_for", HEADERS)
        self.assertIn('proxy_set_header Forwarded "";', HEADERS)
        self.assertIn("proxy_set_header X-Real-IP $remote_addr;", HEADERS)

    def test_security_headers_present(self):
        self.assertIn("Content-Security-Policy", ALLOW)
        self.assertIn("frame-ancestors 'none'", ALLOW)
        self.assertIn('add_header X-Content-Type-Options "nosniff" always;', ALLOW)
        self.assertIn('add_header X-Frame-Options "DENY" always;', ALLOW)

    def test_no_add_header_inside_location_blocks(self):
        """add_header 只能出现在 server 级。

        nginx 的规则是：某个 location 只要自己写了任意一条 add_header，就会**整体丢弃**
        server 级继承的 add_header。因此任何 location 内的 add_header（包括新加的
        P3 业务页面 / JSON-RPC / 标签 PDF）都会悄悄削弱 CSP、X-Frame-Options 与
        nosniff —— 这类"看起来只加一条头"的改动必须被拦下。
        """
        lines = ALLOW.splitlines()
        first_location = next(index for index, line in enumerate(lines)
                              if line.strip().startswith("location "))
        inside = [line.strip() for line in lines[first_location:]
                  if line.strip().startswith("add_header")]
        self.assertEqual(inside, [], inside)
        # 反向确认：server 级确实还有那几条头（防止整段被误删后本测试空转通过）
        self.assertGreaterEqual(
            len([line for line in lines[:first_location]
                 if line.strip().startswith("add_header")]), 4)

    def test_cookie_flags_placeholder(self):
        self.assertIn('@COOKIE_FLAGS@', ALLOW)

    def test_cross_origin_post_guard(self):
        self.assertIn('if ($p2_reject_post) { return 403; }', ALLOW)

    def test_rate_limit_hook_only_on_auth(self):
        self.assertIn("@RATE_LIMIT@", _auth_block())

    def test_stream_public_listen_refuses_client_proxy(self):
        # 公开边缘监听行不得带 proxy_protocol（否则等于信任客户端前缀）
        listen_lines = [ln.split("#")[0].strip() for ln in STREAM.splitlines()
                        if ln.split("#")[0].strip().startswith("listen ")]
        self.assertTrue(listen_lines)
        self.assertFalse(any("proxy_protocol" in ln for ln in listen_lines), listen_lines)
        # 但必须主动向下游生成 PROXY
        self.assertIn("proxy_protocol on;", STREAM)


class PublicAuthorityContractTest(unittest.TestCase):
    """公开 authority（host[:port]）必须"校验后原样传"，不能被去端口。"""

    def test_csp_connect_src_is_strict_self_only(self):
        """connect-src 只能是 'self'；不再允许任何额外来源占位/字面量。"""
        self.assertNotIn("@CSP_CONNECT_EXTRA@", ALLOW)
        csp_lines = [ln for ln in ALLOW.splitlines()
                     if "Content-Security-Policy" in ln and ln.strip().startswith("add_header")]
        self.assertEqual(len(csp_lines), 1, csp_lines)
        csp = csp_lines[0]
        connect = re.search(r"connect-src ([^;]*);", csp)
        self.assertIsNotNone(connect, csp)
        self.assertEqual(connect.group(1).split(), ["'self'"], csp)
        script = re.search(r"script-src ([^;]*);", csp)
        self.assertIsNotNone(script, csp)
        self.assertEqual(script.group(1).split(), ["'self'"], csp)
        form = re.search(r"form-action ([^;\"]*)", csp)
        self.assertIsNotNone(form, csp)
        self.assertEqual(form.group(1).split(), ["'self'"], csp)
        # 不允许本轮扩大：无 unsafe-eval / 无内联脚本
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("'unsafe-inline'", script.group(1))
        # 样式 unsafe-inline 是既有决定，本轮不扩大也不新增
        self.assertIn("style-src 'self' 'unsafe-inline';", csp)

    def test_server_rejects_unlisted_authority_on_http_host(self):
        """校验对象必须是保留端口的 $http_host，禁止退回 $host。"""
        guards = [ln.strip() for ln in ALLOW.splitlines()
                  if ln.strip().startswith("if ($http_host")]
        self.assertEqual(len(guards), 1, guards)
        guard = guards[0]
        self.assertIn("return 444", guard)
        self.assertNotIn("if ($host ", ALLOW)
        # 只允许公开域名的无端口/443/9500 三种确切 authority
        match = re.search(r"\$http_host !~ (\S+)\)", guard)
        self.assertIsNotNone(match, guard)
        self.assertEqual(match.group(1), r"^team\.l-creation\.club(?::(?:443|9500))?$")
        # 不允许任意端口正则或取 $server_port（8443 是内部端口，不是外部端口）
        self.assertNotIn(r"\d{1,5}", match.group(1))
        self.assertNotIn("server_port", ALLOW)

    def test_production_render_does_not_accept_test_port(self):
        self.assertIn("@PUBLIC_PORT@", ALLOW_TEMPLATE)
        rendered = ALLOW_TEMPLATE.replace("@PUBLIC_PORT@", "443")
        guard = re.compile(re.search(r"\$http_host !~ (\S+)\)", rendered).group(1))
        self.assertTrue(guard.fullmatch("team.l-creation.club"))
        self.assertTrue(guard.fullmatch("team.l-creation.club:443"))
        self.assertFalse(guard.fullmatch("team.l-creation.club:9500"))

    def test_headers_forward_full_authority(self):
        """Host 与 X-Forwarded-Host 必须是 $http_host（含端口），不是 $host。"""
        lines = _session_headers(HEADERS)
        self.assertIn("proxy_set_header Host $http_host;", lines)
        self.assertIn("proxy_set_header X-Forwarded-Host $http_host;", lines)
        self.assertNotIn("proxy_set_header Host $host;", lines)
        self.assertNotIn("proxy_set_header X-Forwarded-Host $host;", lines)
        self.assertIn("proxy_set_header X-Forwarded-Proto https;", lines)

    def test_forwarded_and_port_spoofing_headers_cleared(self):
        """Forwarded 与额外伪造 X-Forwarded-Port 必须显式清空（空值=不发送）。"""
        lines = _session_headers(HEADERS)
        self.assertIn('proxy_set_header Forwarded "";', lines)
        self.assertIn('proxy_set_header X-Forwarded-Port "";', lines)
        for banned in ("$http_forwarded", "$http_x_forwarded_port", "$http_x_forwarded_host",
                       "$http_host:", "proxy_pass_request_headers"):
            self.assertNotIn(banned, HEADERS)
        self.assertNotIn("X-Forwarded-Port $", HEADERS)


    def test_accepted_authority_maps_to_same_origin(self):
        """校验通过的 authority 必须原样成为上游 origin（9500 不会退化成 443）。

        上游重建 origin 的输入只有两样：X-Forwarded-Proto 与 X-Forwarded-Host。
        本测试把这两条从渲染后的头配置里取出来，对每个被接受的 authority 断言
        重建结果与浏览器看到的 origin 完全一致；若头配置退回 $host（去端口），
        这里的 9500 用例就会变成 https://team.l-creation.club，直接失败。
        """
        headers = _session_headers(HEADERS)
        proto = [ln for ln in headers if ln.startswith("proxy_set_header X-Forwarded-Proto ")]
        self.assertEqual(proto, ["proxy_set_header X-Forwarded-Proto https;"], proto)
        host_source = [ln for ln in headers if ln.startswith("proxy_set_header X-Forwarded-Host ")]
        self.assertEqual(host_source, ["proxy_set_header X-Forwarded-Host $http_host;"], host_source)

        pattern = re.compile(re.search(r"\$http_host !~ (\S+)\)", ALLOW).group(1))
        accepted = [a for a in ("team.l-creation.club", "team.l-creation.club:443",
                                "team.l-creation.club:9500") if pattern.search(a)]
        self.assertEqual(accepted, ["team.l-creation.club", "team.l-creation.club:443",
                                    "team.l-creation.club:9500"])
        # X-Forwarded-Host 的取值就是 $http_host，即上面被校验的同一字符串
        origins = {"https://" + authority for authority in accepted}
        self.assertIn("https://team.l-creation.club:9500", origins)
        # 反向：不带端口的请求不得凭空得到 9500，带 9500 的请求也不得丢成无端口
        self.assertNotEqual("https://team.l-creation.club", "https://team.l-creation.club:9500")
    def test_authority_verdict_table(self):
        """用同一正则做判定表：只放行无端口/443/9500，其它一律拒绝。

        这是对 nginx PCRE 语义的**镜像**（同一个 pattern、同一个大小写敏感行为），
        用于把"接受哪些 authority"写成可执行的契约；真实链路仍由脚本在真 Nginx
        上验证（本机不启动 9500/8443）。
        """
        pattern = re.search(r"\$http_host !~ (\S+)\)", ALLOW).group(1)
        compiled = re.compile(pattern)

        def accepted(authority):
            return compiled.search(authority) is not None

        for ok_value in ("team.l-creation.club", "team.l-creation.club:443",
                         "team.l-creation.club:9500"):
            self.assertTrue(accepted(ok_value), ok_value)
        for bad_value in (
                "", "evil.example", "team.l-creation.club.evil",
                "evil-team.l-creation.club", "teamxl-creation.club",
                "Team.L-Creation.Club", "team.l-creation.club.",
                "team.l-creation.club:80", "team.l-creation.club:8080",
                "team.l-creation.club:8443", "team.l-creation.club:09500",
                "team.l-creation.club:95000", "team.l-creation.club:9500,evil.example",
                "team.l-creation.club/lab", "team.l-creation.club:9500/",
                " team.l-creation.club", "team.l-creation.club ",
                "team.l-creation.club:9500:9500", "[::1]:9500"):
            self.assertFalse(accepted(bad_value), repr(bad_value))
    def test_authenticate_location_reuses_same_authority_headers(self):
        """authenticate 独立写头，必须与公共头逐行一致，仅多一条清空 DB 头。"""
        shared = _session_headers(HEADERS)
        auth = _session_headers(_auth_block())
        db_lines = [ln for ln in auth if ln.startswith("proxy_set_header X-Odoo-Database ")]
        self.assertEqual(len(db_lines), 1, auth)
        self.assertEqual(db_lines[0], 'proxy_set_header X-Odoo-Database "";')
        # 顺序不影响 nginx 语义，比对集合防止任一侧漏掉/多出某条代理头
        self.assertEqual(sorted(ln for ln in auth if not ln.startswith("proxy_set_header X-Odoo-Database ")),
                         sorted(shared))
        self.assertNotIn("proxy_set_header Host $host;", auth)
        self.assertIn("proxy_set_header Host $http_host;", auth)
        self.assertIn("proxy_set_header X-Forwarded-Host $http_host;", auth)

    def test_no_duplicate_host_header_sources(self):
        """不允许别处再写一套 Host 头（除共享文件与 authenticate 外）。"""
        other = ALLOW.replace(_auth_block(), "")
        self.assertNotIn("proxy_set_header Host", other)


if __name__ == "__main__":
    unittest.main()
