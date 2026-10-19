#!/usr/bin/env bash
#
# 实验室库存系统 —— Odoo 模块升级（失败即给回滚指令，不静默）
#
# 顺序刻意固定为：备份 -> 停服务 -> 换代码(可选) -> -u -> 健康检查 -> 起服务。
# 任何一步失败都停在那里并打印恢复命令；**不自动回滚数据**（自动 DROP 生产库风险更大）。
#
# 用法：
#   sudo bash upgrade_modules.sh                                   # 只升级已在位的代码
#   sudo bash upgrade_modules.sh --code-dir /root/lc-elc-new       # 先换代码再升级
#   sudo bash upgrade_modules.sh --no-service                      # 不碰 systemd（容器/chroot 测试）
#   sudo bash upgrade_modules.sh --config /etc/odoo.conf --db LcHardwareHouse
#
# 退出码：0 成功；非 0 失败（回滚命令已打印）。
set -euo pipefail

CONFIG=/etc/odoo.conf
DB=LcHardwareHouse
UNIT=odoo.service
CODE_DIR=''
MANAGE_SERVICE=1
ADDONS=''
SELF_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2;;
    --db) DB="$2"; shift 2;;
    --unit) UNIT="$2"; shift 2;;
    --code-dir) CODE_DIR="$2"; shift 2;;
    --addons) ADDONS="$2"; shift 2;;
    --no-service) MANAGE_SERVICE=0; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

[[ $EUID -eq 0 ]] || { echo '请用 sudo 运行' >&2; exit 1; }

PY=${LC_PYTHON:-}
if [[ -z "$PY" ]]; then
  if [[ -x /opt/odoo/venv/bin/python ]]; then PY=/opt/odoo/venv/bin/python; else PY=python3; fi
fi
if ! CONF_LINE="$(
  $PY - "$CONFIG" "$SELF_DIR" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[2])   # 必须是**脚本自身目录**（含 lc_odoo_conf.py），
                                  # 不能靠 cwd 或 /opt/lc-elc-tools 猜测
import lc_odoo_conf as c
conf = c.load(sys.argv[1])
print(conf['db_user'], conf['db_host'], conf['db_port'], conf['data_dir'],
      (conf['addons_path'].split(',')[0].strip() or ''), c.modules_dir(conf))
PYEOF
)"; then
  echo "配置解析失败，升级中止（未执行备份或换代码）" >&2
  exit 1
fi
read -r DB_USER DB_HOST DB_PORT DATA_DIR ADDONS_CONF MODULES_DIR <<<"$CONF_LINE"

# 业务模块所在目录（默认 /opt/odoo/custom-addons），不是 addons_path 第一项
[[ -n "${ADDONS:-}" ]] || ADDONS="$MODULES_DIR"
[[ -n "$ADDONS" && -d "$ADDONS" ]] || { echo "模块目录无效: $ADDONS" >&2; exit 1; }

# 故障注入钩子：允许测试用桩替换备份脚本（默认仍是同目录里的真实脚本）
BACKUP_SCRIPT="${LC_BACKUP_SCRIPT:-$SELF_DIR/odoo_backup.py}"
[[ -f "$BACKUP_SCRIPT" ]] || { echo "找不到备份脚本: $BACKUP_SCRIPT" >&2; exit 1; }

# 服务控制参数：必须**显式**传给子备份。否则 --no-service（容器/chroot）下备份仍会去
# 调 systemd（无 systemd 时失败），自定义 --unit 也会被悄悄忽略而停在默认 odoo.service。
if [[ $MANAGE_SERVICE -eq 1 ]]; then
  SVC_ARGS=(--unit "$UNIT")
  RESTORE_OPTS="--unit $UNIT"
else
  SVC_ARGS=(--no-service)
  RESTORE_OPTS="--no-service"
fi

echo "==== Odoo 模块升级 ===="
echo "  config  $CONFIG"
echo "  db      $DB"
echo "  addons  $ADDONS"
echo "  service $([[ $MANAGE_SERVICE -eq 1 ]] && echo "$UNIT" || echo '不管理（--no-service）')"

# ---------- 0) 预检：三个业务模块必须齐全（在位的；若换代码，换入的也必须齐全）
echo
echo "---- 0) 预检（三模块齐全）----"
for mod in lab_inventory lab_catalog lab_workflow; do
  [[ -f "$ADDONS/$mod/__manifest__.py" ]] \
    || { echo "预检失败：$ADDONS/$mod 缺少 __manifest__.py（升级前必须齐全）" >&2; exit 1; }
  [[ -z "$CODE_DIR" || -f "$CODE_DIR/$mod/__manifest__.py" ]] \
    || { echo "预检失败：$CODE_DIR/$mod 缺少 __manifest__.py" >&2; exit 1; }
  echo "  OK  $mod"
