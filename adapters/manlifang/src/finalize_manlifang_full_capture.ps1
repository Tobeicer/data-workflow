param(
    [string]$BatchDir = "",
    [switch]$SkipImageDownload,
    [double]$ImageDelay = 0.25
)

$ErrorActionPreference = "Stop"

$WorkflowRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$StateFile = Join-Path $WorkflowRoot "runtime\tmp\manlifang\current_capture_batch.json"
$State = $null
if (Test-Path -LiteralPath $StateFile) {
    $State = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
}

if (-not $BatchDir) {
    if (-not $State -or -not $State.batch_dir) {
        throw "No active capture batch was found. Provide -BatchDir explicitly."
    }
    $BatchDir = [string]$State.batch_dir
}
$BatchDir = (Resolve-Path -LiteralPath $BatchDir).Path

if ($State) {
    $ProcessIds = @()
    if ($State.listener_process_id) {
        $ProcessIds += [int]$State.listener_process_id
    }
    if ($State.proxy_port) {
        $Listener = Get-NetTCPConnection -State Listen -LocalPort ([int]$State.proxy_port) -ErrorAction SilentlyContinue
        if ($Listener) {
            $ProcessIds += $Listener.OwningProcess
        }
    }
    if ($State.process_id) {
        $ProcessIds += [int]$State.process_id
    }
    foreach ($ProcessId in ($ProcessIds | Select-Object -Unique)) {
        $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($Process) {
            Stop-Process -Id $Process.Id
            $Process.WaitForExit(5000)
            Write-Output "CAPTURE_STOPPED process_id=$($Process.Id)"
        }
    }
}

(Get-Date).ToString("o") | Set-Content -LiteralPath (Join-Path $BatchDir "capture_completed_at.txt") -Encoding UTF8

$Python = (Get-Command python -ErrorAction Stop).Source
$Downloader = Join-Path $PSScriptRoot "download_manlifang_images.py"
$Builder = Join-Path $PSScriptRoot "build_manlifang_capture_workbook.py"
$Sanitizer = Join-Path $PSScriptRoot "sanitize_manlifang_capture.py"

& $Python $Sanitizer $BatchDir
if ($LASTEXITCODE -ne 0) {
    throw "Capture sanitizer failed with exit code $LASTEXITCODE"
}

if (-not $SkipImageDownload) {
    & $Python $Downloader $BatchDir --delay $ImageDelay
    if ($LASTEXITCODE -ne 0) {
        throw "Image downloader failed with exit code $LASTEXITCODE"
    }
}

& $Python $Builder $BatchDir
if ($LASTEXITCODE -ne 0) {
    throw "Workbook builder failed with exit code $LASTEXITCODE"
}

$Workbook = Get-ChildItem -LiteralPath $BatchDir -Filter "*.xlsx" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

Write-Output "CAPTURE_FINALIZED"
Write-Output "batch_dir=$BatchDir"
if ($Workbook) {
    Write-Output "workbook=$($Workbook.FullName)"
}
