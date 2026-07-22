@echo off
title Sua quyen truy cap Python va don dep .venv
chcp 65001 > nul
cd /d "%~dp0"

echo ==========================================================
echo           SỬA LỖI QUYỀN TRUY CẬP PYTHON (ACCESS DENIED)
echo ==========================================================
echo.

:: Kiểm tra quyền Admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [CẢNH BÁO] File này cần chạy dưới quyền Administrator!
    echo.
    echo Vui lòng nhấp chuột phải vào file 'Fix-PythonPermissions.bat' 
    echo và chọn "Run as administrator" (Chạy với quyền Quản trị viên).
    echo.
    pause
    exit /b
)

echo [1/3] Đang cấp quyền truy cập đầy đủ cho thư mục Python...
icacls "C:\Users\HP\AppData\Local\Programs\Python" /grant "%USERNAME%":(OI)(CI)F /T /C /Q
icacls "C:\Users\HP\AppData\Local\Programs\Python" /grant Users:(OI)(CI)F /T /C /Q

echo [2/3] Đang dọn dẹp môi trường ảo (.venv) bị lỗi...
if exist ".venv" (
    rd /s /q ".venv"
    echo Đã xóa thư mục .venv cũ.
)

echo [3/3] Hoàn tất!
echo.
echo ==========================================================
echo Sửa lỗi hoàn tất! Bạn có thể chạy lại file Toollb.bat.
echo ==========================================================
echo.
pause
