param(
    [switch]$SkipPyInstaller,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Desktop = Join-Path $Root "desktop"
$Resources = Join-Path $Desktop "resources"
$BackendResources = Join-Path $Resources "backend"
$FrontendResources = Join-Path $Resources "frontend"

Write-Host "==> Building frontend"
Push-Location $Frontend
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
Pop-Location

Write-Host "==> Preparing Electron resources"
if (Test-Path $Resources) {
    Remove-Item -LiteralPath $Resources -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BackendResources, $FrontendResources | Out-Null
Copy-Item -Path (Join-Path $Frontend "dist\*") -Destination $FrontendResources -Recurse -Force

if (-not $SkipPyInstaller) {
    Write-Host "==> Building backend executable"
    Push-Location $Backend
    uv sync --group dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
    uv run pyinstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name tail-strategy-backend `
        --collect-all pyarrow `
        --collect-all pandas `
        --collect-all numpy `
        --hidden-import uvicorn.loops.auto `
        --hidden-import uvicorn.protocols.http.auto `
        --hidden-import uvicorn.protocols.websockets.auto `
        --hidden-import uvicorn.lifespan.on `
        run_server.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    Pop-Location
}

$BackendExe = Join-Path $Backend "dist\tail-strategy-backend.exe"
if (-not (Test-Path $BackendExe)) {
    throw "Backend executable not found: $BackendExe. Run without -SkipPyInstaller first."
}
Copy-Item -LiteralPath $BackendExe -Destination $BackendResources -Force

Write-Host "==> Installing desktop dependencies"
Push-Location $Desktop
if (-not (Test-Path "node_modules")) {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "Desktop npm install failed." }
}

Write-Host "==> Packaging Electron app"
if ($Installer) {
    npm run dist
} else {
    npm run pack
}
if ($LASTEXITCODE -ne 0) { throw "Electron packaging failed." }
Pop-Location

Write-Host "==> Done"
Write-Host "Output: $Desktop\dist"
