# -*- coding: utf-8 -*-
"""lab_workflow 测试包。

**必须显式 import 测试模块**：Odoo 的 ``loader.get_test_modules()`` 只扫描
``tests`` 包命名空间里名为 ``test_*`` 的**已导入模块对象**
（``inspect.getmembers(tests_mod, inspect.ismodule)``），
不会自动遍历目录。少了下面的 import，``--test-enable`` 会报
「0 failed, 0 error(s) of 0 tests」，看着像通过其实是没跑。

* ``test_offline_logic``：纯逻辑（解析/指纹/排版/二维码组件），无需数据库
* ``test_p3_contract_logic``：P3 窄接口纯规则
  （分页/角色/映射排序/日期/库位守卫/PDF 边界/扫码迁移），无需数据库
* ``test_workflow_business``：Odoo 19 隔离库集成测试
  （真实 stock.move/quant/lot、幂等、权限、服务边界、历史库存适配、标签只读）
* ``test_p3_backend_api``：P3 窄接口 + 安全修复
  （袋列表/详情、库位改停用、类别映射、成员角色、history 过滤、PDF、
  S1 跨账号归还、S3 adopt 回滚、S5 停用库位、S2 畸形入参）
* ``test_workflow_concurrency``：**真实并发**（多线程 + Barrier 相交执行），
  需要 ``LAB_WORKFLOW_CONCURRENCY=1`` 与独立临时库
* ``qr_decode_probe``：旧自研二维码解码器，仅作历史实现回归对照
"""

from . import test_offline_logic          # noqa: F401
from . import test_p3_contract_logic      # noqa: F401
from . import test_workflow_business      # noqa: F401
from . import test_p3_backend_api         # noqa: F401
from . import test_workflow_concurrency   # noqa: F401
from . import test_client_updates        # noqa: F401
