#!/usr/bin/env python3
"""Netlify HTTPS origin adapter; the public frontend and origin names must be distinct."""
import importlib.util
import pathlib
import re

SPEC=importlib.util.spec_from_file_location('public_gateway',pathlib.Path(__file__).with_name('render-public-gateway.py'))
PUBLIC=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLIC)


def hostname(value):
    if len(value)>253 or not all(re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in value.split('.')):
        raise ValueError('invalid literal hostname')
    return value


def render(tls_config,output,public_port,listen_port,database,nginx_version,
           origin_host,canonical_host,frontend_hosts,upstream='http://127.0.0.1:8069'):
    origin_host=hostname(origin_host);canonical_host=hostname(canonical_host)
    frontend_hosts=tuple(dict.fromkeys(hostname(value) for value in frontend_hosts))
    if canonical_host not in frontend_hosts or origin_host in frontend_hosts:
        raise ValueError('frontends must include canonical host and exclude origin host')
    base,headers=PUBLIC.render(tls_config,output,public_port,listen_port,database,nginx_version,upstream)
    _,server=base.split('server {',1)
    config='server {'+server
    config=config.replace('server_name team.l-creation.club;','server_name '+origin_host+';')
    old=next(line for line in config.splitlines() if 'if ($http_host !~ ' in line)
    expression=origin_host.replace('.','[.]')+'(?::(?:443|'+str(public_port)+'))?$'
    config=config.replace(old,'    if ($http_host !~ ^'+expression+') { return 444; }')
    # Public origin is fixed after the incoming origin Host is validated. Never trust XFH.
    for old,new in (('proxy_set_header Host $http_host;','proxy_set_header Host '+canonical_host+';'),
                    ('proxy_set_header X-Forwarded-Host $http_host;','proxy_set_header X-Forwarded-Host '+canonical_host+';')):
        config=config.replace(old,new);headers=headers.replace(old,new)
    config=config.replace('lc_bore_','lc_netlify_')
    maps=['map $http_origin $lc_netlify_origin_ok {','    default 0;','    "" 1;']
    for frontend in frontend_hosts:
        maps.append('    ~^https://'+frontend.replace('.','[.]')+'(?::443)?$ 1;')
    maps.extend(['}',
                 'map "$request_method:$lc_netlify_origin_ok" $lc_netlify_reject_post { default 0; "POST:0" 1; }',
                 'map $request_method $lc_netlify_auth_key { default ""; POST "shared-netlify-entry"; }',
                 'limit_req_zone $lc_netlify_auth_key zone=lc_netlify_auth:1m rate=6r/m;',
                 ''])
    cache=chr(10).join([
        '    proxy_cache off;',
        '    proxy_hide_header Cache-Control;',
        '    proxy_hide_header Expires;',
        '    proxy_hide_header Pragma;',
        '    proxy_hide_header ETag;',
        '    proxy_hide_header Last-Modified;',
        '    add_header Cache-Control "private, no-store, max-age=0" always;',
        '    add_header CDN-Cache-Control "no-store" always;',
        '    add_header Netlify-CDN-Cache-Control "no-store" always;',
        '    add_header Pragma "no-cache" always;',
        '    proxy_redirect https://'+canonical_host+'/ /;',
    ])
    config=config.replace('    server_tokens off;','    server_tokens off;'+chr(10)+cache)
    # A fixed non-sensitive marker proves HTTPS proxying without using credentials.
    probe = '    location = /__lc_origin_probe { limit_except GET HEAD { deny all; } default_type text/plain; return 200 "lc-elc-netlify-https-origin-v1"; }'
    config = config.replace('    location / { return 404; }', probe + chr(10) + '    location / { return 404; }')
    # TLS certificate references must be for origin_host. Actual hostname validation is
    # performed by deployment probes, not by opening certificate/key files here.
    return chr(10).join(maps)+config,headers
