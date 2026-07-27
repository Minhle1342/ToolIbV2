[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptRoot

$pythonExecutable = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $pythonExecutable = ".venv\Scripts\python.exe"
}

Write-Host "[SCHEDULER] Starting ToolIbV2 training control plane..." -ForegroundColor Cyan
Write-Host "[SCHEDULER] Press Ctrl+C to stop." -ForegroundColor DarkGray
& $pythonExecutable training_scheduler.py
