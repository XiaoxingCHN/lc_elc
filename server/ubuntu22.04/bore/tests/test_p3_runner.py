#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 运行器自测（不需要 Odoo/PG/浏览器）。

覆盖：
  1. 助手源码可用：`--print-verify-helper` 输出可编译的 Python；`--selftest` 全绿。
  2. 输入校验：缺环境变量/相对 P3_BASE/非回环 URL → blocked(3)，不产生证据。
  3. 工作目录复用拒绝(4)：P3_WORK 已有 results.jsonl。
  4. rc 传播：外部断言脚本（测试专用 P3_VERIFY_SCRIPT）返回 7 → 运行器返回 7。
  5. 计数与 summary：pass 记录 → exit 0；fail 记录 → exit 1；blocked 记录 → exit 3。
  6. 证据一致性：`--check-evidence` 对正常/篡改/缺失 summary 的行为。
  7. 原子写：正常结束后工作目录无 *.tmp 残留。
  8. 脱敏：内置助手 selftest 已覆盖 session_id/长 id；此处用**运行时合成**的
     高熵口令/密文喂真实样本，断言输出不含密文（仓库不留可复用凭据字面量，
     credential-scan 无需豁免）。
  9. 库存口径：助手 ``internal_stock_domain()`` 只取内部/在途库位（虚拟库位 quant
     会相互抵消，用全库合计做断言会永远看不到收发/领用变化）。

不启动 Odoo、不监听正式端口、不联网；只用临时目录。
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BORE = os.path.dirname(HERE)
SCRIPT = os.path.join(BORE, 'scripts', 'verify-p3-write.sh')
PY = sys.executable or 'python3'
BASH = shutil.which('bash') or '/bin/bash'

DOLLAR = '\u0024'


def synth_secret(prefix, size=16):
    """运行时合成测试口令/密文：仓库里不留任何可复用的凭据字面量。

    用 ``secrets.token_hex`` 而不是固定常量：credential-scan 没有可命中的
    硬编码值，同时脱敏断言仍然作用在真实的高熵样本上（不是弱化验证）。
    """
    return '%s-%s' % (prefix, secrets.token_hex(size))


PASSWORD = synth_secret('p3synth')


def base_env(work, extra=None):
    env = dict(os.environ)
    for name in ('P3_WORK', 'P3_RUN_ID', 'P3_BASE', 'P3_VERIFY_SCRIPT',
                 'P3_GATE_URL', 'P3_SEED', 'P3_PASS'):
        env.pop(name, None)
    env.update({
        'PYTHON': PY,
        'ODOO_URL': 'http://127.0.0.1:18069',
        'DB_NAME': 'p3_runner_selftest',
        'P3_USERS': 'p3_norole:p3_catalog:p3_operator:p3_manager',
        'P3_PASS': PASSWORD,
        'P3_ADMIN': 'p3_admin',
        'P3_ADMIN_PASS': PASSWORD,
        'P3_BASE': work,
        'P3_WORK': os.path.join(work, 'run1'),
        'P3_TIMEOUT': '5',
    })
    if extra:
        env.update(extra)
    return env


def run_script(args, env, timeout=180):
    return subprocess.run([BASH, SCRIPT] + list(args), capture_output=True,
                          text=True, timeout=timeout, env=env)


def write_verify_script(path, lines, rc=0):
    """生成外部断言脚本：只写自己那段结果并返回给定 rc。"""
    body = ['#!/usr/bin/env bash', 'set -u']
    body.append('EV="%s"' % (DOLLAR + '{P3_EVIDENCE_PY}'))
    body.append('WORK="%s"' % (DOLLAR + '{P3_WORK}'))
    body.append('PY="%s"' % (DOLLAR + '{PYTHON:-python3}'))
    for ident, state, detail in lines:
        body.append('"$PY" "$EV" add "$WORK/results.jsonl" "%s" "%s" "%s"'
                    % (ident, state, detail))
    body.append('exit %d' % rc)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(body) + '\n')
    os.chmod(path, 0o755)
    return path


