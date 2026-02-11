$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$BackendDir = Join-Path $RepoRoot "backend"
$BuildDir = Join-Path $RepoRoot "desktop-electron\.backend-build"
$OutputDir = Join-Path $RepoRoot "desktop-electron\backend-bin"

if (Test-Path $BuildDir) {
  Remove-Item -Path $BuildDir -Recurse -Force
}

New-Item -ItemType Directory -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$VenvDir = Join-Path $BuildDir "venv"
python -m venv $VenvDir

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $BackendDir "requirements.txt") pyinstaller

& $PythonExe -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name catchup-backend `
  --hidden-import aiosqlite `
  --hidden-import sqlalchemy.dialects.sqlite.aiosqlite `
  --distpath (Join-Path $BuildDir "dist") `
  --workpath (Join-Path $BuildDir "work") `
  --specpath $BuildDir `
  --paths $BackendDir `
  (Join-Path $BackendDir "desktop_server.py")

Copy-Item `
  -Path (Join-Path $BuildDir "dist\catchup-backend.exe") `
  -Destination (Join-Path $OutputDir "catchup-backend.exe") `
  -Force

Write-Host "Backend binary written to $(Join-Path $OutputDir 'catchup-backend.exe')"
