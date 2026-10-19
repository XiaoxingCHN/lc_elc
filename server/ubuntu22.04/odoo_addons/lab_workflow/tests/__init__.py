# -*- coding: utf-8 -*-
"""lab_workflow 测试包。

**必须显式 import 测试模块**：Odoo 的 ``loader.get_test_modules()`` 只扫描
``tests`` 包命名空间里名为 ``test_*`` 的**已导入模块对象**
（``inspect.getmembers(tests_mod, inspect.ismodule)``），
不会自动遍历目录。少了下面的 import，``--test-enable`` 会报
「0 failed, 0 error(s) of 0 tests」，看着像通过其实是没跑。

* ``test_offline_logic``：纯逻辑（解析/指纹/排版/二维码组件），无需数据库
* ``test_workflow_business``：Odoo 19 隔离库集成测试
  （真实 stock.move/quant/lot、幂等、权限、服务边界、历史库存适配、标签只读）
* ``test_workflow_concurrency``：**真实并发**（多线程 + Barrier 相交执行），
  需要 ``LAB_WORKFLOW_CONCURRENCY=1`` 与独立临时库
* ``qr_decode_probe``：旧自研二维码解码器，仅作历史实现回归对照
"""

from . import test_offline_logic          # noqa: F401
from . import test_workflow_business      # noqa: F401
from . import test_workflow_concurrency   # noqa: F401
