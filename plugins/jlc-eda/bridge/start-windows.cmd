@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "runtime\node.exe" (
  echo [错误] 未找到 runtime\node.exe。
  echo 请确认压缩包完整，或使用已安装的 Node.js 运行：node server.mjs
  pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem 固定配对码：桥接每次启动都随机生成配对码，重启后旧码失效，插件里保存的
rem 那个就作废了——表现就是"切到别的页面再回来显示未登录"。这里把配对码固定
rem 下来（存在本目录的 relay-token.txt，首次运行自动生成），重启桥接不再变化。
rem
rem 想换一个配对码：删掉 relay-token.txt 再启动即可。
rem 想自己指定：set LAB_RELAY_TOKEN=你的配对码 后再启动。
rem ---------------------------------------------------------------------------
if not defined LAB_RELAY_TOKEN (
  if exist "relay-token.txt" (
    set /p LAB_RELAY_TOKEN=<relay-token.txt
  ) else (
    for /f "delims=" %%i in ('"runtime\node.exe" -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"') do set LAB_RELAY_TOKEN=%%i
    >relay-token.txt echo %LAB_RELAY_TOKEN%
  )
)

echo 正在启动实验室库存本机桥接...
echo 关闭本窗口即停止桥接。
echo 配对码已固定（保存在 relay-token.txt），重启桥接不会变化。
echo.
"runtime\node.exe" "server.mjs" %*
echo.
echo 桥接已停止。
pause
