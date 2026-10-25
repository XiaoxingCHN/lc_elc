# -*- coding: utf-8 -*-
"""lab_team_web 测试包。

两种发现方式都要照顾：

* Odoo 的 loader.get_test_modules() 只扫描 tests 包里**已导入**的
  test_* 模块对象，不会遍历目录；少了下面的 import，--test-enable
  会显示 0 tests。
* 本机纯 Python 的 unittest discover 没有 Odoo；test_team_web_http
  在导入阶段会抛 unittest.SkipTest。这里用 find_spec('odoo') 预判，
  避免包被整体导入时把 SkipTest 抛到 discover 外层。
"""
import importlib.util

from . import test_paths  # noqa: F401

if importlib.util.find_spec('odoo') is not None:  # pragma: no cover - 取决于运行环境
    from . import test_team_web_http  # noqa: F401
