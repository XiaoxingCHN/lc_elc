# -*- coding: utf-8 -*-
"""product.template 扩展：立创商城信息与实验室自有字段。

映射关系（源系统 components 表）：
    internal_code      -> default_code（内部参考，唯一）
    part_number(C码)   -> lab_lcsc_code
    mpn                -> lab_mpn
    brand              -> lab_brand
    package_name       -> lab_package
    description        -> lab_description
    specifications     -> lab_specifications（JSON 字符串）
    datasheet_url      -> lab_datasheet_url
    source_url         -> lab_source_url
    image_url          -> image_1920
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# SN 序列标识（ir.sequence）
SN_SEQUENCE_CODE = 'lab.component.sn'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _default_lab_sn(self):
        """生成实验室内部 SN：LAB-000001 / LAB-000002 ...

        序列不存在时懒创建（省掉一个额外的 data 文件，也避免升级顺序问题）。
        沿用源系统 internal_code 的 LAB-%06d 格式，手机端 / EDA 插件无需改动即可识别。
        """
        val = self.env['ir.sequence'].next_by_code(SN_SEQUENCE_CODE)
        if not val:
            self.env['ir.sequence'].sudo().create({
                'name': '实验室元器件 SN',
                'code': SN_SEQUENCE_CODE,
                'prefix': 'LAB-',
                'padding': 6,
                'number_increment': 1,
                'number_next': 1,
                'company_id': False,
            })
            val = self.env['ir.sequence'].next_by_code(SN_SEQUENCE_CODE)
        return val or ''

    lab_sn = fields.Char(
        string='SN 码', copy=False, index=True,
        default=_default_lab_sn,
        help='实验室内部唯一编号，独立于立创商城。'
             '自来料 / 立创上没有的器件靠它做唯一识别，可打印成条码贴在料盒上。')

    lab_lcsc_code = fields.Char(
        string='立创商城编号', copy=False, index=True,
        help='立创商城 C 编号，如 C123456；手动物料留空')
    lab_mpn = fields.Char(
        string='制造商型号 (MPN)', index=True)
    lab_brand = fields.Char(string='品牌')
    lab_package = fields.Char(string='封装')
    lab_description = fields.Text(string='器件描述')
    lab_specifications = fields.Text(
        string='规格参数 (JSON)',
        help='键值对 JSON 字符串，例如 {"阻值": "270Ω", "精度": "±1%"}')
    lab_datasheet_url = fields.Char(string='数据手册链接')
    lab_source_url = fields.Char(string='来源链接')

    @api.constrains('lab_sn')
    def _check_lab_sn_unique(self):
        """SN 必须全局唯一（同一 SN 不能挂两个物料）。"""
        for rec in self:
            if not rec.lab_sn:
                continue
            dup = self.search([('lab_sn', '=', rec.lab_sn),
                               ('id', '!=', rec.id)], limit=1)
            if dup:
                raise ValidationError(
                    'SN 码「%s」已被「%s」占用，请换一个！'
                    % (rec.lab_sn, dup.display_name))
