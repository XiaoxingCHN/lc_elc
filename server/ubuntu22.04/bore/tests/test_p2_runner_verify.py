#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 verify 脚本的证据助手测试（纯逻辑/合成，不跑真实 Odoo 链）。

覆盖：
  1. verify-real-odoo.sh 内所有内联 python heredoc 都能编译（防运行期语法错）。
  2. 输入校验失败（缺变量/非回环/系统库）时：rc=3，且 results.jsonl + summary.json
     仍然完整写出并可被 --check-evidence 独立重算通过（配置错误也有一致证据）。
  3. 浏览器证据核对块：stdout 与落盘 browser.json 不一致、rc 非零、缺步骤、
     json.ok=false、密码泄漏 都必须被检出；postData/cookie/csrf 必须被剥除。
  4. verify 的 since_line 语义：只统计自己那段结果（runner 前置记录不计入）。

不启动 Nginx/bore/Odoo，不占用 18069/9500/8443/55432。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BORE = os.path.dirname(HERE)
SCRIPTS = os.path.join(BORE, "scripts")
RUNNER = os.path.join(SCRIPTS, "run-p2-isolated.sh")
VERIFY = os.path.join(SCRIPTS, "verify-real-odoo.sh")
PY = sys.executable or "python3"


def run(cmd, env=None, timeout=180):
    base = dict(os.environ)
    for key in ("P2_WORK", "P2_RUN_ID", "P2_EVIDENCE_PY", "P2_RESULTS_SINCE",
                "P2_RUNNER_OWNS_SUMMARY"):
        base.pop(key, None)
    if env:
        base.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=base)


def heredoc_blocks(path):
    """抽出所有 <<'PY' heredoc 的 (起始行, 内容)。"""
    text = pathlib.Path(path).read_text(encoding="utf-8")
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        if re.search(r"<<'?PY'?", lines[i]):
            start = i + 1
            j = start
            while j < len(lines) and lines[j].strip() != "PY":
                j += 1
            blocks.append((start + 1, "\n".join(lines[start:j])))
            i = j
        i += 1
    return blocks


def block_after(path, marker):
    """抽出 "$(...)" 里以 marker 开头的内联 python 块。"""
    lines = pathlib.Path(path).read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if marker in ln)
    j = start + 1
    while lines[j].strip() != "PY":
        j += 1
    return "\n".join(lines[start + 1:j])


