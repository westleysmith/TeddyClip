@echo off
rem Double-click to install or update TeddyClip. It opens the TeddyClip setup window.
rem Works inside the TeddyClip folder, or on its own (it downloads the installer).
cd /d "%~dp0"
if exist "%~dp0install.ps1" (
    start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0install.ps1" %*
) else (
    start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "try { [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; $f = Join-Path $env:TEMP 'teddyclip-install.ps1'; Invoke-WebRequest 'https://raw.githubusercontent.com/westleysmith/TeddyClip/main/install.ps1' -OutFile $f -UseBasicParsing -ErrorAction Stop; & $f %* } catch { Add-Type -AssemblyName System.Windows.Forms; [void][Windows.Forms.MessageBox]::Show('TeddyClip setup could not be downloaded. Check that the internet is working, then double-click Install TeddyClip again.', 'TeddyClip setup') }"
)
