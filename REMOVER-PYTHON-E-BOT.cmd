@echo off
setlocal
cd /d "%TEMP%"
echo Removes registered Python versions and D:\Armazenamento do Bot.
echo Close INICIAR-PC and other programs using Python first.
set "REMOVAL_SCRIPT_PATH=%~dp0remove_python_windows.ps1"
if not exist "%REMOVAL_SCRIPT_PATH%" set "REMOVAL_SCRIPT_PATH=%~dp0scripts\remove_python_windows.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REMOVAL_SCRIPT_PATH%" -RemoveBotFiles
echo.
echo Review the result above. This window can now be closed.
pause
