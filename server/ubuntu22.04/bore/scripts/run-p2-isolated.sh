#!/usr/bin/env bash
# P2 隔离运行器（正式脚本：不写本机用户名/本机盘符路径；凭据只从环境变量来，不落盘不打印）
#
# 职责（本脚本是本轮“同轮证据”的唯一所有者）：
#   1. 输入校验：必需变量、loopback URL、端口格式；不使用 eval 展开环境输入。
#   2. 启动前拒绝端口占用；占用/配置错误立即 blocked(exit 3)，不启动任何子进程。
#   3. 用独立进程组启动 Odoo，校验监听 PID 属于本轮子进程（不复用旧服务）。
#   4. 启动失败快速失败；Odoo / post-start 日志保留到本轮受限目录（只输出脱敏 tail）。
#   5. 调用 verify-real-odoo.sh 并透传真实 rc（非零即 FAIL）；summary 从 results.jsonl 重算。
#   6. latest-run 只在完整证据原子发布后更新；进行中只写 current-run。
#   7. cleanup 保留真实 rc、只杀自有进程组；ODOO_STOP_CMD 只在本轮创建资源时执行。
#
# 必需：NGINX_BIN BORE_BIN ODOO_URL DB_NAME P2_USERS P2_PASS ODOO_START_CMD
# 可选：MODULE_SO P2_COOKIE_FLAGS P2_ASSET_URL P2_DETAIL_KEY ODOO_POST_START_CMD
#       ODOO_STOP_CMD P2_PREEXISTING_CMD P2_START_TIMEOUT P2_WORK P2_RUN_ID P2_BASE
#       P2_VERIFY_SCRIPT P2_CHROME_BIN P2_BROWSER_LOGIN PYTHON
#
# 用法：
#   run-p2-isolated.sh                              正常跑一轮
#   run-p2-isolated.sh --check-evidence <workdir>   从 results.jsonl 重算并核对 summary.json
#   run-p2-isolated.sh --print-evidence-helper      输出证据助手源码（供 verify 脚本复用）
set -uo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON="${PYTHON:-python3}"
# 让被调用的 verify 脚本复用同一解释器（子进程通过环境拿不到未导出的 shell 变量）
export PYTHON
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy 2>/dev/null || true
export NO_PROXY="*" no_proxy="*"

