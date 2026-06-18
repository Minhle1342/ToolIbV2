# Chuyển thư mục làm việc về thư mục chứa file script này
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

Clear-Host
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "              🚀 TEAM YOLO LABELING HUB 🏷️               " -ForegroundColor White -BackgroundColor Blue
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# Kiểm tra Virtual Environment (.venv)
$PythonPath = "python"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[HỆ THỐNG] Không tìm thấy môi trường ảo (.venv). Đang tiến hành tạo mới..." -ForegroundColor Yellow
    
    $pythonCheck = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCheck) {
        Write-Host "[LỖI] Không tìm thấy lệnh 'python' trên hệ thống. Vui lòng cài đặt Python và thử lại." -ForegroundColor Red
        Pause
        Exit
    }

    Write-Host "[VENV] Tạo môi trường ảo .venv..." -ForegroundColor Cyan
    python -m venv .venv

    if (Test-Path ".venv\Scripts\python.exe") {
        Write-Host "[VENV] Đã tạo môi trường ảo thành công." -ForegroundColor Green
        
        if (Test-Path "requirements.txt") {
            Write-Host "[PIP] Đang cài đặt các thư viện từ requirements.txt..." -ForegroundColor Cyan
            & ".venv\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
            & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
            Write-Host "[PIP] Hoàn tất cài đặt thư viện Python!" -ForegroundColor Green
        }
        $PythonPath = ".venv\Scripts\python.exe"
    } else {
        Write-Host "[LỖI] Tạo môi trường ảo thất bại. Sẽ thử sử dụng Python hệ thống..." -ForegroundColor Red
    }
} else {
    Write-Host "[VENV] Đã phát hiện môi trường ảo (.venv). Sử dụng Python từ .venv..." -ForegroundColor Green
    $PythonPath = ".venv\Scripts\python.exe"
}

# Kiểm tra thư viện Node.js (nếu có package.json)
if ((Test-Path "package.json") -and -not (Test-Path "node_modules")) {
    $npmCheck = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCheck) {
        Write-Host "[NPM] Đang cài đặt thư viện Node.js (TailwindCSS)..." -ForegroundColor Cyan
        npm install
        Write-Host "[NPM] Hoàn tất cài đặt thư viện Node.js!" -ForegroundColor Green
    } else {
        Write-Host "[CẢNH BÁO] Cần Node.js (npm) để cài thư viện giao diện nhưng không tìm thấy trên máy." -ForegroundColor Yellow
    }
}

# Tự động mở trình duyệt web sau 1.5 giây
Start-Job -ScriptBlock {
    Start-Sleep -Milliseconds 1500
    Start-Process "http://localhost:5000"
} | Out-Null

# Khởi chạy Flask App
Write-Host "[SERVER] Đang khởi chạy Flask server tại http://localhost:5000..." -ForegroundColor Cyan
Write-Host "[LƯU Ý] Nhấn Ctrl + C trong cửa sổ này để tắt Server." -ForegroundColor DarkGray
Write-Host "----------------------------------------------------------" -ForegroundColor Gray

& $PythonPath app.py

Write-Host ""
Write-Host "Nhấn phím bất kỳ để đóng cửa sổ này..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
