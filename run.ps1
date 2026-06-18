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
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "[VENV] Đã phát hiện môi trường ảo (.venv). Sử dụng Python từ .venv..." -ForegroundColor Green
    $PythonPath = ".venv\Scripts\python.exe"
} else {
    Write-Host "[HỆ THỐNG] Không tìm thấy thư mục .venv. Sử dụng Python hệ thống..." -ForegroundColor Yellow
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
