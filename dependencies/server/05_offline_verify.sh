#!/usr/bin/env bash
#
# 05 — Offline acceptance check. Run this ON THE TARGET, with no network.
#
# Level 1 (always): integrity + real offline installation into throwaway venvs.
#   * every file matches SHA256SUMS
#   * every .deb parses (dpkg-deb)
#   * the Odoo source tarball is readable and complete
#   * wheelhouse-odoo and wheelhouse-crawler each install with --no-index into a
#     fresh venv — a REAL install, not a dry run, so it is the strongest
#     statement available without touching the system Python
#   * python3-gevent (Odoo's one APT-provided runtime dependency) is present
#
# Level 2 (--docker, requires a working Docker engine):
#   * builds a local apt repo from debs/ and installs the package set inside a
#     clean ubuntu:22.04 with --network none. That is what proves the APT
#     closure is actually complete. Skipped with a clear message if the engine
#     is unavailable — starting Docker Desktop is never attempted.
#
# Exit code 0 = every executed check passed. Any failed check aborts.

set -euo pipefail
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

WITH_DOCKER=0
[ "${1:-}" = "--docker" ] && WITH_DOCKER=1

cd "${OUT_DIR}"

echo "=============================================================="
echo " offline acceptance check"
echo " out dir : ${OUT_DIR}"
echo " docker  : $([ "${WITH_DOCKER}" -eq 1 ] && echo 'level 1 + 2' || echo 'level 1 only')"
echo "=============================================================="

# ---------------------------------------------------------------------------
# 1. Hashes
# ---------------------------------------------------------------------------
run "verify SHA256SUMS" sha256sum -c SHA256SUMS --quiet
hashed="$(wc -l < SHA256SUMS | tr -d ' ')"
ok "${hashed} files match SHA256SUMS"

# ---------------------------------------------------------------------------
# 2. Every .deb is a readable package
# ---------------------------------------------------------------------------
check_debs() {
    local bad=0 total=0 deb
    for deb in debs/*.deb; do
        total=$((total + 1))
        if ! dpkg-deb --info "${deb}" >/dev/null 2>&1; then
            warn "corrupt or unreadable: ${deb}"
            bad=$((bad + 1))
        fi
    done
    log "checked ${total} .deb files, ${bad} bad"
    [ "${bad}" -eq 0 ] || die "${bad} .deb file(s) are corrupt — do not install this bundle"
}
run "validate every .deb (dpkg-deb)" check_debs

# ---------------------------------------------------------------------------
# 3. Odoo source tarball
# ---------------------------------------------------------------------------
odoo_tar="$(find odoo -maxdepth 1 -name 'odoo-*.tar.gz' | head -n1)"
[ -n "${odoo_tar}" ] || die "no odoo-*.tar.gz found under odoo/"
# shellcheck disable=SC2016
run "read the Odoo tarball" bash -c "tar -tzf '${odoo_tar}' > /tmp/.lcsc_odoo_listing 2>/dev/null"
entries="$(wc -l < /tmp/.lcsc_odoo_listing | tr -d ' ')"
[ "${entries}" -gt 1000 ] || die "Odoo tarball lists only ${entries} entries"
grep -q '/odoo-bin$' /tmp/.lcsc_odoo_listing || die "odoo-bin not present in the tarball"
rm -f /tmp/.lcsc_odoo_listing
ok "Odoo tarball OK: ${entries} entries, odoo-bin present"

# ---------------------------------------------------------------------------
# 4. Real offline wheel installation
# ---------------------------------------------------------------------------
verify_wheelhouse() {
    local wh="$1" req="$2" label="$3"
    if [ ! -d "${wh}" ]; then
        warn "${label}: wheelhouse ${wh} not present — skipped"
        return 0
    fi
    if ! python3 -c 'import venv' 2>/dev/null; then
        warn "${label}: python3-venv is not installed on this host; install"
        warn "  python3-venv from debs/ first, then re-run this script."
        return 0
    fi
    [ -f "${req}" ] || { warn "${label}: requirements ${req} missing — skipped"; return 0; }

    local venv
    venv="$(mktemp -d)/venv"
    python3 -m venv "${venv}"
    "${venv}/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

    # No --index-url, no network: pip may only read the local directory.
    "${venv}/bin/python" -m pip install \
        --no-index --find-links "${wh}" \
        --no-build-isolation \
        -r "${req}" \
        >"/tmp/lcsc-pip-${label}.log" 2>&1 \
        || { tail -30 "/tmp/lcsc-pip-${label}.log" >&2; die "${label}: offline install FAILED"; }

    local n
    n="$("${venv}/bin/python" -m pip list --format=freeze | wc -l | tr -d ' ')"
    ok "${label}: installed ${n} distributions offline from $(basename "${wh}")"
    rm -rf -- "$(dirname "${venv}")"
}

# The Odoo wheelhouse deliberately excludes gevent (APT provides it); verify
# against the filtered requirement list that was produced during preparation.
odoo_req="${WORK_DIR_ODOO_REQ:-}"
if [ -f "odoo/odoo-requirements.txt" ]; then
    filtered="/tmp/lcsc-odoo-req-offline.txt"
    from_apt="$( [ -f ODOO-FROM-APT.txt ] && tr '\n' ' ' < ODOO-FROM-APT.txt || true )"
    log "excluding (provided by APT): ${from_apt:-<none>}"
    awk -v skip="${from_apt}" '
        BEGIN { n = split(skip, names, /[ ,]+/) }
        {
            body = $0; sub(/#.*/, "", body)
            name = body; sub(/[<>=!; ].*$/, "", name); gsub(/^[ \t]+|[ \t]+$/, "", name)
            for (i = 1; i <= n; i++) if (names[i] != "" && tolower(name) == tolower(names[i])) next
            print $0
        }
    ' odoo/odoo-requirements.txt > "${filtered}"
    run "offline install: Odoo wheelhouse" verify_wheelhouse "${PWD}/wheelhouse-odoo" "${filtered}" "odoo"
