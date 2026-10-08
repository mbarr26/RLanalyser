# Build the RL Analyser installer: PyInstaller -> dist\RL Analyser\, then Inno Setup -> dist\RLAnalyser-Setup-<version>.exe
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
# One-off setup:  pip install pyinstaller   and   winget install JRSoftware.InnoSetup

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (python -c "from version import APP_VERSION; print(APP_VERSION)").Trim()
Write-Host "Building RL Analyser $version"

python -m PyInstaller rl_analyser.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup not found (winget install JRSoftware.InnoSetup)" }

& $iscc "/DAppVersion=$version" installer\RLAnalyser.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "Done: dist\RLAnalyser-Setup-$version.exe"
