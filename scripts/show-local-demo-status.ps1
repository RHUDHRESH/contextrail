$ErrorActionPreference = 'Continue'
Write-Host 'ContextRail local demo is running in separate processes.' -ForegroundColor Cyan
Write-Host 'Open http://127.0.0.1:3100/engine-demo' -ForegroundColor Green
Write-Host 'This status terminal can be closed without stopping the app.' -ForegroundColor DarkGray
while ($true) {
    $web = try { (Invoke-WebRequest -Uri 'http://127.0.0.1:3100/engine-demo' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 'offline' }
    $engine = try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8117/health' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 'offline' }
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  Web: $web  Engine: $engine"
    Start-Sleep -Seconds 10
}
