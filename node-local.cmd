@echo off
setlocal
set "NODE_EXE=%~dp0.tools-tar\node-v24.15.0-win-x64\node.exe"
if not exist "%NODE_EXE%" (
  echo Local Node.js runtime not found at "%NODE_EXE%".
  echo Run setup-node-local.cmd first.
  exit /b 1
)
"%NODE_EXE%" %*
exit /b %ERRORLEVEL%

