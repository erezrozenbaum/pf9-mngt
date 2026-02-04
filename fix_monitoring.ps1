#!/usr/bin/env pwsh

<#
.SYNOPSIS
Simple script to fix monitoring after docker-compose up -d

.DESCRIPTION  
When you run docker-compose up -d manually instead of startup.ps1,
monitoring won't work because no data is collected from PF9 hosts.
This script fixes that issue.
#>

Write-Host "🔧 Quick Fix: Setting up monitoring..." -ForegroundColor Cyan

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ Error: .env file missing" -ForegroundColor Red
    Write-Host "   Please run: cp .env.template .env" -ForegroundColor Yellow
    exit 1
}

# Collect initial metrics
Write-Host "📊 Collecting metrics from PF9 hosts..." -ForegroundColor Yellow
try {
    python host_metrics_collector.py --once
    Write-Host "✅ Metrics collected successfully!" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to collect metrics: $_" -ForegroundColor Red
    exit 1
}

# Check if scheduled task exists
$taskExists = (schtasks /query /tn "PF9 Metrics Collection" 2>$null) -and ($LASTEXITCODE -eq 0)

if (-not $taskExists) {
    Write-Host "⏰ Creating scheduled task for continuous collection..." -ForegroundColor Yellow
    
    $action = New-ScheduledTaskAction -Execute "python" -Argument "host_metrics_collector.py --once" -WorkingDirectory (Get-Location)
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 2)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    
    try {
        Register-ScheduledTask -TaskName "PF9 Metrics Collection" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
        Write-Host "✅ Scheduled task created (runs every 30 minutes)" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ Could not create scheduled task: $_" -ForegroundColor Yellow
        Write-Host "   You can manually run: python host_metrics_collector.py --once" -ForegroundColor Blue
    }
} else {
    Write-Host "✅ Scheduled task already exists" -ForegroundColor Green
}

Write-Host ""
Write-Host "🎯 Monitoring setup complete!" -ForegroundColor Green
Write-Host "📊 Check: http://localhost:5173 (Monitoring tab)" -ForegroundColor White
Write-Host "🔄 Data updates every 30 minutes automatically" -ForegroundColor White