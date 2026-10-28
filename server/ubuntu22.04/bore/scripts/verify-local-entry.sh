#!/usr/bin/env bash
# 本地 P1 隔离入口验证（真实 Nginx + bore + 合成上游）
# 链路：访客 → 公开边缘 Nginx(stream, 不接受客户端 PROXY) → bore 隧道 → 入口 Nginx(TLS+PROXY) → 上游
# 依赖：NGINX_BIN、BORE_BIN、MODULE_SO（stream 模块）必填；缺失 -> blocked(exit 3)
# 运行目录：默认在 local/build/bore-p1-20261026/runs 下新建唯一目录；若 WORK 已存在则拒绝运行。
set -uo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BORE_DIR/../../.." && pwd)"
BASE="$REPO_ROOT/local/build/bore-p1-20261026"
PYTHON="${PYTHON:-python3}"
OPENSSL="${OPENSSL:-openssl}"
DB_SYNTH="bore_p1_synth_db"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy 2>/dev/null || true
export NO_PROXY="*" no_proxy="*"

P_HTTP=8082; P_BORETLS=8444; P_ENTRY=8443; P_UP=9000; P_EDGE=9500
P_BORE_CTRL=7835; P_BORE_PUB=20000; P_BORE_TLS_PUB=20001

PASS=0; FAIL=0
TRACK=()   # 条目：pid|starttime|ident（ident: nginx|bore|python）
say() { printf '%s\n' "$*"; }
jline() { "$PYTHON" -c 'import json,sys; sys.stdout.write(json.dumps({"id":sys.argv[1],"result":sys.argv[2],"detail":sys.argv[3]})+"\n")' "$1" "$2" "$3"; }
ok()  { PASS=$((PASS+1)); say "PASS  $1"; jline "$1" pass "" >> "$RESULTS"; }
bad() { FAIL=$((FAIL+1)); say "FAIL  $1 :: $2"; jline "$1" fail "$2" >> "$RESULTS"; }
blocked() {
  say "BLOCKED: $*"
  printf '{"blocked":"%s","pass":%d,"fail":%d}\n' "$*" "$PASS" "$FAIL" > "$WORK/summary.json" 2>/dev/null || true
  exit 3
}
track() { # pid ident
  local pid=$1 ident=$2 st
  [ -r "/proc/$pid/stat" ] || return 1
  st=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)
  [ -n "$st" ] && TRACK+=("$pid|$st|$ident")
}
same_process() { # pid starttime ident
  local pid=$1 st=$2 ident=$3
  [ -r "/proc/$pid/stat" ] || return 1
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$st" ] || return 1
  local comm; comm=$(cat "/proc/$pid/comm" 2>/dev/null)
  case "$ident" in
    nginx) [ "$comm" = "nginx" ] ;;
    bore)  [ "$comm" = "bore" ] ;;
    python) case "$comm" in python*|Python*) true ;; *) false ;; esac ;;
    *) false ;;
  esac
}
cleanup() {
  local entry pid st ident i
  for entry in "${TRACK[@]:-}"; do
    [ -n "$entry" ] || continue
    IFS='|' read -r pid st ident <<< "$entry"
    same_process "$pid" "$st" "$ident" || continue
    kill "$pid" 2>/dev/null
    for i in $(seq 1 20); do
      same_process "$pid" "$st" "$ident" || break
      sleep 0.1
    done
    same_process "$pid" "$st" "$ident" && kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  done
}
trap cleanup EXIT

# ---------- 运行目录（唯一，拒绝复用）----------
mkdir -p "$BASE/runs"
if [ -n "${WORK:-}" ]; then
  [ -e "$WORK" ] && { say "REFUSE: WORK 已存在，拒绝复用：$WORK"; exit 4; }
  mkdir -p "$WORK" || { say "REFUSE: 无法创建 WORK"; exit 4; }
else
  WORK="$(mktemp -d "$BASE/runs/run.XXXXXX")" || { say "REFUSE: mktemp 失败"; exit 4; }
fi
echo "$WORK" > "$BASE/latest-run"
RESULTS="$WORK/results.jsonl"; : > "$RESULTS"