done

# ---------- 1) 备份（升级前）
echo
echo "---- 1) 升级前备份 ----"
BACKUP_LOG=$(mktemp)
if ! $PY "$BACKUP_SCRIPT" --config "$CONFIG" --db "$DB" \
        --label before-upgrade --addons-path "$ADDONS" "${SVC_ARGS[@]}" >"$BACKUP_LOG" 2>&1; then
  echo "备份失败，升级中止："; tail -20 "$BACKUP_LOG"; exit 1
fi
BACKUP_DIR=$(sed -n 's/^  目录    //p' "$BACKUP_LOG" | head -1)
tail -3 "$BACKUP_LOG" | sed 's/^/  /'
[[ -n "$BACKUP_DIR" ]] || { echo '未能解析备份目录，升级中止' >&2; exit 1; }
echo "  备份点 $BACKUP_DIR"

# ---------- 2) 停服务（验证式；失败立即终止，绝不在服务可能仍在运行时 -u）
echo
echo "---- 2) 停止服务 ----"
if [[ $MANAGE_SERVICE -eq 1 ]]; then
  if ! $PY - "$SELF_DIR" "$UNIT" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import lc_service
lc_service.stop_verified(sys.argv[2])   # 停止并复核；未确认即抛错 -> 非零退出
PYEOF
  then
    echo "停止/确认服务失败，升级中止：$UNIT" >&2
    exit 1
  fi
  echo "  已确认 $UNIT inactive"
else
  echo "  按 --no-service 跳过"
fi

# ---------- 3) 可选：换代码（旧的保留）
RESTORE_CODE=''
code_failure() {
  echo "升级中止；服务保持停机。回滚代码：检查 $ADDONS 中各模块，已移动的旧代码位于 <模块>.pre-upgrade-$STAMP；先将失败新代码移到独立保留目录，再移回对应旧代码，勿删除或覆盖保留目录。" >&2
  echo "升级前备份：$BACKUP_DIR；确认代码恢复后，按安装说明恢复备份，勿对旧代码再次 -u。" >&2
  exit 1
}
if [[ -n "$CODE_DIR" ]]; then
  echo
  echo "---- 3) 替换代码（旧代码保留）----"
  STAMP=$(date -u +%Y%m%dT%H%M%SZ)
  for mod in lab_inventory lab_catalog lab_workflow; do
    [[ -d "$CODE_DIR/$mod" ]] || { echo "  $CODE_DIR/$mod 不存在" >&2; exit 1; }
    if [[ -d "$ADDONS/$mod" ]]; then
      [[ ! -e "$ADDONS/$mod.pre-upgrade-$STAMP" ]] || { echo "旧代码保留目录已存在，拒绝覆盖" >&2; code_failure; }
      mv -- "$ADDONS/$mod" "$ADDONS/$mod.pre-upgrade-$STAMP" || { echo "保留旧代码失败：$mod；升级中止，服务保持停机" >&2; code_failure; }
    fi
    cp -a -- "$CODE_DIR/$mod" "$ADDONS/$mod" || { echo "复制新代码失败：$mod；升级中止，旧代码保留于 $ADDONS/$mod.pre-upgrade-$STAMP" >&2; code_failure; }
    echo "  $mod 已替换（旧：$mod.pre-upgrade-$STAMP）"
  done
  # 归属：存在 odoo 用户则修正并**校验生效**；chown 静默失败会让服务读不到新代码。
  if ! $PY - "$SELF_DIR" "$ADDONS" <<'PYEOF'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import odoo_restore as r
ids = r.resolve_odoo_ids('odoo')
if not ids:
    print('  没有 odoo 用户，跳过归属修正（容器/以 root 运行）')
    sys.exit(0)
uid, gid = ids
for m in ('lab_inventory', 'lab_catalog', 'lab_workflow'):
    p = pathlib.Path(sys.argv[2]) / m
    if p.exists():
        r.chown_and_verify(p, uid, gid)
        print('  归属已校验 %s -> %d:%d' % (p, uid, gid))
PYEOF
  then
    echo "归属修正/校验失败，升级中止" >&2
    exit 1
  fi
  RESTORE_CODE="旧代码保留在 $ADDONS/<模块>.pre-upgrade-$STAMP；确认路径后先将当前失败代码移到独立保留目录，再移回旧代码。不要删除目录，也不要对旧代码再次执行 -u。"
