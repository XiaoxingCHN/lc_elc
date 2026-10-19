#!/usr/bin/env bash
#
# 03b — Retry the quarantined sdists using headers extracted from the .deb files
#       that 01 already downloaded. This is the "bootstrap from downloaded debs"
#       path: no sudo, no apt install, nothing written outside the delivery and
#       scratch directories.
#
# Why this exists: python-ldap==3.4.0 has no wheel, and the WSL image lacks
# libldap2-dev / libsasl2-dev. jammy's own python3-ldap is 3.2.0, while Odoo 19
# pins 3.4.0 (its comment says "min version = 3.2.0"), so to satisfy the pin
# exactly the 3.4.0 sdist has to be compiled — and the headers for that are
# sitting inside debs/libldap2-dev_*.deb and debs/libsasl2-dev_*.deb.
#
# On success the resulting wheel is moved into the wheelhouse and the package is
# removed from ODOO-FROM-APT.txt.

set -euo pipefail
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

require_cmd dpkg-deb python3 find
ensure_dirs

SRC_DIR="${OUT_DIR}/sdists-odoo"
PREFIX="${WORK_DIR}/deb-prefix"
VENV="${WORK_DIR}/venv-quarantine"
WH="${WHEEL_DIR_ODOO}"

# Header / link libraries the quarantined sdists need, taken from our own debs.
# NOTE: `libldap2-dev` must NOT be used here - on jammy it is transitional and
# ships no headers. `libldap-dev` is the real development package.
DEV_DEBS="${QUARANTINE_DEV_DEBS:-libldap-dev libsasl2-dev libldap-2.5-0 libsasl2-2 libsasl2-modules-db}"

if [ ! -d "${SRC_DIR}" ] || [ -z "$(find "${SRC_DIR}" -maxdepth 1 -type f -print -quit)" ]; then
    ok "nothing quarantined; nothing to do"
    exit 0
fi

log "quarantined sdists in ${SRC_DIR}:"
find "${SRC_DIR}" -maxdepth 1 -type f -printf '    %f\n' | sort

# ---------------------------------------------------------------------------
# 1. Unpack the -dev debs into a private prefix (no system change)
# ---------------------------------------------------------------------------
unpack_prefix() {
    rm -rf -- "${PREFIX}"
    mkdir -p "${PREFIX}"
    local pkg deb found
    for pkg in ${DEV_DEBS}; do
        deb="$(find "${DEB_DIR}" -maxdepth 1 -name "${pkg}_*.deb" | head -n1)"
        if [ -z "${deb}" ]; then
            warn "expected deb not found in ${DEB_DIR}: ${pkg}_*.deb"
            continue
        fi
        log "unpacking $(basename "${deb}")"
        dpkg-deb -x "${deb}" "${PREFIX}"
        found=1
    done
    [ -n "${found:-}" ] || die "none of these debs were found: ${DEV_DEBS}"
    log "prefix: $(summarise_tree "${PREFIX}")"
    # Sanity: the two headers we actually need must now exist. ldap.h lives
    # under the multiarch include dir on Debian/Ubuntu.
    local h found_hdr=0
    for h in usr/include/ldap.h usr/include/x86_64-linux-gnu/ldap.h \
             usr/include/sasl/sasl.h usr/include/x86_64-linux-gnu/sasl/sasl.h \
             usr/include/lber.h usr/include/x86_64-linux-gnu/lber.h; do
        if [ -e "${PREFIX}/${h}" ]; then ok "header ${h}"; found_hdr=1; fi
    done
    [ "${found_hdr}" -eq 1 ] || warn "no expected headers found in the prefix"
}
run "unpack -dev debs into a private prefix" unpack_prefix

# ---------------------------------------------------------------------------
# 2. Build with that prefix on the compiler search path
# ---------------------------------------------------------------------------
# NOTE: each include/lib directory needs its OWN -I / -L flag. Writing
# "-I${DIR1}:${DIR2}" makes gcc look for a single directory literally named
# "DIR1:DIR2", which silently fails and resurfaces as
# "lber.h: No such file or directory" even though the header is right there.
INCS_FLAGS="-I${PREFIX}/usr/include -I${PREFIX}/usr/include/x86_64-linux-gnu"
LIBS_FLAGS="-L${PREFIX}/usr/lib/x86_64-linux-gnu -L${PREFIX}/usr/lib"
INCS="${INCS_FLAGS}"
LIBS="${PREFIX}/usr/lib/x86_64-linux-gnu:${PREFIX}/usr/lib"

