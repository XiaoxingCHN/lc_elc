#!/usr/bin/env bash
# Validate payload only; production requires a paired backup and targeted upgrade.
set -euo pipefail
base="$(cd -- "$(dirname -- "$0")" && pwd)"
for file in lab_catalog/static/src/css/lc_theme_dark.css lab_catalog/static/src/unified/unified_catalog.scss lab_catalog/__manifest__.py; do
  test -f "$base/$file" || { echo "Missing payload: $file" >&2; exit 1; }
done
echo 'Theme payload exists. No production files or services were changed.'
echo 'Follow docs/operations/SERVER.md: freeze source, verify backup, upgrade only lab_catalog, validate assets and health.'
echo 'A restart alone does not update the installed asset manifest.'
