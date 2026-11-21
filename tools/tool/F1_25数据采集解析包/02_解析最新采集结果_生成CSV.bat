@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PARSE_BAT=%SCRIPT_DIR%f1_25_full_parse_to_csv.bat"
set "CAPTURE_DIR=%SCRIPT_DIR%captures"
set "OUTPUT_ROOT=%SCRIPT_DIR%解析结果"

if not exist "%PARSE_BAT%" (
    echo 未找到解析脚本: "%PARSE_BAT%"
    pause
    exit /b 1
)

if not exist "%CAPTURE_DIR%" (
    echo 未找到采集目录: "%CAPTURE_DIR%"
    echo 请先运行“01_开始采集_F1_25数据.bat”
    pause
    exit /b 1
)

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$file = Get-ChildItem -Path '%CAPTURE_DIR%' -Filter '*.jsonl' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($file) { $file.FullName }"`) do set "LATEST_JSONL=%%I"

if not defined LATEST_JSONL (
    echo 在 "%CAPTURE_DIR%" 中没有找到 jsonl 采集文件。
    echo 请先运行“01_开始采集_F1_25数据.bat”
    pause
    exit /b 1
)

for %%F in ("%LATEST_JSONL%") do set "OUTPUT_DIR=%OUTPUT_ROOT%\%%~nF_full_csv"

if not exist "%OUTPUT_ROOT%" mkdir "%OUTPUT_ROOT%"

echo ========================================
echo F1 25 数据解析
echo ========================================
echo.
echo 将解析最新采集文件:
echo "%LATEST_JSONL%"
echo.
echo CSV 输出目录:
echo "%OUTPUT_DIR%"
echo.

call "%PARSE_BAT%" "%LATEST_JSONL%" --output-dir "%OUTPUT_DIR%"
set "EXIT_CODE=%errorlevel%"

echo.
if %EXIT_CODE%==0 (
    echo 解析完成。
    echo CSV 结果保存在 "%OUTPUT_DIR%"
) else (
    echo 解析失败，退出码: %EXIT_CODE%
    echo 注意：解析步骤需要 Windows 已安装 Python 3。
)
echo.
pause
exit /b %EXIT_CODE%
