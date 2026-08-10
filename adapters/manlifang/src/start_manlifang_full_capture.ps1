param(
    [string]$BatchId = ("manlifang_full_" + (Get-Date -Format "yyyyMMdd_HHmmss")),
    [int]$ProxyPort = 8080,
    [int]$WebPort = 8081
)

$ErrorActionPreference = "Stop"

$WorkflowRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$ProjectRoot = (Resolve-Path (Join-Path $WorkflowRoot "..")).Path
$Mitmweb = Join-Path $ProjectRoot ".venv-mitmproxy\Scripts\mitmweb.exe"
$Addon = Join-Path $PSScriptRoot "capture_manlifang_full.py"
$BatchDir = Join-Path $WorkflowRoot ("runtime\runs\manlifang\" + $BatchId)
$StateFile = Join-Path $WorkflowRoot "runtime\tmp\manlifang\current_capture_batch.json"

if (-not (Test-Path -LiteralPath $Mitmweb)) {
    throw "mitmweb not found: $Mitmweb"
}
if (-not (Test-Path -LiteralPath $Addon)) {
    throw "capture addon not found: $Addon"
}

$BusyPorts = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @($ProxyPort, $WebPort) }
if ($BusyPorts) {
    throw "Port $ProxyPort or $WebPort is already in use."
}

New-Item -ItemType Directory -Path $BatchDir -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $StateFile) -Force | Out-Null
$StdoutLog = Join-Path $BatchDir "mitmweb.stdout.log"
$StderrLog = Join-Path $BatchDir "mitmweb.stderr.log"

$Arguments = @(
    "--listen-host", "0.0.0.0",
    "--listen-port", "$ProxyPort",
    "--web-host", "127.0.0.1",
    "--web-port", "$WebPort",
    "--set", "block_global=false",
    "--set", "connection_strategy=lazy",
    "--set", "web_open_browser=false",
    "--set", "manlifang_capture_dir=$BatchDir",
    "-s", $Addon
)

$StartParameters = @{
    FilePath = $Mitmweb
    ArgumentList = $Arguments
    WorkingDirectory = $ProjectRoot
    RedirectStandardOutput = $StdoutLog
    RedirectStandardError = $StderrLog
    WindowStyle = "Hidden"
    PassThru = $true
}
$Process = Start-Process @StartParameters

$Ready = $false
for ($Index = 0; $Index -lt 40; $Index++) {
    Start-Sleep -Milliseconds 250
    if ($Process.HasExited) {
        $ErrorText = if (Test-Path -LiteralPath $StderrLog) { Get-Content -LiteralPath $StderrLog -Raw } else { "" }
        throw "mitmweb exited during startup. $ErrorText"
    }
    $Listening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $ProxyPort }
    if ($Listening) {
        $Ready = $true
        break
    }
}
if (-not $Ready) {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    throw "mitmweb did not listen on port $ProxyPort within 10 seconds."
}

$LanAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.InterfaceAlias -notlike "*vEthernet*"
    } |
    Select-Object -First 1 -ExpandProperty IPAddress

$State = [ordered]@{
    batch_id = $BatchId
    batch_dir = $BatchDir
    process_id = $Process.Id
    listener_process_id = ($Listening | Select-Object -First 1 -ExpandProperty OwningProcess)
    proxy_host = $LanAddress
    proxy_port = $ProxyPort
    web_url = "http://127.0.0.1:$WebPort"
    started_at = (Get-Date).ToString("o")
}
$State | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8

Write-Output "CAPTURE_STARTED"
Write-Output "batch_dir=$BatchDir"
Write-Output "process_id=$($Process.Id)"
Write-Output "phone_proxy=$LanAddress`:$ProxyPort"
Write-Output "mitmweb=http://127.0.0.1:$WebPort"