fi

if [ -f "crawler-requirements.txt" ]; then
    run "offline install: crawler wheelhouse" \
        verify_wheelhouse "${PWD}/wheelhouse-crawler" "${PWD}/crawler-requirements.txt" "crawler"
fi

# ---------------------------------------------------------------------------
# 5. The APT-provided runtime dependencies really are in the bundle
# ---------------------------------------------------------------------------
check_apt_provided() {
    local missing=0 pkg
    for pkg in ${APT_EXPECT:-python3-gevent python3-greenlet python3-lxml python3-psycopg2 python3-ldap python3-pil python3-psutil postgresql-14}; do
        if find debs -maxdepth 1 -name "${pkg}_*.deb" | grep -q .; then
            :
        else
            warn "expected .deb not found: ${pkg}"
            missing=$((missing + 1))
        fi
    done
    [ "${missing}" -eq 0 ] || die "${missing} expected package(s) missing from debs/"
    ok "all expected APT-provided packages are present"
}
run "check APT-provided runtime packages" check_apt_provided

# ---------------------------------------------------------------------------
# 6. Level 2: prove the closure installs in a clean, network-less container
# ---------------------------------------------------------------------------
if [ "${WITH_DOCKER}" -eq 1 ]; then
    if ! command -v docker >/dev/null 2>&1; then
        warn "docker CLI not found — level 2 SKIPPED (level 1 already passed)"
    elif ! docker info >/dev/null 2>&1; then
        warn "docker engine not reachable — level 2 SKIPPED (level 1 already passed)"
        warn "start the engine yourself if you want this check; this script will not."
    else
        pkgs="$(grep -vE '^\s*(#|$)' apt_packages.list | tr -d '[:blank:]' | sed 's/^!//' | tr '\n' ' ')"
        log "installing in clean ubuntu:22.04 with --network none: ${pkgs}"
        run "level 2: apt install from debs/ in a network-less container" \
            docker run --rm --network none \
                -v "${PWD}/debs:/debs:ro" \
                -e "PKGS=${pkgs}" \
                ubuntu:22.04 \
                bash -c '
                    set -euo pipefail
                    echo "deb [trusted=yes] file:/debs ./" > /etc/apt/sources.list.d/local.list
                    apt-get update \
                        -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/local.list \
                        -o Dir::Etc::sourceparts=- \
                        -o APT::Get::List-Cleanup=0 >/dev/null
                    apt-get install -y --no-install-recommends ${PKGS}
                    echo "INSTALL-OK: local repo closure is complete"
                '
        ok "level 2 passed: the APT closure installs cleanly with no network"
    fi
else
    log "level 2 not requested (re-run with --docker to include it)"
fi

echo
echo "=============================================================="
echo " OFFLINE ACCEPTANCE PASSED"
echo "=============================================================="
echo "checked : $(wc -l < SHA256SUMS | tr -d ' ') hashed files, $(find debs -name '*.deb' | wc -l | tr -d ' ') debs"
echo "wheels  : odoo=$(find wheelhouse-odoo -name '*.whl' 2>/dev/null | wc -l | tr -d ' ') crawler=$(find wheelhouse-crawler -name '*.whl' 2>/dev/null | wc -l | tr -d ' ')"
echo "odoo    : ${odoo_tar}"
if [ "${WITH_DOCKER}" -eq 0 ]; then
    echo
    echo "NOTE: level 2 (clean-container apt install) was NOT run."
fi
