#!/usr/bin/env python3
"""从公开边缘发起：先发伪造 PROXY 行，再完成正常 TLS/HTTP。
预期：入口把伪造行当 TLS 垃圾 → 握手失败；脚本 exit 0 表示被拒绝，exit 1 表示意外成功。"""
import socket
import ssl
import sys

host, port, cafile, servername = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
raw = socket.create_connection((host, port), timeout=8)
raw.sendall(b"PROXY TCP4 6.6.6.6 127.0.0.1 4444 4444\r\n")
ctx = ssl.create_default_context(cafile=cafile)
try:
    tls = ctx.wrap_socket(raw, server_hostname=servername)
except (ssl.SSLError, OSError) as exc:
    print("REJECTED:", type(exc).__name__, str(exc)[:120])
    sys.exit(0)
try:
    tls.sendall(b"GET /team HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % servername.encode())
    data = tls.recv(64)
except OSError as exc:
    print("REJECTED:", type(exc).__name__)
    sys.exit(0)
print("UNEXPECTED_SUCCESS:", data[:40])
sys.exit(1)
