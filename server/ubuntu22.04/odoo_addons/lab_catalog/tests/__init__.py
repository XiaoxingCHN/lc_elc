# -*- coding: utf-8 -*-
"""lab_catalog 测试包。

Odoo 的 loader 只扫描 tests 包里**已导入**的 test_* 模块；纯 unittest
discover 也需要包。``test_asset_cache`` / ``test_param_search`` 不依赖
Odoo 数据库；``test_catalog_param_search_orm`` 需要 Odoo 测试运行器。
"""
from . import test_asset_cache  # noqa: F401
from . import test_param_search  # noqa: F401
from . import test_catalog_param_search_orm  # noqa: F401
