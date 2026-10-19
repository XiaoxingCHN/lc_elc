#!/usr/bin/env bash
# ============================================================================
# 命名空间内部执行体（由 run_isolation_tests.sh 通过 unshare 调用）
# 已经在 user namespace 里、uid=0、/tmp 已 tmpfs。
# ============================================================================
set -uo pipefail

R="$LABWF_RUNTIME"
OUT="$LABWF_OUT"
echo "== 命名空间 =="
echo "  uid=$(id -u) gid=$(id -g)"

mount --make-rprivate / 2>/dev/null || true
mount -t tmpfs -o mode=1777,size=4G tmpfs /tmp || { echo "tmpfs /tmp 失败"; exit 3; }
mount -t tmpfs -o mode=755,size=32M tmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /dev/shm
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount -t tmpfs tmpfs /dev/shm 2>/dev/null || true
ip link set lo up 2>/dev/null && echo "  loopback up（仅命名空间内）" || echo "  loopback 未启用"

mount -t tmpfs -o mode=755,size=64M tmpfs /opt
mkdir -p /opt/odoo /opt/odoo-venv
mount --bind -o ro "$R/opt/odoo" /opt/odoo
mount --bind -o ro "$R/opt/odoo-venv" /opt/odoo-venv
for d in usr lib lib64 bin sbin; do
  [[ -e "/$d" ]] && mount --bind -o ro "$R/$d" "/$d" 2>/dev/null
done
mount --bind -o ro "$R/etc/passwd" /etc/passwd 2>/dev/null || true
mount --bind -o ro "$R/etc/group" /etc/group 2>/dev/null || true
echo "  runtime overlay 完成"

# ---------------------------------------------------------------------------
# 非 root OS 用户执行（PG 禁止以 uid 0 启动）
#
# unshare(1) 2.37 只支持「当前用户映射到一个 uid」，且本环境不允许 setgroups()，
# 因此 runuser/su 都不可用。这里用**再一层 user namespace**：
#   outer ns: 宿主 uid1000 -> ns uid 0（有 CAP_SYS_ADMIN，可 mount）
#   inner ns: 当前用户 -> uid 101，于是 PG 以 101 运行（宿主仍是非 root 用户）
# uid 101 必须能读运行时文件，故对所有只读挂载补 a+rX。
# ---------------------------------------------------------------------------
PUID=101   # rootfs /etc/passwd 里的 postgres
run_as_pg() {
  unshare --user --map-user="$PUID" --map-group="$PUID" -- \
    env HOME=/tmp/libpgdata PATH="$R/usr/lib/postgresql/14/bin:$R/usr/bin:$R/bin" \
    "$@"
}

W=/tmp/labwf
mkdir -p "$W"/pgdata "$W"/sock "$W"/data "$W"/logs "$W"/addons/custom "$W"/libpgdata
chmod 777 "$W" "$W/logs" "$W/sock" "$W/data" "$W/libpgdata"
chmod 700 "$W/pgdata"

# 官方 addons 不复制：直接从只读 overlay（/opt/odoo/addons、/opt/odoo/odoo/addons）加载
# 真实三模块：--real-catalog 指向源码 addons 目录时，lab_catalog + lab_inventory
# 都用**源码真实版本**（不用测试桩、不用 runtime 里的旧副本）。
if [[ -n "${LABWF_REAL_CATALOG:-}" && -d "$LABWF_REAL_CATALOG/lab_catalog" ]]; then
  cp -r "$LABWF_REAL_CATALOG/lab_catalog" "$W/addons/custom/"
  echo "  + lab_catalog（真实交付物源码）"
  if [[ -d "$LABWF_REAL_CATALOG/lab_inventory" ]]; then
    cp -r "$LABWF_REAL_CATALOG/lab_inventory" "$W/addons/custom/"
    echo "  + lab_inventory（真实交付物源码）"
  fi
elif [[ -d "$R/opt/odoo-custom/lab_inventory" ]]; then
  cp -r "$R/opt/odoo-custom/lab_inventory" "$W/addons/custom/"
  echo "  + lab_inventory（runtime 副本）"
