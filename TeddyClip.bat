@echo off
rem Process every finished recording in 1 - Raw recordings and cut every suggested clip.
rem The console has no editor; the TeddyClip window lets you review suggestions first.
cd /d "%~dp0"
"%~dp0.venv\Scripts\teddyclip.exe" --cut-all
pause
