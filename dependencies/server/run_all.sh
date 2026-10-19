#!/usr/bin/env bash
#
# run_all — drive the whole preparation in the correct order.
#
#   OUT_DIR=<...>/out  WORK_DIR=/tmp/lcsc-dep-work  bash run_all.sh
#
# Ordering constraints (do not rearrange):
#   01 must precede 03b   (03b extracts headers from the debs 01 downloaded)
#   02 must precede 03    (03 reads the requirements.txt 02 lifted out)
#   03  must precede 03b  (03 identifies which sdists could not be built)
#   03b must precede 04   (04 hashes the final wheel set)
#
# Every step is exit-code checked; the run stops at the first failure.

set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

run_step() {
    local name="$1"
    echo
    echo "############################################################"
    echo "# ${name}"
    echo "############################################################"
    set +e
    bash "${HERE}/${name}"
    local code=$?
    set -e
    if [ "${code}" -ne 0 ]; then
        echo "FAILED: ${name} (exit ${code}) — aborting run_all" >&2
        exit "${code}"
    fi
}

mkdir -p "${WORK_DIR:-/tmp/lcsc-dep-work}"

run_step 00_preflight.sh
run_step 01_download_apt_closure.sh
run_step 02_fetch_odoo.sh
run_step 03a_requests_wheelhouse.sh
run_step 03_build_odoo_wheelhouse.sh
run_step 03b_build_quarantined_from_debs.sh
run_step 04_build_manifest.sh
run_step 05_offline_verify.sh

echo
echo "############################################################"
echo "# ALL STEPS COMPLETE"
echo "############################################################"
echo "Bundle: ${OUT_DIR:-${HERE}/out}"
echo "Remember: do NOT ship out/apt/ (isolated apt scratch)."