# ---------------------------------------------------------------------------
# 证据助手（结果 JSONL / 汇总重算 / 脱敏 / JSON-RPC payload），单一定义处
# ---------------------------------------------------------------------------
p2_evidence_source() {
  cat <<'P2EVID'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 证据助手：结果 JSONL、汇总重算、脱敏、JSON-RPC 载荷（仅标准库）。
结果行：{"run_id":..,"id":..,"result":"pass|fail|blocked|skip","detail":..,"at":..}
"""
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile

VALID = ("pass", "fail", "blocked", "skip")
SCHEMA = "p2-evidence-1"


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_run_id():
    rid = (os.environ.get("P2_RUN_ID") or "").strip()
    if rid:
        return rid
    work = (os.environ.get("P2_WORK") or "").rstrip("/")
    return os.path.basename(work) or "run"


def fail(msg, code=2):
    sys.stderr.write("p2_evidence: %s\n" % msg)
    return code


def atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".p2tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def load_results(path):
    counts = dict((key, 0) for key in VALID)
    bad = []
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        return None, "cannot-read %s (%s)" % (os.path.basename(path), exc.__class__.__name__)
    run_ids = set()
    records = []
    for number, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            bad.append(number)
            continue
        if (not isinstance(record, dict) or record.get("result") not in counts
                or not isinstance(record.get("id"), str) or not record.get("id")):
            bad.append(number)
            continue
        counts[record["result"]] += 1
        records.append(record)
        if isinstance(record.get("run_id"), str):
            run_ids.add(record["run_id"])
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "badlines": bad,
        "run_ids": sorted(run_ids),
        "raw": raw,
        "records": records,
    }, None


def cmd_add(argv):
    if len(argv) < 3:
        return fail("add <results> <id> <result> [detail]")
    path, ident, result = argv[0], argv[1], argv[2]
    detail = argv[3] if len(argv) > 3 else ""
    if result not in VALID:
        return fail("invalid result %r" % (result,))
    if not ident or any(ch in ident for ch in "\n\r\t"):
        return fail("invalid id %r" % (ident,))
    record = {
        "run_id": current_run_id(),
        "id": ident,
        "result": result,
        "detail": " ".join(str(detail).split())[:400],
        "at": now_utc(),
    }
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        return fail("cannot-append-results (%s)" % exc.__class__.__name__)
    return 0


def cmd_summarize(argv):
    if len(argv) < 4:
        return fail("summarize <results> <summary> <work> <exit_code>")
    results_path, out_path, work, exit_code = argv[0], argv[1], argv[2], argv[3]
    try:
        code = int(exit_code)
    except ValueError:
        return fail("exit_code not an integer")
    loaded, err = load_results(results_path)
    if loaded is None:
        return fail(err)
    if loaded["badlines"]:
        return fail("results.jsonl has invalid lines: %s" % loaded["badlines"][:10])
    counts = loaded["counts"]
    run_ids = loaded["run_ids"]
    if len(run_ids) > 1:
        return fail("results.jsonl mixes run_id values: %s" % run_ids)
    run_id = run_ids[0] if run_ids else current_run_id()
    if counts["fail"]:
        status = "fail"
    elif counts["blocked"]:
        status = "blocked"
    else:
        status = "pass"
    summary = {
        "schema": SCHEMA,
        "run_id": run_id,
        "work": work,
        "status": status,
        "passed": status == "pass" and code == 0,
        "exit_code": code,
        "counts": counts,
        "total": loaded["total"],
        "results": {
            "path": "results.jsonl",
            "lines": loaded["total"],
            "bytes": len(loaded["raw"]),
            "sha256": hashlib.sha256(loaded["raw"]).hexdigest(),
        },
        "generated_at": now_utc(),
    }
    atomic_write(out_path, json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    sys.stdout.write("SUMMARY " + json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.write("COUNTS pass=%d fail=%d blocked=%d skip=%d total=%d status=%s exit_code=%d\n"
                     % (counts["pass"], counts["fail"], counts["blocked"], counts["skip"],
                        loaded["total"], status, code))
    return 0


def _counts_of(obj):
    if not isinstance(obj, dict):
        return None
    source = obj.get("counts") if isinstance(obj.get("counts"), dict) else obj
    out = {}
    for key in VALID:
        value = source.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        out[key] = value
    return out


def cmd_compare(argv):
    """核对 verify 自报汇总与 results.jsonl 是否一致。"""
    if len(argv) < 2:
        return fail("compare <verify-summary.json> <results.jsonl>")
    summary_path, results_path = argv[0], argv[1]
    try:
        with open(summary_path, encoding="utf-8") as handle:
            verify_summary = json.load(handle)
    except (OSError, ValueError):
        sys.stdout.write("COMPARE missing-or-invalid %s\n" % os.path.basename(summary_path))
        return 1
    loaded, err = load_results(results_path)
    if loaded is None:
        return fail(err)
    declared = _counts_of(verify_summary)
    if declared is None:
        sys.stdout.write("COMPARE verify-summary-without-counts\n")
        return 1
    # since_line：verify 只对自己追加的那段结果负责（前面是 runner 的记录）
    since = verify_summary.get("since_line")
    if since is None:
        expected = loaded["counts"]
        scope = "all"
    elif isinstance(since, int) and not isinstance(since, bool) and since >= 0:
        expected = dict((key, 0) for key in VALID)
        if since > len(loaded["records"]):
            sys.stdout.write("COMPARE since-line-beyond-results\n")
            return 1
        for record in loaded["records"][since:]:
            expected[record["result"]] += 1
        scope = "since_line=%d" % since
    else:
        sys.stdout.write("COMPARE invalid-since-line\n")
        return 1
    if declared != expected:
        sys.stdout.write("COMPARE mismatch(%s) declared=%s results=%s\n"
                         % (scope, json.dumps(declared, sort_keys=True),
                            json.dumps(expected, sort_keys=True)))
        return 1
    sys.stdout.write("COMPARE ok(%s) %s\n" % (scope, json.dumps(expected, sort_keys=True)))
    return 0


def cmd_recount(argv):
    """只从 results.jsonl 重算计数（供 runner 决定最终 rc）。"""
    if len(argv) < 1:
        return fail("recount <results>")
    loaded, err = load_results(argv[0])
    if loaded is None:
        return fail(err)
    if loaded["badlines"]:
        return fail("results.jsonl has invalid lines: %s" % loaded["badlines"][:10])
    counts = loaded["counts"]
    sys.stdout.write("RECOUNT pass=%d fail=%d blocked=%d skip=%d total=%d\n"
                     % (counts["pass"], counts["fail"], counts["blocked"],
                        counts["skip"], loaded["total"]))
    return 0


def cmd_check(argv):
    """从 results.jsonl 独立重算并核对 summary.json（主代理可复用）。"""
    if len(argv) < 1:
        return fail("check <workdir>")
    work = argv[0].rstrip("/")
    results_path = os.path.join(work, "results.jsonl")
    summary_path = os.path.join(work, "summary.json")
    loaded, err = load_results(results_path)
    if loaded is None:
        sys.stdout.write("CHECK evidence_integrity=fail reason=%s\n" % err)
        return 2
    verdict = {"work": work, "evidence_integrity": "pass", "run_status": None, "run_exit_code": None, "run_passed": False, "problems": []}
    try:
        with open(summary_path, encoding="utf-8") as handle:
            summary = json.load(handle)
    except (OSError, ValueError):
        verdict["problems"].append("summary.json missing-or-invalid")
        summary = None
    if loaded["badlines"]:
        verdict["problems"].append("bad-results-lines=%s" % loaded["badlines"][:10])
    if len(loaded["run_ids"]) > 1:
        verdict["problems"].append("mixed-run-ids")
    if summary is not None:
        declared = _counts_of(summary)
        if declared != loaded["counts"]:
            verdict["problems"].append("counts-mismatch")
        if summary.get("total") != loaded["total"]:
            verdict["problems"].append("total-mismatch")
        digest = (summary.get("results") or {}).get("sha256")
        if digest != hashlib.sha256(loaded["raw"]).hexdigest():
            verdict["problems"].append("sha256-mismatch")
        if type(summary.get("exit_code")) is not int:
            verdict["problems"].append("missing-exit-code")
        if summary.get("work") != work:
            verdict["problems"].append("work-mismatch")
        if loaded["run_ids"] and summary.get("run_id") not in loaded["run_ids"]:
            verdict["problems"].append("run-id-mismatch")
        counts = loaded["counts"]
        expected_status = "fail" if counts["fail"] else ("blocked" if counts["blocked"] else "pass")
        code = summary.get("exit_code")
        expected_passed = expected_status == "pass" and code == 0
        if summary.get("status") != expected_status:
            verdict["problems"].append("status-mismatch")
        if type(summary.get("passed")) is not bool or summary.get("passed") != expected_passed:
            verdict["problems"].append("passed-mismatch")
        if (expected_status == "pass" and code != 0) or (expected_status == "fail" and code == 0) or (expected_status == "blocked" and code != 3):
            verdict["problems"].append("exit-counts-mismatch")
        metadata = summary.get("results") or {}
        if metadata.get("lines") != loaded["total"] or metadata.get("bytes") != len(loaded["raw"]):
            verdict["problems"].append("results-metadata-mismatch")
        verdict.update(run_status=summary.get("status"), run_exit_code=code, run_passed=summary.get("passed"))
    verdict["result_counts"] = loaded["counts"]
    verdict["total"] = loaded["total"]
    if verdict["problems"]:
        verdict["evidence_integrity"] = "fail"
    sys.stdout.write(json.dumps(verdict, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if verdict["evidence_integrity"] == "pass" else 1


SECRET_PATTERNS = (
    (re.compile(r"(?i)(set-cookie\s*:\s*)[^\n]*"), r"\1***"),
    (re.compile(r"(?i)((?:session_id|cookie|csrf_token|token)\s*[=:]\s*)[^\s;,\"'}]+"), r"\1***"),
    (re.compile(r"(?i)((?:password|passwd|pwd|secret|api[_-]?key|authorization)\s*[=:]\s*)[^\s,;&\"'}]+"), r"\1***"),
    (re.compile(r"(?i)(--db[_-]password[= ]+)[^\s]+"), r"\1***"),
)


def redact_text(text):
    secret = os.environ.get("P2_PASS") or ""
    out = text
    if secret:
        out = out.replace(secret, "***")
    for pattern, repl in SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def cmd_redact(argv):
    limit = 4000
    if argv:
        try:
            limit = max(0, int(argv[0]))
        except ValueError:
            return fail("redact <max_chars>")
    out = redact_text(sys.stdin.read())
    if limit and len(out) > limit:
        out = out[:limit] + "...(truncated)"
    sys.stdout.write(out)
    return 0


def _read_lines(count):
    """严格按行数读取：多一行即报错，避免含换行的凭据被静默截断。"""
    data = sys.stdin.read().splitlines()
    if len(data) != count:
        return None
    return data


def cmd_auth(argv):
    """stdin 4 行：db / login / password / id -> JSON-RPC 认证载荷（凭据不进 argv）。"""
    lines = _read_lines(4)
    if lines is None:
        return fail("auth expects exactly 4 stdin lines (db/login/password/id; "
                    "credentials must not contain newlines)")
    db, login, password, ident = lines
    try:
        ident = int(ident)
    except ValueError:
        return fail("auth id not an integer")
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {"db": db, "login": login, "password": password},
        "id": ident,
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


def cmd_sess(argv):
    lines = _read_lines(1)
    if lines is None:
        return fail("sess expects exactly 1 stdin line")
    try:
        ident = int(lines[0])
    except ValueError:
        return fail("sess id not an integer")
    payload = {"jsonrpc": "2.0", "method": "call", "params": {}, "id": ident}
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


def cmd_call(argv):
    """stdin 2 行：id / params(JSON 对象) -> JSON-RPC call 载荷。"""
    lines = _read_lines(2)
    if lines is None:
        return fail("call expects exactly 2 stdin lines")
    try:
        ident = int(lines[0])
        params = json.loads(lines[1])
    except ValueError:
        return fail("call id/params invalid")
    if not isinstance(params, dict):
        return fail("call params must be an object")
    payload = {"jsonrpc": "2.0", "method": "call", "params": params, "id": ident}
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


COMMANDS = {
    "add": cmd_add,
    "summarize": cmd_summarize,
    "compare": cmd_compare,
    "recount": cmd_recount,
    "check": cmd_check,
    "redact": cmd_redact,
    "auth": cmd_auth,
    "sess": cmd_sess,
    "call": cmd_call,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.stderr.write("usage: p2_evidence.py {%s} ...\n" % "|".join(sorted(COMMANDS)))
        return 2
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
P2EVID
}

if [ "${1:-}" = "--print-evidence-helper" ]; then
  p2_evidence_source
  exit 0
fi

command -v "$PYTHON" >/dev/null 2>&1 || { echo "BLOCKED: 缺少 $PYTHON"; exit 3; }

if [ "${1:-}" = "--check-evidence" ]; then
  _work="${2:-}"
  [ -n "$_work" ] || { echo "usage: $0 --check-evidence <workdir>"; exit 2; }
  _helper="$(mktemp)" || exit 2
  p2_evidence_source > "$_helper" || exit 2
  "$PYTHON" "$_helper" check "$_work"
  _rc=$?
  rm -f "$_helper"
  exit "$_rc"
fi

# ---------------------------------------------------------------------------
# 运行目录（进行中只写 current-run；latest-run 在完整发布后才更新）
# ---------------------------------------------------------------------------
BASE="${P2_BASE:-$REPO_ROOT/local/build/bore-p2-20261026}"
case "$BASE" in
  /*) ;;
  *) echo "BLOCKED: P2_BASE 必须是绝对路径"; exit 3 ;;
esac
mkdir -p "$BASE/runs" || { echo "BLOCKED: 无法创建 runs 目录"; exit 3; }
if [ -n "${P2_WORK:-}" ]; then
  case "$P2_WORK" in
    /*) ;;
    *) echo "BLOCKED: P2_WORK 必须是绝对路径"; exit 3 ;;
  esac
  [ -e "$P2_WORK" ] && { echo "REFUSE: P2_WORK 已存在，拒绝复用：$P2_WORK"; exit 4; }
  WORK="$P2_WORK"
  mkdir -p "$WORK" || { echo "REFUSE: 无法创建 P2_WORK"; exit 4; }
else
  WORK="$(mktemp -d "$BASE/runs/run.XXXXXX")" || { echo "REFUSE: mktemp 失败"; exit 4; }
fi
chmod 700 "$WORK" 2>/dev/null || true
RUN_ID="${P2_RUN_ID:-p2-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$WORK")}"
export P2_RUN_ID="$RUN_ID" P2_WORK="$WORK"
mkdir -p "$WORK/logs" || { echo "REFUSE: 无法创建证据目录"; exit 4; }

EV="$WORK/.p2_evidence.py"
RESULTS="$WORK/results.jsonl"
: > "$RESULTS" || { echo "REFUSE: 无法写 results.jsonl"; exit 4; }
p2_evidence_source > "$EV" || { echo "REFUSE: 无法生成证据助手"; exit 4; }
chmod 600 "$EV" "$RESULTS" 2>/dev/null || true

# current-run 仅表示“进行中”；latest-run 仅表示“已完成且完整”
if printf '%s\n' "$WORK" > "$BASE/.current-run.tmp" 2>/dev/null; then
  mv -f "$BASE/.current-run.tmp" "$BASE/current-run" 2>/dev/null || true
fi

PASS=0; FAIL=0; BLOCKED=0; SKIP=0
EVIDENCE_ERROR=0; FINALIZED=0; CLEANED=0; CLEANUP_FAIL=0
WE_ATTEMPTED_START=0; PREEXISTING=1; STOP_ALLOWED=0; VERIFY_INVOKED=0
ODOO_PID=""; ODOO_PGID=""; ODOO_ST=""

ev() { # id result [detail]
  local ident=$1 result=$2 detail="${3:-}"
  printf '%-7s %s%s\n' "$(printf '%s' "$result" | tr 'a-z' 'A-Z')" "$ident" "${detail:+ :: $detail}"
  "$PYTHON" "$EV" add "$RESULTS" "$ident" "$result" "$detail" \
    || { printf 'EVIDENCE-WRITE-FAILED %s\n' "$ident" >&2; EVIDENCE_ERROR=1; }
  case "$result" in
    pass) PASS=$((PASS + 1)) ;;
    fail) FAIL=$((FAIL + 1)) ;;
    blocked) BLOCKED=$((BLOCKED + 1)) ;;
    skip) SKIP=$((SKIP + 1)) ;;
  esac
}
say() { printf '%s\n' "$*"; }
redacted_tail() { # file [lines]
  local file=$1 lines="${2:-12}"
  [ -r "$file" ] || { printf '(no-log)'; return 0; }
  tail -n "$lines" "$file" 2>/dev/null | "$PYTHON" "$EV" redact 1200 2>/dev/null | tr '\n' ' '
}

# ---------------------------------------------------------------------------
# 进程/端口工具（不用 eval；/proc/<pid>/stat 以最后一个 ')' 分界，comm 可含空格/括号）
# ---------------------------------------------------------------------------
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
alive() { # pid starttime
  local pid=$1 st=$2 cur
  cur=$(proc_field "$pid" 22 2>/dev/null) || return 1
  [ -n "$cur" ] && [ "$cur" = "$st" ]
}
group_members() { # pgid -> 属于该进程组的 pid 列表
  local pg=$1 dir pid
  for dir in /proc/[0-9]*; do
    pid="${dir#/proc/}"
    [ "$(proc_field "$pid" 5 2>/dev/null)" = "$pg" ] && printf '%s\n' "$pid"
  done
  return 0
}
ss_listen_port() { # port -> 监听行
  ss -lnt 2>/dev/null | awk -v p=":$1" 'NR > 1 && $4 ~ (p "$") { print }'
}
ss_port_pids() { # port -> 监听 pid（同用户可见）
  ss -lntp 2>/dev/null | awk -v p=":$1" 'NR > 1 && $4 ~ (p "$") { print }' \
    | grep -o 'pid=[0-9][0-9]*' | cut -d= -f2 | sort -u | tr '\n' ' '
}
port_busy() { [ -n "$(ss_listen_port "$1")" ]; }

# ---------------------------------------------------------------------------
# 清理与原子发布（EXIT trap：保留真实 rc，只动本轮自有进程）
# ---------------------------------------------------------------------------
p2_cleanup() {
  [ "$CLEANED" = 1 ] && return 0
  CLEANED=1
  local i members
  # 先优雅停止本轮创建的资源（如 pg_ctl stop），再回收进程组；
  # 顺序很重要：直接 kill -TERM 进程组会连带把本轮启动的 Postgres 硬杀。
  if [ -n "${ODOO_STOP_CMD:-}" ] && [ "$WE_ATTEMPTED_START" = 1 ] && [ "$STOP_ALLOWED" = 1 ]; then
    if bash -c "$ODOO_STOP_CMD" </dev/null >"$WORK/logs/stop.log" 2>&1; then
      ev cleanup-stop pass "本轮创建的资源已优雅停止"
    else
      _src=$?
      CLEANUP_FAIL=1
      say "FAIL  cleanup-stop :: rc=$_src tail=$(redacted_tail "$WORK/logs/stop.log" 8)"
      ev cleanup-stop fail "rc=$_src tail=$(redacted_tail "$WORK/logs/stop.log" 8)"
    fi
  elif [ -n "${ODOO_STOP_CMD:-}" ]; then
    ev cleanup-stop skip "资源非本轮创建或未启动：不执行 ODOO_STOP_CMD（避免误停既有 Postgres）"
  else
    ev cleanup-stop skip "未提供 ODOO_STOP_CMD"
  fi
  if [ -n "$ODOO_PGID" ] && [ -n "$ODOO_ST" ]; then
    members="$(group_members "$ODOO_PGID" 2>/dev/null)"
    if [ -n "$members" ]; then
      kill -TERM -- "-$ODOO_PGID" 2>/dev/null
      for i in $(seq 1 40); do
        [ -z "$(group_members "$ODOO_PGID" 2>/dev/null)" ] && break
        sleep 0.1
      done
      if [ -n "$(group_members "$ODOO_PGID" 2>/dev/null)" ]; then
        kill -KILL -- "-$ODOO_PGID" 2>/dev/null
        sleep 0.2
      fi
    fi
    if [ -n "$ODOO_PID" ]; then wait "$ODOO_PID" 2>/dev/null; fi
    members="$(group_members "$ODOO_PGID" 2>/dev/null | tr '\n' ' ')"
    if [ -n "${members// /}" ]; then
      CLEANUP_FAIL=1
      say "FAIL  cleanup-children :: 进程组 $ODOO_PGID 仍有残留：$members"
      ev cleanup-children fail "pgid=$ODOO_PGID left=$members"
    else
      ev cleanup-children pass "pgid=$ODOO_PGID 已全部退出"
    fi
  else
    ev cleanup-children skip "本轮未启动自有进程组"
  fi
  if [ "$EVIDENCE_ERROR" = 1 ]; then
    CLEANUP_FAIL=1
    ev cleanup-evidence fail "存在证据写入失败"
  fi
  return 0
}

p2_finalize() { # exit_code
  [ "$FINALIZED" = 1 ] && return 0
  FINALIZED=1
  local code=$1 out sres
  out=$("$PYTHON" "$EV" summarize "$RESULTS" "$WORK/summary.json" "$WORK" "$code" 2>&1)
  sres=$?
  printf '%s\n' "$out"
  if [ "$sres" -ne 0 ] || ! printf '%s' "$out" | grep -q '^SUMMARY '; then
    say "EVIDENCE-FINALIZE-FAILED rc=$sres work=$WORK"
    return 4
  fi
  # latest-run 只在“完整结果已原子发布”之后更新：
  #   - verify 实际跑过的轮次（pass/fail/异常）-> latest-run
  #   - 启动前就被拒绝的轮次（端口占用/配置错误）-> latest-blocked-run，不覆盖上一轮真实证据
  local pointer="latest-run"
  [ "$VERIFY_INVOKED" = 1 ] || pointer="latest-blocked-run"
  if printf '%s\n' "$WORK" > "$BASE/.${pointer}.tmp" && mv -f "$BASE/.${pointer}.tmp" "$BASE/$pointer"; then
    say "PUBLISHED ${pointer}=$WORK"
  else
    say "EVIDENCE-PUBLISH-FAILED ${pointer}"
    return 4
  fi
  rm -f "$BASE/current-run" 2>/dev/null || true
  return 0
}

p2_on_exit() {
  local rc=$? recount fail_n blocked_n
  trap - EXIT INT TERM
  p2_cleanup
  [ "$CLEANUP_FAIL" = 1 ] && [ "$rc" -eq 0 ] && rc=1
  [ "$EVIDENCE_ERROR" = 1 ] && [ "$rc" -eq 0 ] && rc=4
  # 最终 rc 从 results.jsonl 重算，保证 rc / summary / 记录三者不可能互相矛盾
  recount="$("$PYTHON" "$EV" recount "$RESULTS" 2>/dev/null)"
  fail_n=$(printf "%s" "$recount" | sed -n "s/.*fail=\([0-9][0-9]*\).*/\1/p")
  blocked_n=$(printf "%s" "$recount" | sed -n "s/.*blocked=\([0-9][0-9]*\).*/\1/p")
  if [ -z "$fail_n" ] || [ -z "$blocked_n" ]; then
    EVIDENCE_ERROR=1
    say "EVIDENCE-RECOUNT-FAILED work=$WORK"
    [ "$rc" -eq 0 ] && rc=4
  elif [ "$fail_n" -gt 0 ] && [ "$rc" -eq 0 ]; then
    rc=1
    say "FAIL  runner-rc-consistency :: 本轮记录存在 $fail_n 条 FAIL，rc 提升为 1（不得 EXIT0 隐藏）"
    ev runner-rc-consistency fail "recorded_fail=$fail_n forced_rc=1"
    recount="$("$PYTHON" "$EV" recount "$RESULTS" 2>/dev/null)"
  elif [ "$blocked_n" -gt 0 ] && [ "$rc" -eq 0 ]; then
    rc=3
    say "BLOCKED runner-rc-consistency :: 本轮记录存在 $blocked_n 条 BLOCKED，rc 设为 3"
    ev runner-rc-consistency blocked "recorded_blocked=$blocked_n forced_rc=3"
    recount="$("$PYTHON" "$EV" recount "$RESULTS" 2>/dev/null)"
  fi
  p2_finalize "$rc" || { [ "$rc" -eq 0 ] && rc=4; }
  say ""
  say "RUN_SUMMARY run_id=$RUN_ID exit_code=$rc ${recount:-counts-unavailable} work=$WORK"
  exit "$rc"
}
trap p2_on_exit EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------------------
# 输入校验（严格格式、不使用 eval；不合法 -> blocked(3)，且不启动任何子进程）
# ---------------------------------------------------------------------------
blocked_exit() { ev "$1" blocked "$2"; say "BLOCKED $1 :: $2"; exit 3; }
require_var() {
  [ -n "${!1:-}" ] || blocked_exit "input-$1" "缺少环境变量 $1"
}
for _v in NGINX_BIN BORE_BIN ODOO_URL DB_NAME P2_USERS P2_PASS ODOO_START_CMD; do
  require_var "$_v"
done
command -v ss >/dev/null 2>&1 || blocked_exit runner-ss "缺少 ss（无法校验端口占用/监听者）"
say "RUN_ID=$RUN_ID"
say "WORK=$WORK"
ev runner-inputs pass "run_id=$RUN_ID"

URL_RE='^(https?)://(127\.0\.0\.1|localhost)(:([0-9]{1,5}))?$'
if [[ "$ODOO_URL" =~ $URL_RE ]]; then
  ODOO_SCHEME="${BASH_REMATCH[1]}"
  ODOO_PORT="${BASH_REMATCH[4]:-}"
  if [ -z "$ODOO_PORT" ]; then
    if [ "$ODOO_SCHEME" = "https" ]; then ODOO_PORT=443; else ODOO_PORT=80; fi
  fi
  if ! [[ "$ODOO_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$ODOO_PORT" -gt 65535 ]; then
    blocked_exit runner-url "ODOO_URL 端口格式非法（不允许前导零/越界）：$ODOO_PORT"
  fi
  ev runner-url pass "scheme=$ODOO_SCHEME port=$ODOO_PORT host=loopback"
else
  blocked_exit runner-url "ODOO_URL 必须是 http(s)://127.0.0.1|localhost[:端口]，不含路径/查询/凭据"
fi
[[ "$DB_NAME" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,40}$ ]] || blocked_exit runner-db "DB_NAME 含非法字符"
case "$DB_NAME" in
  postgres|template0|template1) blocked_exit runner-db "DB_NAME 不得为系统库" ;;
esac
ev runner-db pass "db=$DB_NAME"
[ -x "$NGINX_BIN" ] || blocked_exit runner-nginx "NGINX_BIN 不可执行"
[ -x "$BORE_BIN" ] || blocked_exit runner-bore "BORE_BIN 不可执行"
VERIFY_SCRIPT="${P2_VERIFY_SCRIPT:-$SCRIPT_DIR/verify-real-odoo.sh}"
[ -r "$VERIFY_SCRIPT" ] || blocked_exit runner-verify-script "VERIFY 脚本不可读：$(basename "$VERIFY_SCRIPT")"
ev runner-verify-script pass "script=$(basename "$VERIFY_SCRIPT")"
if [ -n "${MODULE_SO:-}" ] && [ ! -f "$MODULE_SO" ]; then
  blocked_exit runner-module "MODULE_SO 缺失"
fi

# 启动前拒绝端口占用（预先运行的服务一律不复用、不停机）
if port_busy "$ODOO_PORT"; then
  blocked_exit runner-port-free "端口 $ODOO_PORT 已被占用（pid=$(ss_port_pids "$ODOO_PORT")），拒绝复用"
fi
ev runner-port-free pass "port=$ODOO_PORT"
say "PORT=$ODOO_PORT free"

# 资源归属：依赖服务预先运行（如系统 Postgres）则 cleanup 不执行 ODOO_STOP_CMD
if [ -n "${P2_PREEXISTING_CMD:-}" ]; then
  if bash -c "$P2_PREEXISTING_CMD" >/dev/null 2>&1; then
    PREEXISTING=1
    ev runner-preexisting pass "依赖服务已在运行：本轮不注册 STOP"
  else
    PREEXISTING=0
    ev runner-preexisting pass "依赖服务未运行：本轮启动，成功后注册 STOP"
  fi
else
  PREEXISTING=1
  ev runner-preexisting skip "未提供 P2_PREEXISTING_CMD：归属未知，cleanup 不执行 ODOO_STOP_CMD"
fi

# ---------------------------------------------------------------------------
# 启动（独立进程组；失败快速失败，日志留在本轮目录）
# ---------------------------------------------------------------------------
ODOO_LOG="$WORK/logs/odoo.log"
START_TIMEOUT="${P2_START_TIMEOUT:-120}"
[[ "$START_TIMEOUT" =~ ^[0-9]{1,4}$ ]] || START_TIMEOUT=120
WE_ATTEMPTED_START=1
set -m
bash -c "$ODOO_START_CMD" </dev/null >"$ODOO_LOG" 2>&1 &
ODOO_PID=$!
set +m
ODOO_ST=$(proc_field "$ODOO_PID" 22 2>/dev/null) || ODOO_ST=""
ODOO_PGID=$(proc_field "$ODOO_PID" 5 2>/dev/null) || ODOO_PGID=""
if [ -z "$ODOO_ST" ] || [ -z "$ODOO_PGID" ] || [ "$ODOO_PGID" != "$ODOO_PID" ]; then
  ev runner-start-group blocked "无法建立本轮独立进程组（pid=$ODOO_PID pgid=${ODOO_PGID:-?}）"
  say "BLOCKED runner-start-group :: 无法建立本轮独立进程组"
  exit 3
fi
ev runner-started pass "pid=$ODOO_PID pgid=$ODOO_PGID log=logs/odoo.log"
say "ODOO_PID=$ODOO_PID PGID=$ODOO_PGID"

READY=0; EARLY_EXIT=0
STARTED_AT=$SECONDS
while :; do
  if ! alive "$ODOO_PID" "$ODOO_ST"; then EARLY_EXIT=1; break; fi
  if [ -n "$(ss_listen_port "$ODOO_PORT")" ]; then READY=1; break; fi
  [ $((SECONDS - STARTED_AT)) -ge "$START_TIMEOUT" ] && break
  sleep 0.25
done
if [ "$EARLY_EXIT" = 1 ]; then
  sleep 0.3
  _tail="$(redacted_tail "$ODOO_LOG" 12)"
  ev runner-start fail "启动命令在端口监听前退出；tail=$_tail"
  say "FAIL  runner-start :: 启动命令在监听前退出：$_tail"
  exit 1
fi
if [ "$READY" != 1 ]; then
  _tail="$(redacted_tail "$ODOO_LOG" 12)"
  ev runner-listen fail "timeout=${START_TIMEOUT}s tail=$_tail"
  say "FAIL  runner-listen :: ${START_TIMEOUT}s 内端口 $ODOO_PORT 未监听：$_tail"
  exit 1
fi
ev runner-listen pass "port=$ODOO_PORT waited=$((SECONDS - STARTED_AT))s"

# 监听 PID 必须属于本轮进程组（不复用旧服务）
LISTEN_PIDS="$(ss_port_pids "$ODOO_PORT")"
LISTEN_OK=1; LISTEN_DETAIL=""
for _lp in $LISTEN_PIDS; do
  _lpg=$(proc_field "$_lp" 5 2>/dev/null) || _lpg=""
  _lst=$(proc_field "$_lp" 22 2>/dev/null) || _lst=""
  if [ "$_lpg" != "$ODOO_PGID" ] || [ -z "$_lst" ] || [ "$_lst" -lt "$ODOO_ST" ]; then
    LISTEN_OK=0
    LISTEN_DETAIL="pid=$_lp pgid=$_lpg start=$_lst"
  fi
done
if [ -z "${LISTEN_PIDS// /}" ]; then
  LISTEN_OK=0
  LISTEN_DETAIL="no-listener-pid"
fi
if [ "$LISTEN_OK" != 1 ]; then
  ev runner-listener-owned fail "port=$ODOO_PORT owner-not-ours $LISTEN_DETAIL"
  say "FAIL  runner-listener-owned :: 端口 $ODOO_PORT 监听者不是本轮子进程（$LISTEN_DETAIL）"
  exit 1
fi
ev runner-listener-owned pass "port=$ODOO_PORT pids=${LISTEN_PIDS} pgid=$ODOO_PGID"

if [ "$PREEXISTING" = 0 ] && [ -n "${ODOO_STOP_CMD:-}" ]; then
  STOP_ALLOWED=1
  ev runner-stop-registered pass "本轮创建资源；cleanup 将执行 STOP"
else
  ev runner-stop-registered skip "非本轮创建或无 STOP 命令：cleanup 不执行 STOP"
fi

# post-start（日志留在本轮目录；失败快速失败，只输出脱敏 tail）
if [ -n "${ODOO_POST_START_CMD:-}" ]; then
  PS_LOG="$WORK/logs/post-start.log"
  if bash -c "$ODOO_POST_START_CMD" </dev/null >"$PS_LOG" 2>&1; then
    ev runner-post-start pass "log=logs/post-start.log"
  else
    _prc=$?
    _tail="$(redacted_tail "$PS_LOG" 12)"
    ev runner-post-start fail "rc=$_prc tail=$_tail"
    say "FAIL  runner-post-start :: rc=$_prc tail=$_tail"
    exit 1
  fi
else
  ev runner-post-start skip "未提供 ODOO_POST_START_CMD"
fi

# ---------------------------------------------------------------------------
# 调用 verify（同轮 WORK/RUN_ID；真实 rc 透传，非零即 FAIL）
# ---------------------------------------------------------------------------
VERIFY_INVOKED=1
export P2_EVIDENCE_PY="$EV" P2_RUNNER_OWNS_SUMMARY=1
# verify 只对 from-this-line 之后的结果负责（前面的记录属于 runner）
P2_RESULTS_SINCE="$(grep -c '' "$RESULTS" 2>/dev/null || echo 0)"
case "$P2_RESULTS_SINCE" in ''|*[!0-9]*) P2_RESULTS_SINCE=0 ;; esac
export P2_RESULTS_SINCE
say "--- verify: $(basename "$VERIFY_SCRIPT") (results_since=$P2_RESULTS_SINCE)"
bash "$VERIFY_SCRIPT"
VERIFY_RC=$?
export P2_EVIDENCE_PY="" P2_RESULTS_SINCE="" P2_RUNNER_OWNS_SUMMARY=""
# verify 自报计数须与 results.jsonl 严格一致（先核对，再追加本轮 runner 记录，
# 否则 since_line 会把 runner 自己后加的行算进 verify 的配额）
if [ -f "$WORK/verify-summary.json" ]; then
  if "$PYTHON" "$EV" compare "$WORK/verify-summary.json" "$RESULTS"; then
    ev runner-verify-summary pass "verify-summary 与 results.jsonl 一致"
  else
    ev runner-verify-summary fail "verify-summary 与 results.jsonl 不一致"
    [ "$VERIFY_RC" -eq 0 ] && VERIFY_RC=1
  fi
else
  ev runner-verify-summary skip "verify 未写 verify-summary.json"
fi

# rc 语义：0=通过 1=失败 3=配置/环境 blocked 4=证据错误；一律原样透传，不吞成 EXIT0
case "$VERIFY_RC" in
  0) ev runner-verify-exit pass "rc=0" ;;
  3) ev runner-verify-exit blocked "rc=3（verify 判定配置/环境 blocked）" ;;
  *) ev runner-verify-exit fail "rc=$VERIFY_RC" ;;
esac
[ "$VERIFY_RC" -ne 0 ] && say "VERIFY-RC=$VERIFY_RC（非零不隐藏，最终 rc 原样透传）"

exit "$VERIFY_RC"