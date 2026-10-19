#!/usr/bin/env bash
#
# 02 — Fetch the official Odoo 19 source at a fixed, recorded revision.
#
# Produces a `git archive` tarball (no .git, no stray files) plus a REVISION
# file and a copy of the revision's requirements.txt, so the wheelhouse step and
# the offline target both work from an auditable pin.
#
# Pin the exact commit with:  ODOO_REV=<full sha> ./02_fetch_odoo.sh
# Otherwise the branch tip is used and its resolved SHA is recorded — the
# bundle is still reproducible because the SHA is written into REVISION and
# covered by SHA256SUMS.

set -euo pipefail
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

require_cmd git tar sha256sum find
ensure_dirs

SRC="${WORK_DIR}/odoo-src"

# Refuse to delete anything outside our scratch dir.
case "${SRC}" in
    "${WORK_DIR}"/*) ;;
    *) die "refusing to remove unexpected path: ${SRC}" ;;
esac
rm -rf -- "${SRC}"

# ---------------------------------------------------------------------------
# 1. Clone / fetch
# ---------------------------------------------------------------------------
if [ -n "${ODOO_REV}" ]; then
    log "pinned revision requested: ${ODOO_REV}"
    mkdir -p "${SRC}"
    run "git init" git init -q "${SRC}"
    run "git remote add origin ${ODOO_REPO}" git -C "${SRC}" remote add origin "${ODOO_REPO}"
    run "git fetch --depth 1 origin ${ODOO_REV}" \
        git -C "${SRC}" fetch --depth 1 origin "${ODOO_REV}"
    run "git checkout FETCH_HEAD" git -C "${SRC}" checkout -q FETCH_HEAD
else
    run "git clone --depth 1 --branch ${ODOO_BRANCH}" \
        git clone --depth 1 --branch "${ODOO_BRANCH}" "${ODOO_REPO}" "${SRC}"
fi

REV="$(git -C "${SRC}" rev-parse HEAD)"
COMMIT_DATE="$(git -C "${SRC}" log -1 --format=%cI)"
[ -n "${REV}" ] || die "could not resolve a commit for the Odoo source"
ok "resolved revision ${REV} (${COMMIT_DATE})"

if [ -n "${ODOO_REV}" ] && [ "${REV}" != "${ODOO_REV}" ]; then
    die "requested ODOO_REV ${ODOO_REV} but got ${REV}"
fi

# ---------------------------------------------------------------------------
# 2. Sanity-check that this really looks like the Odoo 19 source
# ---------------------------------------------------------------------------
[ -f "${SRC}/odoo-bin" ]        || die "odoo-bin missing at ${REV} — not an Odoo source tree?"
[ -f "${SRC}/requirements.txt" ] || die "requirements.txt missing at ${REV}"

major="$(sed -n "s/.*version_info *= *\[\([0-9]*\).*/\1/p" "${SRC}/odoo/release.py" 2>/dev/null | head -n1 || true)"
if [ -n "${major}" ]; then
    if [ "${major}" != "19" ]; then
        warn "odoo/release.py reports major version ${major}, expected 19"
        warn "the tarball will still be produced and the version recorded in REVISION"
    else
        ok "odoo/release.py confirms major version 19"
    fi
fi

# ---------------------------------------------------------------------------
# 3. Export a clean tarball
# ---------------------------------------------------------------------------
TARBALL="${ODOO_DIR}/odoo-${REV}.tar.gz"
run "git archive -> $(basename "${TARBALL}")" \
    git -C "${SRC}" archive --format=tar.gz \
        --prefix="odoo-${REV}/" -o "${TARBALL}" "${REV}"

# ---------------------------------------------------------------------------
# 4. Record the pin and lift out requirements.txt
# ---------------------------------------------------------------------------
REQ_OUT="${ODOO_DIR}/odoo-requirements.txt"
run "copy requirements.txt from the pinned revision" \
    cp "${SRC}/requirements.txt" "${REQ_OUT}"

cat > "${ODOO_DIR}/REVISION" <<EOF
repo=${ODOO_REPO}
branch=${ODOO_BRANCH}
commit=${REV}
commit_date=${COMMIT_DATE}
requested_pin=${ODOO_REV:-<branch tip>}
tarball=odoo-${REV}.tar.gz
fetched_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
fetched_on=$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}" || echo unknown)
EOF
ok "wrote ${ODOO_DIR}/REVISION"

# ---------------------------------------------------------------------------
# 5. Verify the tarball is readable and complete
# ---------------------------------------------------------------------------
listing="${WORK_DIR}/odoo_tarball_listing.txt"
run "tar -tzf (readability check)" bash -c "tar -tzf '${TARBALL}' > '${listing}'"

entries="$(wc -l < "${listing}" | tr -d ' ')"
[ "${entries}" -gt 1000 ] || die "tarball lists only ${entries} entries — that is implausibly small"

grep -qx "odoo-${REV}/odoo-bin" "${listing}" \
    || die "odoo-bin not found inside the tarball"
grep -qx "odoo-${REV}/requirements.txt" "${listing}" \
    || die "requirements.txt not found inside the tarball"
ok "tarball verified: ${entries} entries, odoo-bin and requirements.txt present"

# ---------------------------------------------------------------------------
# 6. Report
# ---------------------------------------------------------------------------
sha="$(sha256sum "${TARBALL}" | cut -d' ' -f1)"
size="$(du -h "${TARBALL}" | cut -f1)"
printf 'odoo tarball : %s (%s)\n' "$(basename "${TARBALL}")" "${size}"
printf 'sha256       : %s\n' "${sha}"
printf 'requirements : %s (%s lines)\n' \
    "$(basename "${REQ_OUT}")" "$(grep -vc '^\s*\(#\|$\)' "${REQ_OUT}" || echo 0)"
ok "Odoo source ready in ${ODOO_DIR}"
