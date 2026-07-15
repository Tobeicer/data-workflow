[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Invoke-VersionProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName,

        [string[]]$Arguments = @()
    )

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        return [ordered]@{
            available = $false
            path = $null
            version = $null
            exit_code = $null
        }
    }

    $output = @(& $command.Source @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 0
    }

    return [ordered]@{
        available = ($exitCode -eq 0)
        path = $command.Source
        version = (($output -join "`n").Trim())
        exit_code = $exitCode
    }
}

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..\..")).Path
$dataWorkflowRoot = Join-Path $workspace "data-workflow"
$runtimeRoot = Join-Path $dataWorkflowRoot "runtime"
$deliveriesRoot = Join-Path $dataWorkflowRoot "deliveries"
$topologyPath = Join-Path $PSScriptRoot "topology.json"

$n8nProbe = Invoke-VersionProbe -CommandName "n8n" -Arguments @("--version")
$dockerProbe = Invoke-VersionProbe -CommandName "docker" -Arguments @("compose", "version")
$nodeProbe = Invoke-VersionProbe -CommandName "node" -Arguments @("--version")
$powerShellProbe = Invoke-VersionProbe -CommandName "powershell" -Arguments @("-NoProfile", "-Command", '$PSVersionTable.PSVersion.ToString()')

$venvPython = Join-Path $workspace ".venv-data\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonOutput = @(& $venvPython --version 2>&1 | ForEach-Object { $_.ToString() })
    $pythonProbe = [ordered]@{
        available = ($LASTEXITCODE -eq 0)
        path = (Resolve-Path -LiteralPath $venvPython).Path
        version = (($pythonOutput -join "`n").Trim())
        exit_code = $LASTEXITCODE
    }
}
else {
    $pythonProbe = Invoke-VersionProbe -CommandName "python" -Arguments @("--version")
}

$workspaceDriveName = ([System.IO.Path]::GetPathRoot($workspace)).TrimEnd("\").TrimEnd(":")
$workspaceDrive = Get-PSDrive -Name $workspaceDriveName -ErrorAction SilentlyContinue
$redisService = Get-Service -Name "Redis" -ErrorAction SilentlyContinue

$n8nStatus = if ($n8nProbe.available) { "available" } else { "unavailable" }
$runnerStatus = if ($pythonProbe.available -and $powerShellProbe.available) { "available" } else { "unavailable" }

$topology = [ordered]@{
    schema_version = "1.0.0"
    inspected_at = [DateTimeOffset]::UtcNow.ToString("o")
    n8n = [ordered]@{
        status = $n8nStatus
        command = $n8nProbe
        deployment_mode = if ($n8nProbe.available) { "local_command" } else { "not_detected" }
        docker_compose = $dockerProbe
        real_import_export_ready = $false
    }
    runner = [ordered]@{
        status = $runnerStatus
        operating_system = [System.Environment]::OSVersion.VersionString
        workspace = $workspace
        python = $pythonProbe
        powershell = $powerShellProbe
        node = $nodeProbe
        invocation = "local_process_cli"
    }
    runtime_storage = [ordered]@{
        status = if ((Test-Path -LiteralPath $runtimeRoot) -and (Test-Path -LiteralPath $deliveriesRoot)) { "available" } else { "unavailable" }
        runtime_root = $runtimeRoot
        deliveries_root = $deliveriesRoot
        workspace_drive = ([System.IO.Path]::GetPathRoot($workspace))
        free_bytes = if ($null -ne $workspaceDrive) { [int64]$workspaceDrive.Free } else { $null }
        git_tracked = $false
    }
    lock_store = [ordered]@{
        status = "unavailable"
        selected = $null
        detected_candidate = if ($null -ne $redisService) { "redis_service" } else { $null }
        candidate_status = if ($null -ne $redisService) { $redisService.Status.ToString().ToLowerInvariant() } else { "not_detected" }
        atomic_compare_and_set_verified = $false
        lease_renewal_verified = $false
        reason = "No project lock implementation and renewal contract has been verified."
    }
    credential_store = [ordered]@{
        status = if ($n8nProbe.available) { "unverified" } else { "unavailable" }
        owner = "n8n_when_provisioned"
        reference_policy = "identifiers_only"
        local_environment_file = ".env.local"
        local_environment_file_tracked = $false
        values_inspected = $false
    }
    network_boundary = [ordered]@{
        n8n_to_runner = [ordered]@{
            status = if ($n8nProbe.available -and $runnerStatus -eq "available") { "unverified" } else { "blocked" }
            interface = "local_process_cli"
        }
        acquisition = [ordered]@{
            executor = "windows_runner"
            allowed_scope = "public_or_authorized_sources"
        }
        database = [ordered]@{
            status = "reference_only"
            production_business_writes_allowed = $false
        }
    }
    reproduction = [ordered]@{
        script = "powershell -ExecutionPolicy Bypass -File data-workflow/orchestration/n8n/deployment/inspect_environment.ps1"
        test = ".\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_deployment_topology.py -q"
    }
}

$json = $topology | ConvertTo-Json -Depth 10
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($topologyPath, $json + [Environment]::NewLine, $utf8WithoutBom)

Write-Output "Topology written: $topologyPath"
Write-Output "n8n=$n8nStatus runner=$runnerStatus lock_store=$($topology.lock_store.status)"
