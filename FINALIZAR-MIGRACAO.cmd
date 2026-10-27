@echo off
setlocal
cd /d "%~dp0"
echo Run this ONLY after /ask works with the PC worker connected.
echo This removes the OLD hosted Q^&A database and backup, after receipt verification.
echo Your PC archive and the rest of the hosted bot are preserved.
"D:\Armazenamento do Bot\.pc-venv\Scripts\python.exe" "%~dp0knowledge_pc.py" --directory "D:\Armazenamento do Bot" --finalize-host
pause
