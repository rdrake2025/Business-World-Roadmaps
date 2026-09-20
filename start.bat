@echo off
setlocal enabledelayedexpansion
title AnswerRank

REM  Double-click this file to set up and run AnswerRank on Windows.
REM
REM  Deliberately a .bat and not a .ps1: PowerShell blocks unsigned scripts by
REM  default, so a .ps1 fails on a clean machine with a confusing error. A .bat
REM  always runs. It also pauses on every exit path, so the window never
REM  vanishes before you can read what went wrong.

cd /d "%~dp0"

echo.
echo  ================================================================
echo    ANSWERRANK
echo  ================================================================
echo.

REM ---------------------------------------------------------------- update
REM  Requiring a manual `git pull` after every change put a terminal between
REM  the operator and their own business. Update here instead, quietly, and
REM  never block startup on it: an offline laptop must still run.
git rev-parse --is-inside-work-tree >nul 2>&1
if !errorlevel! equ 0 (
    echo  [0/5] Checking for updates...
    git stash push --quiet --include-untracked -m "start.bat autostash" >nul 2>&1
    set "STASHED=!errorlevel!"
    git pull --quiet --ff-only >nul 2>&1
    if !errorlevel! equ 0 (
        echo        Up to date
    ) else (
        echo        Could not update - continuing with what you have
    )
    if "!STASHED!"=="0" git stash pop --quiet >nul 2>&1
)

REM ---------------------------------------------------------------- python
echo  [1/5] Looking for Python...

set "PY="
for %%C in ("py -3.13" "py -3.12" "py -3.11" "py -3" "python") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
        if !errorlevel! equ 0 set "PY=%%~C"
    )
)

if not defined PY (
    echo.
    echo  [X] Python 3.11 or newer was not found.
    echo.
    echo      Install it from:  https://www.python.org/downloads/
    echo.
    echo      IMPORTANT: on the first installer screen, tick the box
    echo      "Add python.exe to PATH" at the bottom. It is easy to miss,
    echo      and nothing works without it.
    echo.
    echo      Then close this window and double-click start.bat again.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PY% --version 2^>^&1') do set "PYVER=%%V"
echo        Found !PYVER!

REM ---------------------------------------------------------------- venv
echo  [2/5] Setting up an isolated environment...

if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if !errorlevel! neq 0 (
        echo.
        echo  [X] Could not create the environment.
        echo      Try running this from a folder inside your user account,
        echo      for example C:\Users\YourName\Business-World-Roadmaps
        echo.
        pause
        exit /b 1
    )
)

set "VPY=.venv\Scripts\python.exe"

"%VPY%" -m pip install --quiet --upgrade pip >nul 2>&1
"%VPY%" -m pip install --quiet -r requirements.txt
if !errorlevel! neq 0 (
    echo.
    echo  [X] Could not install the dependencies.
    echo      This is usually no internet, or a firewall blocking pip.
    echo.
    pause
    exit /b 1
)
echo        Ready

REM ---------------------------------------------------------------- tests
echo  [3/5] Checking everything works...

"%VPY%" -m unittest discover -s tests >"%TEMP%\answerrank-tests.log" 2>&1
if !errorlevel! neq 0 (
    echo.
    echo  [X] The self-check failed. Last few lines:
    echo.
    powershell -NoProfile -Command "Get-Content '%TEMP%\answerrank-tests.log' -Tail 15" 2>nul
    echo.
    echo      Full log: %TEMP%\answerrank-tests.log
    echo.
    pause
    exit /b 1
)
echo        All tests passed

REM ---------------------------------------------------------------- config
if not exist "answerrank.yml" (
    echo  [4/5] First run - let's set up your business.
    echo.
    echo        Six questions. Nothing here costs money.
    echo        Press Enter to accept anything in [brackets].
    echo.
    "%VPY%" run.py setup
    if !errorlevel! neq 0 (
        echo.
        echo  [X] Setup did not finish. Double-click start.bat to try again.
        echo.
        pause
        exit /b 1
    )
) else (
    echo  [4/5] Configuration found
)

if not exist "budget.yml" "%VPY%" run.py budget-init >nul 2>&1

REM ---------------------------------------------------------------- go
echo  [5/5] Checking what still needs doing...
echo.
"%VPY%" run.py doctor
echo.

"%VPY%" run.py schedule --out schedule\answerrank-schedule.ics >nul 2>&1

echo  ================================================================
echo    STARTING - leave this window open
echo  ================================================================
echo.
echo    DASHBOARD  http://localhost:8000/dashboard  (everything, on one page)
echo    CONSOLE    http://localhost:8000/app        (approve and send, phone-sized)
echo    OPS        http://localhost:8000/ops        (live agent panel)
echo.
echo    The link for your phone is printed below.
echo    Close this window (or press Ctrl+C) to stop.
echo.

start "" "http://localhost:8000/dashboard"

"%VPY%" run.py web --port 8000

echo.
echo  Server stopped.
pause
