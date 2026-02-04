#!/usr/bin/env pwsh
<#
.SYNOPSIS
Automatic monitoring setup script that runs when Docker services start
Ensures metrics collection is always working after docker-compose up

.DESCRIPTION
This script:
1. Collects initial metrics from PF9 hosts
2. Sets up scheduled task for continuous collection (if not exists)
3. Ensures monitoring service has data to serve

Called automatically by Docker monitoring service or manually after docker-compose up
#>

param(
    [switch]$Force
)

# Set error handling
$ErrorActionPreference = "Continue"

Write-Host "🔧 Setting up PF9 monitoring automation..." -ForegroundColor Cyan

# Step 1: Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ .env file not found. Please run: cp .env.template .env" -ForegroundColor Red
    exit 1
}

# Step 2: Collect initial metrics
Write-Host "📊 Collecting initial metrics from PF9 hosts..." -ForegroundColor Yellow
try {
    $result = python host_metrics_collector.py --once 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Initial metrics collected successfully" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Warning: Initial metrics collection had issues: $result" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠️  Warning: Could not collect initial metrics: $_" -ForegroundColor Yellow
}

# Step 3: Check if scheduled task exists
$taskExists = $false
try {
    $task = schtasks /query /tn "PF9 Metrics Collection" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $taskExists = $true
        Write-Host "✅ Scheduled task already exists" -ForegroundColor Green
    }
} catch {
    # Task doesn't exist
}

# Step 4: Create scheduled task if it doesn't exist or if forced
if (-not $taskExists -or $Force) {
    Write-Host "⏰ Setting up scheduled metrics collection..." -ForegroundColor Yellow
    
    $currentDir = Get-Location
    $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonPath) {
        $pythonPath = "python"
    }
    
    $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>$(Get-Date -Format "yyyy-MM-ddTHH:mm:ss")</Date>
    <Author>PF9 Management System</Author>
    <Description>Collects metrics from Platform9 compute nodes every 2 minutes</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT2M</Interval>
      </Repetition>
      <StartBoundary>$(Get-Date -Format "yyyy-MM-ddTHH:mm:ss")</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LimitedUser</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$pythonPath</Command>
      <Arguments>host_metrics_collector.py --once</Arguments>
      <WorkingDirectory>$currentDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

    $tempXmlFile = [System.IO.Path]::GetTempFileName() + ".xml"
    $taskXml | Out-File -FilePath $tempXmlFile -Encoding UTF8
    
    try {
        schtasks /create /tn "PF9 Metrics Collection" /xml $tempXmlFile /f | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Scheduled task created successfully (runs every 2 minutes)" -ForegroundColor Green
        } else {
            Write-Host "⚠️  Warning: Could not create scheduled task" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "⚠️  Warning: Could not create scheduled task: $_" -ForegroundColor Yellow
    } finally {
        Remove-Item $tempXmlFile -ErrorAction SilentlyContinue
    }
}

# Step 5: Verify metrics cache has data
if (Test-Path "metrics_cache.json") {
    $cacheContent = Get-Content "metrics_cache.json" | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($cacheContent -and $cacheContent.hosts -and $cacheContent.hosts.Count -gt 0) {
        Write-Host "✅ Metrics cache has $($cacheContent.hosts.Count) hosts" -ForegroundColor Green
    } else {
        Write-Host "ℹ️  Metrics cache exists but may need time to populate" -ForegroundColor Blue
    }
} else {
    Write-Host "⚠️  Metrics cache file not found" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "🎯 Monitoring setup complete!" -ForegroundColor Green
Write-Host "• Metrics will update every 2 minutes automatically" -ForegroundColor White
Write-Host "• Check monitoring tab in UI: http://localhost:5173" -ForegroundColor White
Write-Host "• Manual collection: python host_metrics_collector.py --once" -ForegroundColor White