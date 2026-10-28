#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 运行器/证据纯逻辑与合成测试（不接触真实 Odoo/Nginx/bore，不占用正式测试端口）。

覆盖：
  1. 证据助手：结果 JSONL 往返、四态计数、summary/退出码一致、summary 篡改可检出、
     坏行可检出、run_id 混用可检出、原子写不留临时文件。
  2. JSON-RPC 载荷序列化：引号/反斜杠/中文/换行/超长密码都产出合法 JSON。
  3. 脱敏：不泄漏密码/Session Cookie，超长被截断。
  4. 输入校验：loopback URL / 端口格式 / 非回环 / DB 名 / P2_BASE -> blocked(3)，不启动子进程。
  5. occupied-port：随机高位端口被占用 -> blocked(3)，占用者不受影响，无残留子进程。
  6. start-failure：启动命令立即失败 -> rc=1，FAIL 证据 + 脱敏日志 tail，日志保留本轮目录。
  7. start-timeout：启动命令存活但不监听 -> rc=1 且 FAIL。
  8. rc 传播：verify 返回 7 -> runner rc=7；verify 记录 fail 但返回 0 -> runner rc=1。
  9. 正常路径：合成 Odoo（python 监听随机端口）-> rc=0，summary/latest-run/current-run 语义正确。
 10. STOP 语义：预先存在资源不执行 STOP；本轮创建则执行。
 11. P2_WORK 复用拒绝(4)；失败轮不更新 latest-run。

合成上游仅用 python socket，不监听 18069/9500/8443/55432；运行目录用 mktemp。
"""
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BORE = os.path.dirname(HERE)
RUNNER = os.path.join(BORE, "scripts", "run-p2-isolated.sh")
PY = sys.executable or "python3"

# 正式测试端口一律避开；合成服务只用内核分配的随机高位端口
FORBIDDEN_PORTS = (18069, 9500, 8443, 55432, 8069, 8072, 7835, 20000)
DOLLAR = "\u0024"


def free_port():
    for _ in range(50):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        finally:
            sock.close()
        if port > 1024 and port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("no free high port")


def helper_source():
    out = subprocess.run(["bash", RUNNER, "--print-evidence-helper"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("helper dump failed: %s" % out.stderr[-400:])
    return out.stdout


def run(cmd, env=None, timeout=180, cwd=None):
    base = dict(os.environ)
    base.pop("P2_WORK", None)
    base.pop("P2_RUN_ID", None)
    if env:
        base.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=base, cwd=cwd)


SYNTH_ODOO = r"""
import sys, time
from socket import socket, SOL_SOCKET, SO_REUSEADDR
port = int(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else "ok"
if mode == "fail":
    sys.stderr.write("synthetic start failure: cannot bind\n")
    sys.exit(3)
sock = socket()
sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(8)
sys.stdout.write("synthetic listening on %d\n" % port)
sys.stdout.flush()
if mode == "hang":
    sock.close()
    time.sleep(600)
    sys.exit(0)
while True:
    try:
        conn, _ = sock.accept()
        conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
        conn.close()
    except KeyboardInterrupt:
        break
"""


def verify_script(path, *lines):
    """生成合成 verify 脚本：只写自己那段结果，rc 由调用方给。"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/usr/bin/env bash\nset -u\n")
        fh.write('EV=' + '"' + DOLLAR + '{P2_EVIDENCE_PY}"' + "\n")
        fh.write('WORK=' + '"' + DOLLAR + '{P2_WORK}"' + "\n")
        fh.write('SINCE=' + '"' + DOLLAR + '{P2_RESULTS_SINCE:-0}"' + "\n")
        for line in lines:
            fh.write(line + "\n")
    os.chmod(path, 0o755)


def add_line(ident, state, detail=""):
    return ('"%(py)s" "$EV" add "$WORK/results.jsonl" "%(ident)s" "%(state)s" "%(detail)s"'
            % {"py": PY, "ident": ident, "state": state, "detail": detail})


