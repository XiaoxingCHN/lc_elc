# -*- coding: utf-8 -*-
"""仅接管 management Host 的根路径；其它所有请求原样交回 Odoo。

为什么改 _dispatch 而不是再注册一个 / 路由：
Odoo Website 已经把 / 注册成自己的首页控制器，再注册一个 / 会形成规则冲突，
并且可能在不同加载顺序下抢占旧官网或网站编辑器。这里改成「决策后短路」：
只有 管理Host + 根路径 + 无 edit 参数 三个条件同时成立才渲染本模块欢迎页，
其它情况一律 super() 原样处理（旧官网、后台、编辑器都不受影响）。
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        try:
            from ..controllers.common import management_root_response
            response = management_root_response()
        except Exception:
            _logger.exception('lab_team_web: 根入口判定异常，回退原逻辑')
            response = None
        if response is not None:
            # 关键：Odoo 原 _dispatch 会对 QWeb Response 调 flatten() 才会真正写出 body。
            # 我们在这里提前 return，如果不手动 flatten，就会返回 200 但 body 为空
            # ——这是隔离环境实测发现的真实缺陷（len=0），不是推测。
            try:
                from odoo.http import Response
                if isinstance(response, Response) and response.is_qweb:
                    response.flatten()
            except Exception:
                _logger.exception('lab_team_web: 根入口响应 flatten 失败')
            return response
        return super(IrHttp, cls)._dispatch(endpoint)