build_quarantined() {
    if [ ! -x "${VENV}/bin/python" ]; then
        python3 -m venv "${VENV}"
    fi
    local PY="${VENV}/bin/python"
    "${PY}" -m pip install --quiet --upgrade pip setuptools wheel

    local tmp="${WORK_DIR}/quarantine-wheels"
    mkdir -p "${tmp}"
    local sdist base ok_count=0 fail_count=0
    shopt -s nullglob
    for sdist in "${SRC_DIR}"/*.tar.gz "${SRC_DIR}"/*.zip; do
        base="$(basename "${sdist}")"
        log "rebuilding ${base} with deb-provided headers"
        if env \
                CFLAGS="${INCS_FLAGS} -O2" \
                CPPFLAGS="${INCS_FLAGS}" \
                CXXFLAGS="${INCS_FLAGS} -O2" \
                LDFLAGS="${LIBS_FLAGS}" \
                LD_LIBRARY_PATH="${LIBS}" \
                "${PY}" -m pip wheel --no-deps --no-cache-dir \
                    --no-build-isolation -w "${tmp}" "${sdist}" \
                >"${WORK_DIR}/rebuild-${base}.log" 2>&1; then
            ok "rebuilt ${base}"
            ok_count=$((ok_count + 1))
        else
            warn "still failing: ${base} (log ${WORK_DIR}/rebuild-${base}.log)"
            fail_count=$((fail_count + 1))
        fi
    done
    shopt -u nullglob

    if compgen -G "${tmp}/*.whl" >/dev/null; then
        cp -f "${tmp}"/*.whl "${WH}/"
    fi
    log "rebuild result: ${ok_count} ok, ${fail_count} failed"
    [ "${ok_count}" -gt 0 ]
}
run "rebuild quarantined sdists" build_quarantined

# ---------------------------------------------------------------------------
# 3. Move any successfully built wheel's project out of ODOO-FROM-APT.txt
# ---------------------------------------------------------------------------
run "update ODOO-FROM-APT.txt" python3 - "${WH}" "${OUT_DIR}/ODOO-FROM-APT.txt" "${SRC_DIR}" <<'PY'
import glob, os, re, sys

wh, apt_file, src_dir = sys.argv[1], sys.argv[2], sys.argv[3]
norm = lambda s: re.sub(r"[-_.]+", "-", s).lower()

wheel_projects = {norm(os.path.basename(p).split("-")[0]) for p in glob.glob(os.path.join(wh, "*.whl"))}

def project_of_sdist(base):
    stem = base[:-7] if base.endswith(".tar.gz") else base[:-4]
    return norm(stem.rsplit("-", 1)[0]) if "-" in stem else norm(stem)

still = []
for path in sorted(glob.glob(os.path.join(src_dir, "*"))):
    base = os.path.basename(path)
    proj = project_of_sdist(base)
    if proj in wheel_projects:
        print(f"resolved from sdist, removing from APT list: {base}")
        os.remove(path)
    else:
        still.append(proj)

existing = []
if os.path.exists(apt_file):
    existing = [l.strip() for l in open(apt_file, encoding="utf-8") if l.strip()]

kept = [e for e in existing if norm(e) not in wheel_projects]
with open(apt_file, "w", encoding="utf-8") as fh:
    for e in kept:
        fh.write(e + "\n")

print(f"ODOO-FROM-APT.txt now: {kept}")
if still:
    print(f"STILL unresolved from source: {still}")
PY

echo
printf 'wheelhouse odoo : %s wheels\n' "$(find "${WH}" -maxdepth 1 -name '*.whl' | wc -l | tr -d ' ')"
ls -1 "${SRC_DIR}" 2>/dev/null | sed 's/^/    still quarantined: /' || true
ok "done"
