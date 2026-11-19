# Run on Windows with Python 3.13 installed. Builds the standalone app, the updater helper,
# a portable ZIP, an updater-compatible ZIP and (with Inno Setup 6.3+) Setup.exe.
#
# The version comes from ONE place: workbench_db.VERSION.
# Optional environment variables:
#   WOSB_SIGNING_KEY   path to the Ed25519 publisher secret (see packaging\Make-Signing-Key.py);
#                      when set, update ZIPs are signed and the public key is bundled.
#   WOSB_PREVIOUS_DIR  previous dist\WoSBWorkbench folder; files it has but this build lacks
#                      are listed for removal in the update ZIP (prevents stale libraries).
#   WOSB_SKIP_TESTS=1  skip the unit tests (not recommended).
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project

# Local builds use the py launcher; CI sets WOSB_PYTHON=python (actions/setup-python).
if ($env:WOSB_PYTHON) { $pyArgs = @() ; $python = $env:WOSB_PYTHON } else { $python = 'py'; $pyArgs = @('-3.13') }
try { & $python @pyArgs --version | Out-Host }
catch { throw 'Install Python 3.13 (with tkinter) before building the Windows executable.' }
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 not available.' }

$venv = Join-Path $project '.build-venv'
& $python @pyArgs -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create build environment.' }
$run = Join-Path $venv 'Scripts\python.exe'
& $run -m pip install --upgrade pip
& $run -m pip install -r (Join-Path $project 'engine\requirements.txt') 'pyinstaller>=6.12,<7' 'pytest>=8'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

$version = (& $run -c "import sys; sys.path.insert(0, r'$project'); from workbench_db import VERSION; print(VERSION)").Trim()
if (-not ($version -match '^\d+(\.\d+){1,3}$')) { throw "Could not read VERSION from workbench_db.py (got '$version')." }
Write-Host "Building WoSB Workbench $version" -ForegroundColor Cyan

if ($env:WOSB_SKIP_TESTS -ne '1') {
  $env:PYTHONUTF8 = '1'   # tests read UTF-8 data files; Windows defaults to cp1252
  & $run -m pytest -q (Join-Path $project 'tests')
  if ($LASTEXITCODE -ne 0) {
    if ($env:WOSB_STRICT_TESTS -eq '1') { throw 'Unit tests failed (strict mode).' }
    Write-Host 'WARNING: some unit tests failed (see above). Continuing the local build; please report the failures.' -ForegroundColor Yellow
  }
}

$publicKey = Join-Path $project 'update-public-key.txt'
$keyData = @()
if (Test-Path -LiteralPath $publicKey) {
  $keyData = @('--add-data', 'update-public-key.txt;.')
  Write-Host 'Bundling update publisher public key (signed updates required).' -ForegroundColor Green
} else {
  Write-Host 'No update-public-key.txt: this build accepts UNSIGNED update ZIPs. Run packaging\Make-Signing-Key.py to enable signing.' -ForegroundColor Yellow
}

& $run -m PyInstaller --noconfirm --clean --windowed --onedir `
  --name WoSBWorkbench `
  --icon 'assets\wosb-workbench.ico' `
  --add-data 'Starter-Catalog.sqlite3;.' `
  --add-data 'Research-Ballistics-Catalog.json;.' `
  --add-data 'Research-Ship-Designs.json;.' `
  --add-data 'Research-Texture-Paths.json;.' `
  --add-data 'viewer;viewer' `
  --add-data 'wiki_site;wiki_site' `
  --add-data 'engine;engine' `
  --add-data 'assets;assets' `
  @keyData `
  --hidden-import protocol_lab --hidden-import protocol_schema --hidden-import game_watcher `
  --hidden-import datamine --hidden-import wiki_engine --hidden-import update_signing `
  --hidden-import battle_sim --hidden-import model_pack --hidden-import combat_sim --hidden-import ball_damage `
  --hidden-import damage_fit --hidden-import wiki_site --hidden-import wiki_publish --hidden-import bom_publish --hidden-import shipyard --hidden-import site_seo --hidden-import site_compact --hidden-import site_legal --hidden-import site_host --hidden-import mechanics_pages `
  --collect-all dnfile `
  --collect-all dncil `
  --collect-all pyzipper `
  --collect-all PIL `
  --collect-all texture2ddecoder `
  --collect-all lz4 `
  desktop_main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Write-Host "Portable executable: $project\dist\WoSBWorkbench\WoSBWorkbench.exe" -ForegroundColor Green

