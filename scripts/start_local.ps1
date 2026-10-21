param(
    [ValidateSet('all', 'user', 'tp', 'ap')]
    [string]$Service = 'all',
    [switch]$NoBrowser,
    [int]$PortOffset = 0,
    [string]$VenvName = '.venv312'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$requirements = Join-Path $root 'requirements-local.txt'
$venv = Join-Path $root $VenvName
$venvPython = Join-Path $venv 'Scripts\python.exe'
$env:PYTHONPATH = $root

function Test-PythonCommand([string]$file, [string[]]$arguments) {
    try {
        $version = & $file @arguments -c 'import sys; print(int(sys.version_info >= (3, 11)))' 2>$null
        return ($LASTEXITCODE -eq 0 -and ($version | Select-Object -Last 1) -eq '1')
    } catch { return $false }
}

function Find-Python {
    $candidates = @(
        @{ File = 'py'; Args = @('-3.12') },
        @{ File = 'py'; Args = @('-3.11') },
        @{ File = 'python'; Args = @() },
        @{ File = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'); Args = @() },
        @{ File = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'); Args = @() }
    )
    foreach ($item in $candidates) {
        if (Test-PythonCommand $item.File $item.Args) { return $item }
    }
    return $null
}

function Ensure-Python {
    $candidate = Find-Python
    if ($candidate) { return $candidate }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw '需要 Python 3.11 或 3.12；当前未检测到 Python 或 winget。请安装 Python 3.12 后重新双击 BAT。'
    }
    Write-Host '未检测到 Python 3.11+，正在通过 winget 为当前用户安装 Python 3.12…'
    & winget install --id Python.Python.3.12 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Python 自动安装失败。请手动安装 Python 3.12 后重新双击 BAT。' }
    $candidate = Find-Python
    if (-not $candidate) { throw 'Python 安装完成但当前终端找不到解释器。请重新打开 BAT；如仍失败，请检查 Python 安装。' }
    return $candidate
}

function Ensure-Environment {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $candidate = Ensure-Python
        Write-Host "正在创建本地 Python 环境：$VenvName"
        & $candidate.File @($candidate.Args) -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) { throw '创建 Python 虚拟环境失败。' }
    }
    & $venvPython -m pip --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '当前 Python 环境缺少 pip，正在尝试通过 ensurepip 修复…'
        & $venvPython -m ensurepip --upgrade | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '虚拟环境缺少 pip，且 ensurepip 修复失败。请重新创建 Python 虚拟环境后再启动。' }
    }
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $marker = Join-Path $venv '.requirements-local.sha256'
    $installed = (Test-Path -LiteralPath $marker) -and ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $hash)
    if ($installed) {
        & $venvPython -c 'import fastapi, uvicorn, httpx, pydantic, cryptography, pymysql, multipart' 2>$null | Out-Null
        $installed = ($LASTEXITCODE -eq 0)
    }
    if (-not $installed) {
        Write-Host '正在安装三个网页服务的依赖；首次运行需要网络连接…'
        & $venvPython -m pip install --disable-pip-version-check -r $requirements | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。请检查网络，或手动运行 .venv312\Scripts\python.exe -m pip install -r requirements-local.txt。' }
        Set-Content -LiteralPath $marker -Value $hash -Encoding ASCII
    }
    $anpRequirements = Join-Path $root 'requirements-anp.txt'
    $anpSource = Join-Path $root 'anp-proxy'
    if ((Test-Path -LiteralPath $anpRequirements) -and (Test-Path -LiteralPath $anpSource -PathType Container)) {
        $anpHash = (Get-FileHash -LiteralPath $anpRequirements -Algorithm SHA256).Hash
        $anpMarker = Join-Path $venv '.requirements-anp.sha256'
        $anpInstalled = (Test-Path -LiteralPath $anpMarker) -and ((Get-Content -LiteralPath $anpMarker -Raw).Trim() -eq $anpHash)
        if ($anpInstalled) {
            & $venvPython -c 'import anp_proxy' 2>$null | Out-Null
            $anpInstalled = ($LASTEXITCODE -eq 0)
        }
        if (-not $anpInstalled) {
            Write-Host '正在安装本地 Octopus 组通信所需的 ANP 依赖…'
            & $venvPython -m pip install --disable-pip-version-check -r $anpRequirements | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'ANP 依赖安装失败。请确认项目包含 anp-proxy 目录并检查网络。' }
            Set-Content -LiteralPath $anpMarker -Value $anpHash -Encoding ASCII
        }
    } elseif (Test-Path -LiteralPath $anpRequirements) {
        Write-Warning '未找到 anp-proxy 源码目录；网页仍可启动，但 Octopus 组内 ANP 通信需要该目录和 requirements-anp.txt 中的依赖。'
    }
    return $venvPython
}

