@echo off & cd /d "%~dp0" & python -m tools.run_native %* & if errorlevel 1 pause
