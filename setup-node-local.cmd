@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0setup-node-local.ps1" %*
exit /b %ERRORLEVEL%
