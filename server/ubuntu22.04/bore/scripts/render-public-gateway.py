#!/usr/bin/env python3
"""Render a loopback TLS gateway from the audited allowlist; never read TLS material."""
import argparse
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parents[1]


def render(tls_config, output, public_port, listen_port, database, nginx_version, upstream='http://127.0.0.1:8069'):
    for port in (public_port, listen_port):
        if not 1024 <= port <= 65535:
            raise ValueError('ports must be unprivileged TCP ports')
    if not re.fullmatch('[A-Za-z0-9_]+', database):
        raise ValueError('invalid database identifier')
    if not re.fullmatch('http://127[.]0[.]0[.]1:[0-9]+', upstream):
        raise ValueError('upstream must be IPv4 loopback')
    # Read only the existing Nginx text configuration, not certificate/key files.
    directives = {}
    for line in tls_config.splitlines():
        match = re.fullmatch('(ssl_certificate|ssl_certificate_key|ssl_protocols) +([^;{}]+);', line.strip())
        if match:
            name, value = match.groups()
            if name in directives and directives[name] != value:
                raise ValueError('ambiguous TLS configuration')
            if name != 'ssl_protocols' and (not value.startswith('/') or any(c in value for c in ('$', chr(34), chr(39)))):
                raise ValueError('TLS path must be a literal absolute reference')
            directives[name] = value
    if not {'ssl_certificate', 'ssl_certificate_key'} <= directives.keys():
        raise ValueError('existing TLS references missing')
    tls = chr(10).join(name + ' ' + directives[name] + ';' for name in ('ssl_certificate', 'ssl_certificate_key'))
    tls += chr(10) + 'ssl_protocols TLSv1.2 TLSv1.3;'
    version = tuple(int(x) for x in nginx_version.split('.'))
    cookie = ('proxy_cookie_flags session_id secure httponly samesite=lax;' if version >= (1, 19, 3)
              else 'proxy_cookie_path / "/; Secure; SameSite=Lax";')
    rate = 'limit_req zone=lc_bore_auth burst=5 nodelay; limit_req_status 429;'
    headers = (BASE / 'nginx/bore-proxy-headers.conf').read_text(encoding='utf-8')
    headers = headers.replace('@DB_HEADER@', 'proxy_set_header X-Odoo-Database ' + database + ';')
    text = (BASE / 'nginx/bore-public-allowlist.conf.template').read_text(encoding='utf-8')
    text = chr(10).join(line for line in text.splitlines() if not line.strip().startswith('#')) + chr(10)
    replacements = {
        '@LISTEN_LINE@': 'listen 127.0.0.1:' + str(listen_port) + ' ssl;',
        '@SSL_LINES@': tls,
        '@REALIP_LINES@': '# Public bore has no PROXY protocol: do not trust incoming forwarding headers.',
        '@COOKIE_FLAGS@': cookie,
        '@PUBLIC_PORT@': str(public_port),
        '@UPSTREAM@': upstream,
        '@RATE_LIMIT@': rate,
        'include bore-proxy-headers.conf;': 'include ' + str(output / 'bore-proxy-headers.conf') + ';',
        '$p2_reject_post': '$lc_bore_reject_post',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # The public relay hides visitor IPs. Limit the shared entry; never trust user XFF.
    # Every authentication route, including the HTML form fallback, uses this zone.
    for route in ('/login', '/team/login'):
        original = 'location = ' + route
        lines = text.splitlines()
        text = chr(10).join(line.replace('proxy_pass ', rate + ' proxy_pass ', 1)
                           if original + ' ' in line and 'proxy_pass ' in line else line for line in lines) + chr(10)
    allowed = []
    for authority in ('team.l-creation.club', 'team.l-creation.club:443', 'team.l-creation.club:' + str(public_port)):
        escaped = authority.replace('.', '[.]')
        allowed.append('    ~^https://' + escaped + '[|]' + escaped + '$ 1;')
    maps = chr(10).join([
        'map "$http_origin|$http_host" $lc_bore_origin_ok {',
        '    default 0;',
        '    ~^[|] 1;',
        *allowed,
        '}',
        'map "$request_method:$lc_bore_origin_ok" $lc_bore_reject_post { default 0; "POST:0" 1; }',
        'map $request_method $lc_bore_auth_key { default ""; POST "shared-public-bore"; }',
        'limit_req_zone $lc_bore_auth_key zone=lc_bore_auth:1m rate=6r/m;',
        '',
    ])
    if re.search('@[A-Z_]+@', text + headers):
        raise ValueError('unrendered placeholder')
    return maps + text, headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tls-config', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--public-port', required=True, type=int)
    parser.add_argument('--listen-port', default=18443, type=int)
    parser.add_argument('--database', required=True)
    parser.add_argument('--nginx-version', required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_dir() or any(output.glob('*.conf')):
        raise SystemExit('output directory must exist and have no conf files')
    config, headers = render(args.tls_config.read_text(encoding='utf-8'), output,
                             args.public_port, args.listen_port, args.database, args.nginx_version)
    (output / 'bore-proxy-headers.conf').write_text(headers, encoding='utf-8')
    (output / 'gateway.conf').write_text(config, encoding='utf-8')
    print('rendered_gateway=ok')


if __name__ == '__main__':
    main()
