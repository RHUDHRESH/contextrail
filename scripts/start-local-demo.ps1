$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$engineScript = Join-Path $PSScriptRoot 'run-local-demo-engine.ps1'
$webScript = Join-Path $PSScriptRoot 'run-local-demo-web.ps1'
$statusScript = Join-Path $PSScriptRoot 'show-local-demo-status.ps1'
foreach ($script in @($engineScript, $webScript, $statusScript)) {
    if (-not (Test-Path -LiteralPath $script)) { throw "Missing demo script: $script" }
}
function Test-DemoUrl([string] $url) {
    try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
    catch { return $false }
}
if (-not (Test-DemoUrl 'http://127.0.0.1:8117/health')) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $engineScript) -WorkingDirectory $repoRoot -WindowStyle Normal
}
if (-not (Test-DemoUrl 'http://127.0.0.1:3100/engine-demo')) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $webScript) -WorkingDirectory $repoRoot -WindowStyle Normal
}
$statusRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*$statusScript*"
} | Select-Object -First 1
if (-not $statusRunning) {
    Start-Process -FilePath 'wt.exe' -ArgumentList @('-w', 'new', 'new-tab', '--title', 'ContextRail-Demo', '--',
        'powershell.exe', '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $statusScript) -WindowStyle Normal
}
Write-Host 'ContextRail services are running independently; Windows Terminal shows their status.' -ForegroundColor Green