fi
if [[ ! -d "$W/addons/custom/lab_catalog" ]]; then
  cp -r "$LABWF_STUB" "$W/addons/custom/lab_catalog"
  echo "  + lab_catalog（测试桩：只提供角色与最小模型）"
fi
cp -r "$LABWF_ADDON_DIR" "$W/addons/custom/lab_workflow"
find "$W/addons/custom/lab_workflow" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
chmod -R a+rX "$W/addons/custom"
echo "  addons/custom: $(ls "$W/addons/custom" | tr '\n' ' ')"

PG="$R/usr/lib/postgresql/14/bin"
echo "== PostgreSQL（ns uid $PUID = postgres，cluster 管理员 lc_test_admin）=="
# 让 uid 101 能读运行时只读挂载（否则 python/pg 二进制打不开）
chmod -R a+rX "$R/usr/lib/postgresql" 2>/dev/null || true
printf "CREATE ROLE lc_odoo WITH LOGIN PASSWORD 'lc_odoo_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;\n" > "$W/roles.sql"
chmod 666 "$W/roles.sql"
run_as_pg "$PG/initdb" -D "$W/pgdata" -E UTF8 --locale=C \
  --username=lc_test_admin -A trust --no-sync > "$W/logs/initdb.log" 2>&1 \
  || { echo "  initdb 失败"; tail -25 "$W/logs/initdb.log"; exit 1; }
echo "  initdb OK（以 uid $PUID 运行）"
run_as_pg "$PG/pg_ctl" -D "$W/pgdata" \
  -o "-k $W/sock -p 55440 -c listen_addresses= -c unix_socket_permissions=0777 -c fsync=off" \
  -l "$W/logs/pg.log" -w -t 60 start \
  || { echo "  pg 启动失败"; tail -25 "$W/logs/pg.log"; exit 1; }
"$PG/pg_isready" -h "$W/sock" -p 55440 && echo "  pg ready"
"$PG/psql" -h "$W/sock" -p 55440 -U lc_test_admin -d postgres -v ON_ERROR_STOP=1 \
  -f "$W/roles.sql" > "$W/logs/pg-roles.log" 2>&1 || { echo "  建角色失败"; cat "$W/logs/pg-roles.log"; exit 1; }
"$PG/createdb" -h "$W/sock" -p 55440 -U lc_test_admin -O lc_odoo labwf_test \
  || { echo "  createdb 失败"; exit 1; }
echo "  业务库 labwf_test 属主 lc_odoo（NOSUPERUSER）"

cat > "$W/odoo.conf" <<CONF
[options]
addons_path = /opt/odoo/addons,/opt/odoo/odoo/addons,$W/addons/custom
data_dir = $W/data
db_host = $W/sock
db_port = 55440
db_name = labwf_test
db_user = lc_odoo
db_password = lc_odoo_pw
db_sslmode = disable
list_db = False
logfile =
without_demo = all
workers = 0
CONF
chmod 644 "$W/odoo.conf"

export PYTHONPATH="/opt/odoo-venv/lib/python3.10/site-packages:$R/usr/lib/python3/dist-packages:$R/opt/odoo"
export TMPDIR="$W"
# 真实并发 suite 的开关（脚本内直接开启，保证 3) 一定真的跑而不是 skip）
export LAB_WORKFLOW_CONCURRENCY=1

odoo_run() {   # odoo_run <label> <args...>
  local label="$1"; shift
  echo "== $label =="
  ( cd /tmp && unshare --user --map-user=1000 --map-group=1000 -- \
      env PYTHONPATH="$PYTHONPATH" TMPDIR="$TMPDIR" HOME=/tmp \
      "$R/opt/odoo-venv/bin/python" "$R/opt/odoo/odoo-bin" -c "$W/odoo.conf" \
      --logfile="$W/logs/$label.log" "$@" )
  local rc=$?
  echo "  日志: $W/logs/$label.log"
  return $rc
}

