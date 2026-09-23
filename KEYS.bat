@echo off
setlocal enabledelayedexpansion
title AnswerRank - Keys

REM  Double-click to save your mailbox password and API keys.
REM
REM  They go in keys.env, next to this file, and never leave this computer.
REM  It asks for each one in plain words, and tests the mailbox before saving.
REM  Run it again any time to add a key; press Enter to keep what is saved.

cd /d "%~dp0"

echo.
echo  ================================================================
echo    ANSWERRANK - KEYS
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

".venv\Scripts\python.exe" run.py keys
echo.
pause
