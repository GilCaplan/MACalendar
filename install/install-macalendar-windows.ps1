# MACalendar installer for Windows — stage one.
#
# In PowerShell:
#
#   irm https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-windows.ps1 | iex
#
# or download it, right-click ▸ Run with PowerShell (or:
#   powershell -ExecutionPolicy Bypass -File install-macalendar-windows.ps1).
#
# It installs what the installer needs — Git, Python 3.12 and Ollama — with
# winget (built into Windows 10/11), fetches MACalendar into
# %USERPROFILE%\MACalendar if it is not there yet, and hands over to
# install\install.py, which asks the rest (an existing install: update /
# reinstall / leave; the role; Jude; desktop shortcuts) and at the end offers
# to delete this file. Safe to run again.
#
# $env:MACALENDAR_HOME puts everything elsewhere. Arguments go to install.py.

$ErrorActionPreference = "Stop"
$Root = if ($env:MACALENDAR_HOME) { $env:MACALENDAR_HOME } else { Join-Path $HOME "MACalendar" }
$RepoUrl = "https://github.com/GilCaplan/MACalendar.git"

function Say($text) { Write-Host "`n> $text" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Need($command, $wingetId, $what) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Say "Installing $what"
        winget install -e --id $wingetId --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
}

Say "MACalendar installer - Windows, into $Root"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again."
    exit 1
}

Need git "Git.Git" "Git"
Need py "Python.Python.3.12" "Python 3.12"
Need ollama "Ollama.Ollama" "Ollama (runs the assistant's model on this PC)"

# The code — fetched once. An EXISTING copy is left for install.py to ask
# about (update, reinstall, or leave it as it is).
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Repo = Join-Path $Root "MACalendar"
$Installer = Join-Path $Repo "install\install.py"
if (Test-Path (Join-Path $Repo ".git")) {
    # Already installed: the NEWEST installer must ask (update / reinstall /
    # leave it), not the one inside an old copy. Fetch — your files stay as
    # they are — and run the fetched one; offline, the one you have. cmd's
    # redirect keeps the bytes exactly (PowerShell's would re-encode them).
    $Tmp = Join-Path $env:TEMP "macalendar-install.py"
    git -C $Repo fetch --quiet --depth 1 origin 2>$null
    if ($LASTEXITCODE -eq 0) {
        cmd /c "git -C `"$Repo`" show FETCH_HEAD:install/install.py > `"$Tmp`""
        if ($LASTEXITCODE -eq 0) { $Installer = $Tmp }
    }
} else {
    Say "Fetching the code"
    git clone --depth 1 $RepoUrl $Repo
}

# Everything else. When this ran from a downloaded FILE (not irm | iex), its
# path goes along so the installer can offer to delete it at the end.
$More = @("--root", $Root)
if ($PSCommandPath) { $More += @("--installer-file", $PSCommandPath) }
& py -3.12 $Installer @More @args
exit $LASTEXITCODE
