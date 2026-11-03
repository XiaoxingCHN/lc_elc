# -*- coding: utf-8 -*-
"""HTTP / JSON-RPC 控制器。"""

from . import lab_api_common
from . import lab_inventory_api
from . import lab_p3_api
from . import lab_labels_api
from . import lab_web
from . import lab_client_updates

__all__ = ['lab_api_common', 'lab_inventory_api', 'lab_p3_api', 'lab_labels_api',
           'lab_web']
