@echo off
setlocal

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  where python >nul 2>nul
  if not %errorlevel%==0 (
    echo ERROR: Python was not found. Install Python 3.12+ or add it to PATH.
    exit /b 1
  )
  set "PY=python"
)

echo Processing JSON files from incoming\complete and incoming\partial...
%PY% -m scripts.ingest_inbox --consume
if errorlevel 1 (
  echo.
  echo Ingest failed. Check the error above and incoming\rejected for quarantined files.
  exit /b 1
)

echo.
echo Archive ingest and site rebuild complete.
echo To view the site, run:
echo   %PY% -m http.server 8000 -d site
echo Then open http://localhost:8000
endlocal
