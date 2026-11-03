@echo off
rem Process every finished recording in the inbox.
cd /d "%~dp0"
"%~dp0.venv\Scripts\teddyclip.exe"
pause
