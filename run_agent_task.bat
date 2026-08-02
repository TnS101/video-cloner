@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%Virtual Environments\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%ROOT%resolve_workspace\VC_Agent_Bridge.py" %*
exit /b %ERRORLEVEL%