fi

# ---------- 4) 升级模块
echo
echo "---- 4) 升级三个模块 ----"
LOG=$(mktemp)
set +e
$PY - "$CONFIG" "$DB" "$SELF_DIR" <<'PYEOF' >"$LOG" 2>&1
import os, pwd, shutil, subprocess, sys
sys.path.insert(0, sys.argv[3])
import lc_odoo_conf as c
conf, db, config_path = c.load(sys.argv[1]), sys.argv[2], sys.argv[1]
# 必须 <venv python> <odoo-bin>：odoo-bin 的 shebang 是 env python3，
# 直接执行会用到系统 python 而缺 babel 等依赖。
cmd = [c.python_bin(conf), c.odoo_bin(conf), '-c', config_path, '-d', db,
       '-u', 'lab_inventory,lab_catalog,lab_workflow',
       '--stop-after-init', '--no-http', '--log-level=warn']
# 以 root 直接跑 odoo-bin 会在 data_dir/filestore 留下 root 属主的文件，
# 之后 systemd 用 odoo 用户启动就会权限失败 —— 存在 odoo 用户时先降权。
if os.geteuid() == 0 and shutil.which('runuser'):
    try:
        pwd.getpwnam('odoo')
        cmd = ['runuser', '-u', 'odoo', '--'] + cmd
    except KeyError:
        pass
raise SystemExit(subprocess.call(cmd))
PYEOF
RC=$?
set -e
ERRS=$(grep -cE 'ERROR|CRITICAL|Traceback' "$LOG" || true)
echo "  退出码=$RC  ERROR/CRITICAL/Traceback 行数=$ERRS"
tail -25 "$LOG" | sed 's/^/  /'

if [[ $RC -eq 0 && $ERRS -gt 0 ]]; then
  echo "升级日志包含 ERROR/CRITICAL/Traceback，拒绝宣告成功" >&2
  RC=1
fi
if [[ $RC -ne 0 ]]; then
  echo
  echo "==== 升级失败 ===="
  echo "  1) 完整日志：$LOG"
  echo "  2) 回滚数据：sudo $PY $SELF_DIR/odoo_restore.py --backup $BACKUP_DIR --db $DB $RESTORE_OPTS --yes"
  if [[ -n "$RESTORE_CODE" ]]; then
    echo "  3) 回滚代码：$RESTORE_CODE"
  fi
  exit $RC
fi

# ---------- 5) 起服务 + 健康检查（启动必须验证；未确认即非零退出并给回滚指令）
echo
echo "---- 5) 启动与健康检查 ----"
if [[ $MANAGE_SERVICE -eq 1 ]]; then
  if ! $PY - "$SELF_DIR" "$UNIT" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import lc_service
lc_service.start_verified(sys.argv[2])   # 启动并复核；未确认即抛错 -> 非零退出
PYEOF
  then
    echo "==== 启动/确认服务失败 ====" >&2
    echo "  回滚数据：sudo $PY $SELF_DIR/odoo_restore.py --backup $BACKUP_DIR --db $DB $RESTORE_OPTS --yes"
    exit 1
  fi
  echo "  已确认 $UNIT active"
  HTTP_PORT=$($PY - "$CONFIG" <<'PYEOF'
import sys, configparser
cfg = configparser.ConfigParser(interpolation=None)
with open(sys.argv[1], encoding='utf-8-sig') as fh:
    cfg.read_file(fh)
o = cfg['options']
# Odoo 19 用 http_port；旧配置里是 xmlrpc_port
print(o.get('http_port') or o.get('xmlrpc_port') or '8069')
PYEOF
)
  code=''
  for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:$HTTP_PORT/web/login" || true)
    if [[ "$code" == "200" ]]; then break; fi
    sleep 2
  done
  echo "  /web/login -> HTTP ${code:-无响应}"
  if [[ "${code:-}" != "200" ]]; then
    echo "==== 服务起来了但健康检查未通过 ===="
    echo "  回滚数据：sudo $PY $SELF_DIR/odoo_restore.py --backup $BACKUP_DIR --db $DB $RESTORE_OPTS --yes"
    exit 1
  fi
else
  echo "  按 --no-service 跳过启动/健康检查"
fi

echo
echo "==== 升级完成 ===="
echo "  备份点（回滚用）$BACKUP_DIR"
echo "  升级日志        $LOG"
exit 0
