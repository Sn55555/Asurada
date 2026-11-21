@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "HOST=0.0.0.0"
set "PORT=20777"
set "OUTPUT="
set "SECONDS="
set "MAX_PACKETS="
set "BUFFER_SIZE=65535"
set "TIMEOUT=0.5"
set "PREVIEW_BYTES=16"
set "SCRIPT_DIR=%~dp0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="-h" goto show_help
if /I "%~1"=="--help" goto show_help

if /I "%~1"=="--host" (
    if "%~2"=="" goto missing_value
    set "HOST=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--port" (
    if "%~2"=="" goto missing_value
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--output" (
    if "%~2"=="" goto missing_value
    set "OUTPUT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--seconds" (
    if "%~2"=="" goto missing_value
    set "SECONDS=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--max-packets" (
    if "%~2"=="" goto missing_value
    set "MAX_PACKETS=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--buffer-size" (
    if "%~2"=="" goto missing_value
    set "BUFFER_SIZE=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--timeout" (
    if "%~2"=="" goto missing_value
    set "TIMEOUT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--preview-bytes" (
    if "%~2"=="" goto missing_value
    set "PREVIEW_BYTES=%~2"
    shift
    shift
    goto parse_args
)

echo Unknown argument: %~1
echo.
goto show_help

:missing_value
echo Missing value for argument: %~1
exit /b 2

:args_done
if not defined OUTPUT (
    for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd_HHmmss')"') do set "STAMP=%%I"
    set "OUTPUT=%SCRIPT_DIR%captures\f1_25_udp_capture_%STAMP%.jsonl"
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$hostValue = [Environment]::GetEnvironmentVariable('HOST', 'Process');" ^
  "$portValue = [Environment]::GetEnvironmentVariable('PORT', 'Process');" ^
  "$outputValue = [Environment]::GetEnvironmentVariable('OUTPUT', 'Process');" ^
  "$secondsValue = [Environment]::GetEnvironmentVariable('SECONDS', 'Process');" ^
  "$maxPacketsValue = [Environment]::GetEnvironmentVariable('MAX_PACKETS', 'Process');" ^
  "$bufferSizeValue = [Environment]::GetEnvironmentVariable('BUFFER_SIZE', 'Process');" ^
  "$timeoutValue = [Environment]::GetEnvironmentVariable('TIMEOUT', 'Process');" ^
  "$previewBytesValue = [Environment]::GetEnvironmentVariable('PREVIEW_BYTES', 'Process');" ^
  "function Test-Positive([string]$name, $value) { if ($null -ne $value -and $value -le 0) { throw ""$name must be greater than 0"" } }" ^
  "$hostIp = [string]$hostValue;" ^
  "$port = [int]$portValue;" ^
  "$outputPath = [System.IO.Path]::GetFullPath($outputValue);" ^
  "$seconds = if ([string]::IsNullOrWhiteSpace($secondsValue)) { $null } else { [double]$secondsValue };" ^
  "$maxPackets = if ([string]::IsNullOrWhiteSpace($maxPacketsValue)) { $null } else { [int]$maxPacketsValue };" ^
  "$bufferSize = [int]$bufferSizeValue;" ^
  "$timeout = [double]$timeoutValue;" ^
  "$previewBytes = [int]$previewBytesValue;" ^
  "Test-Positive 'port' $port;" ^
  "Test-Positive 'seconds' $seconds;" ^
  "Test-Positive 'max-packets' $maxPackets;" ^
  "Test-Positive 'buffer-size' $bufferSize;" ^
  "Test-Positive 'timeout' $timeout;" ^
  "Test-Positive 'preview-bytes' $previewBytes;" ^
  "$outputDir = Split-Path -Parent $outputPath;" ^
  "if (-not [string]::IsNullOrWhiteSpace($outputDir)) { New-Item -ItemType Directory -Force -Path $outputDir | Out-Null }" ^
  "$udpClient = New-Object System.Net.Sockets.UdpClient;" ^
  "$udpClient.Client.ReceiveBufferSize = $bufferSize;" ^
  "$udpClient.Client.Bind((New-Object System.Net.IPEndPoint(([System.Net.IPAddress]::Parse($hostIp)), $port)));" ^
  "$udpClient.Client.ReceiveTimeout = [int]([Math]::Ceiling($timeout * 1000));" ^
  "$remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0);" ^
  "$packetCount = 0;" ^
  "$startedAt = Get-Date;" ^
  "$deadline = if ($null -eq $seconds) { $null } else { $startedAt.AddSeconds($seconds) };" ^
  "Write-Host ('Listening on udp://{0}:{1}' -f $hostIp, $port);" ^
  "Write-Host ('Writing capture to {0}' -f $outputPath);" ^
  "Write-Host 'Press Ctrl+C to stop.';" ^
  "$writer = New-Object System.IO.StreamWriter($outputPath, $false, [System.Text.Encoding]::UTF8);" ^
  "try {" ^
  "  while ($true) {" ^
  "    if ($null -ne $deadline -and (Get-Date) -ge $deadline) { break }" ^
  "    try { $payload = $udpClient.Receive([ref]$remote) } catch [System.Net.Sockets.SocketException] { if ($_.Exception.SocketErrorCode -eq [System.Net.Sockets.SocketError]::TimedOut) { continue } throw }" ^
  "    $packetCount++;" ^
  "    $receivedAt = [DateTimeOffset]::UtcNow;" ^
  "    $record = [ordered]@{" ^
  "      sequence_id = $packetCount;" ^
  "      received_at_ms = [int64]$receivedAt.ToUnixTimeMilliseconds();" ^
  "      received_at_utc = $receivedAt.ToString('o');" ^
  "      source_host = $remote.Address.ToString();" ^
  "      source_port = $remote.Port;" ^
  "      byte_length = $payload.Length;" ^
  "      preview_hex = ([System.BitConverter]::ToString($payload, 0, [Math]::Min($previewBytes, $payload.Length))).Replace('-', '').ToLowerInvariant();" ^
  "      payload_base64 = [Convert]::ToBase64String($payload);" ^
  "    };" ^
  "    $writer.WriteLine(($record | ConvertTo-Json -Compress));" ^
  "    $writer.Flush();" ^
  "    if ($packetCount -eq 1 -or ($packetCount %% 25) -eq 0) { Write-Host ('Captured {0} packets. Last packet: {1} bytes from {2}:{3}' -f $packetCount, $payload.Length, $remote.Address, $remote.Port) }" ^
  "    if ($null -ne $maxPackets -and $packetCount -ge $maxPackets) { break }" ^
  "  }" ^
  "} finally {" ^
  "  $writer.Dispose();" ^
  "  $udpClient.Dispose();" ^
  "};" ^
  "$elapsed = ((Get-Date) - $startedAt).TotalSeconds;" ^
  "Write-Host ('Finished. packets={0} elapsed={1:N2}s output={2}' -f $packetCount, $elapsed, $outputPath);"

exit /b %errorlevel%

:show_help
echo Usage:
echo   f1_25_udp_capture.bat [--host HOST] [--port PORT] [--output PATH] [--seconds N] [--max-packets N] [--buffer-size N] [--timeout N] [--preview-bytes N]
echo.
echo Defaults:
echo   --host 0.0.0.0
echo   --port 20777
echo   --output .\captures\f1_25_udp_capture_YYYYMMDD_HHMMSS.jsonl
echo   --buffer-size 65535
echo   --timeout 0.5
echo   --preview-bytes 16
exit /b 0
