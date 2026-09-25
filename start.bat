@echo off
setlocal enabledelayedexpansion
title AnswerRank

REM  The one button for everything. The first run puts an "AnswerRank" button
REM  on the desktop that opens this; after that, the folder never needs opening.
REM
REM  Deliberately a .bat and not a .ps1: PowerShell blocks unsigned scripts by
REM  default, so a .ps1 fails on a clean machine with a confusing error. A .bat
REM  always runs. It also pauses on every exit path, so the window never
REM  vanishes before you can read what went wrong.

cd /d "%~dp0"
REM  No __pycache__ folders appearing all over the place.
set "PYTHONDONTWRITEBYTECODE=1"

echo.
echo  ================================================================
echo    ANSWERRANK
echo  ================================================================
echo.

REM ---------------------------------------------------------------- update
REM  cmd reads a .bat file a line at a time, so updating this very file while
REM  it runs would make it read the new file from the old position. The whole
REM  update is one bracketed block (parsed before it runs), and if anything
REM  changed it hands over to the new copy rather than carrying on.
git rev-parse --is-inside-work-tree >nul 2>&1
if !errorlevel! equ 0 (
    echo  Checking for updates...
    for /f %%H in ('git rev-parse HEAD 2^>nul') do set "BEFORE=%%H"
    git stash push --quiet --include-untracked -m "start.bat autostash" >nul 2>&1
    set "STASHED=!errorlevel!"
    git pull --quiet --ff-only >nul 2>&1
    set "PULLED=!errorlevel!"
    if "!STASHED!"=="0" git stash pop --quiet >nul 2>&1
    for /f %%H in ('git rev-parse HEAD 2^>nul') do set "AFTER=%%H"
    if not "!PULLED!"=="0" echo    Could not update - carrying on with what you have
    if not "!BEFORE!"=="!AFTER!" (
        echo    Updated. Restarting with the new version...
        "%~f0" %*
    )
)

REM ---------------------------------------------------------------- python
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
    echo      Then close this window and open AnswerRank again.
    echo.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------- venv