class EvidenceHelperTest(unittest.TestCase):
    """证据助手纯逻辑（无网络、无服务子进程）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="p2-ev-")
        cls.helper = os.path.join(cls.tmp, "ev.py")
        with open(cls.helper, "w", encoding="utf-8") as fh:
            fh.write(helper_source())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _results(self, name):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8"):
            pass
        return path

    def add(self, results, ident, state, detail="", run_id="r1"):
        env = dict(os.environ, P2_RUN_ID=run_id, P2_PASS="secret-pass-1")
        out = subprocess.run([PY, self.helper, "add", results, ident, state, detail],
                             capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def test_four_states_and_record_shape(self):
        results = self._results("four.jsonl")
        for ident, state in (("a", "pass"), ("b", "fail"), ("c", "blocked"), ("d", "skip")):
            self.add(results, ident, state, "detail-" + state)
        with open(results, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual([r["result"] for r in records], ["pass", "fail", "blocked", "skip"])
        for record in records:
            self.assertEqual(set(record), {"run_id", "id", "result", "detail", "at"})
            self.assertEqual(record["run_id"], "r1")
            self.assertRegex(record["at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_invalid_state_rejected(self):
        results = self._results("bad-state.jsonl")
        out = subprocess.run([PY, self.helper, "add", results, "x", "weird", ""],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        with open(results, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_summary_matches_results_and_exit_code(self):
        results = self._results("sum.jsonl")
        self.add(results, "a", "pass")
        self.add(results, "b", "blocked", "port busy")
        summary = os.path.join(self.tmp, "summary.json")
        out = subprocess.run([PY, self.helper, "summarize", results, summary, self.tmp, "3"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("COUNTS pass=1 fail=0 blocked=1 skip=0", out.stdout)
        with open(summary, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["counts"], {"pass": 1, "fail": 0, "blocked": 1, "skip": 0})
        self.assertEqual(doc["total"], 2)
        self.assertEqual(doc["exit_code"], 3)
        self.assertEqual(doc["status"], "blocked")
        self.assertFalse(doc["passed"])
        self.assertEqual(doc["run_id"], "r1")
        self.assertRegex(doc["results"]["sha256"], r"^[0-9a-f]{64}$")

    def test_check_detects_tampered_summary(self):
        work = tempfile.mkdtemp(prefix="p2-tamper-", dir=self.tmp)
        results = os.path.join(work, "results.jsonl")
        with open(results, "w", encoding="utf-8"):
            pass
        self.add(results, "a", "pass")
        summary = os.path.join(work, "summary.json")
        subprocess.run([PY, self.helper, "summarize", results, summary, work, "0"],
                       check=True, capture_output=True, text=True)
        ok = run(["bash", RUNNER, "--check-evidence", work])
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        with open(summary, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["counts"]["pass"] = 42
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        bad_out = run(["bash", RUNNER, "--check-evidence", work])
        self.assertEqual(bad_out.returncode, 1, bad_out.stdout)
        self.assertIn("counts-mismatch", bad_out.stdout)

    def test_failed_run_can_have_valid_evidence_without_passing(self):
        work = tempfile.mkdtemp(prefix="p2-failed-evidence-", dir=self.tmp)
        results = os.path.join(work, "results.jsonl")
        self.add(results, "business-failure", "fail")
        summary = os.path.join(work, "summary.json")
        subprocess.run([PY, self.helper, "summarize", results, summary, work, "1"],
                       check=True, capture_output=True, text=True)
        out = run(["bash", RUNNER, "--check-evidence", work])
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        doc = json.loads(out.stdout)
        self.assertEqual(doc["evidence_integrity"], "pass")
        self.assertEqual(doc["run_status"], "fail")
        self.assertEqual(doc["run_exit_code"], 1)
        self.assertFalse(doc["run_passed"])

    def test_check_rejects_pass_claim_over_fail_or_blocked_counts(self):
        for state, code in (("fail", "1"), ("blocked", "3")):
            with self.subTest(state=state):
                work = tempfile.mkdtemp(prefix="p2-false-pass-", dir=self.tmp)
                results = os.path.join(work, "results.jsonl")
                self.add(results, "not-pass", state)
                summary = os.path.join(work, "summary.json")
                subprocess.run([PY, self.helper, "summarize", results, summary, work, code],
                               check=True, capture_output=True, text=True)
                with open(summary, encoding="utf-8") as fh:
                    doc = json.load(fh)
                doc.update(status="pass", exit_code=0, passed=True)
                with open(summary, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
                out = run(["bash", RUNNER, "--check-evidence", work])
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn("status-mismatch", out.stdout)
                self.assertIn("exit-counts-mismatch", out.stdout)

    def test_check_detects_broken_line(self):
        work = tempfile.mkdtemp(prefix="p2-broken-", dir=self.tmp)
        results = os.path.join(work, "results.jsonl")
        with open(results, "w", encoding="utf-8"):
            pass
        self.add(results, "a", "pass")
        summary = os.path.join(work, "summary.json")
        subprocess.run([PY, self.helper, "summarize", results, summary, work, "0"],
                       check=True, capture_output=True, text=True)
        with open(results, "a", encoding="utf-8") as fh:
            fh.write("not-json\n")
        out = run(["bash", RUNNER, "--check-evidence", work])
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("bad-results-lines", out.stdout)

    def test_summarize_rejects_mixed_run_ids(self):
        results = self._results("mixed.jsonl")
        self.add(results, "a", "pass", run_id="r1")
        self.add(results, "b", "pass", run_id="r2")
        out = subprocess.run([PY, self.helper, "summarize", results,
                              os.path.join(self.tmp, "mixed-summary.json"), self.tmp, "0"],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("mixes run_id", out.stderr)

    def test_atomic_write_leaves_no_temp_files(self):
        work = tempfile.mkdtemp(prefix="p2-atomic-", dir=self.tmp)
        results = os.path.join(work, "results.jsonl")
        with open(results, "w", encoding="utf-8"):
            pass
        self.add(results, "a", "pass")
        subprocess.run([PY, self.helper, "summarize", results,
                        os.path.join(work, "summary.json"), work, "0"],
                       check=True, capture_output=True, text=True)
        self.assertEqual([n for n in os.listdir(work) if n.startswith(".p2tmp-")], [])

    def test_jsonrpc_payloads_are_always_valid_json(self):
        nasty = [
            "simple-pass",
            'p@ss"with-quote',
            "p@ss'with-single",
            "p@ss\\with-backslash",
            "p@ss with tab\tand space",
            "\u5bc6\u7801-\u4e2d\u6587-\u53e3\u4ee4",
            '{"looks":"like-json"}',
            "trailing-\u00e9\u00e8",
            "x" * 300,
        ]
        for password in nasty:
            payload = "%s\n%s\n%s\n%s\n" % ("teamweb_test", "p2_manager", password, 11)
            out = subprocess.run([PY, self.helper, "auth"], input=payload,
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            doc = json.loads(out.stdout)
            self.assertEqual(doc["params"]["password"], password)
            self.assertEqual(doc["params"]["db"], "teamweb_test")
            self.assertEqual(doc["jsonrpc"], "2.0")
            self.assertEqual(doc["id"], 11)

    def test_auth_rejects_embedded_newline_instead_of_truncating(self):
        """含换行的密码不能被静默截断，必须显式报错（严格行数）。"""
        payload = "teamweb_test\np2_manager\np@ss\nwith-newline\n11\n"
        out = subprocess.run([PY, self.helper, "auth"], input=payload,
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("exactly 4 stdin lines", out.stderr)
        self.assertEqual(out.stdout.strip(), "")

    def test_jsonrpc_call_requires_object_params(self):
        bad = subprocess.run([PY, self.helper, "call"], input="1\n[1,2,3]\n",
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        ok = subprocess.run([PY, self.helper, "call"], input='2\n{"a":1}\n',
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(json.loads(ok.stdout)["params"], {"a": 1})

    def test_redaction_removes_password_and_session(self):
        payload = ("boot failed for secret-pass-1\n"
                   "Set-Cookie: session_id=abcdef123456; Path=/\n"
                   "password=secret-pass-1\n")
        out = subprocess.run([PY, self.helper, "redact", "4000"], input=payload,
                             capture_output=True, text=True,
                             env=dict(os.environ, P2_PASS="secret-pass-1"))
        self.assertEqual(out.returncode, 0)
        self.assertNotIn("secret-pass-1", out.stdout)
        self.assertNotIn("abcdef123456", out.stdout)
        self.assertIn("boot failed", out.stdout)

    def test_redaction_truncates(self):
        out = subprocess.run([PY, self.helper, "redact", "10"], input="x" * 500,
                             capture_output=True, text=True)
        self.assertIn("truncated", out.stdout)
        self.assertLess(len(out.stdout), 60)


class RunnerSafetyTest(unittest.TestCase):
    """合成运行器测试：不接触真实 Odoo/Nginx/bore，只用高位随机端口。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p2-runner-")
        self.base = os.path.join(self.tmp, "base")
        os.makedirs(self.base, exist_ok=True)
        self.odoo_port = free_port()
        self.script = os.path.join(self.tmp, "synthetic_odoo.py")
        with open(self.script, "w", encoding="utf-8") as fh:
            fh.write(SYNTH_ODOO)
        self.dummy_bin = os.path.join(self.tmp, "dummybin")
        os.makedirs(self.dummy_bin)
        for name in ("nginx", "bore"):
            path = os.path.join(self.dummy_bin, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(path, 0o755)
        self.nginx = os.path.join(self.dummy_bin, "nginx")
        self.bore = os.path.join(self.dummy_bin, "bore")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, start_cmd, extra=None):
        base = {
            "NGINX_BIN": self.nginx,
            "BORE_BIN": self.bore,
            "ODOO_URL": "http://127.0.0.1:%d" % self.odoo_port,
            "DB_NAME": "p2_synth_test",
            "P2_USERS": "u1:u2:u3:u4",
            "P2_PASS": "synth-secret-value",
            "ODOO_START_CMD": start_cmd,
            "P2_BASE": self.base,
            "PYTHON": PY,
            "P2_START_TIMEOUT": "8",
        }
        if extra:
            base.update(extra)
        return base

    def runner(self, env, timeout=180):
        return run(["bash", RUNNER], env=env, timeout=timeout)

    def work(self):
        runs = os.path.join(self.base, "runs")
        names = sorted(os.listdir(runs))
        self.assertTrue(names, "本轮应创建运行目录")
        return os.path.join(runs, names[-1])

    def read_summary(self, work):
        with open(os.path.join(work, "summary.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def read_results(self, work):
        with open(os.path.join(work, "results.jsonl"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def states(self, work):
        return {r["id"]: r["result"] for r in self.read_results(work)}

    # ---- 输入校验 -------------------------------------------------------
    def test_rejects_non_loopback_url(self):
        env = self.env("sleep 5")
        env["ODOO_URL"] = "http://10.0.0.5:%d" % self.odoo_port
        out = self.runner(env)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn("BLOCKED", out.stdout)
        self.assertIn("runner-url", out.stdout)

    def test_rejects_bad_port_format(self):
        for bad in ("http://127.0.0.1:018069", "http://127.0.0.1:99999",
                    "http://127.0.0.1:80/path", "http://127.0.0.1:80?x=1",
                    "ftp://127.0.0.1:80", "http://user:pw@127.0.0.1:80",
                    "http://127.0.0.1:0"):
            env = self.env("sleep 5")
            env["ODOO_URL"] = bad
            out = self.runner(env)
            self.assertEqual(out.returncode, 3, "url=%s out=%s" % (bad, out.stdout))
        # 配置错误一律 blocked，且从未写出 latest-run；每轮 summary 状态为 blocked
        self.assertFalse(os.path.exists(os.path.join(self.base, "latest-run")))
        rounds = sorted(os.listdir(os.path.join(self.base, "runs")))
        self.assertEqual(len(rounds), 7)
        for name in rounds:
            summary = self.read_summary(os.path.join(self.base, "runs", name))
            self.assertEqual(summary["status"], "blocked", name)
            self.assertEqual(summary["exit_code"], 3, name)

    def test_rejects_system_database(self):
        env = self.env("sleep 5")
        env["DB_NAME"] = "postgres"
        out = self.runner(env)
        self.assertEqual(out.returncode, 3, out.stdout)
        self.assertIn("runner-db", out.stdout)

    def test_rejects_missing_required_variable(self):
        env = self.env("sleep 5")
        env.pop("P2_PASS")
        out = self.runner(env)
        self.assertEqual(out.returncode, 3, out.stdout)

    def test_rejects_relative_base(self):
        env = self.env("sleep 5")
        env["P2_BASE"] = "relative/base"
        out = self.runner(env)
        self.assertEqual(out.returncode, 3, out.stdout)
        self.assertIn("P2_BASE", out.stdout)

    # ---- occupied port --------------------------------------------------
    def test_occupied_port_blocks_without_touching_occupant(self):
        occupant = socket.socket()
        occupant.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupant.bind(("127.0.0.1", self.odoo_port))
        occupant.listen(4)
        try:
            out = self.runner(self.env("sleep 30"))
            self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
            self.assertIn("runner-port-free", out.stdout)
            states = self.states(self.work())
            self.assertEqual(states.get("runner-port-free"), "blocked")
            self.assertNotIn("runner-started", states)
            probe = socket.socket()
            try:
                probe.settimeout(2)
                self.assertEqual(probe.connect_ex(("127.0.0.1", self.odoo_port)), 0,
                                 "占用者必须仍在监听（不得被本轮停机）")
            finally:
                probe.close()
        finally:
            occupant.close()

    # ---- start failure / timeout ---------------------------------------
    def test_start_failure_is_fast_fail_with_retained_log(self):
        out = self.runner(self.env("%s %s %d fail" % (PY, self.script, self.odoo_port)))
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("runner-start", out.stdout)
        work = self.work()
        states = self.states(work)
        self.assertEqual(states["runner-start"], "fail")
        log = os.path.join(work, "logs", "odoo.log")
        self.assertTrue(os.path.isfile(log), "Odoo 启动日志必须保留在本轮目录")
        with open(log, encoding="utf-8") as fh:
            self.assertIn("synthetic start failure", fh.read())
        summary = self.read_summary(work)
        self.assertEqual(summary["exit_code"], 1)
        self.assertEqual(summary["status"], "fail")
        self.assertFalse(summary["passed"])

    def test_start_timeout_without_listening_is_fail(self):
        env = self.env("%s %s %d hang" % (PY, self.script, self.odoo_port), {"P2_START_TIMEOUT": "3"})
        out = self.runner(env)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertEqual(self.states(self.work()).get("runner-listen"), "fail")

    def test_password_never_written_to_evidence(self):
        self.runner(self.env("%s %s %d fail" % (PY, self.script, self.odoo_port)))
        work = self.work()
        for name in os.listdir(work):
            path = os.path.join(work, name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    self.assertNotIn(b"synth-secret-value", fh.read(), name)

    # ---- rc propagation -------------------------------------------------
    def test_verify_rc_is_propagated_verbatim(self):
        verify = os.path.join(self.tmp, "verify_rc7.sh")
        verify_script(verify, "echo 'verify ran'", "exit 7")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {"P2_VERIFY_SCRIPT": verify})
        out = self.runner(env)
        self.assertEqual(out.returncode, 7, out.stdout + out.stderr)
        work = self.work()
        self.assertEqual(self.states(work)["runner-verify-exit"], "fail")
        self.assertEqual(self.read_summary(work)["exit_code"], 7)

    def test_verify_blocked_rc3_is_recorded_as_blocked(self):
        verify = os.path.join(self.tmp, "verify_rc3.sh")
        verify_script(verify, "exit 3")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {"P2_VERIFY_SCRIPT": verify})
        out = self.runner(env)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        work = self.work()
        self.assertEqual(self.states(work)["runner-verify-exit"], "blocked")
        self.assertEqual(self.read_summary(work)["status"], "blocked")

    def test_verify_records_fail_but_exits_zero_still_fails(self):
        verify = os.path.join(self.tmp, "verify_lying.sh")
        verify_script(verify, add_line("injected-fail", "fail", "rc hidden"), "exit 0")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {"P2_VERIFY_SCRIPT": verify})
        out = self.runner(env)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("runner-rc-consistency", out.stdout)
        self.assertEqual(self.read_summary(self.work())["exit_code"], 1)

    def test_verify_summary_mismatch_is_detected(self):
        verify = os.path.join(self.tmp, "verify_mismatch.sh")
        verify_script(verify,
                      add_line("one", "pass"),
                      'printf \'{"pass": 99, "fail": 0, "blocked": 0, "skip": 0}\\n\' > "$WORK/verify-summary.json"',
                      "exit 0")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {"P2_VERIFY_SCRIPT": verify})
        out = self.runner(env)
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("runner-verify-summary", out.stdout)
        self.assertEqual(self.states(self.work())["runner-verify-summary"], "fail")

    def test_verify_summary_delta_scope_is_accepted(self):
        verify = os.path.join(self.tmp, "verify_delta.sh")
        verify_script(verify,
                      add_line("x1", "pass"),
                      add_line("x2", "skip", "n/a"),
                      'printf \'{"pass": 1, "fail": 0, "blocked": 0, "skip": 1, "since_line": %s}\\n\' "$SINCE" > "$WORK/verify-summary.json"',
                      "exit 0")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {"P2_VERIFY_SCRIPT": verify})
        out = self.runner(env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.states(self.work())["runner-verify-summary"], "pass")

    # ---- happy path & run publication ----------------------------------
    def test_success_path_publishes_complete_evidence(self):
        verify = os.path.join(self.tmp, "verify_ok.sh")
        verify_script(verify,
                      add_line("a", "pass"),
                      add_line("b", "pass"),
                      add_line("c", "pass"),
                      add_line("d", "skip", "not applicable"),
                      "exit 0")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {"P2_VERIFY_SCRIPT": verify})
        out = self.runner(env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        work = self.work()
        summary = self.read_summary(work)
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["exit_code"], 0)
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["counts"]["fail"], 0)
        self.assertEqual(summary["counts"]["blocked"], 0)
        # skip 只来自 verify 的 1 条 + runner 自己声明的“未提供/不需执行”项
        states = self.states(work)
        self.assertEqual(states["d"], "skip")
        expected_skip = sum(1 for value in states.values() if value == "skip")
        self.assertEqual(summary["counts"]["skip"], expected_skip)
        for ident in ("runner-preexisting", "runner-stop-registered",
                      "runner-post-start", "cleanup-stop"):
            self.assertIn(states[ident], ("skip", "pass"), ident)
        results = self.read_results(work)
        recount = {"pass": 0, "fail": 0, "blocked": 0, "skip": 0}
        for record in results:
            recount[record["result"]] += 1
        self.assertEqual(summary["counts"], recount)
        self.assertEqual(summary["total"], len(results))
        with open(os.path.join(self.base, "latest-run"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), work)
        self.assertFalse(os.path.exists(os.path.join(self.base, "current-run")))
        check = run(["bash", RUNNER, "--check-evidence", work])
        self.assertEqual(check.returncode, 0, check.stdout)
        states = self.states(work)
        self.assertEqual(states["cleanup-children"], "pass")
        self.assertEqual(states["cleanup-stop"], "skip")
        probe = socket.socket()
        try:
            probe.settimeout(1)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", self.odoo_port)), 0,
                                "本轮启动的监听进程必须已回收")
        finally:
            probe.close()

    def test_blocked_run_does_not_overwrite_latest_run(self):
        """启动前被拒绝的轮次：保留上一轮 latest-run，自身写入 latest-blocked-run。"""
        previous = os.path.join(self.tmp, "previous-run")
        os.makedirs(previous, exist_ok=True)
        with open(os.path.join(self.base, "latest-run"), "w", encoding="utf-8") as fh:
            fh.write(previous + "\n")
        env = self.env("sleep 5")
        env["ODOO_URL"] = "http://10.1.2.3:%d" % self.odoo_port
        out = self.runner(env)
        self.assertEqual(out.returncode, 3, out.stdout)
        with open(os.path.join(self.base, "latest-run"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), previous,
                             "blocked 轮不得覆盖上一轮 latest-run")
        with open(os.path.join(self.base, "latest-blocked-run"), encoding="utf-8") as fh:
            blocked = fh.read().strip()
        self.assertTrue(blocked.startswith(os.path.join(self.base, "runs")))
        self.assertEqual(self.read_summary(blocked)["status"], "blocked")

    def test_stop_command_skipped_when_resource_preexisting(self):
        marker = os.path.join(self.tmp, "stop-called")
        verify = os.path.join(self.tmp, "verify_none.sh")
        verify_script(verify, "exit 0")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {
            "P2_VERIFY_SCRIPT": verify,
            "ODOO_STOP_CMD": "touch %s" % marker,
            "P2_PREEXISTING_CMD": "true",
        })
        out = self.runner(env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertFalse(os.path.exists(marker), "预先存在的服务不得被 STOP")
        self.assertEqual(self.states(self.work())["cleanup-stop"], "skip")

    def test_stop_command_runs_when_runner_created_resource(self):
        marker = os.path.join(self.tmp, "stop-called-own")
        verify = os.path.join(self.tmp, "verify_ok2.sh")
        verify_script(verify, "exit 0")
        env = self.env("%s %s %d ok" % (PY, self.script, self.odoo_port), {
            "P2_VERIFY_SCRIPT": verify,
            "ODOO_STOP_CMD": "touch %s" % marker,
            "P2_PREEXISTING_CMD": "false",
        })
        out = self.runner(env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(os.path.exists(marker), "本轮创建的资源必须被 STOP")
        self.assertEqual(self.states(self.work())["cleanup-stop"], "pass")

    def test_work_reuse_refused(self):
        work = os.path.join(self.tmp, "existing-work")
        os.makedirs(work)
        env = self.env("sleep 5", {"P2_WORK": work})
        out = self.runner(env)
        self.assertEqual(out.returncode, 4, out.stdout)
        self.assertIn("REFUSE", out.stdout)


FIXTURE_GEN = os.path.join(BORE, "tests", "fixtures", "signed_update_fixture.py")
LOCAL_SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(BORE))),
                          "local", "build", "bore-p2-20261026", "seed_update.sh")


