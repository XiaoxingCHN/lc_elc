# -*- coding: utf-8 -*-
"""Backfill product.template.lab_search_specs after adding the stored field.

The local archive is small compared with the LCSC catalog, but the migration
still batches by id and never rewrites unrelated columns.
"""
import logging

from odoo.addons.lab_inventory.tools.param_search import build_search_specs

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('product_template')")
    if not cr.fetchone()[0]:
        _logger.info('lab_inventory: product_template missing, skip backfill')
        return

    last_id = 0
    updated = 0
    while True:
        cr.execute("""
            SELECT id, lab_specifications
              FROM product_template
             WHERE id > %s
               AND lab_specifications IS NOT NULL
               AND lab_specifications <> ''
             ORDER BY id
             LIMIT 1000
        """, (last_id,))
        rows = cr.fetchall()
        if not rows:
            break
        for record_id, raw in rows:
            cr.execute(
                'UPDATE product_template SET lab_search_specs = %s WHERE id = %s',
                (build_search_specs(raw), record_id))
        updated += len(rows)
        last_id = rows[-1][0]

    # Make the derived column unambiguous for records without specifications.
    cr.execute("UPDATE product_template SET lab_search_specs = '' "
               "WHERE lab_search_specs IS NULL")
    _logger.info('lab_inventory: lab_search_specs backfilled for %d template(s)', updated)
