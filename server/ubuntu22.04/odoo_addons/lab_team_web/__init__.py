from . import http_patch  # noqa: F401  P2 公网 JSON-RPC 错误脱敏
from .hooks import uninstall_hook  # noqa: F401  Odoo 通过包属性解析 manifest hook

http_patch.install()
# -*- coding: utf-8 -*-
from . import controllers
from . import models
