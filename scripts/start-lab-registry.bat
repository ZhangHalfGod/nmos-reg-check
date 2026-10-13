@echo off
setlocal EnableExtensions
REM Repo root is the parent of this script. The .ps1 resolves it again from %~dp0.. via $PSScriptRoot.
cd /d "%~dp0.."
if errorlevel 1 (
    echo Cannot open the repo root from "%~dp0.."
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-lab-registry.ps1" %*
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
    echo.
    echo Registry start failed with exit code %EXITCODE%.
    pause
    exit /b %EXITCODE%
)
REM Double-click keeps this window open so the probe result can be read.
echo %cmdcmdline% | findstr /I /C:"%~nx0" >nul
if not errorlevel 1 pause
exit /b 0
