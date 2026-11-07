# -*- coding: utf-8 -*-
"""Fill auto-created "立创物料 Cxxx（待补全）" templates from the catalog index.

Background
----------
Receiving a ``lcsc:Cxxx`` that has no local archive creates a minimal
``product.template``.  Before this repair those stubs kept an empty name, MPN,
brand, package and specifications, so printed bag labels showed only
"立创物料 Cxxx（待补全）" plus the trace code.  New stubs are now enriched at
creation (``lab.workflow.common._lab_create_minimal_material``); this script
brings the *existing* stubs up to the same content.

It only fills fields that are still empty — a hand-edited value always wins —
and never touches stock, bags or traces.

Usage (on the server, as the odoo user)::

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin \\
        shell -c /etc/odoo.conf -d LcHardwareHouse --no-http \\
        < /opt/odoo/custom-addons/lab_workflow/tools/enrich_stub_templates.py

Dry run by default.  Set ``APPLY=1`` to write::

    sudo -u odoo env APPLY=1 ... < enrich_stub_templates.py
"""

import json
import os

STUB_MARK = '（待补全）'
STUB_PREFIX = '立创物料 %'


def stub_templates(env):
    """Templates that still carry the auto-created placeholder name."""
    return env['product.template'].search(
        [('name', '=like', STUB_PREFIX + STUB_MARK)])


def enrich_values(template, facts):
    """Only the still-empty fields, so manual edits are never overwritten."""
    values = {}
    if not (template.lab_mpn or '').strip() and facts.get('mpn'):
        values['lab_mpn'] = facts['mpn']
    if not (template.lab_brand or '').strip() and facts.get('brand'):
        values['lab_brand'] = facts['brand']
    if not (template.lab_package or '').strip() and facts.get('package'):
        values['lab_package'] = facts['package']
    if not (template.lab_datasheet_url or '').strip() and facts.get('datasheet_url'):
        values['lab_datasheet_url'] = facts['datasheet_url']
    if not (template.lab_source_url or '').strip() and facts.get('source_url'):
        values['lab_source_url'] = facts['source_url']
    if not (template.lab_specifications or '').strip() and facts.get('specifications'):
        values['lab_specifications'] = json.dumps(
            facts['specifications'], ensure_ascii=False)
    # The placeholder name also drops "（待补全）" once a real name exists.
    if facts.get('name') and STUB_MARK in (template.name or ''):
        values['name'] = facts['name']
    return values


def run(env, apply=False, stream=None):
    """Return ``(scanned, repairable, updated)``; write only when ``apply``."""
    Template = env['product.template']
    scanned = repairable = updated = 0
    for template in stub_templates(env):
        scanned += 1
        code = (template.lab_lcsc_code or '').strip()
        facts = Template._lab_catalog_facts(code) if code else {}
        values = enrich_values(template, facts) if facts else {}
        if not values:
            if stream:
                stream.write('skip  #%s %s（索引无记录或无空字段）\n'
                             % (template.id, template.name))
            continue
        repairable += 1
        if stream:
            stream.write('fill  #%s %s -> name=%s mpn=%s brand=%s pkg=%s\n'
                         % (template.id, template.name, values.get('name', template.name),
                            values.get('lab_mpn', template.lab_mpn or '-'),
                            values.get('lab_brand', template.lab_brand or '-'),
                            values.get('lab_package', template.lab_package or '-')))
        if apply:
            template.write(values)
            updated += 1
    return scanned, repairable, updated


def _main(env):                                    # pragma: no cover - shell entry
    import sys
    apply = os.environ.get('APPLY') == '1'
    scanned, repairable, updated = run(env, apply=apply, stream=sys.stdout)
    print('扫描 %d 个占位档案；可补全 %d 个；已写入 %d 个（APPLY=%s）'
          % (scanned, repairable, updated, '1' if apply else '0'))
    if apply and updated:
        env.cr.commit()
        print('已提交。')


if 'env' in globals():          # odoo shell injects ``env`` into the namespace
    _main(globals()['env'])
