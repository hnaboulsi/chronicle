# Life Manager — Windows Setup Script
# Run once in PowerShell (as Administrator) to install and register the backend.
# Usage: Right-click -> "Run with PowerShell"

$ErrorActionPreference = "Stop"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== Life Manager Windows Setup ===" -ForegroundColor Cyan

# 1. Check Python
Write-Host "`n[1/4] Checking Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "  Found: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# 2. Create venv and install requirements
Write-Host "`n[2/4] Installing dependencies..." -ForegroundColor Yellow
Set-Location $BackendDir
if (-not (Test-Path "venv")) {
    python -m venv venv
}
& "venv\Scripts\pip.exe" install -r requirements.txt --quiet
Write-Host "  Done." -ForegroundColor Green

# 3. Create .env if it doesn't exist
Write-Host "`n[3/4] Checking .env file..." -ForegroundColor Yellow
$envPath = Join-Path $BackendDir ".env"
if (-not (Test-Path $envPath)) {
    $apiKey = Read-Host "  Enter your Gemini API key"
    "GEMINI_API_KEY=`"$apiKey`"" | Out-File -FilePath $envPath -Encoding utf8
    Write-Host "  .env created." -ForegroundColor Green
} else {
    Write-Host "  .env already exists, skipping." -ForegroundColor Green
}

# 4. Register with Task Scheduler (runs at login, hidden window)
Write-Host "`n[4/4] Registering startup task..." -ForegroundColor Yellow
$taskName = "LifeManagerBackend"
$batPath = Join-Path $BackendDir "windows_start.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $BackendDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -Hidden -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

# Remove old task if exists
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Host "  Task '$taskName' registered — backend will start at every login." -ForegroundColor Green

# Start it now too
Write-Host "`n  Starting backend now..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $taskName
Start-Sleep 3

# Test it
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/settings" -UseBasicParsing -TimeoutSec 5
    Write-Host "  Backend is running!" -ForegroundColor Green
} catch {
    Write-Host "  Backend may still be starting. Check http://localhost:8000 in a browser." -ForegroundColor Yellow
}

Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Install Tailscale on this Windows laptop: https://tailscale.com/download/windows" -ForegroundColor Gray
Write-Host "  2. Install Tailscale on your Mac and iPhone (same account)" -ForegroundColor Gray
Write-Host "  3. Run: tailscale ip -4   (on this machine) to get your Tailscale IP" -ForegroundColor Gray
Write-Host "  4. On your Mac, set LIFE_MANAGER_BACKEND=http://<tailscale-ip>:8000 in the menubar app config" -ForegroundColor Gray
Write-Host ""
Write-Host "Your backend URL will be: http://<tailscale-ip>:8000" -ForegroundColor Cyan
Write-Host "Dashboard:               http://<tailscale-ip>:8000/dashboard" -ForegroundColor Cyan
