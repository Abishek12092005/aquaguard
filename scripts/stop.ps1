# ---------------------------------------------------------------------------
# AquaGuard AI — stop dev servers and free the ports.
#
#   .\scripts\stop.ps1
#
# Use this when `npm run dev` says "Port 5173 is already in use", or after a
# terminal was closed without Ctrl+C. It kills whatever is holding the dev
# ports so the next start is clean.
#
# Ports:
#   5173  Vite dev server (frontend)
#   5000  Flask backend
#
# MySQL (3306) is deliberately NOT touched — it is a system service, it is meant
# to keep running, and stopping it would break the backend on next start.
# ---------------------------------------------------------------------------

$ports = @(5173, 5000)

Write-Host "`n=== AquaGuard AI — stopping dev servers ===" -ForegroundColor Cyan

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

    if (-not $connections) {
        Write-Host "  port $port  already free" -ForegroundColor DarkGray
        continue
    }

    foreach ($connection in $connections) {
        $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "  port $port  stopping $($process.ProcessName) (PID $($process.Id))" -ForegroundColor Yellow
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

Start-Sleep -Seconds 2

Write-Host "`n  final state:" -ForegroundColor Cyan
foreach ($port in $ports) {
    $still = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($still) {
        Write-Host "    $port  STILL IN USE" -ForegroundColor Red
    }
    else {
        Write-Host "    $port  free" -ForegroundColor Green
    }
}

$mysql = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
if ($mysql) {
    Write-Host "    3306  MySQL running (left alone)" -ForegroundColor DarkGray
}
else {
    Write-Host "    3306  MySQL NOT running - start the MySQL80 service" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Done. You can start the servers again. ===" -ForegroundColor Green
Write-Host ""
