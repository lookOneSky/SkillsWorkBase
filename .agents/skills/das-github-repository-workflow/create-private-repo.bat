@echo off
setlocal

python "%~dp0create_private_repo.py" %*
exit /b %errorlevel%