class InlinePythonTest(unittest.TestCase):
    def test_all_inline_python_blocks_compile(self):
        blocks = heredoc_blocks(VERIFY)
        self.assertGreaterEqual(len(blocks), 5, "verify 应含 5 段内联 python")
        for line, body in blocks:
            fd, path = tempfile.mkstemp(suffix=".py")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(body)
                proc = subprocess.run([PY, "-m", "py_compile", path],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0,
                                 "内联块(起始行 %d) 编译失败: %s" % (line, proc.stderr[-500:]))
            finally:
                if os.path.exists(path):
                    os.unlink(path)

    def test_runner_evidence_helper_compiles(self):
        out = run(["bash", RUNNER, "--print-evidence-helper"])
        self.assertEqual(out.returncode, 0, out.stderr)
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(out.stdout)
            proc = subprocess.run([PY, "-m", "py_compile", path],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        finally:
            if os.path.exists(path):
                os.unlink(path)


class VerifyBlockedEvidenceTest(unittest.TestCase):
    """配置错误也必须留下与 rc 一致的完整证据。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p2-verify-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self, **overrides):
        env = {
            "NGINX_BIN": "/bin/true",
            "BORE_BIN": "/bin/true",
            "ODOO_URL": "http://127.0.0.1:18069",
            "DB_NAME": "teamweb_test",
            "P2_USERS": "a:b:c:d",
            "P2_PASS": "verify-synth-secret",
            "P2_BASE": os.path.join(self.tmp, "base"),
            "PYTHON": PY,
        }
        env.update(overrides)
        return env

    def run_verify(self, env):
        return run(["bash", VERIFY], env=env)

    def last_work(self, base):
        runs = os.path.join(base, "runs")
        names = sorted(os.listdir(runs))
        return os.path.join(runs, names[-1])

    def assert_evidence_consistent(self, work, expect_status):
        with open(os.path.join(work, "results.jsonl"), encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        self.assertTrue(records, "results.jsonl 不能为空")
        recount = {"pass": 0, "fail": 0, "blocked": 0, "skip": 0}
        for record in records:
            self.assertIn(record["result"], recount)
            self.assertTrue(record.get("run_id"), "每条结果必须带 run_id")
            recount[record["result"]] += 1
        with open(os.path.join(work, "summary.json"), encoding="utf-8") as fh:
            summary = json.load(fh)
        self.assertEqual(summary["counts"], recount)
        self.assertEqual(summary["total"], len(records))
        self.assertEqual(summary["status"], expect_status)
        check = run(["bash", RUNNER, "--check-evidence", work])
        self.assertEqual(check.returncode, 0, check.stdout)
        return records, summary

    def test_missing_variable_is_blocked_with_complete_evidence(self):
        env = self.base_env()
        env.pop("NGINX_BIN")
        out = self.run_verify(env)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        work = self.last_work(env["P2_BASE"])
        records, summary = self.assert_evidence_consistent(work, "blocked")
        self.assertEqual(summary["exit_code"], 3)
        self.assertIn("p2-input-nginx", {r["id"] for r in records})
        with open(os.path.join(work, "verify-summary.json"), encoding="utf-8") as fh:
            declared = json.load(fh)
        self.assertEqual(declared["counts"], summary["counts"])

    def test_non_loopback_url_is_blocked(self):
        env = self.base_env(ODOO_URL="http://10.0.0.9:18069")
        out = self.run_verify(env)
        self.assertEqual(out.returncode, 3, out.stdout)
        self.assertIn("p2-input-url", out.stdout)
        self.assert_evidence_consistent(self.last_work(env["P2_BASE"]), "blocked")

    def test_system_database_is_blocked(self):
        env = self.base_env(DB_NAME="postgres")
        out = self.run_verify(env)
        self.assertEqual(out.returncode, 3, out.stdout)
        self.assertIn("p2-input-db", out.stdout)
        self.assert_evidence_consistent(self.last_work(env["P2_BASE"]), "blocked")

    def test_bad_port_format_is_blocked(self):
        for bad in ("http://127.0.0.1:018069", "http://127.0.0.1:99999",
                    "http://127.0.0.1:8443/path"):
            env = self.base_env(ODOO_URL=bad)
            out = self.run_verify(env)
            self.assertEqual(out.returncode, 3, "url=%s out=%s" % (bad, out.stdout))
            self.assertIn("p2-input-url", out.stdout)

    def test_password_never_in_verify_evidence(self):
        env = self.base_env()
        env.pop("NGINX_BIN")
        self.run_verify(env)
        work = self.last_work(env["P2_BASE"])
        for name in os.listdir(work):
            path = os.path.join(work, name)
            if os.path.isfile(path) and not name.endswith(".py"):
                with open(path, "rb") as fh:
                    self.assertNotIn(b"verify-synth-secret", fh.read(), name)


class BrowserEvidenceCheckTest(unittest.TestCase):
    """浏览器证据核对块：只认 stdout==落盘 且 全部步骤通过 且 rc==0。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="p2-browser-")
        body = block_after(VERIFY, "BROWSER_CHECK=$(")
        cls.block = os.path.join(cls.tmp, "check.py")
        with open(cls.block, "w", encoding="utf-8") as fh:
            fh.write(body)
        cls.stdout = os.path.join(cls.tmp, "stdout.json")
        cls.disk = os.path.join(cls.tmp, "browser.json")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def evaluate(self, out_doc, disk_doc, rc, password="pw-synth"):
        with open(self.stdout, "w", encoding="utf-8") as fh:
            json.dump(out_doc, fh)
        with open(self.disk, "w", encoding="utf-8") as fh:
            json.dump(disk_doc, fh)
        proc = subprocess.run([PY, self.block, self.stdout, self.disk, str(rc)],
                              capture_output=True, text=True,
                              env=dict(os.environ, P2_PASS=password))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    @staticmethod
    def good():
        names = ("env", "chrome-launch", "cdp-connect", "login-page", "login-ui-submit", "lab-authenticated", "search-ui-input", "search-rpc-query", "search-dom-match", "detail-link", "detail-ui-click", "detail-content", "detail-not-error", "refresh-ui", "refresh-authenticated", "refresh-content", "logout-cookie-capture", "logout-ui-submit", "logout-redirect-303", "logout-login-page", "logout-session-anon", "anon-lab-303", "anon-login-page-visible", "anon-old-cookie-invalid", "console-clean", "network-clean", "evidence-redaction", "profile-cleanup")
        return {"ok": True, "steps": [{"name": n, "ok": True, "detail": ""} for n in names],
                "console_errors": [], "screenshots": ["a.png"],
                "network_tail": [{"url": "https://team.l-creation.club:9500/lab", "status": 200}]}

    def test_clean_result_has_no_problems(self):
        doc = self.good()
        self.assertEqual(self.evaluate(doc, doc, 0)["problems"], [])

    def test_stdout_and_file_mismatch_detected(self):
        doc = self.good()
        trimmed = dict(doc, steps=doc["steps"][:-1])
        problems = self.evaluate(doc, trimmed, 0)["problems"]
        self.assertIn("stdout-file-mismatch", problems)

    def test_non_step_evidence_mismatch_detected(self):
        doc = self.good()
        changed = dict(doc, network_tail=[{"url": "/different", "status": 200}])
        self.assertIn("stdout-file-mismatch", self.evaluate(doc, changed, 0)["problems"])

    def test_non_boolean_success_is_rejected(self):
        doc = self.good()
        doc["steps"][0]["ok"] = "false"
        self.assertIn("non-boolean-result", self.evaluate(doc, doc, 0)["problems"])

    def test_duplicate_step_is_rejected(self):
        doc = self.good()
        doc["steps"].append(dict(doc["steps"][0]))
        self.assertIn("duplicate-step", self.evaluate(doc, doc, 0)["problems"])

    def test_console_error_cannot_be_overridden_by_ok(self):
        doc = self.good()
        doc["console_errors"] = ["synthetic security failure"]
        self.assertIn("console-errors-present", self.evaluate(doc, doc, 0)["problems"])

    def test_nested_console_error_is_rejected(self):
        doc = self.good()
        doc.pop("console_errors")
        doc["console"] = {"errors": [{"source": "security", "message": "synthetic CSP failure"}]}
        self.assertIn("console-errors-present", self.evaluate(doc, doc, 0)["problems"])

    def test_nonzero_rc_detected_even_if_steps_pass(self):
        doc = self.good()
        self.assertIn("rc=1", self.evaluate(doc, doc, 1)["problems"])

    def test_missing_required_step_detected(self):
        names = [s["name"] for s in self.good()["steps"] if s["name"] != "search-rpc-query"]
        doc = {"ok": True, "steps": [{"name": n, "ok": True} for n in names],
               "console_errors": []}
        self.assertIn("missing-step:search-rpc-query", self.evaluate(doc, doc, 0)["problems"])

    def test_failed_step_detected(self):
        doc = self.good()
        doc["steps"] = [dict(s, ok=(s["name"] != "detail-content")) for s in doc["steps"]]
        self.assertIn("failed-steps:detail-content", self.evaluate(doc, doc, 0)["problems"])

    def test_json_ok_false_detected(self):
        doc = self.good()
        doc["ok"] = False
        self.assertIn("json-ok-false", self.evaluate(doc, doc, 0)["problems"])

    def test_password_leak_detected(self):
        doc = self.good()
        doc["notes"] = "pw-synth in evidence"
        self.assertIn("password-in-evidence", self.evaluate(doc, doc, 0)["problems"])

    def test_network_secrets_fail_and_are_scrubbed(self):
        doc = self.good()
        doc["network_tail"] = [{"url": "https://x/logout?csrf_token=abc", "status": 303,
                                "postData": "csrf_token=abc", "cookie": "session_id=zzz"}]
        result = self.evaluate(doc, json.loads(json.dumps(doc)), 0)
        self.assertIn("sensitive-fields-in-browser-evidence", result["problems"])
        self.assertGreaterEqual(result["notes"].get("redacted_fields", 0), 1)
        with open(self.disk, encoding="utf-8") as fh:
            written = fh.read()
        self.assertNotIn("postData", written)
        self.assertNotIn("session_id=zzz", written)
        self.assertNotIn("csrf_token=abc", written)


