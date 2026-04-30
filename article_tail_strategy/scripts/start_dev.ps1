param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 5174,
    [switch]$NoBackend,
    [switch]$NoFrontend,
    [switch]$SameWindow
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

function Stop-PortListener {
    param([int]$Port)

    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "[port $Port] free"
        return
    }

    $owners = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $owners) {
        if ($processId -eq 0) { continue }
        try {
            $proc = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "[port $Port] killing PID $processId ($($proc.ProcessName))"
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            Write-Warning "[port $Port] failed to kill PID ${processId}: $_"
        }
    }

    # let the OS release the port
    Start-Sleep -Milliseconds 600
}

function Wait-Port {
    param(
        [int]$Port,
        [int]$TimeoutSec = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listening) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Assert-Path {
    param([string]$Path, [string]$Hint)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required path not found: $Path. $Hint"
    }
}

function Start-DevProcess {
    param(
        [string]$Title,
        [string]$WorkDir,
        [string]$InlineCommand
    )

    if ($SameWindow) {
        Write-Host "==> [$Title] running inline (same window)"
        Push-Location $WorkDir
        try {
            powershell -NoProfile -ExecutionPolicy Bypass -Command $InlineCommand
        } finally {
            Pop-Location
        }
        return
    }

    # Wrap the child command with try/catch + Read-Host so the spawned window
    # never closes silently - users can read the failure message.
    # Write the wrapper to a temp .ps1 file and spawn with -File. This avoids
    # PowerShell's notorious -Command argument quoting issues when the command
    # contains quotes, semicolons, or `--`.
    $lines = @(
        "`$Host.UI.RawUI.WindowTitle = '$Title'",
        "Set-Location '$WorkDir'",
        "Write-Host '[$Title] starting'",
        "Write-Host '> $InlineCommand'",
        "Write-Host ''",
        "try {",
        "    $InlineCommand",
        "    `$code = `$LASTEXITCODE",
        "    Write-Host ''",
        "    Write-Host ('[exit ' + `$code + '] press Enter to close')",
        "} catch {",
        "    Write-Host ''",
        "    Write-Host ('[ERROR] ' + `$_) -ForegroundColor Red",
        "    Write-Host 'press Enter to close'",
        "}",
        "[void](Read-Host)"
    )
    $body = $lines -join "`r`n"

    $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "tail-strategy-launch"
    if (-not (Test-Path -LiteralPath $tmpDir)) {
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
    }
    $tmpFile = Join-Path $tmpDir ("launch_" + [guid]::NewGuid().ToString('N') + ".ps1")
    # Use ASCII to avoid BOM/encoding ambiguity in Windows PowerShell 5.1.
    Set-Content -LiteralPath $tmpFile -Value $body -Encoding ASCII

    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $tmpFile
    ) -WindowStyle Normal | Out-Null
}

if (-not $NoBackend) {
    Assert-Path -Path $Backend -Hint "Expected backend folder."
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        throw "Required command 'uv' not found. Install from https://docs.astral.sh/uv/."
    }
    Stop-PortListener -Port $BackendPort

    Write-Host "==> Starting backend on http://127.0.0.1:$BackendPort"
    $backendCmd = "`$env:ARTICLE_STRATEGY_PORT='$BackendPort'; uv run python run_server.py"
    Start-DevProcess -Title "tail-strategy backend :$BackendPort" -WorkDir $Backend -InlineCommand $backendCmd
}

if (-not $NoFrontend) {
    Assert-Path -Path $Frontend -Hint "Expected frontend folder."
    $viteBin = Join-Path $Frontend "node_modules\vite\bin\vite.js"
    Assert-Path -Path $viteBin -Hint "Run 'npm install' under frontend/ first."
    if (-not (Get-Command "node" -ErrorAction SilentlyContinue)) {
        throw "Required command 'node' not found. Install Node.js (>=18)."
    }
    Stop-PortListener -Port $FrontendPort

    Write-Host "==> Starting frontend on http://localhost:$FrontendPort"
    # Invoke node + vite.js directly to bypass npm.ps1 / npm.cmd wrappers.
    # Exit codes come from vite itself, so error output in the spawned window
    # is the real failure message.
    $frontendCmd = "node 'node_modules\vite\bin\vite.js' --host 0.0.0.0 --port $FrontendPort --strictPort"
    Start-DevProcess -Title "tail-strategy frontend :$FrontendPort" -WorkDir $Frontend -InlineCommand $frontendCmd
}

if (-not $SameWindow) {
    if (-not $NoBackend) {
        Write-Host "    waiting for backend port $BackendPort ..."
        if (Wait-Port -Port $BackendPort -TimeoutSec 25) {
            Write-Host "    backend is up: http://127.0.0.1:$BackendPort"
        } else {
            Write-Warning "    backend did not bind port $BackendPort within 25s; check the spawned backend window for errors"
        }
    }
    if (-not $NoFrontend) {
        Write-Host "    waiting for frontend port $FrontendPort ..."
        if (Wait-Port -Port $FrontendPort -TimeoutSec 30) {
            Write-Host "    frontend is up: http://localhost:$FrontendPort"
        } else {
            Write-Warning "    frontend did not bind port $FrontendPort within 30s; check the spawned frontend window for errors"
        }
    }
}

Write-Host ""
Write-Host "==> Done."
if (-not $SameWindow) {
    Write-Host "    Close the spawned PowerShell windows to stop the services."
}
