$ErrorActionPreference = "SilentlyContinue"

$pids = Get-NetTCPConnection -LocalPort 5678 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid in $pids) {
    Stop-Process -Id $pid -Force
}

& "C:\Users\Administrator\postgres\pgsql\bin\pg_ctl.exe" -D "C:\Users\Administrator\postgres\data" stop -m fast

Write-Output "n8n and local PostgreSQL stopped"
