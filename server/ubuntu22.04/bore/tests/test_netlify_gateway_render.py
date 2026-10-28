import importlib.util,pathlib,re,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('netlify_render',ROOT/'scripts/render-netlify-gateway.py')
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)
TLS='ssl_certificate /test/origin.crt;'+chr(10)+'ssl_certificate_key /test/origin.key;'

class NetlifyGatewayRenderTest(unittest.TestCase):
 def render(self,**changes):
  values=dict(tls_config=TLS,output=pathlib.Path('/test/netlify-release'),public_port=16444,listen_port=18445,database='TestDB',nginx_version='1.18.0',origin_host='origin-team.l-creation.club',canonical_host='team.l-creation.club',frontend_hosts=('team.l-creation.club','rad-taffy-56e1ce.netlify.app'))
  values.update(changes);return MODULE.render(**values)
 def test_origin_and_canonical_authority_are_distinct(self):
  config,headers=self.render()
  self.assertIn('server_name origin-team.l-creation.club;',config)
  self.assertIn('proxy_set_header Host team.l-creation.club;',headers)
  self.assertIn('proxy_set_header X-Forwarded-Host team.l-creation.club;',headers)
  self.assertNotIn('proxy_set_header Host $http_host;',config+headers)
 def test_public_origins_are_exact_and_https_only(self):
  config,_=self.render();patterns=[line.strip().split(' ')[0][1:] for line in config.splitlines() if line.strip().startswith('~^https://')]
  for value in ('https://team.l-creation.club','https://rad-taffy-56e1ce.netlify.app','https://team.l-creation.club:443'):
   self.assertTrue(any(re.fullmatch(p,value) for p in patterns))
  for value in ('https://evil.example','https://other.netlify.app','http://team.l-creation.club','null','https://team.l-creation.club:16444','https://team.l-creation.club.attacker'):
   self.assertFalse(any(re.fullmatch(p,value) for p in patterns))
 def test_no_shared_cache_or_upstream_validator_leaks(self):
  config,_=self.render()
  for value in ('proxy_cache off;','proxy_hide_header ETag;','proxy_hide_header Last-Modified;','add_header Netlify-CDN-Cache-Control "no-store" always;','private, no-store, max-age=0'):
   self.assertIn(value,config)
 def test_independent_maps_and_zones_do_not_clash(self):
  config,_=self.render();self.assertNotIn('lc_bore_',config)
  self.assertIn('zone=lc_netlify_auth',config)
 def test_db_and_forwarding_boundaries_preserved(self):
  config,headers=self.render()
  self.assertIn('proxy_set_header X-Odoo-Database "";',config)
  self.assertIn('proxy_set_header X-Odoo-Database TestDB;',headers)
  self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;',headers)
  self.assertIn('proxy_set_header Forwarded "";',headers)
  self.assertIn('location / { return 404; }',config)
 def test_local_listener_and_cookie_compatibility(self):
  config,_=self.render();self.assertIn('listen 127.0.0.1:18445 ssl;',config)
  self.assertIn('proxy_cookie_path / "/; Secure; SameSite=Lax";',config)
 def test_external_redirects_become_relative(self):
  config,_=self.render();self.assertIn('proxy_redirect https://team.l-creation.club/ /;',config)
 def test_fixed_probe_has_no_upstream(self):
  config,_=self.render();line=next(line for line in config.splitlines() if 'location = /__lc_origin_probe ' in line)
  self.assertIn('limit_except GET HEAD',line)
  self.assertIn('lc-elc-netlify-https-origin-v1',line)
  self.assertNotIn('proxy_pass',line)
 def test_invalid_names_and_recursive_origin_rejected(self):
  for change in (dict(origin_host='team.l-creation.club'),dict(canonical_host='team.l-creation.club;return 200'),dict(frontend_hosts=('evil.example',)),dict(origin_host='origin..example.com')):
   with self.subTest(change=change),self.assertRaises(ValueError):self.render(**change)

if __name__=='__main__':unittest.main()
