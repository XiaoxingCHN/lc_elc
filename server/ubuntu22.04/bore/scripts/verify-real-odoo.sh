#!/usr/bin/env bash
# P2：真实 Odoo 只读自有 UI 与会话/权限验证（经最终 P1 入口模板）
# 所有凭据仅来自环境变量（合成账号）；脚本与文档不保存任何密码/会话值。
# 必填：NGINX_BIN BORE_BIN ODOO_URL DB_NAME P2_USERS P2_PASS
#   P2_USERS 形如 "norole:catalog:operator:manager"（登录名，不含密码）
# 可选：MODULE_SO P2_COOKIE_FLAGS P2_ASSET_URL P2_DETAIL_KEY P2_QUERY
#       P2_CHROME_BIN P2_BROWSER_LOGIN P2_WORK P2_RUN_ID P2_RESULTS
#       P2_EVIDENCE_PY P2_RESULTS_SINCE PYTHON OPENSSL
# 输出仅：数量/状态/标志名；不打印 Cookie 值、密码、完整命令行。
# 证据：每条断言写 results.jsonl（含 run_id）；verify-summary.json 记录本段计数与 since_line。
set -uo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BORE_DIR/../../.." && pwd)"
PYTHON="${PYTHON:-python3}"
OPENSSL="${OPENSSL:-openssl}"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy 2>/dev/null || true
export NO_PROXY="*" no_proxy="*"
P_ENTRY=8443; P_EDGE=9500; P_BORE_PUB=20000; P_BORE_CTRL=7835
DETAIL_KEY="${P2_DETAIL_KEY:-lab:4}"
export P2_DETAIL_KEY="$DETAIL_KEY"

