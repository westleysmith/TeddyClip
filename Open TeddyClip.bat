@echo off
rem Open the TeddyClip page in your web browser.
rem Keep this window open while you use TeddyClip; close it when you are done.
cd /d "%~dp0"
"%~dp0.venv\Scripts\teddyclip.exe" ui
if errorlevel 1 pause
