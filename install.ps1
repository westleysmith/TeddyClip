# TeddyClip installer. Run it through "Install TeddyClip.bat".
# Installs Python 3.12, FFmpeg and Ollama with winget, sets up TeddyClip,
# downloads the AI models and puts shortcuts on the desktop.
# Safe to run again: it updates TeddyClip and keeps config.yaml.
param(
    [string]$InstallDir = "",
    [switch]$SkipPrograms,   # do not install Python, FFmpeg or Ollama (for testing)
    [switch]$SkipModels,     # do not download the AI models (for testing)
    [switch]$SkipShortcuts,  # do not add desktop shortcuts (for testing)
    [string[]]$Names = @(),  # the two names for clip titles, skips the question
    [string]$DataDir = ""    # where recordings and clips go, skips the question
)

# Native programs report failure through exit codes, which every step checks;
# 'Stop' would turn harmless warnings they print into fatal errors.
$ErrorActionPreference = 'Continue'
$Repo = 'westleysmith/TeddyClip'
$WhisperTag = 'whisper-vulkan-v1.9.5'  # the release .github/workflows/whisper-vulkan.yml made
# Windows PowerShell's download progress bar makes large downloads many times slower.
$ProgressPreference = 'SilentlyContinue'

function Say($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Fail($text) {
    Write-Host ""
    Write-Host "Something went wrong: $text" -ForegroundColor Red
    Write-Host "Send a screenshot of this window to whoever set TeddyClip up for you." -ForegroundColor Yellow
    exit 1
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Write-Utf8($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }
function Has-Command($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Install-Program($id, $label, [string[]]$extra = @()) {
    $listed = winget list --id $id --exact --accept-source-agreements 2>$null | Out-String
    if ($listed -match [regex]::Escape($id)) { Write-Host "$label is already installed."; return }
    Write-Host "Installing $label (this can take a few minutes)..."
    winget install --id $id --exact --silent --accept-source-agreements --accept-package-agreements @extra
    if ($LASTEXITCODE -ne 0) { Fail "could not install $label (winget exit code $LASTEXITCODE)." }
    Refresh-Path
}

function Find-Python312 {
    if (Has-Command 'py') {
        $exe = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    }
    $guess = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path $guess) { return $guess }
    return $null
}

function Free-GB($path) {
    try { return [math]::Round(([IO.DriveInfo]::new([IO.Path]::GetPathRoot($path))).AvailableFreeSpace / 1GB) }
    catch { return '?' }
}

# A plain Windows dialog: keep the suggested place, or pick another one (a
# bigger drive, say). A folder named TeddyClip is made inside the one picked.
function Choose-DataFolder($suggested) {
    Add-Type -AssemblyName System.Windows.Forms
    $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false }
    $text = "TeddyClip keeps your recordings, clips, highlight videos and its AI models in one folder:`n`n" +
            "      $suggested`n`n$(Free-GB $suggested) GB is free on that drive. Recordings take a few GB per hour of play.`n`n" +
            "Keep it there?  Choose No to pick another place, for example a bigger drive."
    $answer = [System.Windows.Forms.MessageBox]::Show($owner, $text, 'TeddyClip: where should your clips go?', 'YesNo', 'Question')
    if ($answer -ne 'No') { return $suggested }
    $pick = New-Object System.Windows.Forms.FolderBrowserDialog
    $pick.Description = 'Pick where TeddyClip should keep everything. A folder named TeddyClip is made inside the one you pick.'
    $pick.ShowNewFolderButton = $true
    if ($pick.ShowDialog($owner) -ne 'OK' -or -not $pick.SelectedPath) { return $suggested }
    if ((Split-Path $pick.SelectedPath -Leaf) -eq 'TeddyClip') { return $pick.SelectedPath }
    return (Join-Path $pick.SelectedPath 'TeddyClip')
}

function Find-Ollama {
    if (Has-Command 'ollama') { return (Get-Command ollama).Source }
    $guess = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $guess) { return $guess }
    return $null
}

Write-Host "TeddyClip installer" -ForegroundColor Green
Write-Host "This sets up everything TeddyClip needs. Leave this window open until it says it is done."

