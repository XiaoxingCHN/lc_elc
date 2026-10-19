#!/usr/bin/env bash
# ============================================================================
# 真实 PostgreSQL 锁行为实验（我的私有 namespace / PGDATA，非 root OS 用户）
#
# 目的：确认 Odoo19 隔离验收里 lab_issue 的
#   SELECT id FROM lab_bag WHERE id IN (31) FOR UPDATE
# 在「另一事务更新并提交同一行」后是否真的报 40001
# （psycopg2.errors.SerializationFailure: could not serialize access
#   due to concurrent update），并抓取等待期间的真实 pg_locks。
#
# 同时对照实验：WHERE 条件引用被更新列时的行为差异。
# ============================================================================
set -uo pipefail

R="${LABWF_RUNTIME:-/var/tmp/lc-elc-clean-apt-20261014-082927-594/rootfs}"
[[ -f "$R/opt/odoo/odoo-bin" ]] || { echo "找不到只读运行时：$R"; exit 2; }
OUT="${LABWF_OUT:-/var/tmp/labwf_pgx_out}"
mkdir -p "$OUT"
export LABWF_RUNTIME="$R" LABWF_OUT="$OUT"

unshare --user --map-root-user --mount --net --pid --uts --ipc --fork --mount-proc \
  -- bash "$(dirname "$0")/pgx_inner.sh"
STATUS=$?
echo
echo "=== 实验结束（exit=$STATUS），输出：$OUT ==="
exit $STATUS
