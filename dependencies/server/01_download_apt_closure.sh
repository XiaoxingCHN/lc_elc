#!/usr/bin/env bash
#
# 01 — Download the COMPLETE APT dependency closure for Ubuntu 22.04 amd64.
#
# ISOLATION (nothing on this WSL system is modified)
# --------------------------------------------------
# Every apt path is redirected into the delivery directory and an EMPTY dpkg
# status file is used, so apt behaves as if this machine had nothing installed:
#
#   Dir::State::status   -> <OUT_DIR>/apt/status      (EMPTY FILE)
#   Dir::State::lists    -> <OUT_DIR>/apt/lists
#   Dir::Cache           -> <OUT_DIR>/apt/cache
#   Dir::Cache::archives -> <OUT_DIR>/debs            (the payload)
#   Dir::Etc::sourcelist -> <OUT_DIR>/apt/sources.list (jammy Ubuntu only)
#   Dir::Etc::sourceparts-> "-"                        (third-party repos OFF)
#
# Why the empty status file is the important part: with nothing marked as
# installed, apt cannot consider any dependency "already satisfied", so the
# closure it resolves is the FULL one — including libc6, dpkg and friends.
# That is exactly what an offline target needs, and it is why the bundle is not
# affected by whatever happens to be installed on the machine that builds it.
#
# APT::Get::Download-Only=true plus --download-only means apt fetches .deb files
# and makes NO changes to the system. No sudo, no dpkg run, no /var/lib writes.
#
# Output: ${OUT_DIR}/debs/*.deb plus Packages / Packages.gz / PACKAGES.txt

set -euo pipefail
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

assert_ubuntu_2204
require_cmd apt-get apt-cache dpkg-deb dpkg-scanpackages gzip awk sort find du sed
ensure_dirs
read_pkg_list

APTROOT="${APTROOT:-${OUT_DIR}/apt}"
APT_LOG="${OUT_DIR}/apt-download.log"

TOP=("${REQUIRED_PKGS[@]}")
OPTIONAL=()
if [ "${WITH_OPTIONAL:-1}" = "1" ] && [ "${#OPTIONAL_PKGS[@]}" -gt 0 ]; then
    OPTIONAL=("${OPTIONAL_PKGS[@]}")
fi

log "OUT_DIR   : ${OUT_DIR}"
log "APTROOT   : ${APTROOT}   (isolated: state/cache/lists all live here)"
log "requested : ${#TOP[@]} required, ${#OPTIONAL[@]} optional"

# ---------------------------------------------------------------------------
# 1. Build the isolated apt root
# ---------------------------------------------------------------------------
run "create isolated apt root" bash -c "
    mkdir -p '${APTROOT}/lists/partial' '${APTROOT}/cache/archives/partial' '${DEB_DIR}'
    : > '${APTROOT}/status'
    : > '${APTROOT}/extended_states'
    chmod 0644 '${APTROOT}/status'
"

# Only the stock jammy Ubuntu repositories. The host's sources.list also has
# NVIDIA CUDA and ROS2 entries; those are deliberately excluded so the bundle is
# reproducible and cannot pick up a third-party version of a system library.
gen_sources() {
    local out="${APTROOT}/sources.list"
    grep -hE '^[[:space:]]*deb[[:space:]]+.*(archive\.ubuntu\.com|security\.ubuntu\.com)' \
        /etc/apt/sources.list 2>/dev/null > "${out}" || true
    if [ ! -s "${out}" ]; then
        log "no stock Ubuntu entries found; writing the standard jammy sources"
        cat > "${out}" <<'EOF'
deb https://archive.ubuntu.com/ubuntu/ jammy main restricted universe multiverse
deb https://archive.ubuntu.com/ubuntu/ jammy-updates main restricted universe multiverse
deb https://archive.ubuntu.com/ubuntu/ jammy-backports main restricted universe multiverse
deb https://archive.ubuntu.com/ubuntu/ jammy-security main restricted universe multiverse
EOF
    fi
    log "isolated sources.list:"; sed 's/^/    /' "${out}"
}
run "generate isolated sources.list (stock jammy only)" gen_sources

# ---------------------------------------------------------------------------
# 2. Common apt options
# ---------------------------------------------------------------------------
APT_OPTS=(
    -o "Dir::Etc::sourcelist=${APTROOT}/sources.list"
    -o "Dir::Etc::sourceparts=-"
    -o "Dir::State::status=${APTROOT}/status"
    -o "Dir::State::lists=${APTROOT}/lists"
    -o "Dir::State::extended_states=${APTROOT}/extended_states"
    -o "Dir::Cache=${APTROOT}/cache"
    -o "Dir::Cache::archives=${DEB_DIR}"
    -o "Dir::Etc::trusted=/etc/apt/trusted.gpg"
    -o "Dir::Etc::trustedparts=/etc/apt/trusted.gpg.d"
    -o "APT::Architecture=amd64"
    -o "APT::Architectures=amd64"
    -o "APT::Get::Download-Only=true"
    -o "Acquire::Languages=none"
    -o "DPkg::Use-Pty=0"
    -o "Debug::NoLocking=1"
    -o "Acquire::Retries=3"
)

