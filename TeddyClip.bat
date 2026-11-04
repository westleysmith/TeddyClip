@echo off
rem Process every finished recording in 1 - Raw recordings.
cd /d "%~dp0"
"%~dp0.venv\Scripts\teddyclip.exe"
pause
