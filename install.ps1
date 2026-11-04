# TeddyClip installer. Run it through "Install TeddyClip.bat", which opens the
# setup window. The window runs this script again, hidden, with -Worker: that
# installs Python 3.12, FFmpeg and Ollama with winget, sets up TeddyClip,
# downloads the AI models and puts shortcuts on the desktop.
# Safe to run again: it updates TeddyClip and keeps config.yaml.
# -Console does the same work in a console, without the window.
param(
    [string]$InstallDir = "",
    [switch]$SkipPrograms,   # do not install Python, FFmpeg or Ollama (for testing)
    [switch]$SkipModels,     # do not download the AI models (for testing)
    [switch]$SkipShortcuts,  # do not add desktop shortcuts (for testing)
    [string]$DataDir = "",   # where recordings and clips go (default: your user folder\TeddyClip)
    [string]$You = "",       # names for clip titles (the window asks for these)
    [string]$Friend = "",
    [switch]$Worker,         # do the work with no window (the setup window runs this)
    [switch]$Console,        # do the work in this console instead of the setup window
    [switch]$Demo            # with the window: a quick pretend run that changes nothing
)

# Native programs report failure through exit codes, which every step checks;
# 'Stop' would turn harmless warnings they print into fatal errors.
$ErrorActionPreference = 'Continue'
$Repo = 'westleysmith/TeddyClip'
$WhisperTag = 'whisper-vulkan-v1.9.5'  # the release .github/workflows/whisper-vulkan.yml made
# Windows PowerShell's download progress bar makes large downloads many times slower.
$ProgressPreference = 'SilentlyContinue'
# The setup window's pictures (scripts/make_installer_logo.py fills these in).
$LogoPng = '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'
$IconPng = 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAACEklEQVR42u1bMU7DQBD0ru4Z9EiIkjYp6KjyBn7AU/gBb0hFR5G0lAiJnn9AZSlYMbe3t3O7dm66WLZ3Zm737FtfhqGjo6Oj43JBJSd/PN78nDt++/JJHuQt+JA2yBzQZljzYctg2muQ985dwwghCBNQfBglwNIEJB8qDXZ1f/fn9/fbO3ROQPMhabBpoCn+C6w1oQWfJCGSCzaek3Nfms45wyz5pIizN5LLeP/RZLYYfc25Wljz4WFhkKR1CVJUYpJYFhnHSxNvHZeXKt4qPtcE8Baf4yHhx9qXlSjiNXxOtbLm5tHEn+Ml5UitX0K8Mc10jtLd8RA/WwJrNGFOE3u1tiKIh/QEJbh+fj17/Ovpoan4oq5wrRFzoudgYYYkizmieO01Gt4JWXu1IsbrEaUBXw5bjCDiXsUGLP3FSP1dADFiu802XBZw69TfbbZqIxAmuLXEaoxYhQEWZRHOAG2KlmSDdRmE6gp7lEXItnhLI1JEA/bHQ5wMaL0sthaf458ucdRhc4B20VIi3nphlKRphFgToEfdrB+wppSHG5BL0f3xoBaP6AsQauOC9RtbqXjp04sjbYJsWfvwOcAyXZEtMWqx50dbDhrhpVnK6BTTCmkhXp0Btf1CxIcR7fxEkbbEthZvMgl6Pxlq43MEEp5xKdK2dg/DaQj05waPTCPvLzPeJUbRPlWtfZtOR0dHLPwCM24tOQfsj4QAAAAASUVORK5CYII='

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
    Write-Host "Installing $label..."
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

# Ollama's installer opens Ollama's own window (which asks you to sign in) and
# makes it start with Windows. TeddyClip starts Ollama itself, hidden, when it
# needs it, so that window is closed and the startup entry removed.
function Quiet-Ollama {
    for ($i = 0; $i -lt 15; $i++) {
        $app = Get-Process 'ollama app' -ErrorAction SilentlyContinue
        if ($app) { Start-Sleep 1; $app | Stop-Process -Force -ErrorAction SilentlyContinue; break }
        Start-Sleep 1
    }
    Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Ollama.lnk') -ErrorAction SilentlyContinue
}

