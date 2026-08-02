@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "COMMAND_DIR=%ROOT%.agent\commands\pending"
if not exist "%COMMAND_DIR%" mkdir "%COMMAND_DIR%" 2>nul
if not exist "%COMMAND_DIR%" (
  echo ERROR: Could not create command directory "%COMMAND_DIR%"
  exit /b 1
)
for /f %%R in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$g=[guid]::NewGuid().ToString('N'); $t=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'); Write-Output ($t+'_'+$g)"') do set "RUN_ID=%%R"
if not defined RUN_ID (
  echo ERROR: Could not generate run_id
  exit /b 1
)
set "COMMAND_PATH=%COMMAND_DIR%\BRIDGE_SMOKE_TEST_V1_%RUN_ID%.json"
set "TEMP_PATH=%COMMAND_PATH%.tmp"
set "MODULE=%ROOT%resolve_workspace\modules\bridge_smoke_test.py"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=$env:TEMP_PATH; $o=[ordered]@{schema_version=1; task='BRIDGE_SMOKE_TEST_V1'; run_id=$env:RUN_ID; module='resolve_workspace/modules/bridge_smoke_test.py'; module_path=$env:MODULE; mode='dry_run'; require_project_match=$false; require_timeline_match=$false; status_path=($env:ROOT+'.agent/reports/BRIDGE_SMOKE_TEST_V1/'+$env:RUN_ID+'/status.json'); log_path=($env:ROOT+'.agent/reports/BRIDGE_SMOKE_TEST_V1/'+$env:RUN_ID+'/run.log'); report_path=($env:ROOT+'.agent/reports/BRIDGE_SMOKE_TEST_V1/'+$env:RUN_ID+'/report.json')}; $o | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $p -Encoding UTF8; Move-Item -LiteralPath $p -Destination $env:COMMAND_PATH -Force" 
if errorlevel 1 (
  echo ERROR: Command creation failed
  exit /b 1
)
if not exist "%COMMAND_PATH%" (
  echo ERROR: Command file was not created
  exit /b 1
)
echo run_id: %RUN_ID%
echo command: %COMMAND_PATH%
exit /b 0
