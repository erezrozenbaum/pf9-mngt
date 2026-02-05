#!/usr/bin/env powershell
# PF9 Management Portal Complete Startup Script
# This script sets up automatic metrics collection and starts all services

param(
    [switch]$StopOnly,
    [switch]$NoSchedule
)

Write-Host "=== PF9 Management Portal Setup ===" -ForegroundColor Cyan

# Change to script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if ($StopOnly) {
    Write-Host "Stopping services and cleaning up..." -ForegroundColor Yellow
    
    # Stop Docker services
    docker-compose down
    
    # Remove scheduled task if it exists
    try {
        schtasks /delete /tn "PF9 Metrics Collection" /f 2>$null
        Write-Host "Removed scheduled task" -ForegroundColor Green
    } catch {
        # Task doesn't exist, that's fine
    }
    
    # Stop any running background collection
    Get-Process | Where-Object {$_.ProcessName -eq "python" -and $_.CommandLine -like "*host_metrics_collector*"} | Stop-Process -Force 2>$null
    
    Write-Host "Cleanup completed" -ForegroundColor Green
    exit 0
}

# Function to setup scheduled task
function Setup-MetricsCollection {
    Write-Host "Setting up automatic metrics collection..." -ForegroundColor Yellow
    
    # Remove existing task if it exists
    schtasks /delete /tn "PF9 Metrics Collection" /f 2>$null | Out-Null
    
    # Create new task to run every 30 minutes
    $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT30M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>$((Get-Date).ToString('yyyy-MM-ddTHH:mm:ss'))</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>python</Command>
      <Arguments>host_metrics_collector.py --once</Arguments>
      <WorkingDirectory>$ScriptDir</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Principals>
    <Principal>
      <RunLevel>LeastPrivilege</RunLevel>
      <UserId>$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
</Task>
"@
    
    try {
        $tempFile = [System.IO.Path]::GetTempFileName() + ".xml"
        $taskXml | Out-File -FilePath $tempFile -Encoding unicode
        
        schtasks /create /tn "PF9 Metrics Collection" /xml $tempFile /f | Out-Null
        Remove-Item $tempFile
        
        Write-Host "✓ Scheduled task created - metrics will be collected every 30 minutes" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "⚠ Could not create scheduled task (may need Admin privileges)" -ForegroundColor Yellow
        Write-Host "  Metrics collection will need to be run manually" -ForegroundColor Yellow
        return $false
    }
}

# Step 1: Stop any running services
Write-Host "1. Stopping existing services..." -ForegroundColor Yellow
docker-compose down 2>$null | Out-Null

# Step 2: Collect initial metrics
Write-Host "2. Collecting initial metrics..." -ForegroundColor Yellow
try {
    $result = python host_metrics_collector.py --once 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Initial metrics collected" -ForegroundColor Green
    } else {
        Write-Host "⚠ Could not collect initial metrics" -ForegroundColor Yellow
        Write-Host $result -ForegroundColor Red
    }
} catch {
    Write-Host "⚠ Python not available or metrics collection failed" -ForegroundColor Yellow
}

# Step 3: Setup automatic metrics collection
if (-not $NoSchedule) {
    $scheduleSuccess = Setup-MetricsCollection
}

# Step 4: Start Docker services
Write-Host "3. Starting Docker services..." -ForegroundColor Yellow
try {
    docker-compose up -d
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ All services started successfully" -ForegroundColor Green
    } else {
        Write-Host "✗ Failed to start Docker services" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "✗ Docker compose failed" -ForegroundColor Red
    exit 1
}

# Step 5: Wait for services to be ready
Write-Host "4. Waiting for services to be ready..." -ForegroundColor Yellow
Start-Sleep 15

# Step 6: Verify services
Write-Host "5. Verifying services..." -ForegroundColor Yellow

$services = @(
    @{Name="Database"; Url="http://localhost:5432"; Container="pf9_db"},
    @{Name="API"; Url="http://localhost:8000/health"; Container="pf9_api"},
    @{Name="UI"; Url="http://localhost:3000"; Container="pf9_ui"},
    @{Name="Monitoring"; Url="http://localhost:8001/health"; Container="pf9_monitoring"}
)

$allGood = $true
foreach ($service in $services) {
    $status = docker ps --filter "name=$($service.Container)" --format "{{.Status}}"
    if ($status -like "*Up*") {
        Write-Host "✓ $($service.Name) is running" -ForegroundColor Green
    } else {
        Write-Host "✗ $($service.Name) is not running" -ForegroundColor Red
        $allGood = $false
    }
}

# Final status
Write-Host ""
if ($allGood) {
    Write-Host "=== SUCCESS ===" -ForegroundColor Green
    Write-Host "PF9 Management Portal is ready!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Services:" -ForegroundColor Cyan
    Write-Host "  • UI:         http://localhost:5173" -ForegroundColor White
    Write-Host "  • API:        http://localhost:8000" -ForegroundColor White  
    Write-Host "  • API Metrics: http://localhost:8000/metrics" -ForegroundColor White
    Write-Host "  • Monitoring: http://localhost:8001" -ForegroundColor White
    Write-Host "  • PgAdmin:    http://localhost:8080" -ForegroundColor White
    Write-Host ""
    
    # Start background metrics collector
    Write-Host "Starting background metrics collector..." -ForegroundColor Cyan
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) {
        $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }
    
    if ($pythonExe) {
        # Kill any existing metrics collector
        Get-Process | Where-Object {$_.ProcessName -match "python" -and $_.CommandLine -like "*host_metrics_collector*"} | Stop-Process -Force -ErrorAction SilentlyContinue
        
        # Start new collector in background
        $logFile = "metrics_collector.log"
        Start-Process -FilePath $pythonExe -ArgumentList "host_metrics_collector.py" -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError "${logFile}.err"
        Start-Sleep -Seconds 2
        
        # Check if it started
        $collectorRunning = Get-Process | Where-Object {$_.ProcessName -match "python" -and $_.CommandLine -like "*host_metrics_collector*"}
        if ($collectorRunning) {
            Write-Host "✓ Background metrics collector started (PID: $($collectorRunning.Id))" -ForegroundColor Green
            Write-Host "  Logs: $logFile" -ForegroundColor Gray
        } else {
            Write-Host "⚠ Metrics collector did not start. Check $logFile for errors" -ForegroundColor Yellow
            Write-Host "  Run manually: python host_metrics_collector.py" -ForegroundColor Yellow
        }
    } else {
        Write-Host "⚠ Python not found. Please run manually: python host_metrics_collector.py" -ForegroundColor Yellow
    }
    
    if ($scheduleSuccess) {
        Write-Host "✓ Automatic metrics collection scheduled" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "To stop: .\startup.ps1 -StopOnly" -ForegroundColor Cyan
} else {
    Write-Host "=== ISSUES DETECTED ===" -ForegroundColor Red
    Write-Host "Some services may not be running correctly." -ForegroundColor Red
    Write-Host "Check logs with: docker-compose logs <service_name>" -ForegroundColor Yellow
    exit 1
}