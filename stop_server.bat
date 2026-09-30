@echo off
REM Batch file to stop the background auto_sms server and watch daemon
REM started by start_server.bat.

REM Use PowerShell to find python.exe processes whose command line mentions
REM app.py or watch_daemon.py, and stop each one by its process ID.
REM (A plain "taskkill /IM python.exe" would kill ALL python processes on
REM the machine, which could hit unrelated scripts too, so this is safer.)
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'app\.py' -or $_.CommandLine -match 'watch_daemon\.py' } | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId + ': ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force }"

echo Done.
pause
