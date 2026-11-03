#!/usr/bin/env bash
# 失败路径测试：端口被占用 / WORK 复用 时不得启动子进程、不得影响已有服务
# 依赖：NGINX_BIN、BORE_BIN、MODULE_SO、PYTHON
set -uo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BORE_DIR/../../.." && pwd)"
BASE="$REPO_ROOT/local/build/bore-p1-20261026"
PYTHON="${PYTHON:-python3}"
PASS=0; FAIL=0
say() { printf '%s\n' "$*"; }
ok()  { PASS=$((PASS+1)); say "PASS  $1"; }
bad() { FAIL=$((FAIL+1)); say "FAIL  $1 :: $2"; }

# 入参统一转绝对路径（Nginx -p 后相对 module 路径会解析错误）
abspath() { case "$1" in /*) printf "%s" "$1" ;; *) printf "%s/%s" "$PWD" "$1" ;; esac; }
[ -n "${NGINX_BIN:-}" ] && NGINX_BIN="$(abspath "$NGINX_BIN")"
[ -n "${MODULE_SO:-}" ] && MODULE_SO="$(abspath "$MODULE_SO")"
[ -n "${BORE_BIN:-}" ] && BORE_BIN="$(abspath "$BORE_BIN")"

[ -x "${NGINX_BIN:-}" ] || { say "BLOCKED: NGINX_BIN"; exit 3; }
[ -x "${BORE_BIN:-}" ] || { say "BLOCKED: BORE_BIN"; exit 3; }
[ -f "${MODULE_SO:-}" ] || { say "BLOCKED: MODULE_SO"; exit 3; }
mkdir -p "$BASE"
T="$(mktemp -d "$BASE/failtest.XXXXXX")" || exit 4

DUMMY_PID=""; DUMMY_ST=""
cleanup() {
  if [ -n "$DUMMY_PID" ] && [ -r "/proc/$DUMMY_PID/stat" ] \
     && [ "$(awk '{print $22}' "/proc/$DUMMY_PID/stat")" = "$DUMMY_ST" ]; then
    kill "$DUMMY_PID" 2>/dev/null; wait "$DUMMY_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

# 占用 bore 控制端口 7835 的“已有服务”
"$PYTHON" -c 'import socket,sys,time
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",7835)); s.listen(4)
print("ready", flush=True); time.sleep(120)' >"$T/dummy.log" 2>&1 &
DUMMY_PID=$!
for _ in $(seq 1 50); do grep -q ready "$T/dummy.log" 2>/dev/null && break; sleep 0.1; done
DUMMY_ST=$(awk '{print $22}' "/proc/$DUMMY_PID/stat" 2>/dev/null)
[ -n "$DUMMY_ST" ] && ok "dummy-7835-started" || bad "dummy-7835-started" ""

NGINX_BEFORE=$(pgrep -c nginx 2>/dev/null || echo 0)
BORE_BEFORE=$(pgrep -c bore 2>/dev/null || echo 0)

# 1) 端口被占用：应 blocked(exit 3)，且不启动任何子进程、不杀占用者
RUN1="$T/run1"
OUT1=$(env NGINX_BIN="${NGINX_BIN}" MODULE_SO="${MODULE_SO}" BORE_BIN="${BORE_BIN}" PYTHON="$PYTHON" \
  WORK="$RUN1" bash "$BORE_DIR/scripts/verify-local-entry.sh" 2>&1); RC1=$?
[ "$RC1" = "3" ] && ok "port-busy-exit3" || bad "port-busy-exit3" "rc=$RC1"
echo "$OUT1" | grep -q "7835" && ok "port-busy-names-7835" || bad "port-busy-names-7835" "$OUT1"
echo "$OUT1" | grep -q "BLOCKED" && ok "port-busy-blocked-message" || bad "port-busy-blocked-message" ""

NOW_ST=$(awk '{print $22}' "/proc/$DUMMY_PID/stat" 2>/dev/null)
[ -n "$NOW_ST" ] && [ "$NOW_ST" = "$DUMMY_ST" ] && ok "existing-service-unaffected" || bad "existing-service-unaffected" "starttime changed/process gone"

LEFT=$(pgrep -f "$RUN1" 2>/dev/null | wc -l)
[ "$LEFT" = "0" ] && ok "no-child-processes-after-block" || bad "no-child-processes-after-block" "pids=$LEFT"
NGINX_AFTER=$(pgrep -c nginx 2>/dev/null || echo 0)
BORE_AFTER=$(pgrep -c bore 2>/dev/null || echo 0)
[ "$NGINX_AFTER" = "$NGINX_BEFORE" ] && [ "$BORE_AFTER" = "$BORE_BEFORE" ] \
  && ok "no-extra-nginx-bore" || bad "no-extra-nginx-bore" "nginx $NGINX_BEFORE->$NGINX_AFTER bore $BORE_BEFORE->$BORE_AFTER"

# 2) WORK 已存在：应拒绝(exit 4)，同样不启动子进程
RUN2="$T/run2"; mkdir -p "$RUN2"
OUT2=$(env NGINX_BIN="${NGINX_BIN}" MODULE_SO="${MODULE_SO}" BORE_BIN="${BORE_BIN}" PYTHON="$PYTHON" \
  WORK="$RUN2" bash "$BORE_DIR/scripts/verify-local-entry.sh" 2>&1); RC2=$?
[ "$RC2" = "4" ] && ok "work-exists-exit4" || bad "work-exists-exit4" "rc=$RC2"
LEFT2=$(pgrep -f "$RUN2" 2>/dev/null | wc -l)
[ "$LEFT2" = "0" ] && ok "no-child-processes-work-exists" || bad "no-child-processes-work-exists" "pids=$LEFT2"

# 3) 停掉占用者后端口可复用（只清理本次占用的 dummy）
cleanup; wait "$DUMMY_PID" 2>/dev/null; DUMMY_PID=""
sleep 0.5
(exec 3<>/dev/tcp/127.0.0.1/7835) 2>/dev/null && bad "dummy-port-released" "7835 仍被占用" || ok "dummy-port-released"

say ""
say "FAILPATHS PASS=$PASS FAIL=$FAIL evidence=$T"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
