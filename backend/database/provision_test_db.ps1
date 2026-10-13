<#
.SYNOPSIS
    One-time provisioning of the AquaGuard test database.

.DESCRIPTION
    Creates `aquaguard_db_test`, applies the schema, and grants the application
    account access to it.

    WHY THIS IS A SCRIPT AND NOT PART OF THE APPLICATION SETUP. The test
    database has to be created by a MySQL ADMINISTRATOR. `aquaguard_ai` — the
    account the application connects as — deliberately has no CREATE DATABASE
    right, because granting it would mean a leaked .env could reshape the server.
    So this is the one step that needs root, and it needs doing exactly once.

    WHY IT ASKS FOR THE PASSWORD RATHER THAN TAKING IT. It is never written to
    disk, never passed on a command line (where it would land in shell history),
    and never echoed. It is read into a secure string, converted in memory, and
    handed to `mysql` through the environment for the duration of one call.

.PARAMETER MySqlExe
    Path to mysql.exe. Auto-detected from Program Files when omitted.

.PARAMETER AppPassword
    The password for the `aquaguard_ai` account. Read from backend/.env when
    omitted, so the grant matches the credential the application actually uses.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File backend/database/provision_test_db.ps1
#>

[CmdletBinding()]
param(
    [string]$MySqlExe,
    [string]$MySqlUser = 'root',
    [string]$AppPassword
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SchemaPath = Join-Path $PSScriptRoot 'schema.sql'
$EnvPath = Join-Path (Join-Path $ProjectRoot 'backend') '.env'
$TestDb = 'aquaguard_db_test'

# --- Locate mysql.exe -------------------------------------------------------
if (-not $MySqlExe) {
    $candidates = @(
        'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe',
        'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe',
        'C:\Program Files\MariaDB 11.4\bin\mysql.exe'
    )
    $MySqlExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $MySqlExe -or -not (Test-Path $MySqlExe)) {
    Write-Host "Could not find mysql.exe. Pass it with -MySqlExe." -ForegroundColor Red
    exit 1
}
Write-Host "Using mysql: $MySqlExe" -ForegroundColor Cyan

if (-not (Test-Path $SchemaPath)) {
    Write-Host "Schema not found at $SchemaPath" -ForegroundColor Red
    exit 1
}

# --- Resolve the application account's password ----------------------------
# Read from .env so the grant matches the credential the app actually connects
# with. A grant for a password the application does not use is a silent no-op.
if (-not $AppPassword) {
    if (Test-Path $EnvPath) {
        $line = Get-Content $EnvPath | Where-Object { $_ -match '^\s*DB_PASSWORD\s*=' } | Select-Object -First 1
        if ($line) {
            $AppPassword = ($line -split '=', 2)[1].Trim()
        }
    }
}
if (-not $AppPassword) {
    Write-Host "Could not read DB_PASSWORD from $EnvPath. Pass it with -AppPassword." -ForegroundColor Red
    exit 1
}
Write-Host "Application password resolved from .env ($($AppPassword.Length) characters)." -ForegroundColor Cyan

# --- Root password ----------------------------------------------------------
Write-Host ""
Write-Host "Enter the MySQL ROOT password (never written to disk or history)." -ForegroundColor Yellow
$secure = Read-Host -AsSecureString "MySQL root password"
$rootPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
)

# Passed through the environment, not as an argument, so it cannot appear in
# the process list or in a transcript of this session.
$env:MYSQL_PWD = $rootPassword

function Invoke-MySql {
    param([string]$Sql, [string]$Database)

    # NOT named $args: that is an automatic variable in PowerShell, and
    # assigning to it is what broke the parser on the first attempt.
    $mysqlArgs = @('-u', $MySqlUser, '--connect-timeout=10', '--default-character-set=utf8mb4')
    if ($Database) { $mysqlArgs += $Database }
    $mysqlArgs += @('-e', $Sql)

    $output = & $MySqlExe @mysqlArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "mysql failed: $output"
    }
    return $output
}

