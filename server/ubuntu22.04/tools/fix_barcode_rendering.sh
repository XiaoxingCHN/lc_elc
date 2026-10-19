#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=/opt/odoo/venv/bin/python
[[ -x $python ]] || { echo 'Odoo virtual environment not found' >&2; exit 1; }
if "$python" "$script_dir/check_barcode_rendering.py"; then
  echo 'Odoo barcode renderer is already working.'
  exit 0
fi
wheelhouse=${1:?Pass the matching offline barcode wheel directory}
[[ -d $wheelhouse && -f $wheelhouse/SHA256SUMS ]] || { echo 'Offline wheel directory/checksums missing' >&2; exit 1; }
(cd -- "$wheelhouse" && sha256sum -c SHA256SUMS)
"$python" -m pip install --disable-pip-version-check --no-index --no-deps --only-binary=:all: --find-links "$wheelhouse" rl-renderPM==4.0.3
"$python" "$script_dir/check_barcode_rendering.py"
echo 'Barcode renderer verified. Restart only the Odoo service to reload the backend.'
