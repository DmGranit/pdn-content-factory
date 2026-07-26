@echo off
REM Scheduled launcher for the content-factory orchestrator.
REM Headless `claude --agent content-factory` builds ONE draft INLINE into drafts/.
REM No publishing here - human gate = approve console (run_console.bat).
REM Machine-local overrides (e.g. CF_VAULT) live in local.bat (gitignored, optional).
if exist "%~dp0local.bat" call "%~dp0local.bat"
set CF_DRAFT_MODE=claude
python "%~dp0content_factory_run.py"
