@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "CAPTURE_BAT=%SCRIPT_DIR%f1_25_udp_capture.bat"

if not exist "%CAPTURE_BAT%" (
    echo 未找到采集脚本: "%CAPTURE_BAT%"
    pause
    exit /b 1
)

echo ========================================
echo F1 25 数据采集
echo ========================================
echo.
echo 1. 请先打开 F1 25 游戏
echo 2. 在游戏里开启 UDP Telemetry
echo 3. UDP 端口建议设置为 20777
echo.
set /p CAPTURE_MINUTES=请输入采集时长（单位：分钟，直接回车默认 5 分钟）: 

if "%CAPTURE_MINUTES%"=="" set "CAPTURE_MINUTES=5"

set /a CAPTURE_SECONDS=%CAPTURE_MINUTES%*60

echo.
echo 即将开始采集，时长 %CAPTURE_MINUTES% 分钟
echo 输出目录: "%SCRIPT_DIR%captures"
echo.
echo 采集中按 Ctrl + C 可以提前停止。
echo.

call "%CAPTURE_BAT%" --port 20777 --seconds %CAPTURE_SECONDS%
set "EXIT_CODE=%errorlevel%"

echo.
if %EXIT_CODE%==0 (
    echo 采集结束。
    echo JSONL 文件默认保存在 "%SCRIPT_DIR%captures" 目录下。
) else (
    echo 采集失败，退出码: %EXIT_CODE%
)
echo.
pause
exit /b %EXIT_CODE%
