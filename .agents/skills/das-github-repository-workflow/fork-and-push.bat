@echo off
setlocal

python "%~dp0fork_and_push.py" %*
exit /b %errorlevel%
