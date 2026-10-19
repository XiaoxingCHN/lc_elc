# -*- coding: utf-8 -*-
"""lab_workflow：实验室库存真实作业、追溯与标签。"""

from . import models
from . import controllers
from . import tools
from .hooks import post_init_hook  # noqa: F401  （manifest 里的 post_init_hook）