# 断言测试真的跑了：要求日志里出现 "N failed, M error(s) of T tests" 且 T>0
assert_tests_ran() {   # assert_tests_ran <label>
  local label="$1"
  local log="$W/logs/$label.log"
  local line
  line=$(grep -oE '[0-9]+ failed, [0-9]+ error\(s\) of [0-9]+ tests' "$log" | tail -1)
  if [[ -z "$line" ]]; then
    echo "  !! $label 日志里没有测试统计（可能用例没被导入）"
    grep -E 'test|tests' "$log" | tail -5
    return 1
  fi
  # 形如 "0 failed, 0 error(s) of 46 tests"，用纯 shell 取数（不依赖 awk）
  local failed errors total
  failed="${line%% failed*}"
  local rest="${line#*failed, }"
  errors="${rest%% error*}"
  total="${rest##*of }"
  total="${total%% *}"
  echo "  测试统计：$line（failed=$failed errors=$errors total=$total）"
  if [[ "${total:-0}" -le 0 ]]; then
    echo "  !! $label 收集到 0 个用例，不能算通过"
    return 1
  fi
  if [[ "${failed:-0}" -gt 0 || "${errors:-0}" -gt 0 ]]; then
    echo "  !! $label 有失败用例（failed=$failed errors=$errors）"
    return 1
  fi
  return 0
}

FAIL=0
echo "== 1) 安装 lab_catalog + lab_inventory + lab_workflow =="
if odoo_run install -i lab_catalog,lab_inventory,lab_workflow --stop-after-init --no-http; then
  echo "  安装 OK"
  "$PG/psql" -h "$W/sock" -p 55440 -U lc_odoo -d labwf_test -At -c \
    "select name||':'||state||':'||coalesce(latest_version,'') from ir_module_module where name in ('lab_catalog','lab_inventory','lab_workflow') order by name;" \
    | tee "$W/logs/modules.txt"
  n=$(grep -c ':installed:' "$W/logs/modules.txt" || true)
  [[ "$n" == "3" ]] || { echo "  期望 3 个模块 installed，实际 $n"; FAIL=1; }
else
  echo "  安装失败，尾部日志："; tail -60 "$W/logs/install.log"; FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "== 2) 业务测试（真实 stock.move/quant/lot、幂等、权限、标签、多档案绑定）=="
  # 只跑 at_install 的两个 TransactionCase 类；并发 suite 是 post_install，单独在第 3 步跑
  odoo_run tests_business --test-enable -u lab_workflow \
    --test-tags /lab_workflow:LabWorkflowTransactionTest,/lab_workflow:LabWorkflowHttpTest \
    --stop-after-init --no-http
  rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "  业务测试进程失败($rc)，尾部："; tail -90 "$W/logs/tests_business.log"; FAIL=1
  else
    assert_tests_ran tests_business || { tail -60 "$W/logs/tests_business.log"; FAIL=1; }
    if grep -q 'skipped setUpClass' "$W/logs/tests_business.log"; then
      echo "  !! 业务 suite 有 setUpClass 被跳过，需确认不是关键用例"; FAIL=1
    fi
  fi
fi

if [[ "$FAIL" -eq 0 && "$LABWF_WITH_HTTP" == "1" ]]; then
  echo "== 3) 真实 HTTP 并发（两个登录 cookie + Barrier，http_interface=127.0.0.1）=="
  # 正常 HTTP 服务（**不加 --test-enable**）：每个请求独立事务/独立连接，
  # 两个 cookie + Barrier 真正相交；不用测试框架的 TestCursor/共享锁环境。
  ( cd /tmp && unshare --user --map-user=1000 --map-group=1000 -- \
      env PYTHONPATH="$PYTHONPATH" TMPDIR="$TMPDIR" HOME=/tmp \
      "$R/opt/odoo-venv/bin/python" "$R/opt/odoo/odoo-bin" -c "$W/odoo.conf" \
      --http-interface=127.0.0.1 --http-port=8069 --logfile="$W/logs/odoo_http.log" \
      >/dev/null 2>&1 & echo $! > "$W/odoo.pid" )
  HTTP_UP=0
  # 就绪探测用 venv 自带的 Python（runtime 里没有 curl，不能依赖外部命令）
  for _ in $(seq 1 90); do
    if "$R/opt/odoo-venv/bin/python" -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8069/web/login', timeout=3)
except Exception:
    sys.exit(1)
