#!/usr/bin/env bash
#
# Shared helpers for the Ubuntu 22.04 server dependency preparer.
#
# This file is meant to be SOURCED, not executed:
#   . "$(dirname "$0")/lib/common.sh"
#
# Policy enforced here:
#   * every external command is run through `run` / `run_soft`, which check the
#     exit code. `run` aborts the whole script on a non-zero exit; there is no
#     silent failure path.
#   * no command may install into the host's global Python. The scripts create
#     their own venv under a scratch directory and delete it afterwards.
#   * nothing here touches a production server. These scripts are run on a
#     NETWORKED Ubuntu 22.04 prep machine (or a container) to produce a bundle.

set -euo pipefail

if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_CYA=$'\033[36m'; C_RST=$'\033[0m'
else
    C_RED=''; C_GRN=''; C_YEL=''; C_CYA=''; C_RST=''
fi

log()  { printf '%s[%s]%s %s\n' "$C_CYA" "$(date +%H:%M:%S)" "$C_RST" "$*"; }
ok()   { printf '%sOK%s   %s\n' "$C_GRN" "$C_RST" "$*"; }
warn() { printf '%sWARN%s %s\n' "$C_YEL" "$C_RST" "$*" >&2; }
die()  { printf '%sFAIL%s %s\n' "$C_RED" "$C_RST" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Exit-code-checked command runner
# ---------------------------------------------------------------------------
run() {
    local label="$1"; shift
    log "==> ${label}"
    set +e
    "$@"
    local code=$?
    set -e
    if [ "$code" -ne 0 ]; then
        printf '%sFAILED%s %s (exit code %s)\n' "$C_RED" "$C_RST" "$label" "$code" >&2
        exit "$code"
    fi
    ok "${label}"
}

# Tolerant variant: records the failure and returns the exit code.
# Use ONLY for genuinely optional components, and report the result.
run_soft() {
    local label="$1"; shift
    log "==> ${label} (tolerant)"
    set +e
    "$@"
    local code=$?
    set -e
    if [ "$code" -ne 0 ]; then
        warn "${label} exited ${code} (recorded, not fatal)"
        return "$code"
    fi
    ok "${label}"
    return 0
}

require_cmd() {
    local missing=()
    for c in "$@"; do
        command -v "$c" >/dev/null 2>&1 || missing+=("$c")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        die "missing required command(s): ${missing[*]}
On a plain Ubuntu 22.04 image run:
  apt-get update && apt-get install -y --no-install-recommends ${missing[*]}"
    fi
}

# ---------------------------------------------------------------------------
# Paths / env
# ---------------------------------------------------------------------------
SERVER_DEPS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Where the shippable bundle is written. Override with OUT_DIR=...
OUT_DIR="${OUT_DIR:-${SERVER_DEPS_DIR}/out}"

# Scratch space for clones / venvs. Never inside the bundle.
WORK_DIR="${WORK_DIR:-${SERVER_DEPS_DIR}/.work}"

DEB_DIR="${OUT_DIR}/debs"
ODOO_DIR="${OUT_DIR}/odoo"

# TWO SEPARATE WHEELHOUSES on purpose.
# Odoo 19 pins requests==2.25.1 (jammy wheel) while the crawler service needs
# requests==2.34.2. They are different deployables with different venvs, so
# sharing one wheelhouse would create a pip conflict the moment both requirement
# files were resolved together.
WHEEL_DIR="${OUT_DIR}/wheelhouse-odoo"
WHEEL_DIR_ODOO="${OUT_DIR}/wheelhouse-odoo"
WHEEL_DIR_CRAWLER="${OUT_DIR}/wheelhouse-crawler"

ODOO_REPO="${ODOO_REPO:-https://github.com/odoo/odoo.git}"
ODOO_BRANCH="${ODOO_BRANCH:-19.0}"
# Set ODOO_REV to a full commit SHA to pin an exact revision instead of the
# branch tip. The preparer always records the resolved SHA either way.
ODOO_REV="${ODOO_REV:-}"

# Crawler dependency file shipped with the server bundle (read-only input; the
# preparer never edits it).
#   SERVER_DEPS_DIR = <project>/lc_elc/dependencies/server
#   ../..           = <project>/lc_elc
PROJECT_LC_ELC_DIR="$(cd -- "${SERVER_DEPS_DIR}/../.." && pwd)"
CRAWLER_REQ="${CRAWLER_REQ:-${PROJECT_LC_ELC_DIR}/server/ubuntu22.04/crawler/requirements.txt}"

APT_PKG_LIST="${APT_PKG_LIST:-${SERVER_DEPS_DIR}/apt_packages.list}"

# wkhtmltopdf is optional (PDF report rendering only). If jammy's universe repo
# does not offer it, the preparer falls back to the upstream release .deb.
WKHTMLTOPDF_FALLBACK_URL="${WKHTMLTOPDF_FALLBACK_URL:-}"
WITH_NODE="${WITH_NODE:-1}"

ensure_dirs() {
    mkdir -p "${OUT_DIR}" "${DEB_DIR}" "${ODOO_DIR}" \
             "${WHEEL_DIR_ODOO}" "${WHEEL_DIR_CRAWLER}" "${WORK_DIR}"
}

read_pkg_list() {
    # Strips comments and blank lines from apt_packages.list.
    # Lines starting with "!" are OPTIONAL and only used when WITH_OPTIONAL=1.
    [ -f "${APT_PKG_LIST}" ] || die "package list not found: ${APT_PKG_LIST}"
    REQUIRED_PKGS=()
    OPTIONAL_PKGS=()
    while IFS= read -r raw; do
        line="${raw%%#*}"
        line="$(printf '%s' "${line}" | tr -d '[:space:]')"
        [ -z "${line}" ] && continue
        case "${line}" in
            '!'*) OPTIONAL_PKGS+=("${line#!}") ;;
            *)    REQUIRED_PKGS+=("${line}") ;;
        esac
    done < "${APT_PKG_LIST}"
    [ "${#REQUIRED_PKGS[@]}" -gt 0 ] || die "no packages parsed from ${APT_PKG_LIST}"
}

assert_ubuntu_2204() {
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "22.04" ]; then
            ok "host is Ubuntu 22.04 (codename ${VERSION_CODENAME:-?})"
            return 0
        fi
        warn "host is ${ID:-?} ${VERSION_ID:-?}, not Ubuntu 22.04"
    else
        warn "/etc/os-release not readable; cannot confirm the host release"
    fi
    if [ "${ALLOW_OTHER_RELEASE:-0}" != "1" ]; then
        die "refusing to build a 22.04 bundle on a non-22.04 host.
Run this inside a clean ubuntu:22.04 container (see container_prepare.sh),
or set ALLOW_OTHER_RELEASE=1 to override deliberately."
    fi
    warn "ALLOW_OTHER_RELEASE=1: continuing on a non-22.04 host (bundle may not match)"
}

summarise_tree() {
    local dir="$1"
    if [ -d "${dir}" ]; then
        printf '%s files, %s\n' \
            "$(find "${dir}" -type f | wc -l | tr -d ' ')" \
            "$(du -sh "${dir}" 2>/dev/null | cut -f1)"
    else
        printf 'absent\n'
    fi
}
