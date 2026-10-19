#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "未找到 node，请先安装 Node.js（>= 20.5）或使用 Windows 一键包。"
  exit 1
fi
exec node server.mjs "$@"
