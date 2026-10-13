﻿# ---------------------------------------------------------------------------
# AquaGuard AI — start the backend and frontend together.
#
#   .\scripts\start.ps1
#
# Opens two PowerShell windows (backend, frontend) and reports the URLs. Use
# this instead of starting the two servers by hand when you want the whole app
# running; use `.\scripts\stop.ps1` to shut them down again.
#
# This script exists because two things bite people on Windows:
#
#   1. `node` / `npm` are only on the PATH of terminals opened AFTER Node was
#      installed. A terminal that predates the install gives
#      "npm is not recognized". This script re-reads the machine + user PATH
#      itself, so it works from a stale terminal too.
#
#   2. `npm run dev` fails with "Port 5173 is already in use" when a previous
#      Vite is still running, because vite.config.js sets `strictPort: true`.
#      This script clears the ports first, so starting is never blocked by a
#      server that was left behind.
#
# MySQL (3306) is expected to be running already. This script checks it and
# tells you if it is not, but does not start it — it is a Windows service.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host "`n=== AquaGuard AI — starting dev servers ===" -ForegroundColor Cyan

# --- 0. Environment check --------------------------------------------------
# Re-read PATH from the registry so this works even in a terminal that was open
# before Node was installed.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
[Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path

$nodeDir = 'C:\Program Files\nodejs'
if (-not (Test-Path "$nodeDir\npm.cmd")) {
    throw "npm not found at $nodeDir\npm.cmd — is Node.js installed?"
}
Write-Host "  node       $(& "$nodeDir\node.exe" --version)" -ForegroundColor DarkGray

# Python lives inside the backend venv, created by scripts\setup.ps1.
$python = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Backend venv missing. Run .\scripts\setup.ps1 first (needs $python)."
}
Write-Host "  python     venv found" -ForegroundColor DarkGray

# --- 1. Free the dev ports -------------------------------------------------
# A leftover Vite would otherwise make the frontend fail to start, and a
# leftover Flask would hold port 5000 with stale code loaded.
$freed = @()
foreach ($port in @(5173, 5000)) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($connections) {
        foreach ($connection in $connections) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
        }
        $freed += $port
    }
}
if ($freed.Count -gt 0) {
    Write-Host "  freed      port(s) $($freed -join ', ') (a previous server was still running)" -ForegroundColor Yellow
    Start-Sleep -Seconds 2
}
else {
    Write-Host "  ports      already free" -ForegroundColor DarkGray
}

# --- 2. MySQL --------------------------------------------------------------
$mysql = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
if (-not $mysql) {
    Write-Host "`n  WARNING: MySQL is not listening on 3306." -ForegroundColor Red
    Write-Host "  Start it with:  Start-Service MySQL80" -ForegroundColor Red
    Write-Host "  The backend will boot but /api/health/db will fail.`n" -ForegroundColor Red
}
else {
    Write-Host "  mysql      running on 3306" -ForegroundColor DarkGray
}

# --- 3. Backend ------------------------------------------------------------
# A separate window per server: each is a long-running process with its own log
# stream, and one window would interleave them into an unreadable mess.
Write-Host "`n  starting backend..." -ForegroundColor Yellow
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoExit', '-Command',
"`$host.UI.RawUI.WindowTitle = 'AquaGuard AI - backend'; Set-Location '$root\backend'; Write-Host 'AquaGuard AI backend - http://127.0.0.1:5000' -ForegroundColor Cyan; & '$python' app.py" `
    -WorkingDirectory "$root\backend"

Start-Sleep -Seconds 6

# --- 4. Frontend -----------------------------------------------------------
Write-Host "  starting frontend..." -ForegroundColor Yellow
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoExit', '-Command',
"`$host.UI.RawUI.WindowTitle = 'AquaGuard AI - frontend'; `$env:Path = '$nodeDir;' + `$env:Path; Set-Location '$root\frontend'; Write-Host 'AquaGuard AI frontend - http://localhost:5173' -ForegroundColor Cyan; & '$nodeDir\npm.cmd' run dev" `
    -WorkingDirectory "$root\frontend"

# --- 5. Verify -------------------------------------------------------------
# Poll instead of sleeping a fixed amount. A fixed `Start-Sleep` was reporting
# both servers as NOT LISTENING even though they came up a few seconds later —
# Flask takes ~5-10s to import pandas/sarn, and Vite needs to pre-bundle on a
# cold start. Polling waits exactly as long as it takes and no longer.
Write-Host "`n  checking..." -ForegroundColor Yellow
function Wait-ForPort {
    param([int]$Port, [int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
            return $true
        }
        Start-Sleep -Milliseconds 750
    }
    return $false
}

$backendUp = Wait-ForPort -Port 5000
$frontendUp = Wait-ForPort -Port 5173
Write-Host ""
if ($backendUp) { Write-Host "    backend    OK   http://127.0.0.1:5000" -ForegroundColor Green }
else { Write-Host "    backend    NOT LISTENING after 45s - check the backend window for the error" -ForegroundColor Red }

if ($frontendUp) { Write-Host "    frontend   OK   http://localhost:5173" -ForegroundColor Green }
else { Write-Host "    frontend   NOT LISTENING after 45s - check the frontend window for the error" -ForegroundColor Red }

Write-Host "`n  Open http://localhost:5173 in your browser." -ForegroundColor Cyan
Write-Host "  Stop everything with:  .\scripts\stop.ps1" -ForegroundColor Cyan
Write-Host ""
