# -*- coding: utf-8 -*-
"""目录导入批次：幂等断点与来源留痕。"""
from odoo import fields, models


class LabCatalogImportRun(models.Model):
    _name = 'lab.catalog.import.run'
    _description = '立创资料库导入批次'
    _order = 'id desc'

    name = fields.Char(string='批次', required=True)
    source_path = fields.Char(string='来源快照', required=True,
                              help='原 components.sqlite3 路径（只读，从不修改）')
    source_sha256 = fields.Char(string='快照 SHA256')
    market = fields.Char(string='站点', default='cn')
    state = fields.Selection(
        [('draft', '待运行'), ('running', '运行中'), ('done', '完成'),
         ('failed', '失败')], default='draft', required=True, index=True)
    started_at = fields.Datetime(string='开始时间')
    finished_at = fields.Datetime(string='结束时间')
    rows_seen = fields.Integer(string='已扫描')
    rows_written = fields.Integer(string='已写入')
    rows_skipped = fields.Integer(string='已跳过（指纹未变）')
    rows_failed = fields.Integer(string='失败')
    last_code = fields.Char(string='断点 C 编号',
                            help='幂等断点：重跑时从该编号之后继续')
    log = fields.Text(string='日志')
    catalog_revision = fields.Char(string='导入后目录版本')
