# -*- coding: utf-8 -*-
"""可复用的纯逻辑工具。

说明
----
* ``inventory_codec`` / ``request_keys`` / ``label_render`` / ``font_utils``：
  纯逻辑，可直接离线单测（不依赖 odoo registry）。
* ``pdf_labels``：A4 标签 PDF 生成（依赖 odoo 的 ``_()`` 与 ``UserError``，
  以及 reportlab）。**二维码使用 reportlab 标准组件**
  ``reportlab.graphics.barcode.qr.QrCodeWidget``（barLevel='M'、barBorder=4）。
* ``pdf_selfcheck``：不需要 Odoo 的自检脚本，新增/更换字体后必须跑一次。
* ``qr_encode`` / ``tests/qr_decode_probe.py``：**历史自研实现**，不参与生产码源，
  仅作为回归对照保留；生产二维码一律走 reportlab 标准组件。
"""

from . import inventory_codec
from . import label_render
from . import font_utils
from . import request_keys
from . import pdf_labels

__all__ = ['inventory_codec', 'label_render', 'font_utils', 'request_keys', 'pdf_labels']