# 1. Programs
if (-not $SkipPrograms) {
    Say "Step 1 of 7: programs (Python, FFmpeg, Ollama)"
    if (-not (Has-Command 'winget')) {
        Fail "winget is missing. Open the Microsoft Store, install 'App Installer', then run this again."
    }
    if (-not (Find-Python312)) { Install-Program 'Python.Python.3.12' 'Python 3.12' @('--scope', 'user') }
    else { Write-Host "Python 3.12 is already installed." }
    Install-Program 'Gyan.FFmpeg' 'FFmpeg'
    # winget can still list Ollama after it was removed, so look for the
    # program itself; reinstall with winget, or Ollama's own installer.
    if (Find-Ollama) { Write-Host "Ollama is already installed." }
    else {
        Write-Host "Installing Ollama (this can take a few minutes)..."
        winget install --id Ollama.Ollama --exact --silent --force --accept-source-agreements --accept-package-agreements
        Refresh-Path
        if (-not (Find-Ollama)) {
            try {
                $setup = Join-Path $env:TEMP 'OllamaSetup.exe'
                Invoke-WebRequest 'https://ollama.com/download/OllamaSetup.exe' -OutFile $setup -UseBasicParsing -ErrorAction Stop
                Start-Process $setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
                Remove-Item $setup -Force -ErrorAction SilentlyContinue
                Refresh-Path
            } catch { Write-Host "Could not download Ollama ($($_.Exception.Message))." -ForegroundColor Yellow }
        }
        if (-not (Find-Ollama)) { Write-Host "Ollama could not be installed, so AI titles will be off. TeddyClip still works." -ForegroundColor Yellow }
    }
} else {
    Say "Step 1 of 7: skipped installing programs"
}
$Python = Find-Python312
if (-not $Python) { Fail "Python 3.12 was not found after installing it. Restart the PC and run this again." }

