#!/usr/bin/env bash
# 运行时完整性测试：篡改归档必须在校验阶段被拒且不产生任何解包；非法 .deb 不得被通配解包
# 不占网络端口；只操作运行时归档副本。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BORE_DIR/../../.." && pwd)"
RUNTIME="${RUNTIME:-$REPO_ROOT/local/build/bore-p1-20261026/runtime}"
BASE="$REPO_ROOT/local/build/bore-p1-20261026"
PASS=0; FAIL=0
say() { printf "%s\n" "$*"; }
ok()  { PASS=$((PASS+1)); say "PASS  $1"; }
bad() { FAIL=$((FAIL+1)); say "FAIL  $1 :: $2"; }

[ -d "$RUNTIME/debs" ] || { say "BLOCKED: 缺少运行时目录 $RUNTIME"; exit 3; }
mkdir -p "$BASE"
T="$(mktemp -d "$BASE/fetchtest.XXXXXX")" || exit 4
cleanup() { rm -rf "$T"; }
trap cleanup EXIT

seed() {
  mkdir -p "$1/debs"
  cp "$RUNTIME/bore.tar.gz" "$1/bore.tar.gz"
  cp "$RUNTIME"/debs/*.deb "$1/debs/"
}

seed "$T"
NGINX_CORE="$T/debs/nginx-core_1.18.0-6ubuntu14.21_amd64.deb"
printf "tampered" >> "$NGINX_CORE"
OUT=$(bash "$BORE_DIR/scripts/fetch-runtime.sh" --dest "$T" 2>&1); RC=$?
[ "$RC" -ne 0 ] && ok "tampered-exit-nonzero" || bad "tampered-exit-nonzero" "rc=$RC"
echo "$OUT" | grep -q "HASH-MISMATCH nginx-core" && ok "tampered-detected" || bad "tampered-detected" "$OUT"
[ ! -e "$T/root" ] && ok "no-extract-root" || bad "no-extract-root" "root 已生成"
[ ! -e "$T/bore" ] && ok "no-extract-bore" || bad "no-extract-bore" "bore 已解包"

OUT2=$(bash "$BORE_DIR/scripts/fetch-runtime.sh" --dest "$T" --verify-only 2>&1); RC2=$?
[ "$RC2" -ne 0 ] && ok "verify-only-tampered-nonzero" || bad "verify-only-tampered-nonzero" "rc=$RC2"

rm -rf "$T"
T2="$(mktemp -d "$BASE/fetchtest.XXXXXX")"
seed "$T2"
printf "not a deb" > "$T2/debs/zzz-decoy.deb"
OUT3=$(bash "$BORE_DIR/scripts/fetch-runtime.sh" --dest "$T2" 2>&1); RC3=$?
[ "$RC3" -eq 0 ] && ok "valid-with-decoy-succeeds" || bad "valid-with-decoy-succeeds" "rc=$RC3"
[ -x "$T2/bore" ] && ok "bore-extracted" || bad "bore-extracted" ""
[ -x "$T2/root/usr/sbin/nginx" ] && ok "nginx-extracted" || bad "nginx-extracted" ""
[ -f "$T2/root/usr/lib/nginx/modules/ngx_stream_module.so" ] && ok "stream-module-extracted" || bad "stream-module-extracted" ""
echo "$OUT3" | grep -q "RUNTIME OK" && ok "runtime-ok-line" || bad "runtime-ok-line" ""
rm -rf "$T2"

say ""
say "FETCH PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
