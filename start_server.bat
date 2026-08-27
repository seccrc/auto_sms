@echo off
REM Batch file to start the auto_sms dashboard server and the watch daemon.
REM Run this from the project folder (or double-click it in Windows Explorer).

REM Move to the folder where this batch file lives, so it works regardless
REM of the current working directory.
cd /d "%~dp0"

REM Check that all required Python packages from requirements.txt are installed
REM (pip skips anything already satisfied, so this is safe to run every time).
echo Checking requirements.txt ...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install required packages. Aborting.
    pause
    exit /b 1
)

REM Make sure the logs folder exists.
if not exist "logs" mkdir "logs"

REM Get today's date as YYYY-MM-DD via PowerShell, since %date% format
REM depends on the system locale and isn't reliable to parse.
for /f %%d in ('powershell -NoProfile -Command "(Get-Date).ToString(\"yyyy-MM-dd\")"') do set "TODAY=%%d"

REM Start the Flask dashboard server (app.py) in the background, no window,
REM with stdout/stderr appended to a log file named for today's date.
start "" /b cmd /c python app.py >> "logs\app_%TODAY%.log" 2>&1

REM Start the phone notification watcher (watch_daemon.py) in the background,
REM no window, with stdout/stderr appended to a log file named for today's date.
start "" /b cmd /c python watch_daemon.py >> "logs\watch_daemon_%TODAY%.log" 2>&1

REM Both processes keep running in the background after this script exits.
REM Check logs\app_%TODAY%.log and logs\watch_daemon_%TODAY%.log to see what
REM they're doing, and use Task Manager (or "tasklist" / "taskkill") to stop them.

REM Close this window right away — the server and daemon keep running in the
REM background independently of this window.
exit