" 2>/dev/null; then HTTP_UP=1; break; fi
    if ! kill -0 "$(cat "$W/odoo.pid" 2>/dev/null)" 2>/dev/null; then
      echo "  HTTP 进程已退出"; break
    fi
    sleep 1
  done
  if [[ "$HTTP_UP" != "1" ]]; then
    echo "  HTTP 服务未就绪"; tail -20 "$W/logs/odoo_http.log" 2>/dev/null; FAIL=1
  else
    echo "  HTTP 服务就绪（pid=$(cat "$W/odoo.pid")）"
    "$R/opt/odoo-venv/bin/python" "$LABWF_ADDON_DIR/tools/http_concurrency_check.py" \
      --url http://127.0.0.1:8069 --db labwf_test --admin admin --admin-pass admin \
      2>&1 | tee "$W/logs/http_concurrency.log"
    rc=${PIPESTATUS[0]}
    echo "  http_concurrency_check 退出码：$rc"
    [[ "$rc" -eq 0 ]] || FAIL=1
  fi
  kill "$(cat "$W/odoo.pid" 2>/dev/null)" 2>/dev/null || true
  sleep 2
elif [[ "$LABWF_WITH_HTTP" == "1" ]]; then
  echo "== 3) HTTP 并发跳过（前置失败）=="
else
  echo "== 3) HTTP 并发未启用（加 --with-http，这是并发的主验收路径）=="
fi

if [[ "$FAIL" -eq 0 && "${LABWF_SKIP_PROCESS_CONCURRENCY:-0}" != "1" ]]; then
  echo "== 4) 进程内并发测试（多线程 + Barrier + 独立真实连接 + 非 super 操作员）=="
  # post_install + -u：安装已完成并 commit，新连接能看到 schema，线程才能真正相交。
  # 注意：套件内部用**真实独立连接**（绕过测试模式 TestCursor patch）。
  ( cd /tmp && unshare --user --map-user=1000 --map-group=1000 -- \
      env PYTHONPATH="$PYTHONPATH" TMPDIR="$TMPDIR" HOME=/tmp \
      LAB_WORKFLOW_CONCURRENCY=1 \
      "$R/opt/odoo-venv/bin/python" "$R/opt/odoo/odoo-bin" -c "$W/odoo.conf" \
      --test-enable --test-tags /lab_workflow:LabWorkflowConcurrencyTest \
      -u lab_workflow \
      --logfile="$W/logs/tests_concurrency.log" \
      --stop-after-init --no-http )
  rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "  并发测试进程失败($rc)，尾部："; tail -90 "$W/logs/tests_concurrency.log"; FAIL=1
  else
    assert_tests_ran tests_concurrency || { tail -60 "$W/logs/tests_concurrency.log"; FAIL=1; }
    if grep -q 'skipped setUpClass' "$W/logs/tests_concurrency.log"; then
      echo "  !! 并发 suite 被跳过，不能算通过"; FAIL=1
    fi
    # 四个并发场景必须都真实执行
    for n in test_01_two_threads_issue_70_of_100 test_02_two_threads_return_15_of_20 \
             test_03_same_request_key_two_threads_receipt \
             test_04_same_key_different_payload_concurrent; do
      grep -q "Starting .*$n" "$W/logs/tests_concurrency.log" \
        || { echo "  !! 并发场景未执行：$n"; FAIL=1; }
    done
    grep -E '并发领 70|并发还 15|同 key 不同 payload|同 key 并发' \
      "$W/logs/tests_concurrency.log" | head -10 || true
  fi
fi

if [[ "${LABWF_SKIP_PROCESS_CONCURRENCY:-0}" == "1" ]]; then
  echo "== 4) 进程内并发 skipped（显式参数）；HTTP 并发结果单独记录 =="
fi
echo "== 5) 导出日志/配置 =="
cp -a "$W/logs/." "$OUT/" 2>/dev/null
cp -a "$W/odoo.conf" "$OUT/" 2>/dev/null

runuser -u postgres -- "$PG/pg_ctl" -D "$W/pgdata" -m immediate stop >/dev/null 2>&1 || true
if [[ "$FAIL" -eq 0 ]]; then echo "ALL_PASS"; exit 0; else echo "FAILED"; exit 1; fi
