@echo off
chcp 65001 >nul 2>nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
rem DocForge - run unit tests

set "PY=python"
where python >nul 2>nul
if not errorlevel 1 goto checkver
set "PY=py -3"
where py >nul 2>nul
if not errorlevel 1 goto checkver
goto nopython

:checkver
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython

%PY% tests\run_tests.py
set "CODE=%ERRORLEVEL%"
goto done

:nopython
echo [ERROR] Python not found. Install Python 3.9+ and add it to PATH.
set "CODE=1"

:done
echo.
if "%WORKFLOW_NO_PAUSE%"=="1" exit /b %CODE%
pause
exit /b %CODE%
