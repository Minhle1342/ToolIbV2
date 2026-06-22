@echo off
setlocal EnableDelayedExpansion

:: Đặt tiêu đề cho cửa sổ CMD
title Dừng Team YOLO Labeling Hub

echo ==========================================================
echo               Dừng Team YOLO Labeling Hub
echo ==========================================================
echo.

:: Tìm PID của tiến trình đang lắng nghe trên cổng 5000
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000" ^| findstr "LISTENING"') do (
    set "FOUND=1"
    echo [INFO] Tìm thấy tiến trình PID: %%a đang chạy trên cổng 5000.
    taskkill /PID %%a /F >nul 2>&1
    if !errorlevel! == 0 (
        echo [OK] Đã tắt tiến trình PID %%a thành công.
    ) else (
        echo [LỖI] Không thể tắt tiến trình PID %%a. Hãy thử chạy với quyền Admin.
    )
)

if "!FOUND!"=="0" (
    echo [INFO] Không tìm thấy tiến trình nào đang chạy trên cổng 5000.
)

endlocal
echo.
echo ----------------------------------------------------------
echo Nhấn phím bất kỳ để đóng cửa sổ này...
pause >nul