# 2. TeddyClip itself
Say "Step 2 of 7: TeddyClip files"
if (-not $InstallDir) {
    if (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml')) { $InstallDir = $PSScriptRoot }
    else { $InstallDir = Join-Path $env:LOCALAPPDATA 'TeddyClip-app' }
}
$fromRepo = (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml')) -and
            ((Resolve-Path $PSScriptRoot).Path -eq [IO.Path]::GetFullPath($InstallDir).TrimEnd('\'))
if ($fromRepo) {
    Write-Host "Using the TeddyClip files in $InstallDir"
} else {
    $zip = Join-Path $env:TEMP 'teddyclip-main.zip'
    $unpack = Join-Path $env:TEMP 'teddyclip-main'
    Write-Host "Downloading the latest TeddyClip..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing -ErrorAction Stop
    if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
    Expand-Archive $zip $unpack -ErrorAction Stop
    $src = Get-ChildItem $unpack -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force $InstallDir | Out-Null
    $config = Join-Path $InstallDir 'config.yaml'
    $saved = $null
    if (Test-Path $config) { $saved = Get-Content $config -Raw -Encoding UTF8 }
    Copy-Item (Join-Path $src.FullName '*') $InstallDir -Recurse -Force -ErrorAction Stop
    if ($saved) { Write-Utf8 $config $saved; Write-Host "Kept your settings in config.yaml." }
    Remove-Item $zip, $unpack -Recurse -Force
    Write-Host "TeddyClip is in $InstallDir"
}
Set-Location $InstallDir

# 3. Python packages
Say "Step 3 of 7: TeddyClip's Python packages (a few hundred MB, takes a while)"
$venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create the Python environment." }
}
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { Fail "could not install PyTorch." }
$nvidia = [bool](Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -match 'NVIDIA' })
if ($nvidia) {
    Write-Host "NVIDIA graphics card found: adding GPU support for faster transcription."
    & $venvPy -m pip install --quiet -e ".[gpu]"
} else {
    Write-Host "No NVIDIA graphics card found: transcription will run on your other graphics card through Vulkan (set up in step 5)."
    & $venvPy -m pip install --quiet -e .
}
if ($LASTEXITCODE -ne 0) { Fail "could not install TeddyClip's packages." }

# 4. Names for clip titles
Say "Step 4 of 7: your names"
$config = Join-Path $InstallDir 'config.yaml'
$text = Get-Content $config -Raw -Encoding UTF8
if ($text -match '(?m)^people: \[Teddy, Friend\]') {
    if ($Names.Count -lt 2) {
        Write-Host "TeddyClip uses your names in clip titles."
        $one = Read-Host "Your name (press Enter for Teddy)"
        $two = Read-Host "Your friend's name (press Enter for Friend)"
        $Names = @($one, $two)
    }
    $clean = @()
    foreach ($n in @($Names[0], $Names[1])) {
        $n = ($n -replace '[^\p{L}\p{N} ''.-]', '').Trim()
        $clean += $n
    }
    if (-not $clean[0]) { $clean[0] = 'Teddy' }
    if (-not $clean[1]) { $clean[1] = 'Friend' }
    $text = $text -replace '(?m)^people: \[Teddy, Friend\]', "people: [`"$($clean[0])`", `"$($clean[1])`"]"
    Write-Utf8 $config $text
    Write-Host "Saved: $($clean[0]) and $($clean[1])."
} else {
    Write-Host "Names are already set in config.yaml."
}

# 5. Where everything goes (before the models, which are kept there too)
Say "Step 5 of 7: where to keep your recordings and clips"
$text = Get-Content $config -Raw -Encoding UTF8
if ($text -match '(?m)^root:\s*C:\\Users\\\{user\}\\TeddyClip\s*$') {
    $suggested = Join-Path $env:USERPROFILE 'TeddyClip'
    if (-not $DataDir) { $DataDir = Choose-DataFolder $suggested }
    $DataDir = [IO.Path]::GetFullPath($DataDir).TrimEnd('\')
    if ($DataDir -ne $suggested) {
        $line = "root: '" + ($DataDir -replace "'", "''") + "'"
        $text = [regex]::Replace($text, '(?m)^root:.*$', { param($m) $line })
        Write-Utf8 $config $text
    }
    Write-Host "TeddyClip will keep everything in $DataDir"
} else {
    Write-Host "Keeping the folder already set in config.yaml."
}

# 6. AI models
if (-not $SkipModels) {
    Say "Step 6 of 7: AI models (a few GB on the first run)"
    $model = 'qwen3:4b'
    if ($text -match '(?m)^\s+model:\s*([^\s#]+)') { $model = $Matches[1] }
    $ollama = Find-Ollama
    if ($model -eq 'none') {
        Write-Host "AI titles are turned off in config.yaml, skipping Ollama."
    } elseif (-not $ollama) {
        Write-Host "Ollama was not found, so AI titles will be off until it is installed." -ForegroundColor Yellow
    } else {
        & $ollama list *> $null
        if ($LASTEXITCODE -ne 0) {
            Start-Process $ollama 'serve' -WindowStyle Hidden
            for ($i = 0; $i -lt 30; $i++) { Start-Sleep 1; & $ollama list *> $null; if ($LASTEXITCODE -eq 0) { break } }
        }
        Write-Host "Downloading the AI model $model..."
        & $ollama pull $model
        if ($LASTEXITCODE -ne 0) { Write-Host "Could not download $model. TeddyClip still works without AI titles." -ForegroundColor Yellow }
    }
    $whisper = 'small'
    if ($nvidia) { $whisper = 'large-v3-turbo' }
    Write-Host "Downloading the speech model ($whisper) and the laughter model..."
    $prefetch = @"
from teddyclip.config import load_config
from teddyclip.panns import ensure_assets
from faster_whisper.utils import download_model
cfg = load_config()
cfg.paths.ensure()
ensure_assets(cfg.paths.models)
download_model('$whisper')
"@
    & $venvPy -c $prefetch
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not download every model now. TeddyClip will try again on its first run." -ForegroundColor Yellow }

    if (-not $nvidia) {
        # No NVIDIA card: transcribe on whatever graphics card there is (AMD,
        # Intel...) with whisper.cpp through Vulkan, built by this repository.
        Write-Host "Setting up transcription on your graphics card (whisper.cpp with Vulkan)..."
        try {
            $engine = Join-Path $InstallDir 'engines\whisper-vulkan'
            $zip = Join-Path $env:TEMP 'whisper-vulkan-win-x64.zip'
            Invoke-WebRequest "https://github.com/$Repo/releases/download/$WhisperTag/whisper-vulkan-win-x64.zip" -OutFile $zip -UseBasicParsing -ErrorAction Stop
            if (Test-Path $engine) { Remove-Item $engine -Recurse -Force }
            New-Item -ItemType Directory -Force $engine | Out-Null
            Expand-Archive $zip $engine -Force -ErrorAction Stop
            Remove-Item $zip -Force
            $models = (& $venvPy -c "from teddyclip.config import load_config; print(load_config().paths.models)").Trim()
            $ggml = Join-Path $models 'ggml-large-v3-turbo-q5_0.bin'
            if (-not (Test-Path $ggml)) {
                Write-Host "Downloading its speech model (about 550 MB)..."
                Invoke-WebRequest 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin' -OutFile "$ggml.part" -UseBasicParsing -ErrorAction Stop
                Move-Item "$ggml.part" $ggml -Force
            }
            Write-Host "Graphics-card transcription is ready."
        } catch {
            Write-Host "Could not set up graphics-card transcription ($($_.Exception.Message)). TeddyClip will transcribe on the CPU, which is slower." -ForegroundColor Yellow
        }
    }
} else {
    Say "Step 6 of 7: skipped downloading models"
}

# 7. Shortcuts and a final check
Say "Step 7 of 7: folders and desktop shortcuts"
$root = (& $venvPy -c "from teddyclip.config import load_config; c = load_config(); c.paths.ensure(); print(c.root)").Trim()
$desktop = [Environment]::GetFolderPath('Desktop')
if ($SkipShortcuts) { $desktop = Join-Path $InstallDir 'shortcuts-test'; New-Item -ItemType Directory -Force $desktop | Out-Null }
$shell = New-Object -ComObject WScript.Shell
function Make-Shortcut($folder, $name, $target, $icon, $style = 1) {
    $lnk = $shell.CreateShortcut((Join-Path $folder "$name.lnk"))
    $lnk.TargetPath = $target
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation = $icon
    $lnk.WindowStyle = $style
    $lnk.Save()
}
# Shortcuts from earlier versions, now replaced by the TeddyClip page.
foreach ($old in 'TeddyClip - Make Clips', 'TeddyClip - Make Highlight') {
    Remove-Item (Join-Path $desktop "$old.lnk") -ErrorAction SilentlyContinue
}
$logo = Join-Path $InstallDir 'teddyclip\teddyclip.ico'
# The TeddyClip window: a windowless launcher, so no console appears.
$open = Join-Path $InstallDir '.venv\Scripts\teddyclip-app.exe'
Make-Shortcut $desktop 'TeddyClip' $open "$logo,0"
Make-Shortcut $desktop 'TeddyClip Folders' $root 'shell32.dll,3'
if (-not $SkipShortcuts) {
    # Start menu too, so TeddyClip shows up when you search for it.
    Make-Shortcut ([Environment]::GetFolderPath('Programs')) 'TeddyClip' $open "$logo,0"
}
Write-Host "Added TeddyClip to the desktop and the Start menu, plus a TeddyClip Folders shortcut."
Write-Host "To pin it, right-click the TeddyClip icon and choose Pin to taskbar or Pin to Start."

Say "Checking everything"
& (Join-Path $InstallDir '.venv\Scripts\teddyclip.exe') check

Write-Host ""
Write-Host "All done!" -ForegroundColor Green
Write-Host "Your recordings and clips live in: $root"
Write-Host "How to use it:"
Write-Host "  1. Double-click 'TeddyClip' on the desktop. It opens in its own window."
Write-Host "  2. Click 'Add recordings' and pick your OBS recordings and the game."
Write-Host "  3. Click 'Find clips' and let it run. It suggests the best moments."
Write-Host "  4. Click 'Review' on a suggestion, move its start and end, and click 'Create clip'."
Write-Host "Tip: say 'clip that' out loud while recording and that moment is always suggested."
