@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "SCRIPT=%~dp0scripts\deploy_claude_skills.py"
set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "DEPLOY_ARGS="
if /I "%~1"=="--no-pause" set "DEPLOY_ARGS=--action install"

if not exist "%SCRIPT%" goto :missing_script
if exist "%CODEX_PY%" goto :run_codex_python
where py >nul 2>nul
if not errorlevel 1 goto :run_py
where python >nul 2>nul
if not errorlevel 1 goto :run_python
goto :missing_python

:run_codex_python
"%CODEX_PY%" "%SCRIPT%" %DEPLOY_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
goto :result

:run_py
py -3 "%SCRIPT%" %DEPLOY_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
goto :result

:run_python
python "%SCRIPT%" %DEPLOY_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
goto :result

:missing_script
echo 未找到部署脚本：%SCRIPT%
set "EXIT_CODE=1"
goto :result

:missing_python
echo 未找到 Python 3，请先安装 Python。
set "EXIT_CODE=1"

:result
if "%EXIT_CODE%"=="0" goto :success
echo.
echo Claude/Codex/WorkBuddy Skill 操作失败。
goto :finish

:success
echo.
echo Claude/Codex/WorkBuddy Skill 操作完成。

:finish
if /I not "%~1"=="--no-pause" pause
exit /b %EXIT_CODE%