function Test-Ready([hashtable]$item) {
    $url = "http://127.0.0.1:$($item.Port)$($item.Login)"
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -eq 200 -and $response.Content.Contains($item.Marker))
    } catch { return $false }
}

function Start-Service([hashtable]$item, [string]$python) {
    if (Test-Ready $item) {
        Write-Host "$($item.Name) 已在端口 $($item.Port) 运行。"
        return
    }
    $listener = Get-NetTCPConnection -LocalPort $item.Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw "端口 $($item.Port) 已被其他程序占用；不会结束该进程。请先关闭冲突程序。" }

    $logDir = Join-Path $root 'local_store\bootstrap_logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $outLog = Join-Path $logDir "$($item.Name)-$($item.Port).out.log"
    $errLog = Join-Path $logDir "$($item.Name)-$($item.Port).err.log"
    $arguments = @('-m', 'uvicorn', $item.Module, '--host', '127.0.0.1', '--port', [string]$item.Port)
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline) {
        if (Test-Ready $item) {
            Set-Content -LiteralPath (Join-Path $logDir "$($item.Name)-$($item.Port).pid") -Value $process.Id -Encoding ASCII
            Write-Host "$($item.Name) 已启动：http://127.0.0.1:$($item.Port)$($item.Page)"
            return
        }
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    $lastError = if (Test-Path -LiteralPath $errLog) { (Get-Content -LiteralPath $errLog -Tail 12) -join [Environment]::NewLine } else { '' }
    if (-not $process.HasExited) {
        $null = & taskkill.exe /PID $process.Id /T /F 2>&1
        $process.WaitForExit(3000)
        $process.Refresh()
        if (-not $process.HasExited) {
            throw "$($item.Name) failed to start and cleanup failed; PID $($process.Id) is still running. Retry after running stop_all.bat.`n$lastError"
        }
    }
    throw "$($item.Name) 未能启动。请查看 $errLog`n$lastError"
}

try {
    Set-Location $root
    $python = Ensure-Environment
    $services = @(
        @{ Name = 'TP'; Module = 'app.tp_app:app'; Port = (8111 + $PortOffset); Login = '/tp/login'; Page = '/tp'; Marker = '身份审核登录' },
        @{ Name = 'AP'; Module = 'app.ap_app:app'; Port = (8112 + $PortOffset); Login = '/ap/login'; Page = '/ap'; Marker = 'Agent Provider Console' },
        @{ Name = 'User'; Module = 'app.experience_app:app'; Port = (8110 + $PortOffset); Login = '/user/login'; Page = '/user'; Marker = '智契化身' }
    )
    foreach ($item in $services) {
        if ($Service -eq 'all' -or $Service -eq $item.Name.ToLowerInvariant()) { Start-Service $item $python }
    }
    if (-not $NoBrowser) {
        $page = if ($Service -eq 'all') { $services[2] } else { $services | Where-Object { $_.Name.ToLowerInvariant() -eq $Service } | Select-Object -First 1 }
        Start-Process "http://127.0.0.1:$($page.Port)$($page.Page)"
    }
    Write-Host '完成。登录账号见 README.md。'
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
