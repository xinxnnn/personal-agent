param(
    [int]$PortOffset = 0,
    [string]$VenvName = '.venv312'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path (Join-Path $root $VenvName) 'Scripts\python.exe'
$logDir = Join-Path $root 'local_store\bootstrap_logs'
$services = @(
    @{ Name = 'TP'; Port = (8111 + $PortOffset); Module = 'app.tp_app:app' },
    @{ Name = 'AP'; Port = (8112 + $PortOffset); Module = 'app.ap_app:app' },
    @{ Name = 'User'; Port = (8110 + $PortOffset); Module = 'app.experience_app:app' }
)

function Get-ProcessTreeIds([int]$rootPid) {
    $processes = @(Get-CimInstance Win32_Process)
    $childrenByParent = @{}
    foreach ($process in $processes) {
        $parentPid = [int]$process.ParentProcessId
        if (-not $childrenByParent.ContainsKey($parentPid)) {
            $childrenByParent[$parentPid] = [System.Collections.Generic.List[int]]::new()
        }
        $childrenByParent[$parentPid].Add([int]$process.ProcessId)
    }

    $result = [System.Collections.Generic.List[int]]::new()
    $pending = [System.Collections.Generic.Stack[int]]::new()
    $pending.Push($rootPid)
    while ($pending.Count -gt 0) {
        $currentPid = $pending.Pop()
        if ($result.Contains($currentPid)) { continue }
        $result.Add($currentPid)
        if ($childrenByParent.ContainsKey($currentPid)) {
            foreach ($childPid in $childrenByParent[$currentPid]) { $pending.Push($childPid) }
        }
    }
    return $result.ToArray()
}

function Test-ProcessRunning([int]$processId) {
    return [bool](Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue)
}

function Invoke-Taskkill([int]$processId, [switch]$Force) {
    $arguments = "/PID $processId /T"
    if ($Force) { $arguments += ' /F' }
    & $env:ComSpec /d /c "taskkill $arguments >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

function Stop-ProcessTree([int]$rootPid) {
    $treeIds = @(Get-ProcessTreeIds $rootPid)
    $null = Invoke-Taskkill $rootPid
    $deadline = (Get-Date).AddSeconds(8)
    do {
        $runningIds = @(
            foreach ($processId in $treeIds) {
                $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
                if ($process -and $process.Name -ne 'conhost.exe') { $processId }
            }
        )
        if ($runningIds.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $killOrder = @($runningIds)
    [array]::Reverse($killOrder)
    foreach ($processId in $killOrder) {
        if (Test-ProcessRunning $processId) {
            $null = Invoke-Taskkill $processId -Force
        }
    }
    Start-Sleep -Milliseconds 500
    $remainingIds = @(
        foreach ($processId in $treeIds) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
            if ($process -and $process.Name -ne 'conhost.exe') { $processId }
        }
    )
    if ($remainingIds.Count -gt 0) {
        throw "Could not stop process tree (PIDs: $($remainingIds -join ', ')). Check process permissions and retry stop_all.bat."
    }
}

function Stop-OrphanedWorkers([int]$formerRootPid, [hashtable]$item) {
    $processes = @(Get-CimInstance Win32_Process)
    $descendantIds = @(Get-ProcessTreeIds $formerRootPid | Where-Object { $_ -ne $formerRootPid })
    $workerIds = @(
        foreach ($processId in $descendantIds) {
            $candidate = $processes | Where-Object { [int]$_.ProcessId -eq $processId } | Select-Object -First 1
            if (-not $candidate) { continue }
            $samePython = [string]::Equals([string]$candidate.ExecutablePath, $venvPython, [StringComparison]::OrdinalIgnoreCase)
            $commandLine = [string]$candidate.CommandLine
            $isWorker = $commandLine.Contains('--multiprocessing-fork') -or
                ($commandLine.Contains($item.Module) -and $commandLine.Contains("--port $($item.Port)"))
            if ($samePython -and $isWorker) { $processId }
        }
    )
    foreach ($workerId in $workerIds) {
        if (Test-ProcessRunning $workerId) {
            Stop-ProcessTree $workerId
            Write-Host "Stopped orphaned worker PID $workerId for $($item.Name)."
        }
    }
}

foreach ($item in $services) {
    $pidFile = Join-Path $logDir "$($item.Name)-$($item.Port).pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $pidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $savedPid = 0
    if (-not [int]::TryParse($pidText, [ref]$savedPid) -or $savedPid -le 0) {
        throw "Invalid PID file: $pidFile"
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid" -ErrorAction SilentlyContinue
    if ($process) {
        $commandLine = [string]$process.CommandLine
        $sameProject = $commandLine.Contains($venvPython)
        if ($sameProject -and $commandLine.Contains($item.Module) -and $commandLine.Contains("--port $($item.Port)")) {
            Stop-ProcessTree $savedPid
            Write-Host "$($item.Name) service and child processes stopped."
        } else {
            throw "Refusing to stop $($item.Name): PID $savedPid belongs to another process; the PID file was retained."
        }
    } else {
        Stop-OrphanedWorkers $savedPid $item
    }
    Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
}
