@echo off
setlocal

where py >nul 2>nul
if errorlevel 1 goto use_python
set "PY=py"
goto have_python

:use_python
where python >nul 2>nul
if errorlevel 1 goto no_python
set "PY=python"
goto have_python

:no_python
echo ERROR: Python was not found. Install Python 3.12+ or add it to PATH.
exit /b 1

:have_python
echo Processing JSON files from incoming\complete and incoming\partial...
%PY% -m scripts.ingest_inbox --consume
if errorlevel 1 goto ingest_failed

echo.
echo Archive ingest and site rebuild complete.
echo To view the site, run:
echo   %PY% -m http.server 8000 -d site
echo Then open http://localhost:8000
exit /b 0

:ingest_failed
echo.
echo Ingest failed. Check the error above and incoming\rejected for quarantined files.
exit /b 1
