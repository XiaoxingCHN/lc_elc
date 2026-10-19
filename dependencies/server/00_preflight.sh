#!/usr/bin/env bash
#
# 00 — Preflight for the offline dependency preparer.
#
# Read-only. Reports the environment and, critically, which hosts are reachable,
# because the plan changes depending on whether github.com works from here.
#
# Run inside the WSL distro:
#   wsl -d Ubuntu-22.04 --cd <project> --exec bash --noprofile --norc \
#       lc_elc/dependencies/server/00_preflight.sh

set -uo pipefail

echo "=============================================================="
echo " preflight: offline dependency preparer"
echo "=============================================================="

echo
echo "--- OS ---"
if [ -r /etc/os-release ]; then . /etc/os-release; echo "${PRETTY_NAME:-unknown}"; else echo "unknown"; fi
echo "kernel : $(uname -r)"
echo "arch   : $(dpkg --print-architecture 2>/dev/null || uname -m)"

echo
echo "--- toolchain ---"
for c in python3 pip3 gcc git curl dpkg-deb dpkg-scanpackages apt-get; do
    if command -v "$c" >/dev/null 2>&1; then
        printf '%-20s %s\n' "$c" "$(command -v "$c")"
    else
        printf '%-20s MISSING\n' "$c"
    fi
done
python3 --version 2>&1 | sed 's/^/python3 version      /'
python3 -c 'import venv,sys;print("venv module          OK")' 2>/dev/null || echo "venv module          MISSING"
gcc --version 2>/dev/null | head -1 | sed 's/^/gcc                  /'

echo
echo "--- headers relevant to Odoo C-extension builds ---"
for h in \
    /usr/include/libxml2/libxml/parser.h \
    /usr/include/libxslt/xslt.h \
    /usr/include/jpeglib.h \
    /usr/include/png.h \
    /usr/include/freetype2/ft2build.h \
    /usr/include/lcms2.h \
    /usr/include/openjpeg-2.5/openjpeg.h \
    /usr/include/webp/decode.h \
    /usr/include/tiff.h \
    /usr/include/postgresql/libpq-fe.h \
    /usr/include/ldap.h \
    /usr/include/sasl/sasl.h \
    /usr/include/openssl/ssl.h \
    /usr/include/ffi.h \
    /usr/include/zlib.h
do
    if [ -e "$h" ]; then printf 'present  %s\n' "$h"; else printf 'ABSENT   %s\n' "$h"; fi
done
printf 'libpq-fe.h via pg_config: %s\n' "$(pg_config --includedir 2>/dev/null || echo 'pg_config not found')"

echo
echo "--- disk free ---"
df -h . 2>/dev/null | tail -1 | sed 's/^/project dir  /'
df -h /tmp 2>/dev/null | tail -1 | sed 's/^/tmp          /'
df -h / 2>/dev/null | tail -1 | sed 's/^/root fs      /'

echo
echo "--- apt sources (read-only) ---"
grep -hE '^[[:space:]]*deb ' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null | head -8
echo "components: $(grep -hE '^[[:space:]]*deb ' /etc/apt/sources.list 2>/dev/null | head -1)"

echo
echo "--- network ---"
python3 - <<'PY'
import socket, ssl, urllib.request

hosts = [
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "pypi.org",
    "files.pythonhosted.org",
    "github.com",
    "codeload.github.com",
    "nightly.odoo.com",
]

for h in hosts:
    try:
        socket.getaddrinfo(h, 443, proto=socket.IPPROTO_TCP)
        dns = "DNS_OK"
    except Exception as exc:                       # noqa: BLE001
        print(f"{h:26s} DNS_FAIL   {type(exc).__name__}")
        continue
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(f"https://{h}/", timeout=8, context=ctx) as resp:
            print(f"{h:26s} {dns}  HTTPS {resp.status}")
    except Exception as exc:                       # noqa: BLE001
        print(f"{h:26s} {dns}  HTTPS_FAIL {type(exc).__name__}")
PY

echo
echo "--- pip ---"
python3 -m pip --version 2>&1 | sed 's/^/pip                  /'
python3 -m pip config list 2>/dev/null | sed 's/^/pip config           /' || true

echo
echo "=============================================================="
echo " preflight done"
echo "=============================================================="
