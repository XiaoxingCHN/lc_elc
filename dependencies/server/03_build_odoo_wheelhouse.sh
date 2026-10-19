#!/usr/bin/env bash
#
# 03 — Build the Odoo 19 wheelhouse (cp310 / linux x86_64) and prove it resolves
#      with no network.
#
# Scope: ONLY the Odoo deployable. The crawler has its own wheelhouse
# (03a_requests_wheelhouse.sh) because Odoo pins requests==2.25.1 while the
# crawler needs requests==2.34.2 — resolving them together would conflict.
#
# Strategy:
#   1. pip download everything from the pinned revision's requirements.txt
#   2. build a wheel from every sdist that came down, so the offline target does
#      not need a compiler
#   3. AUTHORITATIVE CHECK: resolve the whole set with --no-index against the
#      wheelhouse. If a single wheel were missing this fails.
#
# Anything still left as an sdist after step 2 is reported explicitly, together
# with the -dev headers it would need on the target. Native builds happen only
# inside a throwaway venv under WORK_DIR; the WSL system is never touched.

set -euo pipefail
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

require_cmd python3 find sort
ensure_dirs

PY="${PYTHON:-python3}"
VENV="${WORK_DIR}/venv-odoo"
WH="${WHEEL_DIR_ODOO}"
REQ="${ODOO_DIR}/odoo-requirements.txt"
PYVER_EXPECT="3.10"

[ -f "${REQ}" ] || die "missing ${REQ} — run 02_fetch_odoo.sh first"

actual_ver="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
[ "${actual_ver}" = "${PYVER_EXPECT}" ] || die "need Python ${PYVER_EXPECT}, found ${actual_ver}"

log "interpreter : python ${actual_ver} ($(python3 -c 'import sys;print(sys.executable)'))"
log "requirements: ${REQ}"
log "wheelhouse  : ${WH}"

# ---------------------------------------------------------------------------
# 1. Throwaway venv (never the host's global Python)
# ---------------------------------------------------------------------------
if [ ! -x "${VENV}/bin/python" ]; then
    run "create throwaway venv (${VENV})" python3 -m venv "${VENV}"
fi
PYV="${VENV}/bin/python"
run "upgrade pip/setuptools/wheel inside the venv" \
    "${PYV}" -m pip install --quiet --upgrade pip setuptools wheel
log "venv pip: $("${PYV}" -m pip --version)"

# ---------------------------------------------------------------------------
# 2. Download everything (wheels where available, sdists otherwise)
# ---------------------------------------------------------------------------
# Packages whose C extension has no cp310 wheel AND whose sdist no longer
# builds under modern Cython are excluded here and supplied by APT instead
# (see python3-* in apt_packages.list). gevent 21.8.0 is the known case:
#   src/gevent/libev/corecext.pyx: undeclared name not builtin: long
# Odoo's own requirements header says these should be the distro python3-*
# packages, so this follows the supported path rather than working around it.
FROM_APT="${ODOO_FROM_APT:-gevent,python-ldap}"