class VerifySummaryScopeTest(unittest.TestCase):
    """verify-summary 的 since_line 只覆盖 verify 自己写的那段结果。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p2-scope-")
        out = run(["bash", RUNNER, "--print-evidence-helper"])
        self.helper = os.path.join(self.tmp, "ev.py")
        with open(self.helper, "w", encoding="utf-8") as fh:
            fh.write(out.stdout)
        self.results = os.path.join(self.tmp, "results.jsonl")
        with open(self.results, "w", encoding="utf-8"):
            pass
        self.env = dict(os.environ, P2_RUN_ID="scope-run")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, ident, state):
        proc = subprocess.run([PY, self.helper, "add", self.results, ident, state, ""],
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_compare_accepts_delta_scope(self):
        self.add("runner-a", "pass")
        self.add("runner-b", "skip")
        with open(self.results, encoding="utf-8") as fh:
            since = sum(1 for line in fh if line.strip())
        self.add("verify-a", "pass")
        self.add("verify-b", "blocked")
        summary = os.path.join(self.tmp, "verify-summary.json")
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump({"pass": 1, "fail": 0, "blocked": 1, "skip": 0,
                       "since_line": since}, fh)
        proc = subprocess.run([PY, self.helper, "compare", summary, self.results],
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("COMPARE ok", proc.stdout)

    def test_compare_rejects_wrong_delta(self):
        self.add("runner-a", "pass")
        since = 1
        self.add("verify-a", "pass")
        summary = os.path.join(self.tmp, "bad.json")
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump({"pass": 2, "fail": 0, "blocked": 0, "skip": 0,
                       "since_line": since}, fh)
        proc = subprocess.run([PY, self.helper, "compare", summary, self.results],
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("COMPARE mismatch", proc.stdout)

    def test_compare_rejects_out_of_range_since(self):
        self.add("verify-a", "pass")
        summary = os.path.join(self.tmp, "oob.json")
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump({"pass": 0, "fail": 0, "blocked": 0, "skip": 0,
                       "since_line": 99}, fh)
        proc = subprocess.run([PY, self.helper, "compare", summary, self.results],
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("since-line-beyond-results", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
