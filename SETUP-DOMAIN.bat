@echo off
setlocal enabledelayedexpansion
title AnswerRank - Domain Setup

REM  Double-click this after buying a domain.
REM
REM  It is a separate file from start.bat on purpose. Domain setup is not a
REM  one-shot: DNS takes minutes to hours to appear, so this is something you
REM  run, go and add a record, and run again. Burying it inside the launcher
REM  would mean restarting the whole server every time you wanted to re-check.

cd /d "%~dp0"

echo.
echo  ================================================================
echo    ANSWERRANK - SENDING DOMAIN SETUP
echo  ================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo  [X] Setup has not been run yet.
    echo.
    echo      Double-click start.bat first and let it finish, then come
    echo      back to this file.
    echo.
    pause
    exit /b 1
)

set "VPY=.venv\Scripts\python.exe"

REM ---------------------------------------------------------------- domain
set "DOMAIN="
if not "%~1"=="" set "DOMAIN=%~1"

if not defined DOMAIN (
    echo    Type the domain you bought and press Enter.
    echo    Just the domain - no https, no www.
    echo.
    echo    Example:  getanswerrank.com
    echo.
    set /p "DOMAIN=    Domain: "
)

if not defined DOMAIN (
    echo.
    echo  [X] No domain entered. Nothing was changed.
    echo.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------- provider
set "PROVIDER="
if not "%~2"=="" set "PROVIDER=%~2"

if not defined PROVIDER (
    echo.
    echo    Where is your email mailbox?
    echo.
    echo      1  Google Workspace     (about $7/month - recommended)
    echo      2  Zoho Mail            (about $1/month)
    echo      3  Microsoft 365        (about $6/month)
    echo      4  Fastmail             (about $5/month)
    echo      5  Not set up yet / something else
    echo.
    set /p "CHOICE=    Choose 1-5 [1]: "
    if "!CHOICE!"=="" set "CHOICE=1"
    if "!CHOICE!"=="1" set "PROVIDER=google"
    if "!CHOICE!"=="2" set "PROVIDER=zoho"
    if "!CHOICE!"=="3" set "PROVIDER=microsoft"
    if "!CHOICE!"=="4" set "PROVIDER=fastmail"
    if "!CHOICE!"=="5" set "PROVIDER="
)

echo.
echo  ----------------------------------------------------------------
echo.

if defined PROVIDER (
    "%VPY%" run.py domain "!DOMAIN!" --provider "!PROVIDER!"
) else (
    "%VPY%" run.py domain "!DOMAIN!"
)
set "RESULT=!errorlevel!"

echo.
echo  ================================================================
if "!RESULT!"=="0" (
    echo    DOMAIN IS READY
    echo  ================================================================
    echo.
    echo    Next: double-click start.bat and read the doctor output.
) else (
    echo    NOT FINISHED YET
    echo  ================================================================
    echo.
    echo    Add the records shown above at your registrar, wait a few
    echo    minutes, then double-click this file again. It is safe to
    echo    run as many times as you need.
)
echo.
pause
