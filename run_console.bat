@echo off
REM Approve console for content-factory drafts. Opens at http://127.0.0.1:5055
REM Approves/publishes ONLY on your click. Stop with Ctrl+C.
REM Machine-local overrides (e.g. CF_VAULT) live in local.bat (gitignored, optional).
if exist "%~dp0local.bat" call "%~dp0local.bat"
python "%~dp0approve_console.py"
