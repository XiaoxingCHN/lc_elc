# -*- coding: utf-8 -*-
"""入口/退出契约的静态回归测试（不需要 Odoo 运行时）。

为什么做静态断言：本轮缺陷不是"函数算错"，而是**接线选错了实现**——
  * 前端曾用 fetch 代提交退出表单（吞掉 303/网络错误并硬编码跳转目标）；
  * 退出/登录链接曾写成不尊重基址的地址；
  * 代理层用 $host 传 authority，非标准端口（9500）被去掉。

这些都属于"源码里某一行的形状"，用运行时 HTTP 很难在无 Odoo 的机器上覆盖，
但用文本断言可以精确锁定，且能在 python -m unittest discover 下真实执行。

对应验收：
  * 退出必须是原生 POST 表单 + CSRF 隐藏域（浏览器自己跟随 303）；
  * lc_logout_url / lc_login_action 必须尊重 current_base() 且是站内相对路径；
  * 模块版本与页面展示版本一致（19.0.1.1.0）。
"""
import ast
import importlib.util
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.dirname(_HERE)


def _read(*parts):
    with open(os.path.join(_MOD, *parts), encoding="utf-8") as handle:
        return handle.read()


TEAM_JS = _read("static", "src", "js", "team.js")
PAGES_XML = _read("views", "pages.xml")
COMMON_PY = _read("controllers", "common.py")
PAGES_PY = _read("controllers", "pages.py")
MANIFEST_PY = _read("__manifest__.py")


def _manifest():
    for node in ast.walk(ast.parse(MANIFEST_PY)):
        if isinstance(node, ast.Dict):
            try:
                return ast.literal_eval(node)
            except Exception:
                continue
    raise AssertionError("manifest dict not found")


class LogoutIsNativeFormTest(unittest.TestCase):
    """退出走原生表单提交，不再有 JS 代提交。"""

    def test_js_has_no_logout_fetch_interception(self):
        self.assertNotIn("initLogout", TEAM_JS)
        self.assertNotIn("lc-logout-form", TEAM_JS)
        # JS 不得替退出构造请求体，也不得写死跳转目标
        self.assertNotIn("FormData", TEAM_JS)
        self.assertNotIn("window.location.href =", TEAM_JS)

    def test_js_has_no_string_eval(self):
        # 严格 CSP（script-src self）下不允许内联脚本/字符串求值
        self.assertNotIn("eval(", TEAM_JS)
        self.assertNotIn("new Function(", TEAM_JS)

    def test_logout_form_is_native_post_with_csrf(self):
        form = re.search(r"<form[^>]*class=\"lc-logout-form\"[^>]*>", PAGES_XML)
        self.assertIsNotNone(form, "缺少退出表单")
        tag = form.group(0)
        self.assertIn('method="post"', tag.lower())
        self.assertIn('t-att-action="lc_logout_url"', tag)
        # action 不得写死某个具体基址或绝对 URL
        self.assertNotIn('action="/team/logout"', tag)
        self.assertNotIn('action="/logout"', tag)
        self.assertNotIn("http", tag.lower())
        self.assertIn('name="csrf_token"', PAGES_XML)
        self.assertIn('t-att-value="lc_csrf_token"', PAGES_XML)


class BaseAwareRelativeUrlTest(unittest.TestCase):
    """lc_logout_url / lc_login_action 必须尊重 current_base() 且是站内相对路径。"""

    def test_logout_url_uses_base(self):
        match = re.search(r"'lc_logout_url':\s*(.+?),\n", COMMON_PY)
        self.assertIsNotNone(match, "未找到 lc_logout_url 赋值")
        self.assertEqual(match.group(1).strip(), "logout_url(base)")
        self.assertNotIn("'lc_logout_url': '/logout'", COMMON_PY)
        self.assertNotIn("'lc_logout_url': base + '/logout'", COMMON_PY)

    def test_login_action_uses_base(self):
        self.assertIn("'lc_login_action': (base + '/login') if base else '/login',", PAGES_PY)
        self.assertNotIn("'lc_login_action': '/login',", PAGES_PY)

    def test_entry_links_are_site_relative(self):
        """入口链接不得带 scheme/host：绝对 URL 的 origin 由代理层推导，会丢端口。"""
        for name, source in (("common.py", COMMON_PY), ("pages.py", PAGES_PY)):
            for match in re.finditer(r"https?://", source):
                start = source.rfind("\n", 0, match.start()) + 1
                end = source.find("\n", match.start())
                line = source[start:end if end >= 0 else len(source)]
                # 注释里的域名只是说明文字；代码行里出现绝对 origin 不允许
                self.assertIn("#", line, "%s 出现绝对 origin：%s" % (name, line.strip()))

    def test_logout_redirect_is_relative_and_base_aware(self):
        block = PAGES_PY.split("def logout(", 1)[1].split("@http.route", 1)[0]
        self.assertIn("base = current_base()", block)
        self.assertIn("return redirect((base + '/login') if base else '/login', code=303)", block)
        self.assertNotIn("redirect('/login', code=303)", block)

    def test_logout_url_pure_function_shapes(self):
        """与 tools/paths.logout_url 的直接契约一致（纯函数，无 Odoo 依赖）。"""
        path = os.path.join(_MOD, "tools", "paths.py")
        spec = importlib.util.spec_from_file_location("ltw_paths_for_entry", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # /team 兼容入口与管理 Host 根级各自成对
        self.assertEqual(module.logout_url(""), "/logout")
        self.assertEqual(module.logout_url("/team"), "/team/logout")
        self.assertEqual(module.login_url(""), "/login")
        self.assertEqual(module.login_url("/team"), "/team/login")
        for base in ("", "/team"):
            for url in (module.logout_url(base), module.login_url(base),
                        module.lab_url(base), module.welcome_url(base)):
                self.assertTrue(url.startswith("/"), url)
                self.assertFalse(url.startswith("//"), url)
                self.assertNotIn("://", url)


class ModuleVersionTest(unittest.TestCase):
    """候选版本独立递增到 19.0.1.1.0，且页面展示版本与 manifest 一致。"""

    def test_manifest_version(self):
        self.assertEqual(_manifest()["version"], "19.0.1.1.0")

    def test_lc_version_matches_manifest(self):
        match = re.search(r"'lc_version':\s*'([^']+)'", COMMON_PY)
        self.assertIsNotNone(match, "页面上下文缺少 lc_version")
        self.assertEqual(match.group(1), _manifest()["version"])

    def test_manifest_declares_required_hook_and_data(self):
        manifest = _manifest()
        self.assertIn("uninstall_hook", manifest)
        self.assertIn("views/pages.xml", manifest["data"])


if __name__ == "__main__":
    unittest.main()
