"""Restore only backed-up menu/view active flags inside Odoo shell.
Set LC_UI_PROFILE_BACKUP to the exact configuration backup folder to restore.
Never restores user roles, database snapshots or stock records.
"""
import json
import os
from pathlib import Path

snapshot = json.loads((Path(os.environ['LC_UI_PROFILE_BACKUP']) / 'ui-before.json').read_text())
targets = []
for key, model in [('menus', 'ir.ui.menu'), ('views', 'ir.ui.view')]:
    for row in snapshot[key]:
        record = env[model].with_context(active_test=False).browse(row['id']).exists()
        if not record:
            raise RuntimeError('Backup record is missing: ' + model + ':' + str(row['id']))
        if row.get('xmlid') and env.ref(row['xmlid']) != record:
            raise RuntimeError('Backup identity does not match current database')
        targets.append((record, row['active']))
with env.cr.savepoint():
    for record, active in targets:
        record.write({'active': active})
env.cr.commit()
print('RESTORED_MENU_VIEW_FLAGS', len(targets))
