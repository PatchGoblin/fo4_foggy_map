# Builds a distributable FoggyMap-<version>.zip in dist\.
#
#   .\tools\package_release.ps1
#
# Tests, builds the plugin without debug symbols, freezes the companion, stages the
# MO2/Vortex layout, refuses to continue if anything staged names the maintainer, then
# zips. Safe to run with the game open: nothing is deployed to MO2.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$dist = Join-Path $repo 'dist'
$stage = Join-Path $dist 'stage'
$plugins = Join-Path $stage 'F4SE\Plugins'

function Step($text) { Write-Host "== $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

$version = [regex]::Match((Get-Content (Join-Path $repo 'plugin\xmake.lua') -Raw), 'set_version\("([^"]+)"\)').Groups[1].Value
if (-not $version) { throw 'no set_version in plugin\xmake.lua' }
$zip = Join-Path $dist "FoggyMap-$version.zip"

Step 'tests'
& $python -m pytest (Join-Path $repo 'tests'); Check 'pytest'

Step 'plugin'
# Release mode: no debug symbols, so the DLL records nothing about this machine. It
# gets its own xmake config folder, so your development config -- its mode and its MO2
# deploy folder -- is never touched, and nothing is deployed from here.
$xmake = (Get-Command xmake -ErrorAction SilentlyContinue).Source
if (-not $xmake) { $xmake = Join-Path $repo '.tools\xmake\xmake\xmake.exe' }
$env:XMAKE_CONFIGDIR = Join-Path $repo 'build\xmake-release'
Push-Location (Join-Path $repo 'plugin')
try {
    & $xmake f -y -m release; Check 'xmake config'
    & $xmake build -y FoggyMap; Check 'xmake'
} finally {
    Pop-Location
    Remove-Item Env:XMAKE_CONFIGDIR
}
$dll = Join-Path $repo 'plugin\build\windows\x64\release\FoggyMap.dll'

Step 'companion'
$work = Join-Path $repo 'build\pyinstaller'
& $python -m PyInstaller --noconfirm --clean --onedir --console `
    --name FoggyMapCompanion `
    --paths (Join-Path $repo 'viewer') `
    --add-data "$(Join-Path $repo 'site');site" `
    --exclude-module PySide6 --exclude-module shiboken6 --exclude-module tkinter `
    --exclude-module matplotlib --exclude-module contourpy --exclude-module kiwisolver `
    --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'work') --specpath $work `
    (Join-Path $repo 'tools\companion_entry.py')
Check 'PyInstaller'

Step 'stage'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $plugins | Out-Null
Copy-Item $dll $plugins
Copy-Item (Join-Path $repo 'plugin\FoggyMap.ini') $plugins
Copy-Item (Join-Path $work 'dist\FoggyMapCompanion') (Join-Path $plugins 'FoggyMap') -Recurse

Step 'identity scan'
& $python (Join-Path $repo 'tools\identity_scan.py') $stage
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $zip) { Remove-Item $zip -Force }
    throw 'identity scan found leaks; nothing was zipped'
}

Step 'zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
Write-Host "built $zip"
