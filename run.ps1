[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Chuyen thu muc lam viec ve thu muc chua file script nay
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

$postgresConfigLoaded = $false
$postgresEnvironmentPath = Join-Path $scriptPath '.env.postgres.local'
if (Test-Path -LiteralPath $postgresEnvironmentPath) {
    foreach ($line in Get-Content -LiteralPath $postgresEnvironmentPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) {
            continue
        }
        $name, $value = $trimmed -split '=', 2
        if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
    $postgresConfigLoaded = $true
}

Clear-Host
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "              TEAM YOLO LABELING HUB                      " -ForegroundColor White -BackgroundColor Blue
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
if ($postgresConfigLoaded) {
    Write-Host "[DATABASE] Da nap cau hinh PostgreSQL local." -ForegroundColor Green
}

# Kiem tra Virtual Environment (.venv)
$PythonPath = "python"

# Kiem tra xem .venv co hoat dong hop le khong
$venvValid = $false
if (Test-Path ".venv\Scripts\python.exe") {
    $testVenv = & ".venv\Scripts\python.exe" --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $venvValid = $true
        Write-Host "[VENV] Da phat hien moi truong ao (.venv) hop le. Su dung Python tu .venv..." -ForegroundColor Green
        $PythonPath = ".venv\Scripts\python.exe"
    } else {
        Write-Host "[CANH BAO] Thu muc .venv hien tai bi loi (khong the truy cap Python goc)." -ForegroundColor Yellow
        Write-Host "[HE THONG] Dang tien hanh don dep .venv bi loi..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
    }
}

if (-not $venvValid) {
    Write-Host "[HE THONG] Dang kiem tra moi truong Python..." -ForegroundColor Cyan
    
    $pythonCheck = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCheck) {
        Write-Host "----------------------------------------------------------" -ForegroundColor Red
        Write-Host "[LOI CRITICAL] Khong the truy cap hoac tim thay Python tren may!" -ForegroundColor Red
        Write-Host "Nguyen nhan: Thu muc Python goc (C:\Users\HP\AppData\Local\Programs\Python) bi chan quyen (Access is Denied)." -ForegroundColor Yellow
        Write-Host "CACH SUA DE DANG:" -ForegroundColor Green
        Write-Host "  1. Nhap chuot phai vao file 'Fix-PythonPermissions.bat' trong thu muc nay" -ForegroundColor White
        Write-Host "  2. Chon 'Run as administrator' (Chay voi quyen Quan tri vien)" -ForegroundColor White
        Write-Host "  3. Thu chay lai 'Toollb.bat'!" -ForegroundColor White
        Write-Host "----------------------------------------------------------" -ForegroundColor Red
        Write-Host "Nhan phim bat ky de dong..." -ForegroundColor Yellow
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        Exit
    }

    Write-Host "[VENV] Tao moi moi truong ao .venv..." -ForegroundColor Cyan
    python -m venv .venv

    if (Test-Path ".venv\Scripts\python.exe") {
        Write-Host "[VENV] Da tao moi truong ao thanh cong." -ForegroundColor Green
        
        if (Test-Path "requirements.txt") {
            Write-Host "[PIP] Dang cai dat cac thu vien tu requirements.txt..." -ForegroundColor Cyan
            & ".venv\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
            & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
            Write-Host "[PIP] Hoan tat cai dat thu vien Python!" -ForegroundColor Green
        }
        $PythonPath = ".venv\Scripts\python.exe"
    } else {
        Write-Host "[CANH BAO] Tao moi truong ao that bai. Se thu su dung Python he thong..." -ForegroundColor Red
    }
}

# Kiem tra thu vien Node.js (neu co package.json)
if ((Test-Path "package.json") -and -not (Test-Path "node_modules")) {
    $npmCheck = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCheck) {
        Write-Host "[NPM] Dang cai dat thu vien Node.js (TailwindCSS)..." -ForegroundColor Cyan
        npm install
        Write-Host "[NPM] Hoan tat cai dat thu vien Node.js!" -ForegroundColor Green
    } else {
        Write-Host "[CANH BAO] Can Node.js (npm) de cai thu vien giao dien nhung khong tim thay tren may." -ForegroundColor Yellow
    }
}

# Tu dong mo trinh duyiet web sau 1.5 giay
Start-Job -ScriptBlock {
    Start-Sleep -Milliseconds 1500
    Start-Process "https://localhost:5000"
} | Out-Null

# Khoi chay Flask App
Write-Host "[SERVER] Dang khoi chay Flask server bao mat tai https://localhost:5000..." -ForegroundColor Cyan
Write-Host "[DATABASE] Dang khoi tao va kiem tra schema truoc khi chay cac process..." -ForegroundColor Cyan
& $PythonPath -c "from app import create_app; create_app()"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[LOI] Khong the khoi tao database. Scheduler va Flask chua duoc khoi chay." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[DATABASE] Schema da san sang." -ForegroundColor Green
Write-Host "[SCHEDULER] Dang khoi chay training control plane rieng..." -ForegroundColor Cyan
Write-Host "[LUU Y] Nhan Ctrl + C trong cua so nay de tat Server." -ForegroundColor DarkGray
Write-Host "----------------------------------------------------------" -ForegroundColor Gray

$schedulerProcess = $null
try {
    $schedulerProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @("training_scheduler.py") `
        -PassThru `
        -WindowStyle Hidden
    Start-Sleep -Milliseconds 300
    if ($schedulerProcess.HasExited) {
        Write-Host "[CANH BAO] Training scheduler khong khoi dong duoc. Chay run_training_scheduler.ps1 de xem log." -ForegroundColor Yellow
        $schedulerProcess = $null
    } else {
        Write-Host "[SCHEDULER] Da khoi chay (PID $($schedulerProcess.Id))." -ForegroundColor Green
    }

    & $PythonPath app.py
} finally {
    if ($null -ne $schedulerProcess -and -not $schedulerProcess.HasExited) {
        Write-Host "[SCHEDULER] Dang dung training control plane..." -ForegroundColor DarkGray
        Stop-Process -Id $schedulerProcess.Id -ErrorAction SilentlyContinue
        Wait-Process -Id $schedulerProcess.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Nhan phim bat ky de dong cua so nay..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