# 入参统一转绝对路径（Nginx -p 后相对 module 路径会解析错误）
abspath() { case "$1" in /*) printf "%s" "$1" ;; *) printf "%s/%s" "$PWD" "$1" ;; esac; }
[ -n "${NGINX_BIN:-}" ] && NGINX_BIN="$(abspath "$NGINX_BIN")"
[ -n "${MODULE_SO:-}" ] && MODULE_SO="$(abspath "$MODULE_SO")"
[ -n "${BORE_BIN:-}" ] && BORE_BIN="$(abspath "$BORE_BIN")"

# ---------- 依赖与端口 ----------
[ -x "${NGINX_BIN:-}" ] || blocked "NGINX_BIN 不可执行"
[ -x "${BORE_BIN:-}" ] || blocked "BORE_BIN 不可执行"
[ -f "${MODULE_SO:-}" ] || blocked "MODULE_SO(stream) 缺失"
command -v "$PYTHON" >/dev/null || blocked "缺少 $PYTHON"
command -v "$OPENSSL" >/dev/null || blocked "缺少 $OPENSSL"
port_free_now() { ! ss -lnt 2>/dev/null | grep -q ":$1 "; }
wait_port_free() { for _ in $(seq 1 50); do port_free_now "$1" && return 0; sleep 0.1; done; return 1; }
for p in "$P_HTTP" "$P_BORETLS" "$P_ENTRY" "$P_UP" "$P_EDGE" "$P_BORE_CTRL" "$P_BORE_PUB" "$P_BORE_TLS_PUB"; do
  wait_port_free "$p" || blocked "端口已被占用：$p"
done
mkdir -p "$WORK/nginx" "$WORK/edge" "$WORK/certs" "$WORK/logs"

# ---------- 证书（失败即 blocked）----------
"$OPENSSL" req -x509 -newkey rsa:2048 -nodes -keyout "$WORK/certs/ca.key" -out "$WORK/certs/ca.pem" \
  -days 2 -subj "/CN=bore-p1-local-test-ca" >/dev/null 2>&1 || blocked "生成测试 CA 失败"
printf 'subjectAltName=DNS:team.l-creation.club\nextendedKeyUsage=serverAuth\n' > "$WORK/certs/server.ext"
"$OPENSSL" req -newkey rsa:2048 -nodes -keyout "$WORK/certs/server.key" -out "$WORK/certs/server.csr" \
  -subj "/CN=team.l-creation.club" >/dev/null 2>&1 || blocked "生成服务端 CSR 失败"
"$OPENSSL" x509 -req -in "$WORK/certs/server.csr" -CA "$WORK/certs/ca.pem" -CAkey "$WORK/certs/ca.key" \
  -CAcreateserial -out "$WORK/certs/server.pem" -days 2 -extfile "$WORK/certs/server.ext" >/dev/null 2>&1 \
  || blocked "签发测试证书失败"
say "work: $WORK"

# ---------- 渲染 ----------
render_entry() { # name listen ssl realip db rate
  local name=$1 listen=$2 ssl=$3 realip=$4 db=$5 rate=$6
  sed -e "s|@LISTEN_LINE@|$listen|" -e "s|@SSL_LINES@|$ssl|" -e "s|@REALIP_LINES@|$realip|" \
      -e "s|@UPSTREAM@|http://127.0.0.1:$P_UP|" -e "s|@RATE_LIMIT@|$rate|" \
      -e "s|@COOKIE_FLAGS@||" -e "s|@PUBLIC_PORT@|$P_EDGE|g" \
      -e "s|include bore-proxy-headers.conf;|include $WORK/nginx/headers-$name.conf;|g" \
      "$BORE_DIR/nginx/bore-public-allowlist.conf.template" > "$WORK/nginx/variant-$name.conf"
  sed -e "s|@DB_HEADER@|proxy_set_header X-Odoo-Database $db;|" \
      "$BORE_DIR/nginx/bore-proxy-headers.conf" > "$WORK/nginx/headers-$name.conf"
}
CERT="ssl_certificate $WORK/certs/server.pem; ssl_certificate_key $WORK/certs/server.key; ssl_protocols TLSv1.2 TLSv1.3;"
render_entry http    "listen 127.0.0.1:$P_HTTP;" "" "" "$DB_SYNTH" ""
render_entry boretls "listen 127.0.0.1:$P_BORETLS ssl;" "$CERT" "" "$DB_SYNTH" ""
sed -i "s|@COOKIE_FLAGS@||g" "$WORK"/nginx/variant-*.conf 2>/dev/null || true
render_entry entry   "listen 127.0.0.1:$P_ENTRY ssl proxy_protocol;" "$CERT" \
  "real_ip_header proxy_protocol; set_real_ip_from 127.0.0.1;" "$DB_SYNTH" \
  "limit_req zone=bore_auth nodelay; limit_req_status 503;"

cat > "$WORK/nginx/nginx.conf" <<EOF
load_module $MODULE_SO;
worker_processes 1;
pid $WORK/nginx/nginx.pid;
error_log $WORK/nginx/error.log info;
events { worker_connections 256; }
http {
    map \$http_origin \$p2_origin_ok { default 0; "" 1; "https://team.l-creation.club" 1; "https://team.l-creation.club:9500" 1; }
    map "\$request_method:\$p2_origin_ok" \$p2_reject_post { default 0; "POST:0" 1; }
    access_log $WORK/nginx/access.log;
    client_body_temp_path $WORK/nginx/body;
    proxy_temp_path $WORK/nginx/proxy;
    fastcgi_temp_path $WORK/nginx/fcgi;
    uwsgi_temp_path $WORK/nginx/uwsgi;
    scgi_temp_path $WORK/nginx/scgi;
    limit_req_zone \$remote_addr zone=bore_auth:1m rate=1r/m;
    include $WORK/nginx/variant-http.conf;
    include $WORK/nginx/variant-boretls.conf;
    include $WORK/nginx/variant-entry.conf;
}
EOF

# 边缘由正式模板渲染（公开监听不接受客户端 PROXY）
sed -e "s|@EDGE_LISTEN@|127.0.0.1:$P_EDGE|" -e "s|@TUNNEL_ADDR@|127.0.0.1:$P_BORE_PUB|" \
    "$BORE_DIR/nginx/bore-edge-stream.conf.template" > "$WORK/edge/nginx.conf"
sed -i "1i load_module $MODULE_SO;" "$WORK/edge/nginx.conf"
sed -i "1a worker_processes 1;\npid $WORK/edge/nginx.pid;\nerror_log $WORK/edge/error.log warn;" "$WORK/edge/nginx.conf"

"$NGINX_BIN" -p "$WORK/nginx" -c "$WORK/nginx/nginx.conf" -t 2>"$WORK/logs/entry-t.err" \
  && ok "entry-nginx-config" || { bad "entry-nginx-config" "$(tail -3 "$WORK/logs/entry-t.err")"; cleanup; exit 1; }
"$NGINX_BIN" -p "$WORK/edge" -c "$WORK/edge/nginx.conf" -t 2>"$WORK/logs/edge-t.err" \
  && ok "edge-nginx-config" || { bad "edge-nginx-config" "$(tail -3 "$WORK/logs/edge-t.err")"; cleanup; exit 1; }

# ---------- 启动 ----------
# 合成上游：在共享实现（tests/synthetic_upstream.py，行为不变、不改它）的记录字段之外，
# 额外记录 Host / X-Forwarded-Host / X-Forwarded-Port，用于本轮"外部端口是否被保留"
# 与"伪造转发头是否被覆盖/清空"的断言。只写在本次运行目录，不改共享测试资产。
: > "$WORK/logs/upstream.jsonl"
cat > "$WORK/upstream_logger.py" <<'PY'
import json, re, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]); LOG = sys.argv[2]
ITEM = re.compile(r"^/(?:team/)?lab/items/[^/]+$")
EXACT = {
    "/", "/login", "/team", "/team/", "/team/login", "/team/lab", "/lab",
    "/lab/api/asset", "/lab/client/updates/manifest",
    "/lab/api/catalog/search", "/lab/api/catalog/detail",
    "/lab/api/catalog/categories", "/lab/api/catalog/facets",
    "/web/session/authenticate", "/web/session/get_session_info", "/web/session/destroy",
    "/team/api/session", "/api/team/session", "/team/logout", "/logout",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self):
        path = self.path.split("?")[0]
        known = (path in EXACT or bool(ITEM.match(path))
                 or path.startswith("/lab_team_web/static/")
                 or path.startswith("/lab/client/updates/assets/"))
        entry = {
            "method": self.command, "path": path, "known": known,
            "host": self.headers.get("Host", ""),
            "xff": self.headers.get("X-Forwarded-For", ""),
            "x_real_ip": self.headers.get("X-Real-IP", ""),
            "xf_proto": self.headers.get("X-Forwarded-Proto", ""),
            "xf_host": self.headers.get("X-Forwarded-Host", ""),
            "xf_port": self.headers.get("X-Forwarded-Port", ""),
            "forwarded": self.headers.get("Forwarded", ""),
            "x_odoo_database": self.headers.get("X-Odoo-Database", ""),
        }
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if known:
            body = b'{"synthetic":true,"ok":true}'; status = 200
        else:
            body = b'{"synthetic":true,"error":"not_found"}'; status = 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_HEAD = _handle

    def log_message(self, *args):
        return


HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
PY
"$PYTHON" "$WORK/upstream_logger.py" "$P_UP" "$WORK/logs/upstream.jsonl" \
  >"$WORK/logs/upstream.out" 2>&1 & track $! python
"$BORE_BIN" server --bind-addr 127.0.0.1 --bind-tunnels 127.0.0.1 >"$WORK/logs/bore-server.log" 2>&1 &
track $! bore
sleep 1
"$BORE_BIN" local "$P_BORETLS" --to 127.0.0.1 --port "$P_BORE_TLS_PUB" >"$WORK/logs/bore-client.log" 2>&1 &
track $! bore
"$BORE_BIN" local "$P_ENTRY" --to 127.0.0.1 --port "$P_BORE_PUB" >"$WORK/logs/bore-entry.log" 2>&1 &
track $! bore
"$NGINX_BIN" -p "$WORK/nginx" -c "$WORK/nginx/nginx.conf" 2>>"$WORK/logs/entry.err" \
  || { bad "entry-nginx-start" "$(tail -3 "$WORK/logs/entry.err" 2>/dev/null)"; exit 1; }
track "$(cat "$WORK/nginx/nginx.pid")" nginx
"$NGINX_BIN" -p "$WORK/edge" -c "$WORK/edge/nginx.conf" 2>>"$WORK/logs/edge.err" \
  || { bad "edge-nginx-start" "$(tail -3 "$WORK/logs/edge.err" 2>/dev/null)"; exit 1; }
track "$(cat "$WORK/edge/nginx.pid")" nginx
sleep 1

wait_port() { for _ in $(seq 1 50); do (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return 0; sleep 0.15; done; return 1; }
wait_port "$P_UP" && ok "upstream-listening" || { bad "upstream-listening" ""; exit 1; }
wait_port "$P_HTTP" && ok "http-listener" || { bad "http-listener" ""; exit 1; }
wait_port "$P_EDGE" && ok "edge-listener" || { bad "edge-listener" ""; exit 1; }
# Nginx 进程身份校验（防旧 pid 复用）
for name in nginx edge; do
  pf="$WORK/$name/nginx.pid"
  if [ -f "$pf" ] && tr '\0' ' ' < "/proc/$(cat "$pf")/cmdline" 2>/dev/null | grep -q "$WORK"; then
    ok "$name-pid-identity"
  else
    bad "$name-pid-identity" "pid 不属于本次运行"
  fi
done

CODE=""; RC=0
call() { # method url host [curl args...]
  local method=$1 url=$2 host=$3; shift 3
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 10 -X "$method" -H "Host: $host" "$@" "$url" 2>/dev/null); RC=$?
}
upstream_lines() { wc -l < "$WORK/logs/upstream.jsonl"; }
upstream_count() { grep -c "\"method\": \"$1\", \"path\": \"$2\"" "$WORK/logs/upstream.jsonl" 2>/dev/null || true; }
expect() { # id want method path
  call "$3" "http://127.0.0.1:$P_HTTP$4" team.l-creation.club --path-as-is
  [ "$CODE" = "$2" ] && ok "$1" || bad "$1" "want=$2 got=$CODE rc=$RC"
}

# ---------- 渲染不得残留占位；CSP 严格 self ----------
grep -q "@CSP_CONNECT_EXTRA@" "$WORK/nginx/variant-entry.conf" \
  && bad "csp-placeholder-removed" "模板仍含 @CSP_CONNECT_EXTRA@" || ok "csp-placeholder-removed"
grep -qE "connect-src 'self';" "$WORK/nginx/variant-entry.conf" \
  && ok "csp-connect-self-only" || bad "csp-connect-self-only" "connect-src 非严格 self"

# ---------- 公开 authority（严格校验 $http_host，保留外部端口）----------
call GET "http://127.0.0.1:$P_HTTP/team" team.l-creation.club
[ "$CODE" = "200" ] && ok "host-match" || bad "host-match" "got=$CODE rc=$RC"
# 外部 9500 端口必须被接受；随后还要证明它被原样传给上游（见"头覆盖"段）
call GET "http://127.0.0.1:$P_HTTP/team" "team.l-creation.club:$P_EDGE"
[ "$CODE" = "200" ] && ok "host-with-external-port-9500" || bad "host-with-external-port-9500" "got=$CODE rc=$RC"
call GET "http://127.0.0.1:$P_HTTP/team" "team.l-creation.club:443"
[ "$CODE" = "200" ] && ok "host-with-port-443" || bad "host-with-port-443" "got=$CODE rc=$RC"
# 非法 authority（其它域名/内部端口/越界/大小写/末尾点/逗号注入/前导零/带路径）一律断开且上游 0
: > "$WORK/logs/upstream.jsonl"
for spec in "evil.example|other-domain" "team.l-creation.club:$P_HTTP|internal-port" \
            "team.l-creation.club:$P_ENTRY|entry-port-8443" "team.l-creation.club:95000|out-of-range" \
            "Team.L-Creation.Club|uppercase" "team.l-creation.club.|trailing-dot" \
            "team.l-creation.club:9500,evil.example|comma-injection" \
            "team.l-creation.club:09500|leading-zero" "team.l-creation.club/lab|path-suffix"; do
  host="${spec%%|*}"; why="${spec#*|}"
  call GET "http://127.0.0.1:$P_HTTP/team" "$host"
  # 断开(000/rc≠0) 或 nginx 直接 400（如含 "/" 的畸形 Host）都算拒绝；
  # 唯一禁止的是 200（即被当成合法公开 authority 放行）
  if [ "$CODE" != "200" ] && { [ "$CODE" = "000" ] || [ "$CODE" = "400" ]; }; then
    ok "host-reject-$why"
  else
    bad "host-reject-$why" "host=$host got=$CODE rc=$RC"
  fi
done
[ "$(upstream_lines)" = "0" ] && ok "host-reject-no-upstream" || bad "host-reject-no-upstream" "upstream_hit"
# Host 头缺失也不得落到 URL 自带主机（127.0.0.1:port）而被当成合法 authority
before=$(upstream_lines)
CODE=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 10 -H "Host:" \
  "http://127.0.0.1:$P_HTTP/team" 2>/dev/null); RC=$?
after=$(upstream_lines)
# nginx 对缺失 Host 直接回 400；不论 400 还是断开，都不得 200 且不得到达上游
[ "$CODE" != "200" ] && [ "$before" = "$after" ] && ok "host-missing-closed" \
  || bad "host-missing-closed" "got=$CODE rc=$RC delta=$((after-before))"

: > "$WORK/logs/upstream.jsonl"
for p in / /login /team /team/ /team/login /lab /team/lab /lab/items/lab:3 /lab/items/lcsc:C123 \
         /lab_team_web/static/src/css/team.css "/lab/api/asset?url=x" /lab/client/updates/manifest; do
  expect "allow-GET-$p" 200 GET "$p"
done
expect "allow-GET-encoded-colon" 200 GET "/lab/items/lab%3A3"
for p in /lab/api/catalog/search /lab/api/catalog/detail /lab/api/catalog/categories /lab/api/catalog/facets \
         /login /team/login /team/logout /logout /api/team/session /team/api/session \
         /web/session/authenticate /web/session/get_session_info /web/session/destroy; do
  expect "allow-POST-$p" 200 POST "$p"
done
for spec in "GET /lab/api/catalog/search" "POST /lab" "POST /lab/api/asset" "GET /web/session/authenticate" "GET /logout"; do
  set -- $spec; expect "method-$1-$2" 403 "$1" "$2"
done
for p in /web/dataset/call_kw /jsonrpc /odoo /website/home /web/login /web/database/selector \
         /report/x "/web/image?id=1" /longpolling /websocket; do
  before=$(upstream_lines); expect "deny-$p" 404 GET "$p"; after=$(upstream_lines)
  [ "$before" = "$after" ] && ok "deny-no-upstream-$p" || bad "deny-no-upstream-$p" "upstream_hit"
done
for p in /team/../web/dataset/call_kw //web/dataset /%77eb/dataset /lab/api/catalog/search/ \
         /lab/api/catalog/search%2F /lab/items/a/b /lab/items/../../web/dataset; do
  before=$(upstream_lines); expect "bypass-$p" 404 GET "$p"; after=$(upstream_lines)
  [ "$before" = "$after" ] && ok "bypass-no-upstream-$p" || bad "bypass-no-upstream-$p" "upstream_hit"
done

# ---------- 头覆盖（XFF/X-Real-IP/Forwarded/X-Forwarded-Port）----------
: > "$WORK/logs/upstream.jsonl"
call GET "http://127.0.0.1:$P_HTTP/team" team.l-creation.club \
  -H 'X-Forwarded-For: 1.2.3.4' -H 'Forwarded: for=1.2.3.4' -H 'X-Real-IP: 1.2.3.4' \
  -H 'X-Forwarded-Host: evil.example:1234' -H 'X-Forwarded-Port: 1234'
sleep 0.3; LAST=$(tail -1 "$WORK/logs/upstream.jsonl")
echo "$LAST" | grep -q '"xff": "127.0.0.1"' && ok "xff-overwritten" || bad "xff-overwritten" "$LAST"
echo "$LAST" | grep -q '"x_real_ip": "127.0.0.1"' && ok "x-real-ip-overwritten" || bad "x-real-ip-overwritten" "$LAST"
echo "$LAST" | grep -q '"forwarded": ""' && ok "forwarded-cleared" || bad "forwarded-cleared" "$LAST"
# 伪造的 X-Forwarded-Port 必须清空（空值 = 不发给上游），不能据此重建 origin
echo "$LAST" | grep -q '"xf_port": ""' && ok "xf-port-spoof-cleared" || bad "xf-port-spoof-cleared" "$LAST"
# 伪造的 X-Forwarded-Host 必须被覆盖为已校验 authority，而不是被原样透传
echo "$LAST" | grep -q '"xf_host": "team.l-creation.club"' && ok "xf-host-spoof-overwritten" || bad "xf-host-spoof-overwritten" "$LAST"
echo "$LAST" | grep -q '"host": "team.l-creation.club"' && ok "host-no-port-upstream" || bad "host-no-port-upstream" "$LAST"
echo "$LAST" | grep -q "\"x_odoo_database\": \"$DB_SYNTH\"" && ok "db-header-page" || bad "db-header-page" "$LAST"

# 外部 9500：上游必须看到带端口的 Host 与 X-Forwarded-Host（回归本轮丢端口缺陷）
: > "$WORK/logs/upstream.jsonl"
call GET "http://127.0.0.1:$P_HTTP/team" "team.l-creation.club:$P_EDGE" \
  -H 'X-Forwarded-Host: team.l-creation.club' -H 'X-Forwarded-Port: 443'
sleep 0.3; PORTED=$(tail -1 "$WORK/logs/upstream.jsonl")
echo "$PORTED" | grep -q "\"host\": \"team.l-creation.club:$P_EDGE\"" \
  && ok "host-keeps-external-port" || bad "host-keeps-external-port" "$PORTED"
echo "$PORTED" | grep -q "\"xf_host\": \"team.l-creation.club:$P_EDGE\"" \
  && ok "xf-host-keeps-external-port" || bad "xf-host-keeps-external-port" "$PORTED"
echo "$PORTED" | grep -q '"xf_port": ""' && ok "xf-port-not-reintroduced" || bad "xf-port-not-reintroduced" "$PORTED"

: > "$WORK/logs/upstream.jsonl"
call POST "http://127.0.0.1:$P_HTTP/web/session/authenticate" "team.l-creation.club:$P_EDGE" \
  -H 'X-Forwarded-Host: evil.example' -H 'X-Forwarded-Port: 8443'
sleep 0.3; AUTH=$(tail -1 "$WORK/logs/upstream.jsonl")
echo "$AUTH" | grep -q '"x_odoo_database": ""' && ok "auth-clears-db-header" || bad "auth-clears-db-header" "$AUTH"
echo "$AUTH" | grep -q "\"xf_host\": \"team.l-creation.club:$P_EDGE\"" \
  && ok "auth-xf-host-keeps-external-port" || bad "auth-xf-host-keeps-external-port" "$AUTH"
echo "$AUTH" | grep -q '"xf_port": ""' && ok "auth-xf-port-spoof-cleared" || bad "auth-xf-port-spoof-cleared" "$AUTH"
echo "$AUTH" | grep -q '"xf_proto": "https"' && ok "auth-xf-proto-https" || bad "auth-xf-proto-https" "$AUTH"

# ---------- bore 无 PROXY（证明来源丢失）----------
: > "$WORK/logs/upstream.jsonl"
TLS_CODE=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 10 --cacert "$WORK/certs/ca.pem" \
  --resolve "team.l-creation.club:$P_BORE_TLS_PUB:127.0.0.1" -H 'Host: team.l-creation.club' \
  "https://team.l-creation.club:$P_BORE_TLS_PUB/team" 2>/dev/null)
[ "$TLS_CODE" = "200" ] && ok "bore-tls-no-proxy" || bad "bore-tls-no-proxy" "got=$TLS_CODE"
sleep 0.3; BL=$(tail -1 "$WORK/logs/upstream.jsonl")
echo "$BL" | grep -q '"xff": "127.0.0.1"' && ok "bore-loses-visitor-ip" || bad "bore-loses-visitor-ip" "$BL"

# ---------- 完整链路 + 伪造头 ----------
chain() { local ip=$1; shift
  curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 12 --cacert "$WORK/certs/ca.pem" \
    --interface "$ip" --resolve "team.l-creation.club:$P_EDGE:127.0.0.1" -H 'Host: team.l-creation.club' \
    "$@" "https://team.l-creation.club:$P_EDGE/team" 2>/dev/null; }
: > "$WORK/logs/upstream.jsonl"
C3=$(chain 127.0.0.3); [ "$C3" = "200" ] && ok "chain-source-127.0.0.3" || bad "chain-source-127.0.0.3" "got=$C3"
C6=$(chain 127.0.0.6); [ "$C6" = "200" ] && ok "chain-source-127.0.0.6" || bad "chain-source-127.0.0.6" "got=$C6"
CS=$(chain 127.0.0.3 -H 'X-Forwarded-For: 9.9.9.9' -H 'Forwarded: for=9.9.9.9' -H 'X-Real-IP: 9.9.9.9')
[ "$CS" = "200" ] && ok "chain-spoof-headers-request" || bad "chain-spoof-headers-request" "got=$CS"
sleep 0.3
grep -q '"xff": "127.0.0.3"' "$WORK/logs/upstream.jsonl" && ok "chain-xff-127.0.0.3" || bad "chain-xff-127.0.0.3" ""
grep -q '"xff": "127.0.0.6"' "$WORK/logs/upstream.jsonl" && ok "chain-xff-127.0.0.6" || bad "chain-xff-127.0.0.6" ""
if grep '"path": "/team"' "$WORK/logs/upstream.jsonl" | grep -q '"xff": "9.9.9.9"'; then
  bad "chain-spoof-not-trusted" "上游看到伪造 XFF"
else ok "chain-spoof-not-trusted"; fi

# 直接访问入口：正确 SNI/CA，仍必须失败（原因=缺少 PROXY），且上游 0
: > "$WORK/logs/entry-err-tail"; before=$(upstream_lines)
DCODE=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 6 --cacert "$WORK/certs/ca.pem" \
  --resolve "team.l-creation.club:$P_ENTRY:127.0.0.1" -H 'Host: team.l-creation.club' \
  "https://team.l-creation.club:$P_ENTRY/team" 2>/dev/null); DRC=$?
after=$(upstream_lines)
if [ "$DCODE" != "200" ] && [ "$DRC" -ne 0 ] && [ "$before" = "$after" ] \
   && grep -qi 'PROXY' "$WORK/nginx/error.log"; then
  ok "entry-direct-no-proxy-rejected"
else
  bad "entry-direct-no-proxy-rejected" "code=$DCODE rc=$DRC delta=$((after-before)) log=$(grep -ci proxy "$WORK/nginx/error.log")"
fi

# 伪造 PROXY 前缀（经公开边缘，正常 TLS 尝试）→ 必须被拒且上游 0
before=$(upstream_lines)
FORGED=$("$PYTHON" "$BORE_DIR/tests/forged_proxy_client.py" 127.0.0.1 "$P_EDGE" "$WORK/certs/ca.pem" team.l-creation.club 2>&1); FRC=$?
sleep 0.3; after=$(upstream_lines)
[ "$FRC" -eq 0 ] && [ "$before" = "$after" ] && ok "forged-proxy-rejected" || bad "forged-proxy-rejected" "rc=$FRC delta=$((after-before)) out=$FORGED"

# ---------- 限速 ----------
auth_chain() { local ip=$1; shift
  curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 12 --cacert "$WORK/certs/ca.pem" \
    --interface "$ip" --resolve "team.l-creation.club:$P_EDGE:127.0.0.1" -H 'Host: team.l-creation.club' \
    "$@" -X POST "https://team.l-creation.club:$P_EDGE/web/session/authenticate" 2>/dev/null; }
A1=$(auth_chain 127.0.0.5); A2=$(auth_chain 127.0.0.5)
[ "$A1" = "200" ] && [ "$A2" = "503" ] && ok "rate-limit-A-blocks" || bad "rate-limit-A-blocks" "A1=$A1 A2=$A2"
B1=$(auth_chain 127.0.0.6)
[ "$B1" = "200" ] && ok "rate-limit-B-unaffected" || bad "rate-limit-B-unaffected" "B1=$B1"
A3=$(auth_chain 127.0.0.5 -H 'X-Forwarded-For: 9.9.9.9')
[ "$A3" = "503" ] && ok "rate-limit-forged-xff-no-escape" || bad "rate-limit-forged-xff-no-escape" "A3=$A3"

# ---------- 隧道断开：失败关闭且上游 0 ----------
for entry in "${TRACK[@]:-}"; do
  IFS='|' read -r pid st ident <<< "$entry"
  [ "$ident" = "bore" ] || continue
  same_process "$pid" "$st" bore || continue
  tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'bore server' && { kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; }
done
sleep 1; before=$(upstream_lines)
DOWN=$(chain 127.0.0.3); after=$(upstream_lines)
[ "$DOWN" != "200" ] && [ "$before" = "$after" ] && ok "tunnel-down-fail-closed" || bad "tunnel-down-fail-closed" "code=$DOWN delta=$((after-before))"

say ""
say "SUMMARY PASS=$PASS FAIL=$FAIL"
printf '{"pass":%d,"fail":%d,"work":"%s"}\n' "$PASS" "$FAIL" "$WORK" > "$WORK/summary.json"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
