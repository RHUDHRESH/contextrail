$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$localEnv = Join-Path $repoRoot '.env'
if (-not (Test-Path -LiteralPath $localEnv)) { throw "Local .env is missing: $localEnv" }
$tokenLine = Get-Content -LiteralPath $localEnv | Where-Object { $_ -match '^ENGINE_TOKEN=' } | Select-Object -Last 1
if (-not $tokenLine) { throw 'ENGINE_TOKEN is missing from .env' }
$env:ENGINE_TOKEN = $tokenLine.Substring('ENGINE_TOKEN='.Length).Trim()
$env:DEMO_ENGINE_URL = 'http://127.0.0.1:8117'
Set-Location -LiteralPath $repoRoot
Write-Host 'ContextRail web app on http://127.0.0.1:3100/engine-demo' -ForegroundColor Cyan
Write-Host 'Keep this terminal open while using the demo.' -ForegroundColor DarkGray
& npm.cmd run dev
if ($LASTEXITCODE -ne 0) { Write-Host "Web app exited with code $LASTEXITCODE" -ForegroundColor Red }
