@echo off
setlocal
set "VC_ROOT=%~dp0"
python "%VC_ROOT%scripts\standalone\video_cloner_media_prep.py" --project-root "%VC_ROOT%." %*
exit /b %errorlevel%