# ---------------------------------------------------------------------------
# 证据目录与助手（独立运行时自己建；由 run-p2-isolated.sh 调用时复用同轮目录）
# ---------------------------------------------------------------------------
BASE="${P2_BASE:-$REPO_ROOT/local/build/bore-p2-20261026}"
case "$BASE" in /*) ;; *) echo "BLOCKED: P2_BASE 必须是绝对路径"; exit 3 ;; esac
if [ -n "${P2_WORK:-}" ]; then
  WORK="$P2_WORK"
  mkdir -p "$WORK" || { echo "BLOCKED: 无法创建 WORK"; exit 3; }
else
  mkdir -p "$BASE/runs" || { echo "BLOCKED: 无法创建 runs"; exit 3; }
  WORK="$(mktemp -d "$BASE/runs/run.XXXXXX")" || { echo "BLOCKED: mktemp 失败"; exit 3; }
fi
chmod 700 "$WORK" 2>/dev/null || true
RUN_ID="${P2_RUN_ID:-p2-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$WORK")}"
export P2_RUN_ID="$RUN_ID" P2_WORK="$WORK"
mkdir -p "$WORK/logs" "$WORK/nginx" "$WORK/edge" "$WORK/certs" "$WORK/jars" || { echo "BLOCKED: 证据目录不可写"; exit 3; }

EV="${P2_EVIDENCE_PY:-}"
if [ -z "$EV" ] || [ ! -r "$EV" ]; then
  EV="$WORK/.verify_evidence.py"
  bash "$SCRIPT_DIR/run-p2-isolated.sh" --print-evidence-helper > "$EV" || { echo "BLOCKED: 证据助手不可用"; exit 3; }
  chmod 600 "$EV" 2>/dev/null || true
fi
RESULTS="${P2_RESULTS:-$WORK/results.jsonl}"
[ -f "$RESULTS" ] || : > "$RESULTS" || { echo "BLOCKED: results.jsonl 不可写"; exit 3; }
SINCE="${P2_RESULTS_SINCE:-0}"
case "$SINCE" in ''|*[!0-9]*) SINCE=0 ;; esac

PASS=0; FAIL=0; BLOCKED=0; SKIP=0; EVIDENCE_ERROR=0; FINALIZED=0
say() { printf '%s\n' "$*"; }
ev() { # id result [detail]
  local ident=$1 result=$2 detail="${3:-}"
  "$PYTHON" "$EV" add "$RESULTS" "$ident" "$result" "$detail" \
    || { printf 'EVIDENCE-WRITE-FAILED %s\n' "$ident" >&2; EVIDENCE_ERROR=1; }
  case "$result" in
    pass) PASS=$((PASS + 1)) ;;
    fail) FAIL=$((FAIL + 1)) ;;
    blocked) BLOCKED=$((BLOCKED + 1)) ;;
    skip) SKIP=$((SKIP + 1)) ;;
  esac
}
ok()  { say "PASS  $1"; ev "$1" pass ""; }
bad() { say "FAIL  $1 :: ${2:-}"; ev "$1" fail "${2:-}"; }
block() { say "BLOCKED $1 :: ${2:-}"; ev "$1" blocked "${2:-}"; }
skip() { say "SKIP  $1 :: ${2:-}"; ev "$1" skip "${2:-}"; }
redacted_tail() { # file [lines]
  local file=$1 lines="${2:-12}"
  [ -r "$file" ] || { printf '(no-log)'; return 0; }
  tail -n "$lines" "$file" 2>/dev/null | "$PYTHON" "$EV" redact 1200 2>/dev/null | tr '\n' ' '
}
# 证据脱敏：会话 Cookie/token 不留在证据目录
scrub_secrets() {
  local removed=0 f
  for f in "$WORK/jars"/*; do [ -e "$f" ] || continue; rm -f "$f" && removed=$((removed + 1)); done
  for f in "$WORK/last.body" "$WORK/manifest.bin" "$WORK/asset.bin" "$WORK/asset.h" "$WORK/asset.code"; do
    [ -e "$f" ] && rm -f "$f" && removed=$((removed + 1))
  done
  # Browser profiles are removed only by browser_flow after owner-marker verification.
  ev p2-evidence-scrub pass "removed=$removed cookie-jars/body-buffers"
}

finalize() { # exit_code
  [ "$FINALIZED" = 1 ] && return 0
  FINALIZED=1
  local code=$1
  if [ "$EVIDENCE_ERROR" = 1 ] && [ "$code" -eq 0 ]; then code=4; fi
  local summary="${WORK}/verify-summary.json"
  "$PYTHON" - "$summary" "$RUN_ID" "$WORK" "$code" "$SINCE" "$PASS" "$FAIL" "$BLOCKED" "$SKIP" <<'PY'
import json, sys, datetime
path, run_id, work, code, since, p, f, b, s = sys.argv[1:10]
data = {
    "schema": "p2-verify-summary-1",
    "run_id": run_id,
    "work": work,
    "since_line": int(since),
    "counts": {"pass": int(p), "fail": int(f), "blocked": int(b), "skip": int(s)},
    "total": int(p) + int(f) + int(b) + int(s),
    "exit_code": int(code),
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
    fh.flush()
    import os
    os.fsync(fh.fileno())
os.replace(tmp, path)
print("VERIFY_SUMMARY " + json.dumps(data, ensure_ascii=False, sort_keys=True))
PY
  # 独立运行（不经 run-p2-isolated.sh）时自己写 summary.json，保证证据完整；
  # 由 runner 调用时 summary.json 归 runner 所有（它还要追加自己的检查项）。
  if [ -z "${P2_RUNNER_OWNS_SUMMARY:-}" ]; then
    "$PYTHON" "$EV" summarize "$RESULTS" "$WORK/summary.json" "$WORK" "$code" >/dev/null 2>&1 \
      || say "EVIDENCE-SUMMARY-FAILED work=$WORK"
  fi
  say ""
  say "SUMMARY PASS=$PASS FAIL=$FAIL BLOCKED=$BLOCKED SKIP=$SKIP since_line=$SINCE exit_code=$code work=$WORK run_id=$RUN_ID"
  return 0
}
on_exit() {
  local rc=$?
  trap - EXIT INT TERM
  # cleanup 定义在本文件后半段；提前失败时函数尚不存在，按名字探测避免 command not found
  declare -F cleanup >/dev/null 2>&1 && cleanup
  declare -F scrub_secrets >/dev/null 2>&1 && scrub_secrets
  finalize "$rc"
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

blocked_exit() { block "$1" "${2:-}"; say "BLOCKED (exit 3)"; exit 3; }

# JSON-RPC 载荷统一由助手序列化（避免引号/密码破坏 JSON；凭据走 stdin，不进 argv）
rpc_auth() { # login password id
  printf '%s\n%s\n%s\n%s\n' "$DB_NAME" "$1" "$2" "$3" | "$PYTHON" "$EV" auth
}
rpc_sess() { printf '%s\n' "$1" | "$PYTHON" "$EV" sess; }
rpc_call() { # id params-json
  printf '%s\n%s\n' "$1" "$2" | "$PYTHON" "$EV" call
}

# ---------------------------------------------------------------------------
# 输入与端口校验
# ---------------------------------------------------------------------------
[ -n "${NGINX_BIN:-}" ] || blocked_exit p2-input-nginx "缺少 NGINX_BIN"
[ -n "${BORE_BIN:-}" ] || blocked_exit p2-input-bore "缺少 BORE_BIN"
[ -n "${ODOO_URL:-}" ] || blocked_exit p2-input-url "缺少 ODOO_URL"
[ -n "${DB_NAME:-}" ] || blocked_exit p2-input-db "缺少 DB_NAME"
[ -n "${P2_USERS:-}" ] || blocked_exit p2-input-users "缺少 P2_USERS"
[ -n "${P2_PASS:-}" ] || blocked_exit p2-input-pass "缺少 P2_PASS"

URL_RE='^(https?)://(127\.0\.0\.1|localhost)(:([0-9]{1,5}))?$'
if [[ "$ODOO_URL" =~ $URL_RE ]]; then
  ODOO_PORT="${BASH_REMATCH[4]:-}"
  [ -n "$ODOO_PORT" ] || { [ "${BASH_REMATCH[1]}" = https ] && ODOO_PORT=443 || ODOO_PORT=80; }
  if ! [[ "$ODOO_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$ODOO_PORT" -gt 65535 ]; then
    blocked_exit p2-input-url "ODOO_URL 端口格式非法：$ODOO_PORT"
  fi
else
  blocked_exit p2-input-url "ODOO_URL 必须为回环地址 http(s)://127.0.0.1|localhost[:端口]"
fi
[[ "$DB_NAME" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,40}$ ]] || blocked_exit p2-input-db "DB_NAME 非法"
case "$DB_NAME" in postgres|template0|template1) blocked_exit p2-input-db "DB_NAME 不得为系统库" ;; esac
[ -x "$NGINX_BIN" ] && [ -x "$BORE_BIN" ] || blocked_exit p2-input-runtime "运行时不可执行"
if [ -n "${MODULE_SO:-}" ]; then
  [ -f "$MODULE_SO" ] || blocked_exit p2-input-module "MODULE_SO 缺失"
  LOAD_LINE="load_module $MODULE_SO;"
else
  LOAD_LINE=""
fi
command -v ss >/dev/null 2>&1 || blocked_exit p2-input-ss "缺少 ss"
command -v "$OPENSSL" >/dev/null 2>&1 || blocked_exit p2-input-openssl "缺少 $OPENSSL"
ev p2-inputs pass "run_id=$RUN_ID db=$DB_NAME detail_key_len=${#DETAIL_KEY}"

port_free() { ! ss -lnt 2>/dev/null | awk -v p=":$1" 'NR > 1 && $4 ~ (p "$") { found=1 } END { exit(found ? 0 : 1) }'; }
for _p in "$P_ENTRY" "$P_EDGE" "$P_BORE_PUB" "$P_BORE_CTRL"; do
  [[ "$_p" =~ ^[1-9][0-9]{0,4}$ ]] && [ "$_p" -le 65535 ] || blocked_exit p2-port-format "端口格式非法：$_p"
  for _ in $(seq 1 30); do port_free "$_p" && break; sleep 0.1; done
  port_free "$_p" || blocked_exit p2-port-free "端口已被占用：$_p（拒绝复用/不停机）"
done
ev p2-port-free pass "ports=$P_ENTRY,$P_EDGE,$P_BORE_PUB,$P_BORE_CTRL"

# ---------------------------------------------------------------------------
# 进程跟踪（pid|starttime|comm），cleanup 只杀本轮自有进程
# ---------------------------------------------------------------------------
TRACK=()
proc_field() { # pid 1-based-stat-index
  local pid=$1 idx=$2 data
  local -a fields
  [ -r "/proc/$pid/stat" ] || return 1
  read -r data < "/proc/$pid/stat" 2>/dev/null || return 1
  data="${data##*)}"
  read -ra fields <<< "$data"
  [ "${#fields[@]}" -ge $((idx - 2)) ] || return 1
  printf '%s' "${fields[$((idx - 3))]}"
}
track() { # pid ident
  local pid=$1 ident=$2 st
  [ -r "/proc/$pid/stat" ] || return 1
  st=$(proc_field "$pid" 22 2>/dev/null) || return 1
  [ -n "$st" ] || return 1
  TRACK+=("$pid|$st|$ident")
}
same_process() { # pid starttime ident
  local pid=$1 st=$2 ident=$3 comm
  [ "$(proc_field "$pid" 22 2>/dev/null)" = "$st" ] || return 1
  comm=$(cat "/proc/$pid/comm" 2>/dev/null)
  case "$ident" in
    nginx) [ "$comm" = "nginx" ] ;;
    bore) [ "$comm" = "bore" ] ;;
  esac
}
cleanup() {
  local entry pid st ident i
  for entry in "${TRACK[@]:-}"; do
    [ -n "$entry" ] || continue
    IFS="|" read -r pid st ident <<< "$entry"
    same_process "$pid" "$st" "$ident" || continue
    kill "$pid" 2>/dev/null
    for i in $(seq 1 20); do same_process "$pid" "$st" "$ident" || break; sleep 0.1; done
    same_process "$pid" "$st" "$ident" && kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  done
}



# ---------------------------------------------------------------------------
# 证书与配置渲染
# ---------------------------------------------------------------------------
"$OPENSSL" req -x509 -newkey rsa:2048 -nodes -keyout "$WORK/certs/ca.key" -out "$WORK/certs/ca.pem" \
  -days 2 -subj "/CN=p2-real-odoo-local-ca" >/dev/null 2>&1 || blocked_exit p2-ca "生成测试 CA 失败"
printf "subjectAltName=DNS:team.l-creation.club\nextendedKeyUsage=serverAuth\n" > "$WORK/certs/s.ext"
"$OPENSSL" req -newkey rsa:2048 -nodes -keyout "$WORK/certs/s.key" -out "$WORK/certs/s.csr" \
  -subj "/CN=team.l-creation.club" >/dev/null 2>&1 || blocked_exit p2-csr "生成服务端 CSR 失败"
"$OPENSSL" x509 -req -in "$WORK/certs/s.csr" -CA "$WORK/certs/ca.pem" -CAkey "$WORK/certs/ca.key" \
  -CAcreateserial -out "$WORK/certs/s.pem" -days 2 -extfile "$WORK/certs/s.ext" >/dev/null 2>&1 \
  || blocked_exit p2-cert "签发测试证书失败"
ev p2-certs pass "SAN=team.l-creation.club"

# CSP：严格 'self'（不再注入额外来源；@CSP_CONNECT_EXTRA@ 保留占位但传空）
render_entry() {
  local rate="${1:-}"
  sed -e "s|@LISTEN_LINE@|listen 127.0.0.1:$P_ENTRY ssl proxy_protocol;|" \
      -e "s|@SSL_LINES@|ssl_certificate $WORK/certs/s.pem; ssl_certificate_key $WORK/certs/s.key; ssl_protocols TLSv1.2 TLSv1.3;|" \
      -e "s|@REALIP_LINES@|real_ip_header proxy_protocol; set_real_ip_from 127.0.0.1;|" \
      -e "s|@UPSTREAM@|$ODOO_URL|" \
      -e "s|@RATE_LIMIT@|$rate|" -e "s|@COOKIE_FLAGS@|${P2_COOKIE_FLAGS:-}|" \
      -e "s|@PUBLIC_PORT@|$P_EDGE|g" \
      -e "s|include bore-proxy-headers.conf;|include $WORK/nginx/headers.conf;|g" \
      "$BORE_DIR/nginx/bore-public-allowlist.conf.template" > "$WORK/nginx/entry.conf"
  sed -e "s|@DB_HEADER@|proxy_set_header X-Odoo-Database $DB_NAME;|" "$BORE_DIR/nginx/bore-proxy-headers.conf" > "$WORK/nginx/headers.conf"
}
render_entry ""
grep -q "@CSP_CONNECT_EXTRA@" "$WORK/nginx/entry.conf" \
  && { bad p2-csp-render "占位未被替换"; } || ok p2-csp-render
grep -qE "connect-src 'self' *;" "$WORK/nginx/entry.conf" \
  && ok p2-csp-self-only || bad p2-csp-self-only "connect-src 非严格 self"

cat > "$WORK/nginx/nginx.conf" <<EOF
$LOAD_LINE
worker_processes 1;
pid $WORK/nginx/nginx.pid;
error_log $WORK/nginx/error.log warn;
events { worker_connections 256; }
http {
    map \$http_origin \$p2_origin_ok { default 0; "" 1; "https://team.l-creation.club" 1; "https://team.l-creation.club:$P_EDGE" 1; }
    map "\$request_method:\$p2_origin_ok" \$p2_reject_post { default 0; "POST:0" 1; }
    log_format p2 '\$request_method \$request_uri status=\$status origin="\$http_origin"';
    access_log $WORK/nginx/access.log p2;
    client_body_temp_path $WORK/nginx/body;
    proxy_temp_path $WORK/nginx/proxy;
    fastcgi_temp_path $WORK/nginx/fcgi;
    uwsgi_temp_path $WORK/nginx/uwsgi;
    scgi_temp_path $WORK/nginx/scgi;
    limit_req_zone \$remote_addr zone=p2_auth:1m rate=1r/m;
    include $WORK/nginx/entry.conf;
}
EOF
sed -e "s|@EDGE_LISTEN@|127.0.0.1:$P_EDGE|" -e "s|@TUNNEL_ADDR@|127.0.0.1:$P_BORE_PUB|" \
    "$BORE_DIR/nginx/bore-edge-stream.conf.template" > "$WORK/edge/nginx.conf"
[ -n "$LOAD_LINE" ] && sed -i "1i $LOAD_LINE" "$WORK/edge/nginx.conf"
sed -i "1a worker_processes 1;\npid $WORK/edge/nginx.pid;\nerror_log $WORK/edge/error.log warn;" "$WORK/edge/nginx.conf"

if "$NGINX_BIN" -p "$WORK/nginx" -c "$WORK/nginx/nginx.conf" -t >"$WORK/logs/entry-t.out" 2>&1; then
  ok entry-config
else
  bad entry-config "nginx-t failed: $(redacted_tail "$WORK/logs/entry-t.out" 8)"
  exit 1
fi
if "$NGINX_BIN" -p "$WORK/edge" -c "$WORK/edge/nginx.conf" -t >"$WORK/logs/edge-t.out" 2>&1; then
  ok edge-config
else
  bad edge-config "nginx-t failed: $(redacted_tail "$WORK/logs/edge-t.out" 8)"
  exit 1
fi

# ---------------------------------------------------------------------------
# 启动 bore / nginx（失败快速失败，日志留存本轮目录）
# ---------------------------------------------------------------------------
wait_owned_port() {
  local port=$1 owner=$2 i
  for ((i=0; i<100; i++)); do
    kill -0 "$owner" 2>/dev/null || return 1
    if ss -H -lntp "sport = :$port" 2>/dev/null | grep -q "pid=$owner,"; then return 0; fi
    sleep 0.1
  done
  return 1
}
"$BORE_BIN" server --bind-addr 127.0.0.1 --bind-tunnels 127.0.0.1 >"$WORK/logs/bore-server.log" 2>&1 &
BORE_SERVER_PID=$!
track "$BORE_SERVER_PID" bore
"$PYTHON" - <<'PY' >/dev/null 2>&1 || { bad odoo-reachable "上游不可达"; exit 1; }
import os, socket, sys
url = os.environ["ODOO_URL"]
rest = url.split("://", 1)[1]
host, _, port = rest.partition(":")
socket.create_connection((host, int(port or 80)), timeout=3).close()
PY
wait_owned_port "$P_BORE_CTRL" "$BORE_SERVER_PID" || { bad bore-control-ready "$(redacted_tail "$WORK/logs/bore-server.log" 5)"; exit 1; }
ok bore-control-ready
"$BORE_BIN" local "$P_ENTRY" --to 127.0.0.1 --port "$P_BORE_PUB" >"$WORK/logs/bore-client.log" 2>&1 &
track $! bore
"$NGINX_BIN" -p "$WORK/nginx" -c "$WORK/nginx/nginx.conf" 2>>"$WORK/logs/entry.err" \
  || { bad entry-start "$(redacted_tail "$WORK/logs/entry.err" 8)"; exit 1; }
track "$(cat "$WORK/nginx/nginx.pid" 2>/dev/null)" nginx
"$NGINX_BIN" -p "$WORK/edge" -c "$WORK/edge/nginx.conf" 2>>"$WORK/logs/edge.err" \
  || { bad edge-start "$(redacted_tail "$WORK/logs/edge.err" 8)"; exit 1; }
track "$(cat "$WORK/edge/nginx.pid" 2>/dev/null)" nginx
wait_owned_port "$P_BORE_PUB" "$BORE_SERVER_PID" || { bad bore-public-ready "$(redacted_tail "$WORK/logs/bore-client.log" 5)"; exit 1; }
ok bore-public-ready
EDGE_READY=0
for _ in $(seq 1 60); do if (exec 3<>/dev/tcp/127.0.0.1/$P_EDGE) 2>/dev/null; then EDGE_READY=1; break; fi; sleep 0.2; done
[ "$EDGE_READY" = 1 ] || { bad edge-ready "listener unavailable"; exit 1; }
ev p2-stack-up pass "entry=$P_ENTRY edge=$P_EDGE"

# ---------------------------------------------------------------------------
# HTTP 助手
# ---------------------------------------------------------------------------
CA="${WORK}/certs/ca.pem"
RESOLVE="team.l-creation.club:$P_EDGE:127.0.0.1"
jar() { printf '%s' "$WORK/jars/$1.txt"; }
CODE=""; RC=0
req() { # jar method path [curl args...]
  local j=$1 m=$2 p=$3; shift 3
  CODE=$(curl -s -o "$WORK/last.body" -w "%{http_code}" --noproxy "*" --max-time 15 --cacert "$CA" \
    --resolve "$RESOLVE" -b "$j" -c "$j" -X "$m" "$@" "https://team.l-creation.club:$P_EDGE$p" 2>/dev/null)
  RC=$?
}
uid_of() { grep -o "\"uid\": *[0-9][0-9]*" "$1" 2>/dev/null | head -1 | grep -o "[0-9][0-9]*"; }
login() { # user password jar -> uid
  local u=$1 pw=$2 j=$3 body
  body="$(rpc_auth "$u" "$pw" 1)" || return 1
  req "$j" POST /web/session/authenticate -H "Content-Type: application/json" --data-binary "$body"
  uid_of "$WORK/last.body"
}
leak_hit() { grep -oE '"debug"|Traceback|File "|/home/|/mnt/|psycopg|SQLSTATE' "$WORK/last.body" | sort -u | tr '\n' ',' ; }

USERS="$P2_USERS"; IFS=":" read -r U_NOROLE U_CAT U_OP U_MGR <<< "$USERS"
[ -n "${U_MGR:-}" ] || blocked_exit p2-users "P2_USERS 需 4 段（norole:catalog:operator:manager）"

# ---------------------------------------------------------------------------
# A 冷登录 / 会话一致 / 页面 / 静态资源
# ---------------------------------------------------------------------------
J1=$(jar catalog); : > "$J1"
req "$J1" GET /login; [ "$CODE" = 200 ] && ok cold-login-page || bad cold-login-page "$CODE"
U1=$(login "$U_CAT" "$P2_PASS" "$J1")
[ -n "$U1" ] && ok cold-auth-uid || bad cold-auth-uid "no-uid"
grep -q "session_id" "$J1" && ok cold-cookie-saved || bad cold-cookie-saved ""
req "$J1" POST /web/session/get_session_info -H "Content-Type: application/json" --data-binary "$(rpc_sess 2)"
U2=$(uid_of "$WORK/last.body"); { [ -n "$U2" ] && [ "$U2" = "$U1" ]; } && ok session-consistent || bad session-consistent ""
req "$J1" GET /lab; [ "$CODE" = 200 ] && ok lab-page-200 || bad lab-page-200 "$CODE"
grep -q "lc-results" "$WORK/last.body" && ok lab-has-results || bad lab-has-results ""
req "$J1" GET "/lab/items/$DETAIL_KEY"; [ "$CODE" = 200 ] && ok detail-200 || bad detail-200 "$CODE"
CSS=$(grep -o "/lab_team_web/static/src/css/team.css?v=[0-9a-f]*" "$WORK/last.body" | head -1)
[ -n "$CSS" ] || CSS="/lab_team_web/static/src/css/team.css"
req "$J1" GET "$CSS"; [ "$CODE" = 200 ] && ok static-200 || bad static-200 "$CODE"
if [ -n "${P2_ASSET_URL:-}" ]; then
  AESC=$(printf %s "$P2_ASSET_URL" | sed "s|/|%2F|g; s|:|%3A|g")
  AC=$(curl -s -D "$WORK/asset.h" -o "$WORK/asset.bin" -w "%{http_code}" --noproxy "*" --max-time 20 \
        --cacert "$CA" --resolve "$RESOLVE" -b "$J1" \
        "https://team.l-creation.club:$P_EDGE/lab/api/asset?url=$AESC")
  AS=$(wc -c < "$WORK/asset.bin")
  { [ "$AC" = 200 ] && [ "$AS" -gt 0 ]; } && ok asset-ok-200 || bad asset-ok-200 "code=$AC size=$AS"
  grep -qiE '^content-type: *image/' "$WORK/asset.h" && ok asset-image-type || bad asset-image-type ""
else
  block asset-ok-200 "隔离环境无可达的项目允许公开域（szlcsc 域名不可达），未放开 SSRF 边界"
  block asset-image-type "依赖 asset-ok-200"
fi
req "$J1" GET "/lab/api/asset?url=http%3A%2F%2Fevil.example%2Fx"; AB=$CODE
{ [ "$AB" = 400 ] || [ "$AB" = 403 ]; } && ok asset-evil-rejected || bad asset-evil-rejected "code=$AB"

# ---------------------------------------------------------------------------
# B 刷新保持
# ---------------------------------------------------------------------------
req "$J1" GET /lab; [ "$CODE" = 200 ] && ok refresh-still-200 || bad refresh-still-200 "$CODE"

# ---------------------------------------------------------------------------
# C 退出
# ---------------------------------------------------------------------------
TOKEN=$(grep -o 'name="csrf_token" value="[^"]*"' "$WORK/last.body" | head -1 | sed 's/.*value="//; s/"$//')
req "$J1" POST /team/logout --data-binary "csrf_token=${TOKEN}"; [ "$CODE" = 303 ] && ok logout-303 || bad logout-303 "$CODE"
req "$J1" POST /web/session/get_session_info -H "Content-Type: application/json" --data-binary "$(rpc_sess 3)"
if [ "$RC" = 0 ] && [ "$CODE" = 200 ] && "$PYTHON" - "$WORK/last.body" <<'PY'
import json, sys
try:
    doc = json.load(open(sys.argv[1], encoding="utf-8"))
    result, error = doc.get("result"), doc.get("error") or {}
    expired = (error.get("data") or {}).get("name") == "odoo.http.SessionExpiredException"
    anonymous = isinstance(result, dict) and "uid" in result and result["uid"] in (False, None)
    sys.exit(0 if expired or anonymous else 1)
except (ValueError, OSError, AttributeError):
    sys.exit(1)
PY
then ok session-invalid-after-logout; else bad session-invalid-after-logout "unknown transport or non-anonymous session"; fi
req "$J1" GET /lab; [ "$CODE" = 303 ] && ok lab-protected-after-logout || bad lab-protected-after-logout "$CODE"

# ---------------------------------------------------------------------------
# D 错误认证 / 非法 DB（含引号与特殊字符的合成密码）
# ---------------------------------------------------------------------------
J2=$(jar wrong); : > "$J2"
login "$U_CAT" 'definitely-wrong-"quoted"-pass' "$J2" >/dev/null
grep -q "AccessDenied" "$WORK/last.body" && ok wrong-password-denied || bad wrong-password-denied ""
if leak_hit | grep -q .; then bad wrong-password-leak "hit=$(leak_hit)"; else ok wrong-password-no-leak; fi
if [ ! -s "$J2" ] || ! grep -q session_id "$J2"; then ok wrong-password-no-cookie; else bad wrong-password-no-cookie ""; fi
J3=$(jar baddb); : > "$J3"
req "$J3" POST /web/session/authenticate -H "Content-Type: application/json" \
  --data-binary "$(rpc_call 4 '{"db":"no_such_db_zz","login":"x","password":"y"}')"
grep -qE "Database not found|AccessError|AccessDenied" "$WORK/last.body" && ok invalid-db-rejected || bad invalid-db-rejected ""
if leak_hit | grep -q .; then bad invalid-db-leak "hit=$(leak_hit)"; else ok invalid-db-no-leak; fi
grep -q '"jsonrpc": "2.0"' "$WORK/last.body" && ok invalid-db-jsonrpc-shape || bad invalid-db-jsonrpc-shape ""
{ grep -q '"error"' "$WORK/last.body" && grep -q '"data"' "$WORK/last.body"; } \
  && ok invalid-db-error-shape || bad invalid-db-error-shape ""
req "$J3" POST /web/session/authenticate -H "X-Team-Gateway: attacker" -H "Content-Type: application/json" \
  --data-binary "$(rpc_auth x y 5)"
if leak_hit | grep -q .; then bad invalid-db-spoof-header-leak "hit=$(leak_hit)"; else ok invalid-db-spoof-header-no-leak; fi
# gating 反向证明：直连 Odoo（无入口覆盖头）保留原 debug 行为，说明补丁仅作用于公网入口
DIRECT=$(curl -s --noproxy "*" --max-time 10 -H "Content-Type: application/json" \
  --data-binary "$(rpc_auth x y 6)" "$ODOO_URL/web/session/authenticate" 2>/dev/null)
printf '%s' "$DIRECT" | grep -q '"debug"' && ok gateway-scope-direct-original || bad gateway-scope-direct-original ""
J8=$(jar d2); : > "$J8"; login "$U_CAT" 'wrong-pass-quoted-"x"' "$J8" >/dev/null
grep -q 'AccessDenied' "$WORK/last.body" && ok safe-exception-kept || bad safe-exception-kept ""
grep -q 'odoo.exceptions.AccessDenied' "$WORK/last.body" && ok access-denied-fullname || bad access-denied-fullname ""
JOK=$(jar ok); : > "$JOK"; login "$U_MGR" "$P2_PASS" "$JOK" >/dev/null
req "$JOK" POST /web/session/get_session_info -H "Content-Type: application/json" --data-binary "$(rpc_sess 7)"
grep -q 'trace_id' "$WORK/last.body" && bad success-no-trace-id "成功响应被改写" || ok success-no-trace-id
SCOPE=$(curl -s --noproxy "*" --max-time 10 -H 'Content-Type: application/json' \
  -H 'X-Team-Gateway: lab-team-web' -H 'X-Forwarded-Host: team.l-creation.club' \
  --data-binary "$(rpc_call 9 '{"model":"res.users","method":"search_read","args":[]}')" \
  "$ODOO_URL/web/dataset/call_kw" 2>/dev/null)
printf '%s' "$SCOPE" | grep -q '"debug"' && ok gateway-endpoint-scope || bad gateway-endpoint-scope ""
grep -q '"ServerError"' "$WORK/last.body" && bad safe-exception-not-generic "AccessDenied 被泛化" || ok safe-exception-not-generic

# ---------------------------------------------------------------------------
# E next 边界
# ---------------------------------------------------------------------------
J4=$(jar next); : > "$J4"
req "$J4" GET "/login?next=//evil.example"
grep -q 'data-next="//evil' "$WORK/last.body" && bad next-open-redirect "unsanitized" || ok next-sanitized
req "$J4" GET "/login?next=/lab/items/$DETAIL_KEY"
DK_RE=$(printf "%s" "$DETAIL_KEY" | sed "s/:/[:%3Aa-fA-F]*/g")
grep -qE "data-next=\"/lab/items/$DK_RE\"" "$WORK/last.body" && ok next-deep-link-preserved \
  || bad next-deep-link-preserved "actual=$(grep -o 'data-next="[^"]*"' "$WORK/last.body" | head -1)"

# ---------------------------------------------------------------------------
# F 角色边界
# ---------------------------------------------------------------------------
role_check() {
  local u=$1 want_lab=$2 want_item=$3 j uid c1 c2
  j=$(jar "role_$u"); : > "$j"
  uid=$(login "$u" "$P2_PASS" "$j"); [ -n "$uid" ] || { bad "role-login-$u" "no-uid"; return; }
  req "$j" GET /lab; c1=$CODE
  [ "$c1" = "$want_lab" ] && ok "role-lab-$u" || bad "role-lab-$u" "got=$c1 want=$want_lab"
  req "$j" GET "/lab/items/$DETAIL_KEY"; c2=$CODE
  [ "$c2" = "$want_item" ] && ok "role-item-$u" || bad "role-item-$u" "got=$c2 want=$want_item"
}
role_check "$U_NOROLE" 403 403
role_check "$U_CAT"   200 200
role_check "$U_OP"    200 200
role_check "$U_MGR"   200 200

# ---------------------------------------------------------------------------
# G 安全头
# ---------------------------------------------------------------------------
HDR=$(curl -s -D - -o /dev/null --noproxy "*" --max-time 10 --cacert "$CA" --resolve "$RESOLVE" \
  "https://team.l-creation.club:$P_EDGE/login")
printf '%s' "$HDR" | grep -qi "content-security-policy" && ok header-csp || bad header-csp ""
printf '%s' "$HDR" | grep -qi "x-content-type-options:.*nosniff" && ok header-nosniff || bad header-nosniff ""
printf '%s' "$HDR" | grep -qi "x-frame-options:.*DENY" && ok header-xfo || bad header-xfo ""
printf '%s' "$HDR" | grep -qi "referrer-policy" && ok header-referrer || bad header-referrer ""

# ---------------------------------------------------------------------------
# H Cookie 标志（只看响应头标志名，不保存值）
# ---------------------------------------------------------------------------
J6=$(jar flags2); : > "$J6"
LOGIN_HDR=$(curl -s -D - -o /dev/null --noproxy "*" --max-time 10 --cacert "$CA" --resolve "$RESOLVE" \
  -c "$J6" -H "Content-Type: application/json" -X POST --data-binary "$(rpc_auth "$U_MGR" "$P2_PASS" 6)" \
  "https://team.l-creation.club:$P_EDGE/web/session/authenticate" | grep -i "^set-cookie:.*session_id" || true)
printf '%s' "$LOGIN_HDR" | grep -qi "HttpOnly" && ok cookie-httponly || bad cookie-httponly ""
printf '%s' "$LOGIN_HDR" | grep -qi "Secure" && ok cookie-secure || bad cookie-secure "缺 Secure（Odoo 上游仅 HttpOnly）"
printf '%s' "$LOGIN_HDR" | grep -qi "SameSite" && ok cookie-samesite || bad cookie-samesite "缺 SameSite（Odoo 上游仅 HttpOnly）"

# ---------------------------------------------------------------------------
# I 跨来源 / 更新清单 / 拒绝路径
# ---------------------------------------------------------------------------
req "$J6" POST /web/session/authenticate -H "Origin: http://evil.example" -H "Content-Type: application/json" \
  --data-binary "$(rpc_auth "$U_MGR" "$P2_PASS" 8)"
JO=$(jar o); : > "$JO"; login "$U_MGR" "$P2_PASS" "$JO" >/dev/null
origin_destroy() { # jar origin
  local j=$1 o=$2 extra=()
  [ "$o" != "__none__" ] && extra=(-H "Origin: $o")
  curl -s -o "$WORK/last.body" -w '%{http_code}' --noproxy "*" --max-time 15 --cacert "$CA" \
    --resolve "$RESOLVE" -b "$j" -c "$j" -X POST "${extra[@]}" \
    -H "Content-Type: application/json" --data-binary "$(rpc_sess 2)" \
    "https://team.l-creation.club:$P_EDGE/web/session/destroy"
}
OE=$(origin_destroy "$JO" "http://evil.example"); [ "$OE" = 403 ] && ok origin-evil-403 || bad origin-evil-403 "$OE"
req "$JO" POST /web/session/get_session_info -H "Content-Type: application/json" --data-binary "$(rpc_sess 2)"
[ -n "$(uid_of "$WORK/last.body")" ] && ok origin-evil-session-kept || bad origin-evil-session-kept ""
ON=$(origin_destroy "$JO" "null"); [ "$ON" = 403 ] && ok origin-null-403 || bad origin-null-403 "$ON"
req "$JO" POST /web/session/get_session_info -H "Content-Type: application/json" --data-binary "$(rpc_sess 2)"
[ -n "$(uid_of "$WORK/last.body")" ] && ok origin-null-session-kept || bad origin-null-session-kept ""
JO2=$(jar o2); : > "$JO2"; login "$U_CAT" "$P2_PASS" "$JO2" >/dev/null
OS=$(origin_destroy "$JO2" "https://team.l-creation.club:$P_EDGE"); [ "$OS" = 200 ] && ok origin-sameport-allowed || bad origin-sameport-allowed "$OS"
JO3=$(jar o3); : > "$JO3"; login "$U_CAT" "$P2_PASS" "$JO3" >/dev/null
OA=$(origin_destroy "$JO3" "__none__"); [ "$OA" = 200 ] && ok origin-native-no-header-allowed || bad origin-native-no-header-allowed "$OA"

JN=$(jar anon); : > "$JN"
MANCODE=$(curl -s -o "$WORK/manifest.bin" -w "%{http_code}" --noproxy "*" --max-time 15 --cacert "$CA" \
  --resolve "$RESOLVE" -b "$JN" -c "$JN" \
  "https://team.l-creation.club:$P_EDGE/lab/client/updates/manifest?platform=android&arch=universal&channel=stable")
MAN=$("$PYTHON" - "$WORK/manifest.bin" <<'PY' 2>/dev/null
import base64, json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
p = json.loads(base64.b64decode(d["payload"]))
print(p["release_id"], p["filename"], p["sha256"], p["size"], p["schema"], p["platform"], p["arch"], p["channel"])
PY
)
if [ "$MANCODE" = 200 ] && [ -n "$MAN" ]; then
  ok updates-anon-200
  # Keep only the anonymous public test manifest and public-key evidence.
  cp "$WORK/manifest.bin" "$WORK/public-manifest.json"
  if [ -n "${P2_UPDATE_KEY_EVIDENCE:-}" ] && [ -r "$P2_UPDATE_KEY_EVIDENCE" ]; then
    cp "$P2_UPDATE_KEY_EVIDENCE" "$WORK/fixture-public-key.json"
    if "$PYTHON" "$BORE_DIR/tests/fixtures/signed_update_fixture.py" verify \
      --manifest "$WORK/public-manifest.json" --public-key-evidence "$WORK/fixture-public-key.json" \
      > "$WORK/signature-verification.json" 2> "$WORK/logs/signature-verification.err"; then
      ok updates-signature-verified "Ed25519 public-key verification of downloaded manifest"
    else
      bad updates-signature-verified "downloaded manifest signature/public-key evidence mismatch"
    fi
  else
    block updates-signature-verified "missing isolated test public-key evidence"
  fi
  set -- $MAN
  { [ "$5" = 1 ] && [ "$6" = android ] && [ "$7" = universal ] && [ "$8" = stable ]; } && ok updates-schema || bad updates-schema "fields=$*"
  REL=$1; FN=$2; WANT_SHA=$3; WANT_SIZE=$4
  ANON=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 15 --cacert "$CA" --resolve "$RESOLVE" -b "$JN" \
    "https://team.l-creation.club:$P_EDGE/lab/client/updates/assets/$REL/$FN")
  { [ "$ANON" = 303 ] || [ "$ANON" = 401 ] || [ "$ANON" = 403 ]; } && ok updates-anon-asset-denied || bad updates-anon-asset-denied "code=$ANON"
  req "$JOK" GET "/lab/client/updates/assets/$REL/$FN"; [ "$CODE" = 200 ] && ok updates-user-asset-200 || bad updates-user-asset-200 "code=$CODE"
  ASIZE=$(wc -c < "$WORK/last.body"); [ "$ASIZE" = "$WANT_SIZE" ] && ok updates-size || bad updates-size "$ASIZE vs $WANT_SIZE"
  ASHA=$(sha256sum "$WORK/last.body" | cut -d" " -f1); [ "$ASHA" = "$WANT_SHA" ] && ok updates-sha256 || bad updates-sha256 ""
  JNO=$(jar noupdate); : > "$JNO"; login "$U_NOROLE" "$P2_PASS" "$JNO" >/dev/null
  req "$JNO" GET "/lab/client/updates/assets/$REL/$FN"; [ "$CODE" = 403 ] && ok updates-norole-denied || bad updates-norole-denied "code=$CODE"
  req "$J6" GET "/lab/client/updates/assets/$REL/..%2F..%2Fetc%2Fpasswd"; [ "$CODE" = 404 ] && ok updates-traversal-404 || bad updates-traversal-404 "code=$CODE"