function Find-Ollama {
    if (Has-Command 'ollama') { return (Get-Command ollama).Source }
    foreach ($guess in (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'), (Join-Path $env:USERPROFILE 'Ollama\ollama.exe')) {
        if (Test-Path $guess) { return $guess }
    }
    return $null
}

Write-Host "TeddyClip installer" -ForegroundColor Green
Write-Host "This sets up everything TeddyClip needs. Leave this window open until it says it is done."

# ---------------------------------------------------------------------------
# The setup window. Double-clicking "Install TeddyClip.bat" lands here: a
# TeddyClip-themed window asks for the names, then runs this same script
# again, hidden, with -Worker, and turns its output into plain progress.
# ---------------------------------------------------------------------------
if (-not $Worker -and -not $Console) {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    Add-Type -Namespace TeddyClipSetup -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
    [void][TeddyClipSetup.Dpi]::SetProcessDPIAware()
    [Windows.Forms.Application]::EnableVisualStyles()

    $Paper = [Drawing.ColorTranslator]::FromHtml('#f3ead8'); $Cream = [Drawing.ColorTranslator]::FromHtml('#fff9ee')
    $Line = [Drawing.ColorTranslator]::FromHtml('#d8c7a8');  $Walnut = [Drawing.ColorTranslator]::FromHtml('#4a2e1f')
    $Muted = [Drawing.ColorTranslator]::FromHtml('#7d6a58'); $Orange = [Drawing.ColorTranslator]::FromHtml('#d4612a')
    $Stripes = '#d4612a', '#d9a227', '#2b7a74', '#6f7d2c' | ForEach-Object { [Drawing.ColorTranslator]::FromHtml($_) }
    function Font($size, $style = 'Regular', $family = 'Segoe UI') { New-Object Drawing.Font($family, $size, [Drawing.FontStyle]$style) }
    function Image64($b64) { if ($b64) { [Drawing.Image]::FromStream((New-Object IO.MemoryStream (, [Convert]::FromBase64String($b64)))) } }

    # Everything the handlers change lives in $S, so they all see the same values.
    $S = @{ step = 0; stepStart = [DateTime]::Now; pos = 0; partial = ''; dec = [Text.Encoding]::UTF8.GetDecoder()
            installDir = ''; root = ''; error = ''; proc = $null; log = '' }
    # Rough seconds per step, so the bar keeps creeping forward inside a long step.
    $Expect = @{ 1 = 240; 2 = 20; 3 = 180; 4 = 2; 5 = 360; 6 = 20; 7 = 30 }
    $Caption = @{ 1 = 'Installing the helper programs TeddyClip uses'; 2 = 'Downloading TeddyClip'
                  3 = 'Putting TeddyClip together'; 4 = 'Saving your settings'
                  5 = 'Downloading the AI that watches your videos'; 6 = 'Adding TeddyClip to your desktop'
                  7 = 'Making sure everything works' }
    # Already installed: the window offers an update instead (a demo always shows a first install).
    $existing = (Test-Path (Join-Path $env:LOCALAPPDATA 'TeddyClip-app\.venv')) -and -not $Demo

    $form = New-Object Windows.Forms.Form -Property @{
        Text = 'TeddyClip setup'; BackColor = $Paper; FormBorderStyle = 'FixedSingle'; MaximizeBox = $false
        StartPosition = 'CenterScreen'; Font = (Font 10); AutoScaleMode = 'Dpi'
        AutoScaleDimensions = (New-Object Drawing.SizeF(96, 96)); ClientSize = (New-Object Drawing.Size(560, 470)) }
    $icon = Image64 $IconPng
    if ($icon) { $form.Icon = [Drawing.Icon]::FromHandle(([Drawing.Bitmap]$icon).GetHicon()) }

    $stripe = New-Object Windows.Forms.Panel -Property @{ Dock = 'Top'; Height = 8 }
    $stripe.Add_Paint({ param($s, $e)
        $w = $s.Width; $cuts = 0, 0.4, 0.7, 0.88, 1
        for ($i = 0; $i -lt 4; $i++) {
            $b = New-Object Drawing.SolidBrush $Stripes[$i]
            $e.Graphics.FillRectangle($b, [int]($w * $cuts[$i]), 0, [int]($w * ($cuts[$i + 1] - $cuts[$i])) + 1, $s.Height)
            $b.Dispose()
        } })
    $logo = New-Object Windows.Forms.PictureBox -Property @{ Image = (Image64 $LogoPng); SizeMode = 'Zoom'
        Location = (New-Object Drawing.Point(130, 26)); Size = (New-Object Drawing.Size(300, 64)) }
    $form.Controls.AddRange(@($stripe, $logo))

    function Page { $p = New-Object Windows.Forms.Panel -Property @{ Location = (New-Object Drawing.Point(0, 106)); Size = (New-Object Drawing.Size(560, 364)); Visible = $false }; $form.Controls.Add($p); $p }
    function Label($page, $text, $x, $y, $w, $h, $font, $color) {
        $l = New-Object Windows.Forms.Label -Property @{ Text = $text; Location = (New-Object Drawing.Point($x, $y))
            Size = (New-Object Drawing.Size($w, $h)); Font = $font; ForeColor = $color; AutoEllipsis = $true }
        $page.Controls.Add($l); $l
    }
    function Button($page, $text, $x, $y, $w, $primary) {
        $b = New-Object Windows.Forms.Button -Property @{ Text = $text; Location = (New-Object Drawing.Point($x, $y))
            Size = (New-Object Drawing.Size($w, 44)); FlatStyle = 'Flat'; Font = (Font 11 'Bold'); Cursor = 'Hand' }
        if ($primary) { $b.BackColor = $Orange; $b.ForeColor = $Cream; $b.FlatAppearance.BorderSize = 0 }
        else { $b.BackColor = $Line; $b.ForeColor = $Walnut; $b.FlatAppearance.BorderSize = 0 }
        $page.Controls.Add($b); $b
    }
    function Round($c) {  # pill-shaped buttons, like the TeddyClip window
        $r = $c.Height; $p = New-Object Drawing.Drawing2D.GraphicsPath
        $p.AddArc(0, 0, $r, $r, 90, 180); $p.AddArc($c.Width - $r - 1, 0, $r, $r, 270, 180); $p.CloseFigure()
        $c.Region = New-Object Drawing.Region($p)
    }

    # Welcome
    $welcome = Page
    $title = if ($existing) { 'Update TeddyClip' } else { "Let's set up TeddyClip" }
    $body = if ($existing) { 'This gets the newest TeddyClip. Your clips, recordings and settings stay as they are.' }
            else { 'TeddyClip finds the best moments in your gaming recordings. Setup installs everything it needs, including the AI that watches your videos.' }
    [void](Label $welcome $title 40 0 480 34 (Font 16 'Bold') $Walnut)
    [void](Label $welcome $body 40 40 480 64 (Font 10.5) $Walnut)
    $youBox = $null
    if (-not $existing) {
        [void](Label $welcome 'Your name' 40 122 260 22 (Font 10 'Bold') $Walnut)
        $youBox = New-Object Windows.Forms.TextBox -Property @{ Location = (New-Object Drawing.Point(40, 146)); Width = 260; Font = (Font 12); BackColor = $Cream; BorderStyle = 'FixedSingle'; MaxLength = 30 }
        $welcome.Controls.Add($youBox)
        [void](Label $welcome 'Optional. TeddyClip can use it in clip titles.' 40 184 480 22 (Font 9.5) $Muted)
    }
    $go = Button $welcome $(if ($existing) { 'Update' } else { 'Install' }) 360 300 160 $true

    # Working
    $work = Page
    [void](Label $work $(if ($existing) { 'Updating TeddyClip' } else { 'Setting up TeddyClip' }) 40 0 480 34 (Font 16 'Bold') $Walnut)
    $stepLabel = Label $work 'Getting started...' 40 54 480 26 (Font 11 'Bold') $Walnut
    $bar = New-Object Windows.Forms.PictureBox -Property @{ Location = (New-Object Drawing.Point(40, 88)); Size = (New-Object Drawing.Size(480, 16)) }
    $bar.Tag = 0.0
    $bar.Add_Paint({ param($s, $e)
        $g = $e.Graphics; $g.SmoothingMode = 'AntiAlias'; $h = $s.Height - 1
        $track = New-Object Drawing.Drawing2D.GraphicsPath
        $track.AddArc(0, 0, $h, $h, 90, 180); $track.AddArc($s.Width - $h - 1, 0, $h, $h, 270, 180); $track.CloseFigure()
        $g.FillPath((New-Object Drawing.SolidBrush $Line), $track)
        $w = [Math]::Max($h, [int](($s.Width - 1) * [double]$s.Tag))
        $fill = New-Object Drawing.Drawing2D.GraphicsPath
        $fill.AddArc(0, 0, $h, $h, 90, 180); $fill.AddArc($w - $h, 0, $h, $h, 270, 180); $fill.CloseFigure()
        $g.FillPath((New-Object Drawing.SolidBrush $Orange), $fill) })
    $work.Controls.Add($bar)
    $detail = Label $work '' 40 112 480 22 (Font 9.5) $Muted
    [void](Label $work 'You can keep using your PC. Leave this window open until it says All set.' 40 140 480 22 (Font 9.5) $Muted)
    $more = New-Object Windows.Forms.LinkLabel -Property @{ Text = 'Show details'; Location = (New-Object Drawing.Point(40, 172)); AutoSize = $true; LinkColor = $Muted; Font = (Font 9) }
    $logBox = New-Object Windows.Forms.TextBox -Property @{ Multiline = $true; ReadOnly = $true; ScrollBars = 'Vertical'; Visible = $false
        Location = (New-Object Drawing.Point(40, 196)); Size = (New-Object Drawing.Size(480, 160)); Font = (Font 8.5 'Regular' 'Consolas'); BackColor = $Cream }
    $more.Add_LinkClicked({ $logBox.Visible = -not $logBox.Visible; $more.Text = $(if ($logBox.Visible) { 'Hide details' } else { 'Show details' }) })
    $work.Controls.AddRange(@($more, $logBox))

    # All set
    $done = Page
    [void](Label $done 'All set!' 40 0 480 34 (Font 16 'Bold') $Walnut)
    $doneText = Label $done '' 40 44 480 120 (Font 10.5) $Walnut
    $open = Button $done 'Open TeddyClip' 330 300 190 $true
    $close = Button $done 'Close' 190 300 120 $false

    # Something went wrong
    $failed = Page
    [void](Label $failed 'Setup hit a problem' 40 0 480 34 (Font 16 'Bold') $Walnut)
    $failText = Label $failed '' 40 42 480 48 (Font 10.5) $Orange
    [void](Label $failed 'Send a screenshot of this window to whoever set TeddyClip up for you.' 40 92 480 22 (Font 9.5) $Muted)
    $failLog = New-Object Windows.Forms.TextBox -Property @{ Multiline = $true; ReadOnly = $true; ScrollBars = 'Vertical'
        Location = (New-Object Drawing.Point(40, 120)); Size = (New-Object Drawing.Size(480, 168)); Font = (Font 8.5 'Regular' 'Consolas'); BackColor = $Cream }
    $failed.Controls.Add($failLog)
    $retry = Button $failed 'Try again' 330 300 190 $true
    $failClose = Button $failed 'Close' 190 300 120 $false

    function Show-Page($page) { foreach ($p in $welcome, $work, $done, $failed) { $p.Visible = ($p -eq $page) } }

    function Start-Engine {
        Show-Page $work
        $S.step = 0; $S.stepStart = [DateTime]::Now; $S.pos = 0; $S.partial = ''; $S.error = ''
        $S.dec = [Text.Encoding]::UTF8.GetDecoder(); $logBox.Clear(); $bar.Tag = 0.0; $bar.Invalidate()
        # A log of its own per run, so two setup windows never share one.
        $S.log = Join-Path $env:TEMP ("teddyclip-setup-" + [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff') + '.log')
        if ($youBox) { $env:TEDDYCLIP_SETUP_YOU = $youBox.Text }
        $pass = ''
        foreach ($name in 'SkipPrograms', 'SkipModels', 'SkipShortcuts', 'Demo') { if ((Get-Variable $name -ValueOnly)) { $pass += " -$name" } }
        if ($InstallDir) { $pass += " -InstallDir `"$InstallDir`"" }
        $ps = Join-Path $PSHOME 'powershell.exe'
        $line = "/d /c `"`"$ps`" -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Worker$pass > `"$($S.log)`" 2>&1`""
        $S.proc = Start-Process cmd.exe -ArgumentList $line -WindowStyle Hidden -PassThru
        [void]$S.proc.Handle  # keeps the exit code readable once it ends
        $timer.Start()
    }

    function Read-Engine {
        if (-not (Test-Path $S.log)) { return }
        $fs = [IO.File]::Open($S.log, 'Open', 'Read', 'ReadWrite')
        try {
            [void]$fs.Seek($S.pos, 'Begin')
            $bytes = New-Object byte[] ([Math]::Max(0, $fs.Length - $S.pos))
            $n = $fs.Read($bytes, 0, $bytes.Length); $S.pos += $n
        } finally { $fs.Close() }
        if ($n -le 0) { return }
        $chars = New-Object char[] ($S.dec.GetCharCount($bytes, 0, $n))
        [void]$S.dec.GetChars($bytes, 0, $n, $chars, 0)
        $lines = @(($S.partial + (New-Object string (, $chars))) -split "`n")
        $S.partial = $lines[-1]
        if ($lines.Count -lt 2) { return }  # no whole line yet
        foreach ($raw in $lines[0..($lines.Count - 2)]) {
            $text = ($raw.TrimEnd("`r") -split "`r")[-1]
            $text = $text -replace "\x1b\[[0-9;?]*[ -/]*[@-~]", '' -replace '[\u2500-\u259F]', ' ' -replace '\s+', ' '
            $text = $text.Trim()
            if (-not $text) { continue }
            if ($text -match '^== Step (\d) of \d+: ') { $S.step = [int]$Matches[1]; $S.stepStart = [DateTime]::Now; $stepLabel.Text = $Caption[$S.step]; $detail.Text = '' }
            elseif ($text -match '^== Checking everything') { $S.step = 7; $S.stepStart = [DateTime]::Now; $stepLabel.Text = $Caption[7] }
            elseif ($text -match '^@@INSTALLDIR (.+)$') { $S.installDir = $Matches[1].Trim(); continue }
            elseif ($text -match '^Something went wrong: (.+)$') { $S.error = $Matches[1] }
            elseif ($text -match '^Your recordings and clips live in: (.+)$') { $S.root = $Matches[1] }
            elseif ($text -notmatch '^(==|To pin it|Press any key)' -and $text -match '[A-Za-z]{3}') { $detail.Text = $text }
            $logBox.AppendText($text + [Environment]::NewLine)
        }
    }

    $timer = New-Object Windows.Forms.Timer -Property @{ Interval = 300 }
    $timer.Add_Tick({
        Read-Engine
        if ($S.step -gt 0) {
            $inStep = 0.9 * (1 - [Math]::Exp(-([DateTime]::Now - $S.stepStart).TotalSeconds / $Expect[$S.step]))
            $bar.Tag = [Math]::Min(0.99, ($S.step - 1 + $inStep) / 7.0); $bar.Invalidate()
        }
        if ($S.proc -and $S.proc.HasExited) {
            $timer.Stop(); Read-Engine
            if ($S.proc.ExitCode -eq 0 -and -not $S.error) {
                $where = if ($S.root) { $S.root } else { Join-Path $env:USERPROFILE 'TeddyClip' }
                $doneText.Text = "TeddyClip is on your desktop and in the Start menu.`n`nYour recordings and clips go in:`n$where`n`nThe TeddyClip Folders shortcut on your desktop opens it."
                Show-Page $done
            } else {
                $why = if ($S.error) { $S.error } else { 'setup stopped before it finished.' }
                $failText.Text = $why.Substring(0, 1).ToUpper() + $why.Substring(1)
                $failLog.Text = $logBox.Text
                Show-Page $failed
                $failLog.SelectionStart = $failLog.TextLength; $failLog.ScrollToCaret()  # the problem is at the end
            }
        } })

    $go.Add_Click({ Start-Engine })
    $retry.Add_Click({ Start-Engine })
    $close.Add_Click({ $form.Close() }); $failClose.Add_Click({ $form.Close() })
    $open.Add_Click({
        $app = Join-Path $S.installDir '.venv\Scripts\teddyclip-app.exe'
        if ($S.installDir -and (Test-Path $app)) { Start-Process $app }
        $form.Close() })
    $form.Add_FormClosing({ param($s, $e)
        if ($S.proc -and -not $S.proc.HasExited) {
            $sure = [Windows.Forms.MessageBox]::Show($form, 'TeddyClip is still being set up. Stop now? You can run setup again later.', 'TeddyClip setup', 'YesNo', 'Question')
            if ($sure -ne 'Yes') { $e.Cancel = $true; return }
            & taskkill.exe /PID $S.proc.Id /T /F *> $null
        } })
    $form.Add_Shown({ foreach ($b in $go, $open, $close, $retry, $failClose) { Round $b }; $form.Activate() })
    Show-Page $welcome
    [void]$form.ShowDialog()
    exit 0
}

# Pretend run for trying the window: -Demo with -Worker prints what a real run
# would, quickly, and changes nothing.
if ($Worker -and $Demo) {
    $labels = 'programs (Python, FFmpeg, Ollama)', 'TeddyClip files', "TeddyClip's Python packages", 'your settings',
              'AI models', 'folders and desktop shortcuts'
    for ($i = 1; $i -le 6; $i++) {
        Say "Step $i of 6: $($labels[$i - 1])"
        foreach ($k in 1..3) { Write-Host "Demo: part $k of this step..."; Start-Sleep -Milliseconds 700 }
    }
    Say "Checking everything"; Write-Host "[ok] Everything needed is working."; Start-Sleep 1
    Write-Host "Your recordings and clips live in: $(Join-Path $env:USERPROFILE 'TeddyClip')"
    Write-Host "@@INSTALLDIR $(Join-Path $env:LOCALAPPDATA 'TeddyClip-app')"
    exit 0
}
if ($Worker) { [Console]::OutputEncoding = [Text.Encoding]::UTF8 }

# 1. Programs
if (-not $SkipPrograms) {
    Say "Step 1 of 6: programs (Python, FFmpeg, Ollama)"
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
        Write-Host "Installing Ollama..."
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
        if (Find-Ollama) { Quiet-Ollama }
        else { Write-Host "Ollama could not be installed, so AI titles will be off. TeddyClip still works." -ForegroundColor Yellow }
    }
} else {
    Say "Step 1 of 6: skipped installing programs"
}
$Python = Find-Python312
if (-not $Python) { Fail "Python 3.12 was not found after installing it. Restart the PC and run this again." }

# 2. TeddyClip itself
Say "Step 2 of 6: TeddyClip files"
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
Say "Step 3 of 6: TeddyClip's Python packages"
$venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create the Python environment." }
}
$pipLog = Join-Path $InstallDir 'install-log.txt'
function Pip-Install([string[]]$pipArgs, $what) {
    & $venvPy -m pip install --quiet --disable-pip-version-check @pipArgs *>> $pipLog
    if ($LASTEXITCODE -ne 0) {
        Get-Content $pipLog -Tail 15 | Write-Host
        Fail "could not install $what (the full log is in $pipLog)."
    }
}
Set-Content $pipLog "" -Encoding UTF8
Pip-Install @('--upgrade', 'pip') 'pip'
Pip-Install @('torch', '--index-url', 'https://download.pytorch.org/whl/cpu') 'PyTorch' 
$nvidia = [bool](Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -match 'NVIDIA' })
if ($nvidia) {
    Write-Host "NVIDIA graphics card found: adding GPU support for faster transcription."
    Pip-Install @('-e', '.[gpu]') "TeddyClip's packages"
} else {
    Write-Host "No NVIDIA graphics card found: transcription will run on your other graphics card through Vulkan (set up in step 5)."
    Pip-Install @('-e', '.') "TeddyClip's packages"
}

$config = Join-Path $InstallDir 'config.yaml'

# 4. Settings: names for clip titles, and where everything goes (before the
# models, which are kept there too). Only on a first install.
Say "Step 4 of 6: your settings"
if (-not $You) { $You = $env:TEDDYCLIP_SETUP_YOU }
if (-not $Friend) { $Friend = $env:TEDDYCLIP_SETUP_FRIEND }
$text = Get-Content $config -Raw -Encoding UTF8
$names = @(@($You, $Friend) | ForEach-Object { ("$_" -replace '[^\p{L}\p{N} ''.-]', '').Trim() } | Where-Object { $_ })
if ($names.Count -and $text -match '(?m)^people:\s*\[\s*\]') {
    $list = ($names | ForEach-Object { '"' + $_ + '"' }) -join ', '
    $text = [regex]::Replace($text, '(?m)^people:\s*\[\s*\]', { param($m) "people: [$list]" })
    Write-Utf8 $config $text
    Write-Host "Clip titles can use the names $($names -join ' and ')."
}
if ($DataDir -and $text -match '(?m)^root:\s*C:\\Users\\\{user\}\\TeddyClip\s*$') {
    $DataDir = [IO.Path]::GetFullPath($DataDir).TrimEnd('\')
    $line = "root: '" + ($DataDir -replace "'", "''") + "'"
    $text = [regex]::Replace($text, '(?m)^root:.*$', { param($m) $line })
    Write-Utf8 $config $text
}

# 5. AI models
if (-not $SkipModels) {
    Say "Step 5 of 6: AI models"
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
                Write-Host "Downloading its speech model..."
                Invoke-WebRequest 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin' -OutFile "$ggml.part" -UseBasicParsing -ErrorAction Stop
                Move-Item "$ggml.part" $ggml -Force
            }
            Write-Host "Graphics-card transcription is ready."
        } catch {
            Write-Host "Could not set up graphics-card transcription ($($_.Exception.Message)). TeddyClip will transcribe on the CPU, which is slower." -ForegroundColor Yellow
        }
    }
} else {
    Say "Step 5 of 6: skipped downloading models"
}

# 6. Shortcuts and a final check
Say "Step 6 of 6: folders and desktop shortcuts"
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
Write-Host "@@INSTALLDIR $InstallDir"
Write-Host "How to use it:"
Write-Host "  1. Double-click 'TeddyClip' on the desktop. It opens in its own window."
Write-Host "  2. Click 'Add recordings' and pick your OBS recordings and the game."
Write-Host "  3. Click 'Find clips' and let it run. It suggests the best moments."
Write-Host "  4. Click 'Review' on a suggestion, move its start and end, and click 'Create clip'."
Write-Host "Tip: say 'clip that' out loud while recording and that moment is always suggested."
