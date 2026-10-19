#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lab_inventory 模块离线校验器（在 Odoo 服务器上运行，不需要登录账号）。

一次性查出：
  1) 视图 / 搜索视图里引用的字段在模型中是否真实存在（并给出相似字段名建议）
  2) inherit_id、search_view_id、菜单 action/parent、权限组 category_id/implied_ids
     等 ref() 引用的 xmlid 是否存在
  3) ir.actions.act_window 的 res_model 是否存在
  4) ir.model.access.csv 里的模型 xmlid / 权限组 xmlid 是否存在
  5) 导出 stock.move / stock.location / product.template / mrp.bom / mrp.bom.line
     的真实字段清单，供修正视图使用

用法（在 Odoo 服务器上）：
    cd /opt/odoo/odoo-19
    sudo /opt/odoo/venv/bin/python <本脚本路径> -d LcHardwareHouse

可选参数：
    -c /etc/odoo.conf      指定配置文件（默认 /etc/odoo.conf）
    -m /path/to/lab_inventory   指定模块目录（默认：本脚本上级目录的 lab_inventory）
    --dump /tmp/fields.txt 把字段清单写到文件
"""
import argparse
import csv
import difflib
import os
import re
import sys
import xml.etree.ElementTree as ET

MAGIC = {
    'id', 'display_name', 'create_uid', 'create_date', 'write_uid',
    'write_date', '__last_update', 'active',
}

DUMP_MODELS = [
    'stock.move', 'stock.location', 'product.template',
    'mrp.bom', 'mrp.bom.line', 'stock.quant', 'stock.picking',
]


def load_odoo():
    try:
        import odoo  # noqa: F401
    except ImportError:
        for p in ('/opt/odoo/odoo-19', '/opt/odoo', '/usr/lib/python3/dist-packages'):
            if os.path.isdir(os.path.join(p, 'odoo')) and p not in sys.path:
                sys.path.insert(0, p)
        import odoo  # noqa: F401
    import odoo
    from odoo.modules.registry import Registry
    return odoo, Registry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-d', '--database', required=True)
    ap.add_argument('-c', '--config', default='/etc/odoo.conf')
    ap.add_argument('-m', '--module', default=None)
    ap.add_argument('--dump', default=None)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    module = os.path.abspath(args.module or os.path.join(here, '..', 'lab_inventory'))

    odoo, Registry = load_odoo()
    from odoo.api import Environment
    from odoo.tools import config as odooconf
    superuser_id = getattr(odoo, 'SUPERUSER_ID', 1)
    odooconf.parse_config(['-c', args.config])
    if args.database:
        odooconf['db_name'] = args.database

    registry = Registry(args.database)
    problems = []
    notes = []
    modname = os.path.basename(module.rstrip('/'))

    with registry.cursor() as cr:
        env = Environment(cr, superuser_id, {})
        IrModelData = env['ir.model.data'].sudo()

        # 模块是否已安装？未安装时 lab_* 字段 / 本模块 xmlid 必然不存在，属正常，需跳过
        row = env['ir.module.module'].sudo().search_read(
            [('name', '=', modname)], ['state'], limit=1)
        installed = bool(row) and row[0]['state'] == 'installed'

        def xmlid_ok(xmlid):
            if not xmlid:
                return False
            if '.' not in xmlid:          # 未限定模块名 -> 属于当前模块
                xmlid = modname + '.' + xmlid
            mod, _, name = xmlid.partition('.')
            if mod == modname and not installed:
                return True               # 本模块的 xmlid，安装后才会存在
            return bool(IrModelData.search_count(
                [('module', '=', mod), ('name', '=', name)]))

        def model_exists(name):
            return name in env

        def fields_of(name):
            return set(env[name]._fields.keys()) | MAGIC

        def check_field(model, fname, where, problems):
            if not model_exists(model):
                if not installed and model.startswith('lab.'):
                    return            # 本模块自建模型，安装后才有
                problems.append('[模型缺失] %s：模型 %s 不存在（模块未安装？）' % (where, model))
                return
            if not installed and fname.startswith('lab_'):
                return                # 本模块扩展字段，安装后才有
            if fname in fields_of(model):
                return
            near = difflib.get_close_matches(fname, sorted(fields_of(model)), n=5, cutoff=0.5)
            hint = ('  相似字段: %s' % ', '.join(near)) if near else ''
            problems.append('[字段缺失] %s：模型 %s 没有字段 "%s"\n%s'
                            % (where, model, fname, hint))

        def walk(el, model, where, problems):
            """递归校验视图 arch 里的 <field name=...>。"""
            for child in el:
                if child.tag == 'xpath':
                    # xpath 常指向 one2many 内部（如 mrp.bom 的 bom_line_ids），
                    # 需要把子字段切到 comodel 上校验，否则全是误报。
                    sub = model
                    for n in re.findall(r"@name\s*=\s*['\"]([^'\"]+)['\"]",
                                        child.get('expr') or ''):
                        f = env[sub]._fields.get(n) if model_exists(sub) else None
                        if f is not None and f.type in ('one2many', 'many2many') \
                                and getattr(f, 'comodel_name', None):
                            sub = f.comodel_name
                    walk(child, sub, where + ' [xpath]', problems)
                elif child.tag == 'field' and child.get('name'):
                    fname = child.get('name')
                    check_field(model, fname, where, problems)
                    f = None
                    if model_exists(model):
                        f = env[model]._fields.get(fname)
                    if f is not None and f.type in ('one2many', 'many2many') \
                            and getattr(f, 'comodel_name', None):
                        walk(child, f.comodel_name, where + '/' + fname, problems)
                    else:
                        walk(child, model, where, problems)
                else:
                    walk(child, model, where, problems)

        # ---------- 遍历模块内所有 XML ----------
        xml_files = []
        for root, _dirs, files in os.walk(module):
            for fn in sorted(files):
                if fn.endswith('.xml'):
                    xml_files.append(os.path.join(root, fn))
        xml_files.sort()

        for path in xml_files:
            rel = os.path.relpath(path, module)
            try:
                tree = ET.parse(path)
            except ET.ParseError as e:
                problems.append('[XML 语法错误] %s: %s' % (rel, e))
                continue
            for rec in tree.getroot():
                if rec.tag != 'record':
                    if rec.tag == 'menuitem':
                        for attr in ('action', 'parent'):
                            v = rec.get(attr)
                            if v and '.' in v and not xmlid_ok(v):
                                problems.append(
                                    '[xmlid 缺失] %s: <menuitem %s="%s"> 不存在' % (rel, attr, v))
                        for g in (rec.get('groups') or '').split(','):
                            g = g.strip()
                            if g and '.' in g and not xmlid_ok(g):
                                problems.append(
                                    '[xmlid 缺失] %s: menuitem groups="%s" 不存在' % (rel, g))
                    continue

                rec_id = rec.get('id')
                # 注意：<record model="X"> 的 model 是"要写入哪个模型"（如 ir.ui.view），
                # 而记录内部 <field name="model"> 的 text 才是视图绑定的业务模型。
                rmodel = rec.get('model')
                vals = {f.get('name'): f for f in rec.findall('field')}

                if rmodel == 'ir.ui.view':
                    if 'model' not in vals or not (vals['model'].text or '').strip():
                        problems.append('[缺少 model] %s: 视图 %s 未指定绑定模型' % (rel, rec_id))
                        continue
                    vmodel = vals['model'].text.strip()
                    arch = vals.get('arch')
                    vname = (vals['name'].text or rec_id or '') if 'name' in vals else rec_id
                    if not model_exists(vmodel):
                        if not installed and vmodel.startswith('lab.'):
                            continue
                        problems.append('[模型缺失] %s: 视图 %s 的模型 %s 不存在' % (rel, vname, vmodel))
                        continue
                    # inherit_id
                    inh = vals.get('inherit_id')
                    if inh is not None and inh.get('ref'):
                        if not xmlid_ok(inh.get('ref')):
                            problems.append('[xmlid 缺失] %s: 视图 %s 的 inherit_id="%s" 不存在'
                                            % (rel, vname, inh.get('ref')))
                    if arch is not None:
                        where = '%s: 视图 %s (%s)' % (rel, vname, vmodel)
                        for child in arch:
                            walk(child, vmodel, where, problems)

                elif rmodel == 'ir.actions.act_window':
                    rm = vals.get('res_model')
                    if rm is not None and rm.text and not model_exists(rm.text.strip()) \
                            and not (not installed and rm.text.strip().startswith('lab.')):
                        problems.append('[模型缺失] %s: action %s 的 res_model=%s 不存在'
                                        % (rel, rec_id, rm.text.strip()))
                    sv = vals.get('search_view_id')
                    if sv is not None and sv.get('ref') and not xmlid_ok(sv.get('ref')):
                        problems.append('[xmlid 缺失] %s: action %s 的 search_view_id="%s" 不存在'
                                        % (rel, rec_id, sv.get('ref')))
                    for f in rec.findall('field'):
                        for m in re.findall(r"ref\((['\"])([^'\"]+)\1\)", f.get('eval') or ''):
                            if not xmlid_ok(m[1]):
                                problems.append('[xmlid 缺失] %s: action %s 的 eval ref("%s") 不存在'
                                                % (rel, rec_id, m[1]))

                elif rmodel == 'ir.ui.menu':
                    for attr, fn in (('action', 'action'), ('parent', 'parent')):
                        f = vals.get(fn)
                        if f is not None and f.get('ref') and not xmlid_ok(f.get('ref')):
                            problems.append('[xmlid 缺失] %s: 菜单 %s 的 %s="%s" 不存在'
                                            % (rel, rec_id, fn, f.get('ref')))

                elif rmodel == 'res.groups':
                    cat = vals.get('category_id')
                    if cat is not None and cat.get('ref') and not xmlid_ok(cat.get('ref')):
                        problems.append('[xmlid 缺失] %s: 权限组 %s 的 category_id="%s" 不存在'
                                        % (rel, rec_id, cat.get('ref')))
                    imp = vals.get('implied_ids')
                    if imp is not None:
                        for m in re.findall(r"ref\((['\"])([^'\"]+)\1\)", imp.get('eval') or ''):
                            if not xmlid_ok(m[1]):
                                problems.append('[xmlid 缺失] %s: 权限组 %s 的 implied_ids ref("%s") 不存在'
                                                % (rel, rec_id, m[1]))

        # ---------- CSV ----------
        for root, _dirs, files in os.walk(module):
            for fn in sorted(files):
                if not fn.endswith('.csv'):
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, module)
                raw = open(path, 'rb').read()
                if raw.startswith(b'\xef\xbb\xbf'):
                    problems.append('[BOM] %s: 文件带 UTF-8 BOM，会导致 "字段名 \\ufeffid 无效"' % rel)
                reader = csv.DictReader(raw.decode('utf-8-sig').splitlines())
                for row in reader:
                    mid = row.get('model_id:id')
                    if mid and not xmlid_ok(mid):
                        problems.append('[xmlid 缺失] %s: model_id:id="%s" 不存在'
                                        % (rel, mid))
                    gid = row.get('group_id:id')
                    if gid and not xmlid_ok(gid):
                        problems.append('[xmlid 缺失] %s: group_id:id="%s" 不存在'
                                        % (rel, gid))

        # ---------- 字段清单 ----------
        dump = []
        for m in DUMP_MODELS:
            if not model_exists(m):
                dump.append('=== %s === (模型不存在，对应模块可能未安装)\n' % m)
                continue
            fs = sorted(fields_of(m))
            dump.append('=== %s (%d 字段) ===' % (m, len(fs)))
            dump.append('  ' + ' '.join(fs))
            dump.append('')
        dump_text = '\n'.join(dump)

    print('=' * 70)
    print('模块目录: %s' % module)
    print('模块名  : %s   安装状态: %s' % (modname, '已安装' if installed else '未安装'))
    print('数据库  : %s' % args.database)
    print('=' * 70)
    if not installed:
        print('\n提示：模块尚未安装，lab_* 扩展字段、lab.* 自建模型、lab_inventory.* xmlid')
        print('      已自动跳过（安装后才有）。装完请再跑一次做完整校验。')
    if problems:
        print('\n发现 %d 个问题：\n' % len(problems))
        for i, p in enumerate(problems, 1):
            print('%2d. %s' % (i, p))
    else:
        print('\n✅ 未发现问题：所有字段 / xmlid 均存在。')
    if notes:
        print('\n'.join(notes))

    print('\n' + '=' * 70)
    print('关键模型字段清单')
    print('=' * 70)
    print(dump_text)

    if args.dump:
        with open(args.dump, 'w', encoding='utf-8') as fh:
            fh.write(dump_text)
        print('\n字段清单已写入: %s' % args.dump)

    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
