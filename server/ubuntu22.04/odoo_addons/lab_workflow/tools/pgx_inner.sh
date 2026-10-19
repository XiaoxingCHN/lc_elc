#!/usr/bin/env bash
# ============================================================================
# pg_lock_experiment.sh 的内部执行体（已在 user namespace，uid=0）
# ============================================================================
set -uo pipefail

R="$LABWF_RUNTIME"
OUT="$LABWF_OUT"
echo "== 命名空间 =="
id

mount --make-rprivate / 2>/dev/null || true
mount -t tmpfs -o mode=1777,size=2G tmpfs /tmp || { echo "tmpfs /tmp 失败"; exit 3; }
mount -t tmpfs -o mode=755,size=32M tmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /dev/shm
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount -t tmpfs tmpfs /dev/shm 2>/dev/null || true
ip link set lo up 2>/dev/null || true

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

PUID=101
run_as_pg() {
  unshare --user --map-user="$PUID" --map-group="$PUID" -- \
    env HOME=/tmp/libpgdata PATH="$R/usr/lib/postgresql/14/bin:$R/usr/bin:$R/bin" \
    "$@"
}

W=/tmp/labpgx
mkdir -p "$W"/pgdata "$W"/sock "$W"/logs "$W"/libpgdata
chmod 777 "$W" "$W/logs" "$W/sock" "$W/libpgdata"
chmod 700 "$W/pgdata"

PG="$R/usr/lib/postgresql/14/bin"
chmod -R a+rX "$R/usr/lib/postgresql" 2>/dev/null || true
run_as_pg "$PG/initdb" -D "$W/pgdata" -E UTF8 --locale=C \
  --username=lc_test_admin -A trust --no-sync > "$W/logs/initdb.log" 2>&1 \
  || { echo "initdb 失败"; tail -25 "$W/logs/initdb.log"; exit 1; }
run_as_pg "$PG/pg_ctl" -D "$W/pgdata" \
  -o "-k $W/sock -p 55441 -c listen_addresses= -c unix_socket_permissions=0777 -c fsync=off" \
  -l "$W/logs/pg.log" -w -t 60 start \
  || { echo "pg 启动失败"; tail -25 "$W/logs/pg.log"; exit 1; }
echo "  pg ready（uid $PUID = postgres 非 root）"

PSQL="$PG/psql -h $W/sock -p 55441 -U lc_test_admin -d postgres -X -q"
$PSQL -v ON_ERROR_STOP=1 -c "CREATE DATABASE pgx;" >/dev/null
Q="$PG/psql -h $W/sock -p 55441 -U lc_test_admin -d pgx -X -q"

# 与 lab_bag 同形的表：主键 id + 会被更新的 quantity 列
$Q -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE lab_bag_x (id integer PRIMARY KEY, quantity numeric NOT NULL);
INSERT INTO lab_bag_x VALUES (31, 100);
SQL
echo "  实验表 lab_bag_x(id=31, quantity=100) 就绪"

run_case() {  # run_case <名称> <A先锁后更新?>
  local name="$1" mode="$2"
  echo
  echo "===== 实验：$name（mode=$mode）===="
  if [[ "$mode" == "lock_then_update" ]]; then
    # A：先 FOR UPDATE 占锁 -> 睡眠 -> 再 UPDATE -> 提交
    # B：在 A 已持锁但尚未 UPDATE 时发起 FOR UPDATE（快照早于 A 的更新）
    ( $Q -c "BEGIN;" \
          -c "SELECT id FROM lab_bag_x WHERE id IN (31) FOR UPDATE;" \
          -c "SELECT pg_sleep(3);" \
          -c "UPDATE lab_bag_x SET quantity = 30 WHERE id = 31;" \
          -c "COMMIT;" > "$W/logs/a_$name.log" 2>&1 ) &
  else
    # A：先 UPDATE 占锁 -> 睡眠 -> 提交（B 的快照晚于 A 的更新）
    ( $Q -c "BEGIN; UPDATE lab_bag_x SET quantity = 30 WHERE id = 31;" \
          -c "SELECT pg_sleep(6);" \
          -c "COMMIT;" > "$W/logs/a_$name.log" 2>&1 ) &
  fi
  local a_pid=$!
  sleep 1.5   # 确保 A 已拿到行锁
  echo "  -- A 持锁期间 pg_locks --"
  $Q -c "SELECT pid, locktype, relation::regclass, mode, granted
         FROM pg_locks WHERE relation = 'lab_bag_x'::regclass ORDER BY pid;" \
     | tee "$W/logs/locks_$name.txt"
  # B：FOR UPDATE（会在 A 的行锁上等待）
  ( $Q -c "SELECT id FROM lab_bag_x WHERE id IN (31) FOR UPDATE;" \
     > "$W/logs/b_$name.log" 2>&1 ; echo "B_EXIT=$?" >> "$W/logs/b_$name.log" ) &
  local b_pid=$!
  sleep 2.5   # B 应在等待中
  echo "  -- B 等待期间 pg_stat_activity / pg_locks --"
  $Q -c "SELECT pid, state, wait_event_type, wait_event, left(query,60) AS q
         FROM pg_stat_activity WHERE datname='pgx' ORDER BY pid;" \
     | tee "$W/logs/wait_$name.txt"
  $Q -c "SELECT pid, locktype, relation::regclass, mode, granted
         FROM pg_locks WHERE relation = 'lab_bag_x'::regclass ORDER BY pid, granted DESC;" \
     | tee -a "$W/logs/wait_$name.txt"
  wait "$b_pid" 2>/dev/null
  wait "$a_pid" 2>/dev/null
  echo "  -- A 日志 --"; sed 's/^/    /' "$W/logs/a_$name.log"
  echo "  -- B 结果 --"; sed 's/^/    /' "$W/logs/b_$name.log"
}

# 用例1：A 先 UPDATE 占锁再提交（B 快照晚于更新）——旧实验，已知成功
run_case "update_first" "update_first"

# 用例2：A 先 FOR UPDATE 占锁，B 开始等待后 A 才 UPDATE（真实 Odoo 时序）
run_case "lock_then_update" "lock_then_update"

echo
echo "== 收尾：停 PG（只停自己的 PGDATA）=="
run_as_pg "$PG/pg_ctl" -D "$W/pgdata" -m immediate stop >/dev/null 2>&1 || true
cp -a "$W/logs/." "$OUT/" 2>/dev/null
echo "PGX_DONE"
