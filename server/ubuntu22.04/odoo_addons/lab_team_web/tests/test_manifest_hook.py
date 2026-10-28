# -*- coding: utf-8 -*-
import ast
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.dirname(_HERE)


def _manifest():
    path = os.path.join(_MOD, "__manifest__.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            try:
                return ast.literal_eval(node)
            except Exception:
                continue
    raise AssertionError("manifest dict not found")


class TestManifestHook(unittest.TestCase):
    def test_uninstall_hook_is_top_level_name(self):
        hook = _manifest().get("uninstall_hook")
        self.assertIsInstance(hook, str)
        self.assertTrue(hook)
        self.assertNotIn(".", hook, "Odoo getattr(py_module, name) 不解析点号")

    def test_hook_exposed_by_package(self):
        hook = _manifest()["uninstall_hook"]
        with open(os.path.join(_MOD, "__init__.py"), encoding="utf-8") as fh:
            init = fh.read()
        with open(os.path.join(_MOD, "hooks.py"), encoding="utf-8") as fh:
            hooks = fh.read()
        self.assertIn("def %s" % hook, hooks)
        self.assertIn("from .hooks import %s" % hook, init)


if __name__ == "__main__":
    unittest.main()
