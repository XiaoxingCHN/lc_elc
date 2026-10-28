#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成更新夹具测试：真实 Ed25519 签名/篡改/路径攻击/标准 ReleaseStore 契约。

只断言行为（不复制夹具内部实现）；可从任意工作目录运行：
  python3 -m unittest server/ubuntu22.04/bore/tests/test_signed_update_fixture.py -v
"""
import base64
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import re
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "signed_update_fixture.py"
REPO = HERE.parents[3]
CLIENT_RELEASE = REPO / "server/ubuntu22.04/odoo_addons/lab_workflow/tools/client_release.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fx = _load("signed_update_fixture", FIXTURE)
store_mod = _load("client_release_contract", CLIENT_RELEASE)


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="p2fixture-")
        self.tmp = pathlib.Path(self._tmp.name)
        self.root = self.tmp / "data" / "lab-client-updates"
        self.keys = self.tmp / "keys"
        self.evidence = self.tmp / "evidence" / "signing.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fx.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _generate(self, release_id="test-rel-001", filename="p2-test-app.apk", key_id=None):
        argv = ["generate", "--root", str(self.root), "--keys", str(self.keys),
                "--evidence", str(self.evidence), "--release-id", release_id,
                "--filename", filename]
        if key_id:
            argv += ["--key-id", key_id]
        rc, out, err = self._run(argv)
        self.assertEqual(rc, 0, err)
        return json.loads(self.evidence.read_text(encoding="utf-8"))

    def _verify(self, manifest, evidence=None):
        return self._run(["verify", "--manifest", str(manifest),
                          "--public-key-evidence", str(evidence or self.evidence)])

    def _tamper(self, manifest, mutate):
        env = json.loads(pathlib.Path(manifest).read_text(encoding="utf-8"))
        mutate(env)
        pathlib.Path(manifest).write_text(json.dumps(env), encoding="utf-8")
        return pathlib.Path(manifest)

    # ---------------------------------------------------------- 正向契约 ---
    def test_generate_then_verify_with_standard_store(self):
        ev = self._generate()
        stable = self.root / "android" / "universal" / "stable.json"
        receipt = self.root / "releases" / "test-rel-001" / "manifest.json"
        asset = self.root / "releases" / "test-rel-001" / "p2-test-app.apk"
        self.assertTrue(stable.is_file() and receipt.is_file() and asset.is_file())

        store = store_mod.ReleaseStore(self.root)
        envelope = store.manifest("android", "universal", "stable")
        self.assertEqual(envelope["key_id"], ev["key_id"])
        data = store_mod.decode_manifest(envelope)
        path, data2 = store.asset("test-rel-001", "p2-test-app.apk")
        self.assertEqual(path.read_bytes(), asset.read_bytes())
        self.assertEqual(path.stat().st_size, data["size"])
        import hashlib
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), data["sha256"])
        self.assertEqual(data["sha256"], data2["sha256"])

        rc, out, err = self._verify(stable)
        self.assertEqual(rc, 0, err)
        summary = json.loads(out)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["release_id"], "test-rel-001")
        self.assertEqual(summary["key_id"], ev["key_id"])
        self.assertEqual(summary["package_sha256"], ev["package_sha256"])

    def test_evidence_and_sources_never_contain_private_key(self):
        self._generate()
        marker = "-----BEGIN " + "PRIVATE " + "KEY-----"
        blob = self.evidence.read_text(encoding="utf-8")
        self.assertNotIn(marker, blob)
        self.assertFalse(json.loads(blob)["private_key_exported"])
        # 夹具源码不得含私钥 PEM 或本机绝对路径常量（F 盘/USERPROFILE 等）
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertNotIn(marker, text)
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", text))
        self.assertNotIn(os.path.expanduser("~"), text)
        key_file = self.keys / fx.PRIVATE_KEY_NAME
        mode = key_file.stat().st_mode & 0o777
        # 尽量 0600；DrvFs/9p 忽略 chmod 时，证据必须记录实测模式而不是宣称 0600
        self.assertEqual(oct(mode), json.loads(blob)["private_key_mode"])
        if mode != 0o600:
            self.assertIn(mode, (0o666, 0o777), "非 0600 只允许 DrvFs 类文件系统")

    # ------------------------------------------------------------ 篡改 ---
    def test_tampered_payload_rejected(self):
        self._generate()
        stable = self.root / "android" / "universal" / "stable.json"

        def mutate(env):
            payload = json.loads(base64.b64decode(env["payload"]))
            payload["size"] += 1
            env["payload"] = base64.b64encode(
                json.dumps(payload).encode("utf-8")).decode("ascii")

        self._tamper(stable, mutate)
        rc, out, err = self._verify(stable)
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertNotIn("PRIVATE KEY", err)

    def test_tampered_signature_rejected(self):
        self._generate()
        stable = self.root / "android" / "universal" / "stable.json"

        def mutate(env):
            sig = bytearray(base64.b64decode(env["signature"]))
            sig[0] ^= 0x01
            env["signature"] = base64.b64encode(bytes(sig)).decode("ascii")

        self._tamper(stable, mutate)
        rc, out, err = self._verify(stable)
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_zero_signature_and_key_id_mismatch_rejected(self):
        self._generate()
        stable = self.root / "android" / "universal" / "stable.json"
        zero = self._tamper(stable, lambda env: env.update(
            signature=base64.b64encode(b"\x00" * 64).decode("ascii")))
        self.assertEqual(self._verify(zero)[0], 1)

        self._generate()
        other = self._tamper(stable, lambda env: env.update(key_id="p2-test-only-other"))
        rc, out, _ = self._verify(other)
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_verify_rejects_foreign_evidence(self):
        self._generate()
        stable = self.root / "android" / "universal" / "stable.json"
        foreign = json.loads(self.evidence.read_text(encoding="utf-8"))
        foreign["public_key_sha256"] = "0" * 64
        path = self.tmp / "foreign.json"
        path.write_text(json.dumps(foreign), encoding="utf-8")
        self.assertEqual(self._verify(stable, path)[0], 1)

    # ------------------------------------------------------ 路径与身份 ---
    def test_rejects_unsafe_release_or_filename(self):
        for release_id, filename in (("../escaped", "a.apk"), ("test-x", "../a.apk"),
                                     ("test/x", "a.apk"), ("test-x", "a.txt"),
                                     ("stable-rel", "a.apk")):
            rc, _, err = self._run(["generate", "--root", str(self.root),
                                    "--keys", str(self.keys),
                                    "--release-id", release_id, "--filename", filename])
            self.assertEqual(rc, 2, "%s/%s 应被拒绝" % (release_id, filename))
            self.assertFalse((self.tmp / "escaped").exists())
        rc, _, _ = self._run(["generate", "--root", str(self.root), "--keys", str(self.keys),
                              "--key-id", "release-20261019"])
        self.assertEqual(rc, 2)
        rc, _, _ = self._run(["generate", "--root", "relative/root", "--keys", str(self.keys)])
        self.assertEqual(rc, 2)

    def test_rejects_symlinked_paths(self):
        real = self.tmp / "real-keys"
        real.mkdir()
        link = self.tmp / "link-keys"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("当前环境不允许创建符号链接")
        rc, _, _ = self._run(["generate", "--root", str(self.root), "--keys", str(link)])
        self.assertEqual(rc, 2)

        self._generate()
        stable = self.root / "android" / "universal" / "stable.json"
        alias = self.tmp / "alias.json"
        alias.symlink_to(stable)
        self.assertEqual(self._verify(alias)[0], 1)

        asset = self.root / "releases" / "test-rel-001" / "p2-test-app.apk"
        asset.unlink()
        asset.symlink_to(self.tmp / "outside.bin")
        self.assertFalse(asset.is_file() and not asset.is_symlink())
        with self.assertRaises(ValueError):
            store_mod.ReleaseStore(self.root).asset("test-rel-001", "p2-test-app.apk")


if __name__ == "__main__":
    unittest.main()
