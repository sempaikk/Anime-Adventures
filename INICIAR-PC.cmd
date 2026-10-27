@echo off
setlocal
cd /d "%~dp0"
"D:\Armazenamento do Bot\.pc-venv\Scripts\python.exe" "%~dp0knowledge_pc.py" --directory "D:\Armazenamento do Bot"
pause