else
  block updates-anon-200 "无合成 release（seed 未运行）: code=$MANCODE"
fi
for p in /web/dataset/call_kw /jsonrpc /web /odoo /website/home /report/x; do
  req "$J6" GET "$p"; [ "$CODE" = 404 ] && ok "deny-$p" || bad "deny-$p" "$CODE"
done

# ---------------------------------------------------------------------------
# K 浏览器流程（headless Chrome，真实页面/JS/CSP）
# 只认“stdout 与落盘 browser.json 完全一致 + 全部步骤通过 + rc==0”，不按部分 steps 记成功
# ---------------------------------------------------------------------------
if [ -n "${P2_CHROME_BIN:-}" ] && [ -x "${P2_CHROME_BIN:-}" ]; then
  BOUT="$WORK/browser"; mkdir -p "$BOUT"
  SPKI=$(openssl x509 -in "$WORK/certs/s.pem" -pubkey -noout | openssl pkey -pubin -outform der 2>/dev/null \
    | openssl dgst -sha256 -binary | openssl base64 -A)
  env CHROME_BIN="$P2_CHROME_BIN" URL="https://team.l-creation.club:$P_EDGE" \
      LOGIN="${P2_BROWSER_LOGIN:-$U_CAT}" PASSWORD="$P2_PASS" OUT_DIR="$BOUT" SPKI="$SPKI" \
      CA_FILE="$WORK/certs/ca.pem" P2_DETAIL_KEY="$DETAIL_KEY" P2_QUERY="${P2_QUERY:-TEST-R-10K}" \
      "$PYTHON" "$BORE_DIR/tests/browser_flow.py" >"$WORK/logs/browser.stdout.json" 2>"$WORK/logs/browser.err"
  BRC=$?
  BROWSER_CHECK=$("$PYTHON" - "$WORK/logs/browser.stdout.json" "$BOUT/browser.json" "$BRC" <<'PY'
import hashlib, json, os, re, sys

stdout_path, file_path, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
problems = []
notes = {}
raw_stdout = b""
raw_file = b""
try:
    with open(stdout_path, "rb") as fh:
        raw_stdout = fh.read()
except OSError:
    problems.append("missing-stdout-json")
try:
    with open(file_path, "rb") as fh:
        raw_file = fh.read()
except OSError:
    problems.append("missing-browser-json")

out = json.loads(raw_stdout) if raw_stdout.strip() else {}
disk = json.loads(raw_file) if raw_file.strip() else {}

def norm(doc):
    steps = [(str(s.get("name")), bool(s.get("ok")), str(s.get("detail") or ""))
             for s in (doc.get("steps") or []) if isinstance(s, dict)]
    console = doc.get("console") or {}
    errors = doc.get("console_errors", console.get("errors", []))
    return {"ok": bool(doc.get("ok")), "steps": steps,
            "console_errors": [str(x) for x in (errors or [])]}

no, nd = norm(out), norm(disk)
if not no["steps"]:
    problems.append("no-steps")
if out != disk:
    problems.append("stdout-file-mismatch")
for doc in (out, disk):
    if type(doc.get("ok")) is not bool or any(type(step.get("ok")) is not bool for step in (doc.get("steps") or []) if isinstance(step, dict)):
        problems.append("non-boolean-result")
if no["console_errors"]:
    problems.append("console-errors-present")
if rc != 0:
    problems.append("rc=%d" % rc)
if not no["ok"]:
    problems.append("json-ok-false")
REQUIRED = ("env", "chrome-launch", "cdp-connect", "login-page", "login-ui-submit", "lab-authenticated", "search-ui-input", "search-rpc-query", "search-dom-match", "detail-link", "detail-ui-click", "detail-content", "detail-not-error", "refresh-ui", "refresh-authenticated", "refresh-content", "logout-cookie-capture", "logout-ui-submit", "logout-redirect-303", "logout-login-page", "logout-session-anon", "anon-lab-303", "anon-login-page-visible", "anon-old-cookie-invalid", "console-clean", "network-clean", "evidence-redaction", "profile-cleanup")
names = [name for name, _, _ in no["steps"]]
if len(names) != len(set(names)):
    problems.append("duplicate-step")
for need in REQUIRED:
    if need not in names:
        problems.append("missing-step:%s" % need)
failed = [name for name, ok, _ in no["steps"] if not ok]
if failed:
    problems.append("failed-steps:" + ",".join(failed))
notes["steps"] = len(no["steps"])
notes["failed"] = len(failed)
notes["console_errors"] = len(no["console_errors"])

# 网络证据脱敏：删除 postData/请求头，剔除 cookie/token/password 字段
SECRET_KEY = re.compile(r"(?i)(cookie|token|password|passwd|authorization|secret|csrf)")
secret = os.environ.get("P2_PASS") or ""

removed = 0
for doc in (disk, out):
    tail = doc.get("network_tail")
    if isinstance(tail, list):
        for entry in tail:
            if not isinstance(entry, dict):
                continue
            for key in list(entry.keys()):
                if SECRET_KEY.search(key):
                    entry.pop(key, None)
                    removed += 1
            if "postData" in entry:
                entry.pop("postData", None)
                removed += 1
            if "url" in entry:
                entry["url"] = re.sub(r"(?i)([?&](?:csrf_token|token|session_id)=)[^&]*", r"\1***", str(entry["url"]))
    for key in ("cookie", "cookies", "headers", "request_headers"):
        if key in doc:
            doc.pop(key, None)
            removed += 1

if secret:
    for doc in (disk, out):
        text = json.dumps(doc)
        if secret in text:
            problems.append("password-in-evidence")

if removed:
    problems.append("sensitive-fields-in-browser-evidence")
    notes["redacted_fields"] = removed
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(disk, fh, ensure_ascii=False, indent=2)
    with open(stdout_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
notes["stdout_sha256"] = hashlib.sha256(raw_stdout).hexdigest()[:16]
notes["browser_json_sha256"] = hashlib.sha256(raw_file).hexdigest()[:16]
print(json.dumps({"problems": problems, "notes": notes}, ensure_ascii=False, sort_keys=True))
PY
)
  BROWSER_OK=1
  printf '%s' "$BROWSER_CHECK" | grep -q '"problems": \[\]' || BROWSER_OK=0
  if [ "$BROWSER_OK" = 1 ]; then
    ok browser-flow "$BROWSER_CHECK"
  else
    bad browser-flow "rc=$BRC check=$BROWSER_CHECK tail=$(redacted_tail "$WORK/logs/browser.err" 6)"
  fi
  # 逐步结果同样进入 results.jsonl（来源=已核对且已脱敏的 browser.json）
  if [ -r "$BOUT/browser.json" ]; then
    while IFS="|" read -r st name flag detail; do
      [ -n "$name" ] || continue
      if [ "$flag" = "1" ]; then ok "browser-$name"; else bad "browser-$name" "$detail"; fi
    done < <("$PYTHON" - "$BOUT/browser.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
for step in doc.get("steps") or []:
    name = str(step.get("name") or "")
    if not name or any(c in name for c in "|\n"):
        continue
    detail = " ".join(str(step.get("detail") or "").split())[:160]
    print("STEP|%s|%s|%s" % (name, "1" if step.get("ok") else "0", detail))
PY
)
  else
    skip browser-steps "无 browser.json，逐步结果不可用"
  fi
else
  skip browser-flow "未提供 P2_CHROME_BIN（headless Chrome 不可用）"
fi

# ---------------------------------------------------------------------------
# J 限速（两个合成来源）与 Odoo 冷却区分：先重渲染启用 1r/m 再 reload
# ---------------------------------------------------------------------------
render_entry "limit_req zone=p2_auth nodelay; limit_req_status 503;"
if "$NGINX_BIN" -p "$WORK/nginx" -c "$WORK/nginx/nginx.conf" -t >/dev/null 2>&1 \
   && "$NGINX_BIN" -p "$WORK/nginx" -c "$WORK/nginx/nginx.conf" -s reload >/dev/null 2>&1; then
  sleep 1
  ev p2-rate-reload pass "已启用 1r/m 限速"
else
  bad p2-rate-reload "$(redacted_tail "$WORK/logs/entry.err" 6)"
fi
rate_login() { # source-ip
  local ip=$1 body
  body="$(rpc_auth "$U_CAT" "$P2_PASS" 8)" || { printf '000'; return 0; }
  curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 12 --interface "$ip" --cacert "$CA" \
    --resolve "$RESOLVE" -X POST -H "Content-Type: application/json" --data-binary "$body" \
    "https://team.l-creation.club:$P_EDGE/web/session/authenticate"
}
A1=$(rate_login 127.0.0.5); A2=$(rate_login 127.0.0.5); B1=$(rate_login 127.0.0.6)
[ "$A1" = 200 ] && ok rate-limit-first-200 || bad rate-limit-first-200 "A1=$A1"
[ "$A2" = 503 ] && ok rate-limit-503 || bad rate-limit-503 "A2=$A2"
[ "$B1" = 200 ] && ok rate-limit-other-source-ok || bad rate-limit-other-source-ok "B1=$B1"

# ---------------------------------------------------------------------------
# K 无角色页不含堆栈
# ---------------------------------------------------------------------------
J7=$(jar norole2); : > "$J7"; login "$U_NOROLE" "$P2_PASS" "$J7" >/dev/null
req "$J7" GET /lab
grep -qE "Traceback|/home/" "$WORK/last.body" && bad norole-no-stack "leak" || ok norole-no-stack

# ---------------------------------------------------------------------------
# 结束：FAIL/BLOCKED/证据错误决定 rc
# ---------------------------------------------------------------------------
if [ "$EVIDENCE_ERROR" = 1 ]; then exit 4; fi
if [ "$FAIL" -gt 0 ]; then exit 1; fi
if [ "$BLOCKED" -gt 0 ]; then exit 3; fi
exit 0