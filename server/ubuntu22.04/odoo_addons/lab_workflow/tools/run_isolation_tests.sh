#!/usr/bin/env bash
# ============================================================================
# lab_workflow 真实隔离验收运行器（WSL / Ubuntu 22.04）
#
# 隔离方式：user namespace（0..65535 全映射）+ mount/net/pid/uts/ipc + tmpfs
#   * ns 内 uid 1000 == 宿主当前用户；ns 内 root 可 setuid 到 101(postgres)/1000(odoo)
#   * 只读 bind 复用 /usr /lib /lib64 /bin /sbin 与 /opt/odoo /opt/odoo-venv
#   * /etc/passwd,/etc/group 只读 bind 自 rootfs（提供 postgres/odoo 账号）
#   * 全部可写数据放 ns 内 tmpfs：/tmp/labwf/{pgdata,sock,data,logs,addons}
#   * loopback 只在命名空间内 up（HTTP fixture 用）
#
# 不复制完整 OS/SDK、不装宿主包、不动 NAS/原快照/发布 ZIP。
#
# 用法： bash run_isolation_tests.sh [--with-http] [--keep] [--real-catalog <dir>]
# ============================================================================
set -uo pipefail

RUNTIME="${LABWF_RUNTIME:-/var/tmp/lc-elc-clean-apt-20261014-082927-594/rootfs}"
WITH_HTTP=0
KEEP=0
REAL_CATALOG=""
STUB_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-http) WITH_HTTP=1; shift ;;
    --keep) KEEP=1; shift ;;
    --real-catalog) REAL_CATALOG="$2"; shift 2 ;;
    --stub) STUB_OVERRIDE="$2"; shift 2 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

[[ -f "$RUNTIME/opt/odoo/odoo-bin" ]] || { echo "找不到只读运行时：$RUNTIME"; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT="$(cd "$ADDON_DIR/../../../.." && pwd)"
if [[ -n "$STUB_OVERRIDE" ]]; then
  STUB="$STUB_OVERRIDE"
else
  STUB="$PROJECT/_analysis/lab_catalog_stub"
fi
INNER="$SCRIPT_DIR/ns_inner_setup.sh"
[[ -f "$INNER" ]] || { echo "缺少内部脚本：$INNER"; exit 2; }
if [[ -z "$REAL_CATALOG" ]]; then
  # 只有不使用真实 lab_catalog 时才要求测试桩存在
  [[ -d "$STUB" ]] || { echo "缺少 lab_catalog 测试桩：$STUB（可用 --stub 指定或 --real-catalog）"; exit 2; }
fi

HOST_OUT="$(mktemp -d /var/tmp/labwf_out.XXXXXX)"
chmod 755 "$HOST_OUT"
export LABWF_RUNTIME="$RUNTIME" LABWF_WITH_HTTP="$WITH_HTTP"
export LABWF_OUT="$HOST_OUT" LABWF_STUB="$STUB" LABWF_REAL_CATALOG="$REAL_CATALOG"
export LABWF_ADDON_DIR="$ADDON_DIR" LABWF_INNER="$INNER"

echo "=== lab_workflow 隔离验收 ==="
echo "运行时: $RUNTIME"
echo "模块目录: $ADDON_DIR"
echo "宿主输出: $HOST_OUT"
echo "HTTP: $WITH_HTTP   真 catalog: ${REAL_CATALOG:-无（使用测试桩）}"

unshare --user --map-root-user --mount --net --pid --uts --ipc --fork --mount-proc \
  -- bash "$INNER"
STATUS=$?

echo
echo "=== 结果：$([ $STATUS -eq 0 ] && echo 全部通过 || echo 失败)（exit=$STATUS）==="
echo "日志/配置：$HOST_OUT"
ls -la "$HOST_OUT" 2>/dev/null | head -25
if [[ $STATUS -ne 0 ]]; then
  for f in "$HOST_OUT"/install.log "$HOST_OUT"/tests_business.log "$HOST_OUT"/tests_concurrency.log; do
    if [[ -f "$f" ]]; then echo "--- tail $f ---"; tail -n 45 "$f"; fi
  done
fi
if [[ $STATUS -eq 0 && $KEEP -ne 1 ]]; then
  rm -rf "$HOST_OUT"
else
  echo "保留宿主输出：$HOST_OUT"
fi
exit $STATUS
