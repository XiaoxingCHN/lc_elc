#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "未找到 node，请先安装 Node.js（>= 20.5）或使用 Windows 一键包。"
  exit 1
fi

# 固定配对码：桥接每次启动都随机生成配对码，重启后旧码失效，插件里保存的那个
# 就作废了——表现就是"切到别的页面再回来显示未登录"。这里把配对码固定下来
# （存在本目录的 relay-token.txt，首次运行自动生成），重启桥接不再变化。
#
# 想换一个配对码：删掉 relay-token.txt 再启动即可。
# 想自己指定：LAB_RELAY_TOKEN=你的配对码 ./start-linux.sh
if [ -z "${LAB_RELAY_TOKEN:-}" ]; then
  if [ -f relay-token.txt ]; then
    LAB_RELAY_TOKEN=$(cat relay-token.txt)
  else
    LAB_RELAY_TOKEN=$(node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))")
    printf '%s' "$LAB_RELAY_TOKEN" > relay-token.txt
    chmod 600 relay-token.txt 2>/dev/null || true
  fi
  export LAB_RELAY_TOKEN
fi

echo "配对码已固定（保存在 relay-token.txt），重启桥接不会变化。"
exec node server.mjs "$@"