class ReleaseFixtureTest(unittest.TestCase):
    """合成更新清单必须用真实 Ed25519 测试签名（不是全零假签名）。

    夹具生成器位于跟踪的 tests/fixtures 中，私钥与生成产物只在临时目录。
    这里按真实契约验证：服务端 decode_manifest 可解析、客户端同款 Ed25519
    公钥可独立验证签名、篡改必被拒、key_id 明确 test-only。
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="p2-fixture-")
        cls.root = os.path.join(cls.tmp, "lab-client-updates")
        cls.keys = os.path.join(cls.tmp, "keys")
        cls.evidence = os.path.join(cls.tmp, "signing.json")
        cls.proc = run([PY, FIXTURE_GEN, "--root", cls.root, "--keys", cls.keys,
                        "--evidence", cls.evidence], timeout=180)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def envelope(self):
        with open(os.path.join(self.root, "android", "universal", "stable.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_generator_succeeds_and_keeps_private_key_private(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertNotIn("PRIVATE KEY", self.proc.stdout)
        with open(self.evidence, encoding="utf-8") as fh:
            self.assertNotIn("PRIVATE KEY", fh.read())

    def test_signature_is_real_ed25519_not_zero_bytes(self):
        env = self.envelope()
        sig = base64.b64decode(env["signature"])
        payload = base64.b64decode(env["payload"])
        self.assertEqual(len(sig), 64)
        self.assertNotEqual(sig, bytes(64), "不得再写全零假签名")
        with open(self.evidence, encoding="utf-8") as fh:
            pub = base64.b64decode(json.load(fh)["public_key_base64"])
        self.assertEqual(len(pub), 32)
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except Exception:
            self.skipTest("cryptography 不可用：跳过公钥独立验证")
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, payload)

    def test_tampered_payload_and_signature_rejected(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except Exception:
            self.skipTest("cryptography 不可用")
        env = self.envelope()
        sig = base64.b64decode(env["signature"])
        payload = bytearray(base64.b64decode(env["payload"]))
        with open(self.evidence, encoding="utf-8") as fh:
            pub = base64.b64decode(json.load(fh)["public_key_base64"])
        key = Ed25519PublicKey.from_public_bytes(pub)
        payload[0] ^= 0x01
        with self.assertRaises(Exception):
            key.verify(sig, bytes(payload))
        bad = bytearray(sig)
        bad[0] ^= 0xFF
        with self.assertRaises(Exception):
            key.verify(bytes(bad), bytes(payload))

    def test_manifest_matches_server_contract(self):
        env = self.envelope()
        self.assertTrue(env["key_id"].startswith("p2-test-only"), env["key_id"])
        data = json.loads(base64.b64decode(env["payload"]))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["app_id"], "com.example.lab_inventory_client")
        self.assertEqual((data["platform"], data["arch"], data["channel"]),
                         ("android", "universal", "stable"))
        self.assertEqual(data["package_type"], "apk")
        self.assertTrue(data["filename"].endswith(".apk"))
        self.assertRegex(data["sha256"], r"^[0-9a-f]{64}$")
        self.assertLessEqual(data["api_min"], data["api_max"])
        pkg = os.path.join(self.root, "releases", data["release_id"], data["filename"])
        self.assertTrue(os.path.isfile(pkg))
        with open(pkg, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), data["sha256"])


@unittest.skipUnless(os.path.isfile(LOCAL_SEED), "本地 seed 脚本不存在（Git 忽略目录）")
class LocalSeedHygieneTest(unittest.TestCase):
    def test_seed_no_longer_writes_zero_signature(self):
        with open(LOCAL_SEED, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("bytes(64)", text, "seed 不得再写全零假签名")
        self.assertIn("tests/fixtures/signed_update_fixture.py", text)
        # seed 只输出非机密摘要，不打印私钥
        self.assertNotIn("private_key_path", text)

class ScriptHygieneTest(unittest.TestCase):
    """静态检查：不得 eval 展开输入、不得 tail 未脱敏日志、证据字段齐备。"""

    def read(self, name):
        with open(os.path.join(BORE, "scripts", name), encoding="utf-8") as fh:
            return fh.read()

    def test_no_eval_of_untrusted_input(self):
        for name in ("run-p2-isolated.sh", "verify-real-odoo.sh"):
            text = self.read(name)
            self.assertNotIn('eval "cur=', text, name)
            self.assertNotIn(DOLLAR + "{!v}", text, name)
            self.assertNotRegex(text, r"(?m)^\s*eval\s", name)

    def test_no_raw_tail_of_odoo_log(self):
        """所有 tail 输出必须经过 redact 助手，不得把未脱敏日志直接打印/落盘。"""
        pattern = re.compile(r"^tails+-n")
        for name in ("run-p2-isolated.sh", "verify-real-odoo.sh"):
            for line in self.read(name).splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or not pattern.match(stripped):
                    continue
                self.assertIn("redact", stripped,
                              "%s: tail 未经脱敏：%s" % (name, stripped))

    def test_summary_has_four_states_and_run_id(self):
        text = self.read("run-p2-isolated.sh")
        for state in ("pass", "fail", "blocked", "skip"):
            self.assertIn('"%s"' % state, text)
        self.assertIn("since_line", text)
        self.assertIn('"run_id"', text)
        self.assertIn('"exit_code"', text)

    def test_verify_serializes_auth_payloads(self):
        text = self.read("verify-real-odoo.sh")
        self.assertIn("rpc_auth", text)
        self.assertIn("rate_login", text)
        # 不得把 shell 变量直接拼进 JSON 的 password 字段（含 rate_login）
        self.assertNotRegex(text, r'"password"\s*:\s*"?\$')
        # rate_login 也必须走序列化助手，而不是内联 -d 拼接
        rate_block = text.split("rate_login()", 1)[1].split("\n}", 1)[0]
        self.assertIn("rpc_auth", rate_block)

    def test_browser_invocation_checks_stdout_and_file(self):
        text = self.read("verify-real-odoo.sh")
        self.assertIn("CA_FILE=", text)
        self.assertIn("P2_DETAIL_KEY", text)
        self.assertIn("browser.json", text)
        self.assertIn("stdout-file-mismatch", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)