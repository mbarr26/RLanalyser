# Make a release: build the app + installer, then write the update manifest next to a copy of the installer.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Notes "What's new in this version"
#   powershell -ExecutionPolicy Bypass -File release.ps1 -NotesFile notes.txt -BaseUrl https://example.com/rla/
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Notes "..." -PublishTo D:\RLAnalyser-Updates
#   ... -SkipBuild   re-use the installer already in dist\ (just rewrite the manifest / re-publish)
#
# Bump APP_VERSION in version.py first. The result is dist\release\:
#   RLAnalyser-Setup-<version>.exe   the installer
#   latest.json                      what the app reads to find out a new version exists
# Upload both to the place UPDATE_URL (version.py) / update_url (config.json) points at.
# -BaseUrl writes an absolute download address into latest.json; without it the address is
# relative, i.e. "the installer sits next to latest.json", which also works from a local folder.
# -PublishTo copies both files into that folder (installer first, manifest last, so an app can never
# read a manifest whose installer isn't there yet): that folder is what update_url points at.

param(
    [string]$Notes = "",
    [string]$NotesFile = "",
    [string]$BaseUrl = "",
    [string]$PublishTo = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($NotesFile) { $Notes = (Get-Content -Raw -Encoding UTF8 $NotesFile).Trim() }
if ($BaseUrl -and -not $BaseUrl.EndsWith("/")) { $BaseUrl += "/" }
if ($BaseUrl -and -not $BaseUrl.StartsWith("https://")) { throw "-BaseUrl must start with https:// (the app refuses other download addresses)" }

if (-not $SkipBuild) {
    & "$PSScriptRoot\build.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }
}

$version = (python -c "from version import APP_VERSION; print(APP_VERSION)").Trim()
$installer = "dist\RLAnalyser-Setup-$version.exe"
if (-not (Test-Path $installer)) { throw "Expected $installer was not built" }

$out = "dist\release"
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item $installer $out -Force

$file = Get-Item "$out\RLAnalyser-Setup-$version.exe"
$manifest = [ordered]@{
    version  = $version
    url      = "$BaseUrl$($file.Name)"
    sha256   = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLower()
    size     = $file.Length
    notes    = $Notes
    released = (Get-Date -Format "yyyy-MM-dd")
}
# UTF-8 without a BOM
[System.IO.File]::WriteAllText("$PSScriptRoot\$out\latest.json", ($manifest | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))

if ($PublishTo) {
    New-Item -ItemType Directory -Force $PublishTo | Out-Null
    Copy-Item $file.FullName $PublishTo -Force                      # the installer first...
    Copy-Item "$PSScriptRoot\$out\latest.json" $PublishTo -Force    # ...then the manifest that announces it
    Write-Host "Published to $PublishTo"
}

Write-Host ""
Write-Host "Release $version is ready in $out :"
Write-Host "  $($file.Name)  ($([math]::Round($file.Length / 1MB, 1)) MB)"
Write-Host "  latest.json    sha256 $($manifest.sha256)"
if (-not $PublishTo) { Write-Host "Upload both files to your update location (or re-run with -PublishTo <folder>)." }