assert_isolated() {
    # Hard guarantee: refuse to run if the resolved status path is not ours.
    local resolved
    resolved="$(apt-config dump "${APT_OPTS[@]}" 2>/dev/null | sed -n 's/^Dir::State::status "\(.*\)";$/\1/p')"
    if [ "${resolved}" != "${APTROOT}/status" ]; then
        die "apt status path is '${resolved}', expected '${APTROOT}/status'.
Refusing to run: a real system package database could be touched."
    fi
    if [ ! -f "${APTROOT}/status" ] || [ -s "${APTROOT}/status" ]; then
        die "isolated status file must exist and be EMPTY: ${APTROOT}/status"
    fi
    ok "apt is fully isolated (status empty and redirected)"
}
run "verify apt isolation" assert_isolated

# ---------------------------------------------------------------------------
# 3. Refresh lists into the isolated root
# ---------------------------------------------------------------------------
run "apt-get update (isolated lists)" \
    apt-get "${APT_OPTS[@]}" update

# ---------------------------------------------------------------------------
# 4. Download the full closure
# ---------------------------------------------------------------------------
# --download-only + APT::Get::Download-Only=true + empty status:
#   * every dependency is unsatisfied, so all of them must be fetched
#   * nothing is unpacked, configured or installed
run "apt-get install --download-only (${#TOP[@]} required + ${#OPTIONAL[@]} optional)" \
    apt-get "${APT_OPTS[@]}" install -y --download-only --no-install-recommends \
        "${TOP[@]}" ${OPTIONAL[@]+"${OPTIONAL[@]}"} 2>&1 | tee "${APT_LOG}"

deb_count="$(find "${DEB_DIR}" -maxdepth 1 -name '*.deb' | wc -l | tr -d ' ')"
log "downloaded ${deb_count} .deb files ($(summarise_tree "${DEB_DIR}"))"

# ---------------------------------------------------------------------------
# 5. Work out what is still missing (optional components only)
# ---------------------------------------------------------------------------
MISS_OPT="${OUT_DIR}/MISSING-OPTIONAL.txt"
: > "${MISS_OPT}"
for pkg in "${OPTIONAL[@]}"; do
    if ! find "${DEB_DIR}" -maxdepth 1 -name "${pkg%%:*}_*.deb" | grep -q .; then
        # Some optional packages are virtual or name-mapped; ask apt directly.
        if ! apt-cache "${APT_OPTS[@]}" policy "${pkg}" 2>/dev/null | grep -q 'Candidate: [^(]'; then
            echo "${pkg}" >> "${MISS_OPT}"
        fi
    fi
done

if grep -qx 'wkhtmltopdf' "${MISS_OPT}" 2>/dev/null; then
    if [ -n "${WKHTMLTOPDF_FALLBACK_URL}" ]; then
        require_cmd curl
        fname="$(basename "${WKHTMLTOPDF_FALLBACK_URL}")"
        if run_soft "download wkhtmltopdf fallback .deb" \
                curl -fL --retry 3 -o "${DEB_DIR}/${fname}" "${WKHTMLTOPDF_FALLBACK_URL}"; then
            sed -i '/^wkhtmltopdf$/d' "${MISS_OPT}" || true
        fi
    else
        warn "wkhtmltopdf is not resolvable from the stock jammy repos and no"
        warn "WKHTMLTOPDF_FALLBACK_URL was set. PDF report printing will not work"
        warn "offline. This is OPTIONAL — Odoo's web UI, the JSON-RPC API, the"
        warn "crawler and the Flutter client do not need it."
    fi
fi

if [ -s "${MISS_OPT}" ]; then
    warn "optional packages NOT included: $(tr '\n' ' ' < "${MISS_OPT}")"
else
    ok "all optional packages resolved"
fi

# ---------------------------------------------------------------------------
# 6. Local-repo index + inventory (generated here; the offline target then
#    only needs apt, not dpkg-dev)
# ---------------------------------------------------------------------------
run "generate local repo index (Packages, Packages.gz)" bash -c "
    cd '${DEB_DIR}'
    dpkg-scanpackages -m . > Packages 2>/dev/null
    gzip -9 -kf Packages
"

run "write debs/PACKAGES.txt (name / version / arch)" bash -c "
    cd '${DEB_DIR}'
    for f in *.deb; do dpkg-deb -f \"\$f\" Package Version Architecture | paste - - -; done | sort > PACKAGES.txt
"

# ---------------------------------------------------------------------------
# 7. Verdict
# ---------------------------------------------------------------------------
if [ "${deb_count}" -lt 100 ]; then
    die "only ${deb_count} .deb files downloaded.
With an EMPTY dpkg status the closure for this package set must be several
hundred packages, so something is wrong (failed apt-get update?). See ${APT_LOG}"
fi

for required in Packages Packages.gz PACKAGES.txt; do
    [ -s "${DEB_DIR}/${required}" ] || die "missing generated index file: ${DEB_DIR}/${required}"
done

printf 'debs        : %s files, %s\n' "${deb_count}" "$(du -sh "${DEB_DIR}" | cut -f1)"
printf 'index       : Packages + Packages.gz + PACKAGES.txt\n'
ok "APT closure complete and isolated; system package database untouched"