try {
    # --- 1. Database --------------------------------------------------------
    Write-Host ""
    Write-Host "[1/4] Creating $TestDb ..." -ForegroundColor Cyan
    Invoke-MySql "CREATE DATABASE IF NOT EXISTS ``$TestDb`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" | Out-Null
    Write-Host "      ok" -ForegroundColor Green

    # --- 2. Schema ----------------------------------------------------------
    # Applied by invoking mysql with the file on stdin, because `SOURCE` inside
    # a -e string resolves relative to the server's cwd, not ours.
    Write-Host "[2/4] Applying schema.sql ..." -ForegroundColor Cyan
    $schemaOutput = Get-Content -Raw $SchemaPath | & $MySqlExe -u $MySqlUser $TestDb 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Schema application failed: $schemaOutput"
    }
    Write-Host "      ok" -ForegroundColor Green

    # --- 3. Grants ----------------------------------------------------------
    # CREATE is granted HERE and only here. The test suite provisions its own
    # tables, so it needs CREATE; scoped to a database that holds no real data,
    # that is not the risk it would be on the production database.
    #
    # ALTER and DROP are granted for the same reason: the suite re-creates its
    # schema, and a column added to a model (for example the password-reset
    # columns on `users`) needs `ALTER TABLE` to reach an existing test database.
    # Without it every migration step fails with "ALTER command denied", which
    # reads like a code problem rather than a missing grant.
    Write-Host "[3/5] Granting access to the application account ..." -ForegroundColor Cyan
    $grant = "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON ``$TestDb``.* TO 'aquaguard_ai'@'localhost'; " +
    "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON ``$TestDb``.* TO 'aquaguard_ai'@'127.0.0.1'; " +
    "FLUSH PRIVILEGES;"
    Invoke-MySql $grant | Out-Null
    Write-Host "      ok" -ForegroundColor Green
    # --- 4. Column migrations ------------------------------------------------
    # schema.sql uses CREATE TABLE IF NOT EXISTS, so it does NOT add a column to
    # a table that already exists. An existing test database therefore misses
    # any column added to a model since it was first created, and the suite fails
    # with "Unknown column" deep inside an unrelated test. Running the same
    # additive migrations the developer database uses keeps the two schemas in
    # step; each is idempotent, so this is safe to run every time.
    Write-Host "[4/5] Applying column migrations ..." -ForegroundColor Cyan
    $backendDir = Join-Path $ProjectRoot 'backend'
    $python = Join-Path $backendDir '.venv\Scripts\python.exe'
    if (Test-Path $python) {
        foreach ($migration in @('database.add_admin_identity_columns', 'database.add_user_reset_columns', 'database.repair_missing_columns')) {
            Push-Location $backendDir
            try {
                & $python -m $migration --database $TestDb
                if ($LASTEXITCODE -ne 0) { throw "Migration $migration failed" }
            }
            finally { Pop-Location }
        }
        Write-Host "      ok" -ForegroundColor Green
    }
    else {
        Write-Host "      skipped (no venv interpreter at $python)" -ForegroundColor Yellow
    }

    # --- 5. Verify ----------------------------------------------------------
    Write-Host "[5/5] Verifying ..." -ForegroundColor Cyan
    $tables = Invoke-MySql "SELECT COUNT(*) AS tables_created FROM information_schema.tables WHERE table_schema='$TestDb';"
    Write-Host "      $($tables | Select-Object -Last 1)" -ForegroundColor Green

    $expected = @('users', 'water_predictions', 'alerts', 'aqua_ai_conversations', 'aqua_ai_messages',
        'login_events', 'admin_settings')
    $missing = @()
    foreach ($table in $expected) {
        $found = Invoke-MySql "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$TestDb' AND table_name='$table';"
        if (($found | Select-Object -Last 1) -notmatch '1') { $missing += $table }
    }

    Write-Host ""
    if ($missing.Count -eq 0) {
        Write-Host "Test database is ready. Run the suite with:" -ForegroundColor Green
        Write-Host "    cd backend; .\.venv\Scripts\python.exe -m pytest tests -q" -ForegroundColor White
    }
    else {
        Write-Host "Database created, but these tables are missing: $($missing -join ', ')" -ForegroundColor Yellow
        Write-Host "Re-run this script, or apply schema.sql manually." -ForegroundColor Yellow
    }
}
catch {
    Write-Host ""
    Write-Host "FAILED: $_" -ForegroundColor Red
    if ("$_" -match 'Access denied') {
        Write-Host "That root password was not accepted. Nothing was changed." -ForegroundColor Yellow
    }
    exit 1
}
finally {
    # Always cleared, including on the failure path, so the credential does not
    # outlive this call in the environment of the shell it was run from.
    Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
    $rootPassword = $null
}
