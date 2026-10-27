@echo off
setlocal
cd /d "%~dp0"
set "PC_KNOWLEDGE_DIR=D:\Armazenamento do Bot"
where py >nul 2>nul
if errorlevel 1 goto missing
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" >nul 2>nul
if errorlevel 1 goto missing
if not exist "%PC_KNOWLEDGE_DIR%" mkdir "%PC_KNOWLEDGE_DIR%"
if not exist "%PC_KNOWLEDGE_DIR%\.pc-venv\Scripts\python.exe" py -3.12 -m venv "%PC_KNOWLEDGE_DIR%\.pc-venv"
if errorlevel 1 goto failed
"%PC_KNOWLEDGE_DIR%\.pc-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements-pc.txt"
if errorlevel 1 goto failed
"%PC_KNOWLEDGE_DIR%\.pc-venv\Scripts\python.exe" "%~dp0knowledge_pc.py" --directory "%PC_KNOWLEDGE_DIR%" --setup
if errorlevel 1 goto failed
echo.
echo Read LEIA-ME-PC.md and the private HOSTING-SETUP file in your data folder.
echo Keep this extracted program folder; INICIAR-PC.cmd uses its files.
pause
exit /b 0
:missing
echo Install Python 3.12 for Windows from python.org, including the Python launcher.
echo Then run this file again. No administrator access is needed by the companion.
pause
exit /b 1
:failed
echo Setup could not finish. Existing data was preserved.
pause
exit /b 1