FILTERED="${WORK_DIR}/odoo-requirements.filtered.txt"
if [ -n "${FROM_APT}" ]; then
    log "excluding (provided by APT as python3-*): ${FROM_APT}"
    awk -v skip="${FROM_APT}" '
        BEGIN { n = split(skip, names, /[ ,]+/) }
        {
            line = $0
            body = line; sub(/#.*/, "", body)
            # requirement name is the leading token before ==, >=, ; or space
            name = body
            sub(/[<>=!; ].*$/, "", name)
            gsub(/^[ \t]+|[ \t]+$/, "", name)
            for (i = 1; i <= n; i++) {
                if (names[i] != "" && tolower(name) == tolower(names[i])) next
            }
            print line
        }
    ' "${REQ}" > "${FILTERED}"
else
    cp "${REQ}" "${FILTERED}"
fi

run "pip download -r odoo-requirements.txt (filtered)" \
    "${PYV}" -m pip download -r "${FILTERED}" -d "${WH}"

count_whl() { find "${WH}" -maxdepth 1 -name '*.whl' | wc -l | tr -d ' '; }
count_sdist() { find "${WH}" -maxdepth 1 \( -name '*.tar.gz' -o -name '*.zip' \) | wc -l | tr -d ' '; }
log "after download: $(count_whl) wheels, $(count_sdist) sdists"

# ---------------------------------------------------------------------------
# 3. Build wheels from the sdists (this is where missing headers bite)
# ---------------------------------------------------------------------------
BUILD_FAILED="${WORK_DIR}/sdist-build-failures.txt"
: > "${BUILD_FAILED}"

build_sdists() {
    local tmp="${WORK_DIR}/built-wheels"
    mkdir -p "${tmp}"
    local sdist base
    shopt -s nullglob
    for sdist in "${WH}"/*.tar.gz "${WH}"/*.zip; do
        base="$(basename "${sdist}")"
        log "building wheel from ${base}"
        if "${PYV}" -m pip wheel --no-deps --no-cache-dir -w "${tmp}" "${sdist}" \
                >"${WORK_DIR}/build-${base}.log" 2>&1; then
            ok "built ${base}"
        else
            warn "FAILED to build ${base} (log: ${WORK_DIR}/build-${base}.log)"
            echo "${base}" >> "${BUILD_FAILED}"
        fi
    done
    shopt -u nullglob
    if compgen -G "${tmp}/*.whl" >/dev/null; then
        cp -f "${tmp}"/*.whl "${WH}/"
    fi
}
if [ "$(count_sdist)" -gt 0 ]; then
    run "build wheels from sdists" build_sdists
fi

log "after build: $(count_whl) wheels, $(count_sdist) sdists, $(wc -l < "${BUILD_FAILED}" | tr -d ' ') build failures"

# ---------------------------------------------------------------------------
# 3b. Keep the wheelhouse PURE WHEELS
# ---------------------------------------------------------------------------
# An offline `pip install --no-index` that finds an sdist will try to compile it,
# and with no index it cannot even fetch its build backend — that is what made
# the first offline check fail on python-ldap. So: drop sdists that were
# successfully converted, and move the unconverted ones out of the wheelhouse
# into sdists-odoo/ and report them.
run "purge converted sdists / quarantine the rest" \
    env WH="${WH}" OUT_DIR="${OUT_DIR}" python3 - <<'PY'
import glob, os, re

wh = os.environ["WH"]
quarantine = os.path.join(os.environ["OUT_DIR"], "sdists-odoo")
os.makedirs(quarantine, exist_ok=True)

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

wheel_projects = set()
for path in glob.glob(os.path.join(wh, "*.whl")):
    wheel_projects.add(norm(os.path.basename(path).split("-")[0]))

dropped, moved = [], []
for path in sorted(glob.glob(os.path.join(wh, "*.tar.gz"))
                   + glob.glob(os.path.join(wh, "*.zip"))):
    base = os.path.basename(path)
    stem = base[:-7] if base.endswith(".tar.gz") else base[:-4]
    project = norm(stem.rsplit("-", 1)[0]) if "-" in stem else norm(stem)
    if project in wheel_projects:
        os.remove(path)
        dropped.append(base)
    else:
        os.replace(path, os.path.join(quarantine, base))
        moved.append(base)

print(f"wheelhouse is now pure wheels: dropped {len(dropped)} converted sdist(s)")
for b in dropped:
    print(f"    dropped  {b}")
print(f"quarantined {len(moved)} unconverted sdist(s) -> sdists-odoo/")
for b in moved:
    print(f"    moved    {b}")
PY

# ---------------------------------------------------------------------------
# 4. AUTHORITATIVE offline check
# ---------------------------------------------------------------------------
run "offline resolution check (--no-index over ${WH})" \
    "${PYV}" -m pip install --no-index --find-links "${WH}" \
        --no-build-isolation \
        -r "${FILTERED}" --dry-run --ignore-installed \
        --report "${OUT_DIR}/pip-resolve-odoo.json"

run "write constraints-odoo.txt" \
    "${PYV}" - "${OUT_DIR}/pip-resolve-odoo.json" "${OUT_DIR}/constraints-odoo.txt" <<'PY'
import json, sys
src, dest = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
pins = {}
for item in data.get("install", []):
    m = item.get("metadata", {})
    if m.get("name") and m.get("version"):
        pins[m["name"]] = m["version"]
with open(dest, "w", encoding="utf-8") as fh:
    fh.write("# Exact versions resolvable OFFLINE from wheelhouse-odoo/.\n")
    fh.write("# Generated by 03_build_odoo_wheelhouse.sh; Odoo 19 pinned revision.\n")
    for name in sorted(pins, key=str.lower):
        fh.write(f"{name}=={pins[name]}\n")
print(f"{len(pins)} distributions pinned -> {dest}")
PY

# ---------------------------------------------------------------------------
# 5. Report precisely what is still not a wheel
# ---------------------------------------------------------------------------
remaining="${OUT_DIR}/ODOO-SDIST-REMAINING.txt"
: > "${remaining}"
find "${WH}" -maxdepth 1 \( -name '*.tar.gz' -o -name '*.zip' \) -printf '%f\n' | sort >> "${remaining}"

# Record what the wheelhouse deliberately does NOT cover, so the target's
# install procedure is unambiguous.
apt_file="${OUT_DIR}/ODOO-FROM-APT.txt"
if [ -n "${FROM_APT}" ]; then
    printf '%s\n' "${FROM_APT}" | tr ',' '\n' | tr -d ' ' | grep -v '^$' > "${apt_file}"
else
    : > "${apt_file}"
fi

echo
printf 'wheelhouse   : %s wheels, %s sdist(s), %s\n' \
    "$(count_whl)" "$(count_sdist)" "$(du -sh "${WH}" | cut -f1)"

if [ -s "${apt_file}" ]; then
    warn "NOT in this wheelhouse (install these from the APT bundle, they are"
    warn "shipped as python3-* packages in debs/):"
    sed 's/^/    /' "${apt_file}" >&2
    warn "the offline check above therefore covers the filtered requirement set."
fi

if [ -s "${remaining}" ]; then
    warn "these Odoo requirements are still source distributions:"
    sed 's/^/    /' "${remaining}" >&2
    warn "the offline target will need a compiler plus these -dev packages:"
    warn "    libxslt1-dev liblcms2-dev libopenjp2-7-dev libtiff5-dev"
    warn "    libldap2-dev libsasl2-dev libffi-dev"
    warn "(they are all present in the APT bundle produced by 01_*; installing it"
    warn " on the target makes the source builds work)"
else
    ok "every Odoo requirement is a wheel — the target needs no compiler"
fi

if [ -s "${BUILD_FAILED}" ]; then
    cp "${BUILD_FAILED}" "${OUT_DIR}/ODOO-SDIST-BUILD-FAILURES.txt"
    warn "build failures recorded in ${OUT_DIR}/ODOO-SDIST-BUILD-FAILURES.txt"
fi

case "${VENV}" in
    "${WORK_DIR}"/*) rm -rf -- "${VENV}" ;;
    *) warn "not removing unexpected venv path: ${VENV}" ;;
esac
ok "done; WSL system and global Python untouched"