if not exist ".venv\Scripts\python.exe" (
    echo  First run: setting up. This takes a few minutes, once.
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

REM  Install only when the list of requirements has changed.
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if !errorlevel! neq 0 (
    echo  Installing what it needs...
    "%VPY%" -m pip install --quiet --upgrade pip >nul 2>&1
    "%VPY%" -m pip install --quiet -r requirements.txt
    if !errorlevel! neq 0 (
        echo.
        echo  [X] Could not install what it needs.
        echo      This is usually no internet, or a firewall blocking pip.
        echo.
        pause
        exit /b 1
    )
    copy /y requirements.txt .venv\requirements.installed >nul
)

REM ---------------------------------------------------------------- self-check
REM  Once per version, not every time: the full check takes minutes, and a
REM  start button that makes you wait minutes is one you stop pressing.
set "VERSION=first-run"
for /f %%H in ('git rev-parse HEAD 2^>nul') do set "VERSION=%%H"
set "CHECKED="
if exist ".venv\checked.txt" set /p CHECKED=<.venv\checked.txt
if not "!CHECKED!"=="!VERSION!" (
    echo  Checking everything works...
    set "ANSWERRANK_QUICK=1"
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
    set "ANSWERRANK_QUICK="
    >.venv\checked.txt echo !VERSION!
)

REM ---------------------------------------------------------------- first run
if not exist "answerrank.yml" (
    echo.
    echo  Let's set up your business. Six questions; nothing here costs money.
    echo  Press Enter to accept anything in [brackets].
    echo.
    "%VPY%" run.py setup
    if !errorlevel! neq 0 (
        echo.
        echo  [X] Setup did not finish. Open AnswerRank again to try again.
        echo.
        pause
        exit /b 1
    )
)
if not exist "budget.yml" "%VPY%" run.py budget-init >nul 2>&1

REM ---------------------------------------------------------------- tidy
REM  Hide the machinery so the folder shows only what a person needs: this
REM  file, the guides, and your own settings. Hidden files still work.
for %%F in (.venv .claude .gitattributes .gitignore .env.example __pycache__ tests answerrank web deploy data schedule run.py requirements.txt LICENSE Dockerfile docker-compose.yml start.sh setup-domain.sh) do (
    if exist "%%F" attrib +h "%%F" >nul 2>&1
)

REM  The desktop button. Made once; delete it and it comes back next time.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $l=Join-Path $d 'AnswerRank.lnk'; if (Test-Path $l) { exit 0 }; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($l); $s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0'; $s.Description='AnswerRank: everything in one menu'; $s.IconLocation='%~dp0deploy\answerrank.ico'; $s.Save(); exit 10" >nul 2>&1
if !errorlevel! equ 10 (
    echo.
    echo  An AnswerRank button is now on your desktop. Use it from now on.
)

REM ---------------------------------------------------------------- menu
:menu
echo.
echo  ================================================================
echo    What would you like to do?
echo  ================================================================
echo.
echo    1  Open AnswerRank                  (or just press Enter)
echo    2  Keys and settings
echo    3  Email domain: set up and check
echo    4  What still needs doing
echo    5  Make the server setup file
echo    6  Practice run - nothing real is sent
echo    7  Close
echo.
set "CHOICE="
set /p "CHOICE=   Type a number and press Enter: "
if not defined CHOICE set "CHOICE=1"
if "!CHOICE!"=="1" goto open
if "!CHOICE!"=="2" goto keys
if "!CHOICE!"=="3" goto domain
if "!CHOICE!"=="4" goto doctor
if "!CHOICE!"=="5" goto server
if "!CHOICE!"=="6" goto practice
if "!CHOICE!"=="7" exit /b 0
echo.
echo    That isn't one of the numbers.
goto menu

:open
echo.
"%VPY%" run.py open
if !errorlevel! equ 3 (
    echo.
    pause
    goto menu
)
"%VPY%" run.py schedule --out data\answerrank-schedule.ics >nul 2>&1
echo  ================================================================
echo    RUNNING - leave this window open while you work
echo  ================================================================
echo.
echo    The dashboard opens in your browser. The link for your phone
echo    is printed below. Close this window to stop.
echo.
start "" "http://localhost:8000/dashboard"
"%VPY%" run.py web --port 8000
echo.
echo  Stopped.
pause
goto menu

:keys
echo.
"%VPY%" run.py keys
echo.
pause
goto menu

:domain
echo.
echo    Press Enter to check the domain you send from, or type another.
set "DOMAIN="
set /p "DOMAIN=    Domain: "
echo.
echo    Where is your mailbox?
echo      1  Google Workspace     (recommended)
echo      2  Zoho Mail
echo      3  Microsoft 365
echo      4  Fastmail
echo      5  Not set up yet / something else
set "PCHOICE="
set /p "PCHOICE=    Choose 1-5 [1]: "
set "PROVIDER=google"
if "!PCHOICE!"=="2" set "PROVIDER=zoho"
if "!PCHOICE!"=="3" set "PROVIDER=microsoft"
if "!PCHOICE!"=="4" set "PROVIDER=fastmail"
if "!PCHOICE!"=="5" set "PROVIDER="
echo.
if defined PROVIDER (
    "%VPY%" run.py domain "!DOMAIN!" --provider "!PROVIDER!"
) else (
    "%VPY%" run.py domain "!DOMAIN!"
)
if !errorlevel! equ 0 (
    echo.
    echo    DOMAIN IS READY.
) else (
    echo.
    echo    NOT FINISHED YET. Add the records shown above at your registrar,
    echo    wait a few minutes, and choose this again. Safe to repeat.
)
echo.
pause
goto menu

:doctor
echo.
"%VPY%" run.py doctor
echo.
pause
goto menu

:server
echo.
echo    Press Enter to use the domain you send from, or type another.
set "DOMAIN="
set /p "DOMAIN=    Domain: "
echo.
if defined DOMAIN (
    "%VPY%" run.py server-script --domain "!DOMAIN!"
) else (
    "%VPY%" run.py server-script
)
set "SETUPFILE="
for %%F in (server-setup-*.sh) do set "SETUPFILE=%%F"
if defined SETUPFILE (
    echo.
    echo    Opening it in Notepad. Press Ctrl+A then Ctrl+C to copy it all,
    echo    and paste it into the server's User data box.
    start "" notepad "!SETUPFILE!"
)
echo.
pause
goto menu

:practice
echo.
"%VPY%" run.py simulate
if !errorlevel! equ 0 (
    echo.
    echo    Every made-up sale was handled end to end.
) else (
    echo.
    echo    Something above is marked with an X. That is the part to look at.
)
echo.
pause
goto menu
