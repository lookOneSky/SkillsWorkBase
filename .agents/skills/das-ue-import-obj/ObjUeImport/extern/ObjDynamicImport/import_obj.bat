@echo off
setlocal

if "%~1"=="" (
    echo Usage: %~nx0 "D:\path\model.obj_or_directory" ["D:\path\import_obj.json"]
    exit /b 2
)

set "SCRIPT_DIR=%~dp0"
set "LAUNCHER=%SCRIPT_DIR%launch_import_obj.py"
set "CONFIG=%SCRIPT_DIR%import_obj.json"
if not "%~2"=="" set "CONFIG=%~f2"

set "PYTHON_COMMAND="
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_COMMAND=python"
)

if not defined PYTHON_COMMAND (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_COMMAND=py -3"
    )
)

if not defined PYTHON_COMMAND (
    echo [Error] Python 3 was not found in PATH.
    exit /b 3
)

%PYTHON_COMMAND% "%LAUNCHER%" "%~f1" --config "%CONFIG%"

exit /b %errorlevel%
