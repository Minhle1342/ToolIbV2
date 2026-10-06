@echo off
setlocal
title Khoi dong Team YOLO Labeling Hub
cd /d "%~dp0"
chcp 65001 > nul

call "%~dp0toollb.bat"
