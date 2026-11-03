#!/usr/bin/env bash
# 下载/校验 P1 本地验证运行时（nginx Ubuntu 包 + bore 发行包），不安装系统包。
# 用法：bash fetch-runtime.sh [--dest <dir>] [--verify-only]
# 安全顺序：先校验全部归档（存在 + 固定 SHA256），任一失败立即非零退出且**不解包**；
#           只解包清单内已校验的 4 个 deb（不使用 *.deb 通配）；
#           最后校验 3 个实际产物（bore、nginx、ngx_stream_module.so）的固定 SHA256。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BORE_DIR/../../.." && pwd)"
DEST="${DEST:-$REPO_ROOT/local/build/bore-p1-20261026/runtime}"
VERIFY_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

NGINX_VER="1.18.0-6ubuntu14.21"
POOL="http://archive.ubuntu.com/ubuntu/pool/main/n/nginx"
BORE_VER="0.5.3"
BORE_URL="https://github.com/ekzhang/bore/releases/download/v${BORE_VER}/bore-v${BORE_VER}-x86_64-unknown-linux-musl.tar.gz"

# 归档固定哈希（下载/解包前校验）
A_BORE="$DEST/bore.tar.gz";                 H_BORE="101536e3f26fb3b87b592d602674ede7169ec9fd616939f9544407ef6b0d361f"
A_NGINX="$DEST/debs/nginx_${NGINX_VER}_amd64.deb";                   H_NGINX="13da9b3623b99a96482575bd96c994b175b54077f15ecdc5b9f99d80aaec0140"
A_COMMON="$DEST/debs/nginx-common_${NGINX_VER}_all.deb";             H_COMMON="7b35829e1896be123f8365c5c134e707978151ea292770e19335340b8bffa40c"
A_CORE="$DEST/debs/nginx-core_${NGINX_VER}_amd64.deb";               H_CORE="266e0799aeba81e6f0bd2a0a75a96756f12bbfb2b3d6704dec921152c0751c10"
A_STREAM="$DEST/debs/libnginx-mod-stream_${NGINX_VER}_amd64.deb";    H_STREAM="c837c72e50a199858ba2e742d750bef8fad292a3882135a622a6397acb9b8088"

# 解包产物固定哈希（由上述已校验归档解包得到，本轮实测登记）
X_BORE="$DEST/bore";                                                     HX_BORE="0be5c2533066bf36cad773657cafb564441d072d6cf0824357a0f22c4dac04dd"
X_NGINX="$DEST/root/usr/sbin/nginx";                                     HX_NGINX="70c002df0571675ada1eab1562a37c745d10b08d53b37d4a280bb230ed772baf"
X_STREAM="$DEST/root/usr/lib/nginx/modules/ngx_stream_module.so";        HX_STREAM="cc9e89cc885628740efc8c88cd9c3be6ecf43f32673bca9c090ee491cac8169f"

fail=0
say() { printf '%s\n' "$*"; }

ensure_dirs() { mkdir -p "$DEST/debs" || { say "FATAL 无法创建 $DEST"; exit 1; }; }

download_missing() {
  [ -f "$A_BORE" ]     || curl -fsSL -o "$A_BORE" "$BORE_URL" || { say "FATAL 下载 bore 失败"; exit 1; }
  [ -f "$A_NGINX" ]    || curl -fsSL -o "$A_NGINX"  "$POOL/nginx_${NGINX_VER}_amd64.deb" || { say "FATAL 下载 nginx 失败"; exit 1; }
  [ -f "$A_COMMON" ]   || curl -fsSL -o "$A_COMMON" "$POOL/nginx-common_${NGINX_VER}_all.deb" || { say "FATAL 下载 nginx-common 失败"; exit 1; }
  [ -f "$A_CORE" ]     || curl -fsSL -o "$A_CORE"   "$POOL/nginx-core_${NGINX_VER}_amd64.deb" || { say "FATAL 下载 nginx-core 失败"; exit 1; }
  [ -f "$A_STREAM" ]   || curl -fsSL -o "$A_STREAM" "$POOL/libnginx-mod-stream_${NGINX_VER}_amd64.deb" || { say "FATAL 下载 stream 模块失败"; exit 1; }
}

verify_archive() { # file expected label
  local f=$1 want=$2 label=$3 got
  if [ ! -f "$f" ]; then say "MISSING-ARCHIVE $label $f"; fail=$((fail+1)); return 1; fi
  got=$(sha256sum "$f" | cut -d' ' -f1)
  if [ "$got" = "$want" ]; then say "OK-ARCHIVE $label"; return 0; fi
  say "HASH-MISMATCH $label want=$want got=$got"; fail=$((fail+1)); return 1
}

verify_archives() {
  verify_archive "$A_BORE"   "$H_BORE"   bore-tar.gz
  verify_archive "$A_NGINX"  "$H_NGINX"  nginx.deb
  verify_archive "$A_COMMON" "$H_COMMON" nginx-common.deb
  verify_archive "$A_CORE"   "$H_CORE"   nginx-core.deb
  verify_archive "$A_STREAM" "$H_STREAM" stream.deb
  [ "$fail" -eq 0 ] || { say "REFUSE: 归档校验失败，未做任何解包"; exit 1; }
}

verify_artifacts() {
  verify_archive "$X_BORE"  "$HX_BORE"  extracted-bore
  verify_archive "$X_NGINX" "$HX_NGINX" extracted-nginx
  verify_archive "$X_STREAM" "$HX_STREAM" extracted-stream-module
  [ "$fail" -eq 0 ] || { say "REFUSE: 解包产物校验失败"; exit 1; }
}

extract_verified() {
  # 只解包清单内、已校验的归档；不使用通配符
  mkdir -p "$DEST/root" || { say "FATAL 创建 root 失败"; exit 1; }
  tar xzf "$A_BORE" -C "$DEST" || { say "FATAL 解包 bore 失败"; exit 1; }
  dpkg-deb -x "$A_NGINX"  "$DEST/root" || { say "FATAL 解包 nginx 失败"; exit 1; }
  dpkg-deb -x "$A_COMMON" "$DEST/root" || { say "FATAL 解包 nginx-common 失败"; exit 1; }
  dpkg-deb -x "$A_CORE"   "$DEST/root" || { say "FATAL 解包 nginx-core 失败"; exit 1; }
  dpkg-deb -x "$A_STREAM" "$DEST/root" || { say "FATAL 解包 stream 模块失败"; exit 1; }
}

ensure_dirs
if [ "$VERIFY_ONLY" -eq 0 ]; then download_missing; fi
verify_archives
if [ "$VERIFY_ONLY" -eq 0 ]; then extract_verified; fi
verify_artifacts
say "RUNTIME OK dest=$DEST"
