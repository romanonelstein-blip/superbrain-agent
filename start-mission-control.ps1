$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "work") | Out-Null

Write-Host ""
Write-Host "============================================================"
Write-Host " SuperBrain SB-027 - WORLD MODEL + OSINT Mission Control"
Write-Host "============================================================"
Write-Host "Stopping stale SuperBrain Mission Control servers..."
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'nexus1000[.]sb022_server' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile
    Write-Host "Created .env from .env.example."
}

Write-Host "Starting this exact build on a fresh local port..."
$db = Join-Path $PSScriptRoot "work\superbrain-state.db"
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3 -m nexus1000.sb022_server --host 127.0.0.1 --port 0 --database $db --open-browser
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw "Python 3.11+ was not found." }
    & python -m nexus1000.sb022_server --host 127.0.0.1 --port 0 --database $db --open-browser
}
