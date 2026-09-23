@echo off
setlocal enabledelayedexpansion
title AnswerRank - Sales Simulation

REM  Double-click to run 30 made-up sales through the real agents.
REM
REM  Nothing real is touched: no email is sent, no AI service is called, and
REM  your own database is never opened. It builds a throwaway copy of the
REM  business, invents the customers and their replies, runs about a hundred
REM  days of selling, and prints what the software got right and wrong.

cd /d "%~dp0"

echo.
echo  ================================================================
echo    ANSWERRANK - SALES SIMULATION
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

".venv\Scripts\python.exe" run.py simulate %*
if !errorlevel! equ 0 (
    echo.
    echo  [OK] Every sale was handled end to end.
) else (
    echo.
    echo  [!] Something above was marked with an X. That is the part to look at.
)
echo.
pause
