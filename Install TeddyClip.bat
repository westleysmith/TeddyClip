@echo off
rem Double-click to install or update TeddyClip.
rem Works inside the TeddyClip folder, or on its own (it downloads TeddyClip).
cd /d "%~dp0"
if exist "%~dp0install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = 'Tls12'; $f = Join-Path $env:TEMP 'teddyclip-install.ps1'; Invoke-WebRequest 'https://raw.githubusercontent.com/westleysmith/TeddyClip/main/install.ps1' -OutFile $f -UseBasicParsing; & $f %*"
)
pause
