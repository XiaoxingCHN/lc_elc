# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def uninstall_hook(env):
    try:
        from . import http_patch
        http_patch.restore()
    except Exception:
        _logger.exception('lab_team_web: 卸载时还原 JSON-RPC 补丁失败')
