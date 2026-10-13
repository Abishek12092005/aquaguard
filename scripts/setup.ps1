# ---------------------------------------------------------------------------
# AquaGuard AI — first-time setup (Windows PowerShell)
# Creates the backend venv, installs both dependency sets, writes .env files.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host "`n=== AquaGuard AI setup ===" -ForegroundColor Cyan

# --- Locate Python ---------------------------------------------------------
$python = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) { throw "Python not found. Install Python 3.11+ and re-run." }
Write-Host "Python: $python"

# --- Locate Node -----------------------------------------------------------
$nodeDir = "C:\Program Files\nodejs"
if (-not (Test-Path "$nodeDir\node.exe")) { throw "Node.js not found at $nodeDir." }
$env:Path = "$nodeDir;" + $env:Path

# --- Backend ---------------------------------------------------------------
Write-Host "`n[1/3] Backend dependencies" -ForegroundColor Yellow
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { & $python -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created backend\.env — set MYSQL_PASSWORD and your secrets." -ForegroundColor Green
}

# --- Frontend --------------------------------------------------------------
Write-Host "`n[2/3] Frontend dependencies" -ForegroundColor Yellow
Set-Location "$root\frontend"
& "$nodeDir\npm.cmd" install

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created frontend\.env" -ForegroundColor Green
}

# --- Database --------------------------------------------------------------
Write-Host "`n[3/3] Database" -ForegroundColor Yellow
Write-Host "Run this yourself (it will prompt for the MySQL root password):"
Write-Host "  mysql -u root -p < `"$root\backend\database\schema.sql`"" -ForegroundColor Cyan

Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "Backend : cd backend; .\.venv\Scripts\Activate.ps1; python run.py"
Write-Host "Frontend: cd frontend; npm run dev"
