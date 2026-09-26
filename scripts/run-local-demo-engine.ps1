$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'engine\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Engine virtual environment is missing: $python" }
Set-Location -LiteralPath $repoRoot
Write-Host 'ContextRail engine + Freshservice + Slack on http://127.0.0.1:8117' -ForegroundColor Cyan
Write-Host 'Keep this terminal open while using the demo.' -ForegroundColor DarkGray
& $python 'scripts/voice-pilot-local.py' --freshservice --slack --port 8117
if ($LASTEXITCODE -ne 0) { Write-Host "Engine exited with code $LASTEXITCODE" -ForegroundColor Red }
