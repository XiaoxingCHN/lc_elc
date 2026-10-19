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
echo 正在启动实验室库存本机桥接...
echo 关闭本窗口即停止桥接。
echo.
"runtime\node.exe" "server.mjs" %*
echo.
echo 桥接已停止。
pause