# Smoke test the frozen build: imports every module and checks bundled resources.
$selfTest = Join-Path $project 'dist\Self-Test.json'
$proc = Start-Process -FilePath (Join-Path $project 'dist\WoSBWorkbench\WoSBWorkbench.exe') `
  -ArgumentList @('--self-test', "`"$selfTest`"") -Wait -PassThru
if ($proc.ExitCode -ne 0) { Get-Content $selfTest -ErrorAction SilentlyContinue | Out-Host; throw 'Frozen self-test failed (see dist\Self-Test.json).' }
Write-Host 'Frozen self-test passed.' -ForegroundColor Green

# Separate one-file updater: it runs OUTSIDE the app directory so it can replace
# the closed app's executable. Stdlib-only, includes the offline_updates engine.
& $run -m PyInstaller --noconfirm --clean --onefile --console `
  --name WoSBUpdater `
  --icon 'assets\wosb-workbench.ico' `
  --hidden-import update_signing `
  --distpath (Join-Path $project 'dist\Updater') `
  --workpath (Join-Path $project 'build\Updater') `
  updater_main.py
if ($LASTEXITCODE -ne 0) { throw 'Updater helper build failed.' }
Copy-Item -LiteralPath (Join-Path $project 'dist\Updater\WoSBUpdater.exe') `
  -Destination (Join-Path $project 'dist\WoSBWorkbench\WoSBUpdater.exe') -Force
Write-Host 'Bundled offline ZIP updater: WoSBUpdater.exe' -ForegroundColor Green

$portable = Join-Path $project "dist\WoSBWorkbench-$version-Portable.zip"
if (Test-Path $portable) { Remove-Item $portable -Force }
Compress-Archive -Path (Join-Path $project 'dist\WoSBWorkbench\*') -DestinationPath $portable
Write-Host "Portable ZIP: $portable" -ForegroundColor Green

# Updater-compatible archive from the compiled tree (NOT .py sources, which frozen EXEs ignore).
$updateZip = Join-Path $project "dist\WoSBWorkbench-$version-Update.zip"
$updateArgs = @('--payload-dir', (Join-Path $project 'dist\WoSBWorkbench'), '--version', $version,
                '--min-version', '3.4.0', '--output', $updateZip,
                '--notes', "WoSB Workbench $version - see RELEASE-NOTES-v$version.md")
if ($env:WOSB_SIGNING_KEY) { $updateArgs += @('--sign-key', $env:WOSB_SIGNING_KEY) }
if ($env:WOSB_PREVIOUS_DIR) { $updateArgs += @('--previous-dir', $env:WOSB_PREVIOUS_DIR) }
& $run (Join-Path $project 'packaging\Make-Offline-Update.py') @updateArgs
if ($LASTEXITCODE -ne 0) { throw 'Could not package verified Windows updater ZIP.' }
Write-Host "Updater-compatible ZIP: $updateZip" -ForegroundColor Green

$iscc = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
  "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if ($iscc) {
  & $iscc "/DMyAppVersion=$version" (Join-Path $project 'packaging\WoSBWorkbench.iss')
  if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
  Write-Host "Windows Setup: dist\Installer\WoSBWorkbench-$version-Setup.exe" -ForegroundColor Green
} else {
  Write-Host 'Optional: install Inno Setup 6.3+ to generate Setup.exe.' -ForegroundColor Yellow
  Write-Host 'The portable .exe and ZIPs are already available.' -ForegroundColor Green
}
Set-Content -LiteralPath (Join-Path $project 'dist\VERSION.txt') -Value $version -Encoding ascii
