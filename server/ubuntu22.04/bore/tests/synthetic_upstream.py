#!/usr/bin/env python3
"""合成上游：仅用于代理链路验证，不是 Odoo；不验证真实会话/权限/库存。"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1])
LOG = sys.argv[2]

ITEM = re.compile(r"^/(?:team/)?lab/items/[^/]+$")
EXACT = {
    "/", "/login", "/team", "/team/", "/team/login", "/team/lab", "/lab",
    "/lab/api/asset", "/lab/client/updates/manifest",
    "/lab/api/catalog/search", "/lab/api/catalog/detail",
    "/lab/api/catalog/categories", "/lab/api/catalog/facets",
    "/web/session/authenticate", "/web/session/get_session_info", "/web/session/destroy",
    "/team/api/session", "/api/team/session", "/team/logout", "/logout",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self):
        path = self.path.split("?")[0]
        known = path in EXACT or bool(ITEM.match(path)) or path.startswith("/lab_team_web/static/") \
            or path.startswith("/lab/client/updates/assets/")
        entry = {
            "method": self.command, "path": path, "known": known,
            "host": self.headers.get("Host", ""),
            "xff": self.headers.get("X-Forwarded-For", ""),
            "x_real_ip": self.headers.get("X-Real-IP", ""),
            "xf_proto": self.headers.get("X-Forwarded-Proto", ""),
            "forwarded": self.headers.get("Forwarded", ""),
            "x_odoo_database": self.headers.get("X-Odoo-Database", ""),
        }
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if not known:
            body = b'{"synthetic":true,"error":"not_found"}'
            self.send_response(404)
        else:
            body = b'{"synthetic":true,"ok":true}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_HEAD = _handle

    def log_message(self, *args):
        return


HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