class HelperSourceTest(unittest.TestCase):
    def test_print_helper_is_valid_python(self):
        out = run_script(['--print-verify-helper'], dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        self.assertIn('def main(', out.stdout)
        self.assertIn('def selftest(', out.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'helper.py')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(out.stdout)
            compiled = subprocess.run([PY, '-m', 'py_compile', path],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr[-400:])

    def test_helper_selftest_passes(self):
        out = run_script(['--selftest'], dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stdout[-600:] + out.stderr[-400:])
        self.assertIn('SELFTEST', out.stdout)
        self.assertNotIn('FAIL ', out.stdout)

    def test_redaction_hides_secrets_in_actual_output(self):
        """功能性脱敏断言：喂真实样本给证据助手，检查**输出**不含密文。

        不再扫描助手源码里的静态字符串——源码里本来就有 `(session_id|csrf_token|password)=`
        这条**脱敏规则**，静态匹配会把红动作代码当成泄漏（runner-linux-r1 的 1 个 fail）。
        """
        secret = synth_secret('sessionvalue', 20)
        sample = ('login failed session_id=%s&csrf_token=%s password=%s'
                  % (secret, secret, secret))

        # 1) 本运行器的断言助手：redact_detail 必须吃掉这些值
        helper_src = run_script(['--print-verify-helper'], dict(os.environ)).stdout
        with tempfile.TemporaryDirectory() as tmp:
            helper = os.path.join(tmp, 'p3_verify.py')
            with open(helper, 'w', encoding='utf-8') as handle:
                handle.write(helper_src)
            redacted = subprocess.run(
                [PY, '-c',
                 'import sys; sys.path.insert(0, %r);'
                 'import importlib.util;'
                 'spec = importlib.util.spec_from_file_location("h", %r);'
                 'mod = importlib.util.module_from_spec(spec);'
                 'spec.loader.exec_module(mod);'
                 'print(mod.redact_detail(sys.argv[1]))' % (tmp, helper), sample],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(redacted.returncode, 0, redacted.stderr[-400:])
        output = redacted.stdout
        self.assertNotIn(secret, output, 'redact_detail 输出里仍有密文：%s' % output)
        self.assertIn('<redacted>', output, 'redact_detail 未产生脱敏占位：%s' % output)

    def test_stock_domain_is_internal_only(self):
        """库存断言必须只看内部库位（虚拟供应商/客户库位的 quant 相互抵消）。

        功能性断言：导入助手源码并调用 ``internal_stock_domain()``，
        不扫描源码文本（避免把规则代码当泄漏的同类误判）。
        """
        helper_src = run_script(['--print-verify-helper'], dict(os.environ)).stdout
        with tempfile.TemporaryDirectory() as tmp:
            helper = os.path.join(tmp, 'p3_verify.py')
            with open(helper, 'w', encoding='utf-8') as handle:
                handle.write(helper_src)
            probe = subprocess.run(
                [PY, '-c',
                 'import json, sys; sys.path.insert(0, %r);'
                 'import importlib.util;'
                 'spec = importlib.util.spec_from_file_location("h", %r);'
                 'mod = importlib.util.module_from_spec(spec);'
                 'spec.loader.exec_module(mod);'
                 'print(json.dumps(mod.internal_stock_domain(7)))' % (tmp, helper)],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(probe.returncode, 0, probe.stderr[-400:])
        domain = json.loads(probe.stdout)
        self.assertIn(['location_id.usage', 'in', ['internal', 'transit']], domain,
                      '库存断言未限定内部/在途库位：%s' % domain)
        self.assertIn(['product_id.product_tmpl_id', '=', 7], domain,
                      '库存断言未按物料档案过滤：%s' % domain)

    def test_evidence_helper_redact_command(self):
        """复用 P2 证据助手的 redact 命令，验证其实际输出已脱敏。"""
        runner = os.path.join(BORE, 'scripts', 'run-p2-isolated.sh')
        helper_src = subprocess.run(['bash', runner, '--print-evidence-helper'],
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(helper_src.returncode, 0, helper_src.stderr[-300:])
        with tempfile.TemporaryDirectory() as tmp:
            helper = os.path.join(tmp, 'p2_evidence.py')
            with open(helper, 'w', encoding='utf-8') as handle:
                handle.write(helper_src.stdout)
            secret = synth_secret('topsecret')
            proc = subprocess.run([PY, helper, 'redact', '400'],
                                  input='password=%s cookie=%s' % (secret, secret),
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertNotIn(secret, proc.stdout, 'P2 助手 redact 输出里仍有密文')


class InputValidationTest(unittest.TestCase):
    def test_missing_env_is_blocked(self):
        with tempfile.TemporaryDirectory() as work:
            env = base_env(work)
            env.pop('P3_PASS')
            out = run_script([], env)
            self.assertEqual(out.returncode, 3, out.stdout[-400:])
            self.assertIn('P3_PASS', out.stdout)
            self.assertFalse(os.path.exists(os.path.join(work, 'run1', 'results.jsonl')))

    def test_relative_base_is_blocked(self):
        with tempfile.TemporaryDirectory() as work:
            env = base_env(work, {'P3_BASE': 'relative/path'})
            out = run_script([], env)
            self.assertEqual(out.returncode, 3, out.stdout[-400:])
            self.assertIn('P3_BASE', out.stdout)

    def test_non_loopback_url_is_blocked(self):
        with tempfile.TemporaryDirectory() as work:
            env = base_env(work, {'ODOO_URL': 'https://team.l-creation.club'})
            out = run_script([], env)
            # 内置助手在 loopback 校验失败时输出 fatal(3)，运行器应返回 3
            self.assertEqual(out.returncode, 3, out.stdout[-600:] + out.stderr[-300:])
            self.assertIn('loopback', out.stdout + out.stderr)


class WorkReuseTest(unittest.TestCase):
    def test_existing_results_refused(self):
        with tempfile.TemporaryDirectory() as work:
            run_dir = os.path.join(work, 'run1')
            os.makedirs(run_dir)
            with open(os.path.join(run_dir, 'results.jsonl'), 'w',
                      encoding='utf-8') as handle:
                handle.write('{"id":"old","result":"pass"}\n')
            out = run_script([], base_env(work))
            self.assertEqual(out.returncode, 4, out.stdout[-400:])
            self.assertIn('拒绝复用', out.stdout)


class VerifyRcTest(unittest.TestCase):
    def test_verify_rc_is_propagated(self):
        with tempfile.TemporaryDirectory() as work:
            script = write_verify_script(
                os.path.join(work, 'fake_verify.sh'),
                [('p3-fake', 'pass', 'ok')], rc=7)
            out = run_script([], base_env(work, {'P3_VERIFY_SCRIPT': script}))
            self.assertEqual(out.returncode, 7, out.stdout[-600:] + out.stderr[-300:])
            summary = json.load(open(os.path.join(work, 'run1', 'verify-summary.json'),
                                     encoding='utf-8'))
            self.assertEqual(summary['counts']['pass'], 1)
            self.assertEqual(summary['verify_rc'], 7)

    def test_fail_record_exits_one(self):
        with tempfile.TemporaryDirectory() as work:
            script = write_verify_script(
                os.path.join(work, 'fake_verify.sh'),
                [('p3-fake-pass', 'pass', 'ok'),
                 ('p3-fake-fail', 'fail', 'boom')], rc=0)
            out = run_script([], base_env(work, {'P3_VERIFY_SCRIPT': script}))
            self.assertEqual(out.returncode, 1, out.stdout[-600:])
            summary = json.load(open(os.path.join(work, 'run1', 'verify-summary.json'),
                                     encoding='utf-8'))
            self.assertEqual(summary['counts'], {'pass': 1, 'fail': 1, 'blocked': 0})

    def test_blocked_record_exits_three(self):
        with tempfile.TemporaryDirectory() as work:
            script = write_verify_script(
                os.path.join(work, 'fake_verify.sh'),
                [('p3-fake-pass', 'pass', 'ok'),
                 ('p3-fake-blocked', 'blocked', 'endpoint missing')], rc=0)
            out = run_script([], base_env(work, {'P3_VERIFY_SCRIPT': script}))
            self.assertEqual(out.returncode, 3, out.stdout[-600:])
            summary = json.load(open(os.path.join(work, 'run1', 'verify-summary.json'),
                                     encoding='utf-8'))
            self.assertEqual(summary['counts']['blocked'], 1)
            self.assertEqual(summary['exit_code'], 3)

    def test_all_pass_exits_zero_and_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as work:
            script = write_verify_script(
                os.path.join(work, 'fake_verify.sh'),
                [('p3-a', 'pass', 'one'), ('p3-b', 'pass', 'two')], rc=0)
            out = run_script([], base_env(work, {'P3_VERIFY_SCRIPT': script}))
            self.assertEqual(out.returncode, 0, out.stdout[-600:])
            run_dir = os.path.join(work, 'run1')
            leftovers = [name for name in os.listdir(run_dir) if name.endswith('.tmp')]
            self.assertEqual(leftovers, [])
            results = open(os.path.join(run_dir, 'results.jsonl'),
                           encoding='utf-8').read().strip().splitlines()
            self.assertEqual(len(results), 2)
            for line in results:
                record = json.loads(line)
                self.assertEqual(record['result'], 'pass')
                self.assertIn('run_id', record)


class EvidenceCheckTest(unittest.TestCase):
    def _prepare(self, work, lines):
        script = write_verify_script(
            os.path.join(work, 'fake_verify.sh'), lines, rc=0)
        out = run_script([], base_env(work, {'P3_VERIFY_SCRIPT': script}))
        return out, os.path.join(work, 'run1')

    def test_check_evidence_ok(self):
        with tempfile.TemporaryDirectory() as work:
            out, run_dir = self._prepare(work, [('p3-a', 'pass', 'x')])
            self.assertEqual(out.returncode, 0, out.stdout[-400:])
            checked = run_script(['--check-evidence', run_dir], dict(os.environ))
            self.assertEqual(checked.returncode, 0, checked.stdout[-400:])
            self.assertIn('EVIDENCE-OK', checked.stdout)

    def test_check_evidence_detects_tamper(self):
        with tempfile.TemporaryDirectory() as work:
            out, run_dir = self._prepare(work, [('p3-a', 'pass', 'x')])
            self.assertEqual(out.returncode, 0)
            path = os.path.join(run_dir, 'verify-summary.json')
            data = json.load(open(path, encoding='utf-8'))
            data['counts']['pass'] = 9
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(data, handle)
            checked = run_script(['--check-evidence', run_dir], dict(os.environ))
            self.assertEqual(checked.returncode, 1, checked.stdout[-400:])
            self.assertIn('EVIDENCE-MISMATCH', checked.stdout)

    def test_check_evidence_missing_files(self):
        with tempfile.TemporaryDirectory() as work:
            checked = run_script(['--check-evidence', os.path.join(work, 'nope')],
                                 dict(os.environ))
            self.assertEqual(checked.returncode, 3, checked.stdout[-400:])

    def test_bad_result_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            out, run_dir = self._prepare(work, [('p3-a', 'pass', 'x')])
            self.assertEqual(out.returncode, 0)
            # 追加非法状态行：--check-evidence 必须报 badlines
            with open(os.path.join(run_dir, 'results.jsonl'), 'a',
                      encoding='utf-8') as handle:
                handle.write('{"id":"p3-bad","result":"maybe"}\n')
            checked = run_script(['--check-evidence', run_dir], dict(os.environ))
            self.assertEqual(checked.returncode, 1, checked.stdout[-400:])


if __name__ == '__main__':
    unittest.main()
