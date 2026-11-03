# -*- coding: utf-8 -*-
"""lab_catalog 测试包。

Odoo 的 loader 只扫描 tests 包里**已导入**的 test_* 模块；纯 unittest
discover 也需要包。这里只导入不依赖 Odoo 数据库的纯逻辑测试。
"""
from . import test_asset_cache  # noqa: F401
