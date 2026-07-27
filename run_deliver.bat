@echo off
REM Delivery runner: publishes APPROVED posts when their slot is due. Run hourly.
REM The script itself decides if a slot arrived, so a post still goes out after downtime.
python "%~dp0deliver.py"
