@echo off
REM Scheduled launcher: builds ONE draft into drafts/. Never publishes.
REM Settings (secrets, site repo) live in .env - read by Python, not by this file.
set CF_DRAFT_MODE=claude
python "%~dp0content_factory_run.py"
