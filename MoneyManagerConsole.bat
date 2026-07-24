@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Portable diagnostic launcher. This file may be renamed or copied outside
rem the repository. The remembered path remains in LocalAppData.
set "BATCH_DIR=%~dp0"
set "PROJECT_DIR="
set "PY_CMD="

call :find_python
if not defined PY_CMD exit /b 1
call :find_project_dir
if not defined PROJECT_DIR call :ask_project_dir
if not defined PROJECT_DIR exit /b 1

pushd "%PROJECT_DIR%" >nul 2>nul
%PY_CMD% "%PROJECT_DIR%\launcher.py" --console --project-dir "%PROJECT_DIR%" %*
set "RUN_EXIT=%errorlevel%"
popd >nul 2>nul

if not "%RUN_EXIT%"=="0" (
    echo.
    echo Money Manager did not start correctly. Exit code: %RUN_EXIT%
    echo Launcher bootstrap log:
    echo   %%LOCALAPPDATA%%\MoneyManagerLauncher\launcher_bootstrap.log
    echo Server log:
    echo   MoneyManagerData\logs\launcher_latest.log
    echo.
    pause
)
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
echo Python 3 was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo Enable the Python launcher or Add python.exe to PATH, then retry.
pause
exit /b 1

:find_project_dir
if defined MONEY_MANAGER_PROJECT_DIR (
    call :try_project_dir "%MONEY_MANAGER_PROJECT_DIR%"
    if defined PROJECT_DIR exit /b 0
)
call :try_project_dir "%BATCH_DIR%."
if defined PROJECT_DIR exit /b 0
call :try_project_dir "%CD%"
if defined PROJECT_DIR exit /b 0
call :search_up_from "%BATCH_DIR%."
if defined PROJECT_DIR exit /b 0
call :search_up_from "%CD%"
if defined PROJECT_DIR exit /b 0
call :load_config_project_dir
if defined CONFIG_PROJECT_DIR call :try_project_dir "%CONFIG_PROJECT_DIR%"
exit /b 0

:load_config_project_dir
set "CONFIG_PROJECT_DIR="
for /f "usebackq delims=" %%I in (`%PY_CMD% -c "import json, os, pathlib; base=os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(pathlib.Path.home()); p=pathlib.Path(base)/'MoneyManagerLauncher'/'config.json'; print(json.loads(p.read_text(encoding='utf-8')).get('project_dir','') if p.exists() else '')" 2^>nul`) do set "CONFIG_PROJECT_DIR=%%I"
exit /b 0

:save_project_dir
%PY_CMD% -c "import json, os, pathlib, sys; base=os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(pathlib.Path.home()); p=pathlib.Path(base)/'MoneyManagerLauncher'/'config.json'; p.parent.mkdir(parents=True, exist_ok=True); data=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; data['project_dir']=sys.argv[1]; p.write_text(json.dumps(data, indent=2), encoding='utf-8')" "%~f1" >nul 2>nul
exit /b 0

:try_project_dir
set "CANDIDATE=%~f1"
if exist "%CANDIDATE%\launcher.py" if exist "%CANDIDATE%\run_money_manager.py" if exist "%CANDIDATE%\requirements.txt" if exist "%CANDIDATE%\money_manager\app.py" (
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
echo Type the folder containing launcher.py, run_money_manager.py,
echo requirements.txt, and money_manager\app.py.
echo.
:ask_loop
set "USER_PROJECT_DIR="
set /p "USER_PROJECT_DIR=Project folder path: "
if not defined USER_PROJECT_DIR goto ask_loop
set "USER_PROJECT_DIR=%USER_PROJECT_DIR:"=%"
call :try_project_dir "%USER_PROJECT_DIR%"
if defined PROJECT_DIR exit /b 0
echo That folder is not a valid Money Manager repository.
goto ask_loop
