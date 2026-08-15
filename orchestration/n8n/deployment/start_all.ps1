$ErrorActionPreference = "Stop"

$pgBin = "C:\Users\Administrator\postgres\pgsql\bin"
$pgData = "C:\Users\Administrator\postgres\data"
$pgLog = "C:\Users\Administrator\postgres\pg.log"
$n8nStart = "C:\Users\Administrator\Desktop\data-workflow\runtime\n8n\start_n8n.ps1"

# 1. PostgreSQL
& "$pgBin\pg_isready.exe" -h 127.0.0.1 -p 5432 *> $null
if ($LASTEXITCODE -ne 0) {
    & "$pgBin\pg_ctl.exe" -D $pgData -l $pgLog -o "-p 5432" start
    Start-Sleep -Seconds 3
}

# 2. n8n database
$exists = & "$pgBin\psql.exe" -h 127.0.0.1 -U data_workflow -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='n8n'"
if ($exists -notmatch "1") {
    & "$pgBin\psql.exe" -h 127.0.0.1 -U data_workflow -d data_workflow -v ON_ERROR_STOP=1 -c "CREATE DATABASE n8n OWNER data_workflow;"
}

# 3. n8n
& $n8nStart

# 4. health check
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:5678/healthz" -TimeoutSec 2
        if ($r.status -eq "ok") { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if ($ready) {
    Write-Output "All services are ready: http://localhost:5678"
} else {
    Write-Error "n8n did not become ready; check runtime/n8n/logs/n8n.log"
}
