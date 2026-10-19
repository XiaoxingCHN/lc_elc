# -*- coding: utf-8 -*-
"""中文字体可用性检测与注册（**纯逻辑**，不依赖 odoo，便于离线实测）。

核心原则：**必须真实检查 cmap 字形**，不能用 ``stringWidth > 0`` 判断。
例如 DejaVuSans 对「测」也能给出 5.4pt 宽度（回退到 ``.notdef``），
实际打印是方块。这里用 reportlab TTFontFace 的 ``charToGlyph`` 直查 cmap：

* ``charToGlyph.get(ord(ch))`` 为 ``None``/``0`` => 缺字形
* 退化路径再比对「字符宽度 == .notdef 宽度」

字体候选顺序：环境变量 → 系统参数 → 模块自带静态 TTF → 系统 CJK 字体。
"""

import logging
import os

_logger = logging.getLogger(__name__)

__all__ = [
    'CJK_PROBE_TEXT',
    'FontUnavailable',
    'font_candidates',
    'font_supports_text',
    'register_cjk_font',
    'register_cjk_font_from_path',
]

# 需要能打印的固定中文字形（标签/提示常用字 + 中文标点）
CJK_PROBE_TEXT = ('物料库位袋追溯码数量型号参数项目领用人操作入库领用归还'
                  '实验室器件标签打印复份页日期备注单位：，。、（）')

_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (定位方式, 值)。定位方式：env / setting / module / system
CANDIDATES = (
    ('setting', 'lab_workflow.font_file'),
    ('module', 'static/fonts/NotoSansSC-Regular.ttf'),
    ('module', 'static/fonts/NotoSansSC-VF.ttf'),
    ('system', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    ('system', '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc'),
    ('system', '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc'),
    ('system', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'),
    ('system', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
    ('system', '/usr/share/fonts/truetype/arphic/uming.ttc'),
    ('system', 'C:/Windows/Fonts/NotoSansSC-VF.ttf'),
)


class FontUnavailable(Exception):
    """找不到任何真正支持所需中文字形的字体。"""


def font_candidates(env=None, env_var='LAB_WORKFLOW_LABEL_FONT',
                    param_key='lab_workflow.label_font'):
    """按优先级返回候选字体绝对路径列表。"""
    paths = []
    explicit = os.environ.get(env_var)
    if explicit:
        paths.append(explicit)
    if env is not None:
        try:
            configured = env['ir.config_parameter'].sudo().get_param(param_key)
        except Exception:  # noqa: BLE001
            configured = None
        if configured:
            paths.append(configured)
    for kind, value in CANDIDATES:
        if kind == 'module':
            paths.append(os.path.join(_MODULE_ROOT, value.replace('/', os.sep)))
        elif kind == 'system':
            paths.append(value)
    seen = set()
    unique = []
    for path in paths:
        if not path:
            continue
        normalized = os.path.abspath(path)
        if normalized in seen or not os.path.isfile(normalized):
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def font_supports_text(font, text):
    """真实判定字体是否有这些字形；返回 ``(ok, missing_char)``。"""
    face = getattr(font, 'face', None)
    char_to_glyph = getattr(face, 'charToGlyph', None)
    glyph_names = getattr(face, 'glyphNames', None)
    notdef_width = None
    try:
        notdef_width = font.stringWidth('\uFFFF', 1000)
    except Exception:  # noqa: BLE001
        notdef_width = None

    for char in sorted(set(text)):
        if char in ('\n', '\r', '\t', ' '):
            continue
        code = ord(char)
        if char_to_glyph is not None:
            try:
                if char_to_glyph.get(code) in (None, 0):
                    return False, char
                continue
            except AttributeError:
                pass
        if glyph_names is not None:
            try:
                if char not in glyph_names:
                    return False, char
                continue
            except TypeError:
                pass
        try:
            width = font.stringWidth(char, 1000)
        except Exception:  # noqa: BLE001
            return False, char
        if width is None or width <= 0:
            return False, char
        if notdef_width is not None and abs(width - notdef_width) < 0.01:
            return False, char
    return True, None


def register_cjk_font(env, required_text='', probe_text=CJK_PROBE_TEXT,
                      candidates=None):
    """挑选并注册一个真正支持所需字形的字体。

    :returns: ``(font_name, font_path)``
    :raises FontUnavailable: 所有候选都缺字形（附中文修复步骤）
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    probe = ''.join(sorted(set(probe_text + (required_text or ''))))
    paths = candidates if candidates is not None else font_candidates(env)
    tried = []
    for path in paths:
        name = 'LabCjkFont%d' % (abs(hash(path)) % 10 ** 8)
        if name not in pdfmetrics.getRegisteredFontNames():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception as exc:  # noqa: BLE001
                tried.append('%s（加载失败：%s）' % (path, exc))
                continue
        try:
            font = pdfmetrics.getFont(name)
        except KeyError:
            tried.append('%s（注册后取不到）' % path)
            continue
        ok, missing = font_supports_text(font, probe)
        if ok:
            _logger.info('标签中文字体已启用：%s (%s)', name, path)
            return name, path
        tried.append('%s（缺字形 %r）' % (path, missing))

    detail = '\n'.join('  - %s' % line for line in tried) or '  - 没有找到任何候选字体文件'
    raise FontUnavailable(
        '找不到能打印中文的标签字体，已拒绝生成 PDF（避免标签丢字）。\n'
        '已尝试的候选：\n%s\n'
        '修复方式（任选其一）：\n'
        '  1) sudo apt-get install -y fonts-noto-cjk\n'
        '  2) 设置环境变量 LAB_WORKFLOW_LABEL_FONT=/path/to/NotoSansCJK-Regular.ttc\n'
        '  3) 在「设置 → 技术 → 系统参数」新增 lab_workflow.label_font = 字体绝对路径\n'
        '  4) 把带许可证的 TTF/OTF 放到 lab_workflow/static/fonts/ 下\n'
        '注意：字体必须是开源或已授权字体（如 SIL OFL 的 Noto Sans CJK），'
        '不要复制 Windows 商业字体。' % detail)


def register_cjk_font_from_path(path, required_text='', probe_text=CJK_PROBE_TEXT):
    """只用一个指定字体文件注册（测试/运维核查用）。"""
    return register_cjk_font(None, required_text=required_text,
                             probe_text=probe_text, candidates=[path])
