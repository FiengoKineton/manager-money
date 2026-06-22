@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Portable bootstrap for Money Manager. This file may be renamed or copied
rem elsewhere, including the Desktop. It stores the remembered project path in
rem the user's AppData folder, not next to this .bat file.

set "BATCH_DIR=%~dp0"
set "PROJECT_DIR="
set "LAUNCHER_PY="
set "PY_CMD="
set "OLD_PATH_CACHE=%BATCH_DIR%.money_manager_project_path.txt"

call :find_python
if not defined PY_CMD exit /b 1

call :find_project_dir
if not defined PROJECT_DIR call :ask_project_dir
if not defined PROJECT_DIR exit /b 1

set "LAUNCHER_PY=%PROJECT_DIR%\launcher.py"

if /I "%~1"=="--foreground" goto run_foreground
if /I "%~1"=="--debug" goto run_foreground

start "Money Manager Launcher" /D "%PROJECT_DIR%" /min %PY_CMD% "%LAUNCHER_PY%" --project-dir "%PROJECT_DIR%" %*
exit /b 0

:run_foreground
pushd "%PROJECT_DIR%" >nul 2>nul
%PY_CMD% "%LAUNCHER_PY%" --project-dir "%PROJECT_DIR%" %*
set "RUN_EXIT=%errorlevel%"
popd >nul 2>nul
exit /b %RUN_EXIT%

:find_python
py -3 -c "import sys" >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
    exit /b 0
)

python -c "import sys" >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=python"
    exit /b 0
)

call :python_missing
exit /b 0

:python_missing
echo Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo During installation, enable "Add python.exe to PATH".
echo Then run launcher.bat again.
pause
exit /b 0

:find_project_dir
rem 1. Explicit environment variable, useful for advanced users or managed PCs.
if defined MONEY_MANAGER_PROJECT_DIR (
    call :try_project_dir "%MONEY_MANAGER_PROJECT_DIR%"
    if defined PROJECT_DIR exit /b 0
)

rem 2. User-level config in AppData. This avoids creating visible helper files
rem next to copied Desktop launchers.
call :load_config_project_dir
if defined CONFIG_PROJECT_DIR (
    call :try_project_dir "%CONFIG_PROJECT_DIR%"
    if defined PROJECT_DIR exit /b 0
)

rem 3. Migrate the old Desktop/local text cache if it exists. A valid old cache
rem is moved into AppData and then removed from next to the .bat.
if exist "%OLD_PATH_CACHE%" (
    set /p OLD_CACHED_PROJECT_DIR=<"%OLD_PATH_CACHE%"
    call :try_project_dir "%OLD_CACHED_PROJECT_DIR%"
    if defined PROJECT_DIR (
        del "%OLD_PATH_CACHE%" >nul 2>nul
        exit /b 0
    )
)

rem 4. Normal case: .bat is inside the repo.
call :try_project_dir "%BATCH_DIR%."
if defined PROJECT_DIR exit /b 0

rem 5. User launched it from a terminal already inside the repo.
call :try_project_dir "%CD%"
if defined PROJECT_DIR exit /b 0

rem 6. Search upward from the .bat folder and from the current folder.
call :search_up_from "%BATCH_DIR%."
if defined PROJECT_DIR exit /b 0
call :search_up_from "%CD%"
exit /b 0

:load_config_project_dir
set "CONFIG_PROJECT_DIR="
for /f "usebackq delims=" %%I in (`%PY_CMD% -c "import json, os, pathlib; base=os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(pathlib.Path.home()); p=pathlib.Path(base) / 'MoneyManagerLauncher' / 'config.json'; print(json.loads(p.read_text(encoding='utf-8')).get('project_dir', '') if p.exists() else '')" 2^>nul`) do set "CONFIG_PROJECT_DIR=%%I"
exit /b 0

:save_project_dir
%PY_CMD% -c "import json, os, pathlib, sys; base=os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(pathlib.Path.home()); p=pathlib.Path(base) / 'MoneyManagerLauncher' / 'config.json'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({'project_dir': sys.argv[1]}, indent=2), encoding='utf-8')" "%~f1" >nul 2>nul
exit /b 0

:try_project_dir
set "CANDIDATE=%~f1"
if exist "%CANDIDATE%\launcher.py" if exist "%CANDIDATE%\money_manager\app.py" if exist "%CANDIDATE%\requirements.txt" if exist "%CANDIDATE%\run_money_manager.py" (
    set "PROJECT_DIR=%CANDIDATE%"
    call :save_project_dir "%CANDIDATE%"
)
exit /b 0

:search_up_from
set "SEARCH_DIR=%~f1"
:search_loop
call :try_project_dir "%SEARCH_DIR%"
if defined PROJECT_DIR exit /b 0
for %%I in ("%SEARCH_DIR%\..") do set "PARENT_DIR=%%~fI"
if /I "%PARENT_DIR%"=="%SEARCH_DIR%" exit /b 0
set "SEARCH_DIR=%PARENT_DIR%"
goto search_loop

:ask_project_dir
echo Money Manager project folder was not found automatically.
echo Type the full path to the folder containing:
echo   money_manager\app.py
echo   requirements.txt
echo   run_money_manager.py
echo.
echo The remembered path will be saved in:
echo   %%LOCALAPPDATA%%\MoneyManagerLauncher\config.json
echo.
:ask_loop
set "USER_PROJECT_DIR="
set /p "USER_PROJECT_DIR=Project folder path: "
if not defined USER_PROJECT_DIR goto ask_loop
set "USER_PROJECT_DIR=%USER_PROJECT_DIR:"=%"
call :try_project_dir "%USER_PROJECT_DIR%"
if defined PROJECT_DIR exit /b 0
echo.
echo That folder does not look like the Money Manager repo. Try again.
echo.
goto ask_loop
