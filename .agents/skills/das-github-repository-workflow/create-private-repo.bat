@echo off
setlocal

py -3 --version >nul 2>nul
if not errorlevel 1 goto use_py

python --version >nul 2>nul
if not errorlevel 1 goto use_python

python3 --version >nul 2>nul
if not errorlevel 1 goto use_python3

echo Error: Python 3 was not found in PATH.
exit /b 9009

:use_py
py -3 "%~dp0create_private_repo.py" %*
exit /b %errorlevel%

:use_python
python "%~dp0create_private_repo.py" %*
exit /b %errorlevel%

:use_python3
python3 "%~dp0create_private_repo.py" %*
exit /b %errorlevel%

