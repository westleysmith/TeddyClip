@echo off
rem Join the clips left in a clip folder into a highlight video.
rem Drop the folder onto this file, or run it and drag the folder into the window.
cd /d "%~dp0"
set "FOLDER=%~1"
if not defined FOLDER set /p "FOLDER=Drag a clip folder from 2 - Clips into this window, then press Enter: "
if not defined FOLDER (
    echo No folder given.
    pause
    exit /b 1
)
set "FOLDER=%FOLDER:"=%"
"%~dp0.venv\Scripts\teddyclip.exe" highlight "%FOLDER%"
pause
