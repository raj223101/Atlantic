@echo off
setlocal
set "NODE_ROOT=%~dp0.tools-tar\node-v24.15.0-win-x64"
set "NODE_EXE=%NODE_ROOT%\node.exe"
set "NPM_CLI=%NODE_ROOT%\node_modules\npm\bin\npm-cli.js"
if not exist "%NODE_EXE%" (
  echo Local Node.js runtime not found at "%NODE_EXE%".
  echo Run setup-node-local.cmd first.
  exit /b 1
)
if not exist "%NPM_CLI%" (
  echo Local npm CLI not found at "%NPM_CLI%".
  echo Re-run setup-node-local.cmd if needed.
  exit /b 1
)
"%NODE_EXE%" "%NPM_CLI%" %*
exit /b %ERRORLEVEL%

