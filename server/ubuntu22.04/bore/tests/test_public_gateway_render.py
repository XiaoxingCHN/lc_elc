"""Deployment renderer boundaries; no production credentials or TLS files."""
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gateway_render', ROOT / 'scripts/render-public-gateway.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TLS = 'ssl_certificate /test/site.crt;' + chr(10) + 'ssl_certificate_key /test/site.key;'


class PublicGatewayRenderTest(unittest.TestCase):
    def render(self, **changes):
        args = dict(tls_config=TLS, output=pathlib.Path('/test/release'), public_port=16443,
                    listen_port=18443, database='TestDB', nginx_version='1.18.0')
        args.update(changes)
        return MODULE.render(**args)

    def test_ipv4_loopback_only_and_no_unrendered_tokens(self):
        text, headers = self.render()
        self.assertIn('listen 127.0.0.1:18443 ssl;', text)
        self.assertNotIn('@', text + headers)
        self.assertIn('location / { return 404; }', text)
        self.assertNotIn('proxy_protocol', text)

    def test_old_nginx_cookie_flags_are_compatible(self):
        text, _ = self.render()
        self.assertIn('proxy_cookie_path / "/; Secure; SameSite=Lax";', text)
        self.assertNotIn('proxy_cookie_flags', text)

    def test_modern_nginx_uses_native_cookie_flags(self):
        text, _ = self.render(nginx_version='1.30.6')
        self.assertIn('proxy_cookie_flags session_id secure httponly samesite=lax;', text)

    def test_origin_pairs_authority_and_port(self):
        text, _ = self.render()
        patterns = [line.strip().split(' ')[0][1:] for line in text.splitlines() if line.strip().startswith('~^https://')]
        self.assertTrue(any(re.fullmatch(p, 'https://team.l-creation.club:16443|team.l-creation.club:16443') for p in patterns))
        for value in ('https://team.l-creation.club:16443|team.l-creation.club', 'https://evil.example|team.l-creation.club:16443', 'https://team.l-creation.club:16443.attacker|team.l-creation.club:16443'):
            self.assertFalse(any(re.fullmatch(p, value) for p in patterns))
        self.assertIn('default 0;', text)

    def test_session_headers_preserve_authority_and_drop_spoofing(self):
        text, headers = self.render()
        for directive in ('proxy_set_header Host $http_host;', 'proxy_set_header X-Forwarded-For $remote_addr;', 'proxy_set_header X-Forwarded-Port "";'):
            self.assertIn(directive, headers)
            self.assertIn(directive, text)
        self.assertIn('proxy_set_header X-Odoo-Database TestDB;', headers)
        self.assertIn('proxy_set_header X-Odoo-Database "";', text)

    def test_auth_form_fallbacks_are_rate_limited(self):
        text, _ = self.render()
        for route in ('/login', '/team/login'):
            line = next(line for line in text.splitlines() if 'location = ' + route + ' ' in line)
            self.assertIn('limit_req zone=lc_bore_auth', line)
        self.assertEqual(text.count('limit_req zone=lc_bore_auth'), 3)

    def test_injected_database_and_nonloopback_upstream_rejected(self):
        for args in (dict(database='TestDB;return 200'), dict(upstream='http://192.0.2.1:8069'), dict(public_port=443)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.render(**args)

    def test_tls_references_required_unambiguous_and_literal(self):
        invalid = ('', TLS + chr(10) + 'ssl_certificate /other/site.crt;', 'ssl_certificate $variable;' + chr(10) + 'ssl_certificate_key /test/site.key;')
        for tls in invalid:
            with self.subTest(tls=tls), self.assertRaises(ValueError):
                self.render(tls_config=tls)


if __name__ == '__main__':
    unittest.main()
