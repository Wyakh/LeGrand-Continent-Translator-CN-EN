@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if exist ".venv\Scripts\python.exe" goto local_python
where py >nul 2>&1
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto python_launcher

:try_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto plain_python

:missing_python
echo Compatible Python not found. Install Python 3.10+ from https://www.python.org/downloads/
echo Enable the Python launcher or Add Python to PATH during installation.
set "RESULT=1"
goto finish

:local_python
".venv\Scripts\python.exe" "launch_news_translation.py" %*
set "RESULT=%ERRORLEVEL%"
goto finish

:python_launcher
py -3 "launch_news_translation.py" %*
set "RESULT=%ERRORLEVEL%"
goto finish

:plain_python
python "launch_news_translation.py" %*
set "RESULT=%ERRORLEVEL%"

:finish
popd
pause
exit /b %RESULT%
