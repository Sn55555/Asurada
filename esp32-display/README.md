# Asurada Wi-Fi display

独立显示适配器，保留 `asurada-core` 和 `live-dashboard/static` 原文件。
原 1200×1200 Canvas 在电脑浏览器绘制，等比缩放为 466×466 RGB565；通过 Wi-Fi TCP 传输 32×32 变化区域。
按用户实物确认的要求，设备专用渲染关闭 `drawOuterShell` 装饰外框，保留黑色仪表主体及全部数据元素。原网页文件不变。
ESP32 先在 PSRAM 完整组帧、校验 CRC32，再将变化区域提交 CO5300。首次连接和断线提示恢复时提交完整帧。ACK 包含序号、校验值、屏幕提交耗时。
超过 2.5 秒无帧显示 LINK LOST；数据源超过 2.5 秒未更新显示 NO LIVE DATA。

## 已确认硬件

- 连接设备 MAC `a0:f2:62:e3:0a:04`，ESP32-S3R8，32 MB Flash。
- Dragon Radar 工程的 Waveshare ESP32-S3-Touch-AMOLED-1.75C。
- CO5300，466×466；QSPI CS12 / CLK38 / D0..D3=4..7，RESET2，x offset 6。
- 引脚和初始化来自 `dragonBall_Radar/firmware/DragonRadar/ui/UiDeviceOwner.cpp` 和 `pin_config.h`。

## 构建及启动

本机固件构建使用已有 PlatformIO 55.3.38 / Arduino 3.3.8 和 Dragon Radar 的 GFX 1.6.4；路径写在 `firmware/platformio.ini`。

```sh
~/.platformio/penv/bin/pio run -d esp32-display/firmware
cd esp32-display
npm install
npx playwright install chromium
node stream.mjs --host DEVICE_IP
node --test protocol.test.mjs
```

已有浏览器可用 `ASURADA_PLAYWRIGHT` 指向 Playwright 包、`ASURADA_CHROMIUM` 指向 Chromium 可执行文件。
默认消费原工程 `asurada-core/runtime_logs/dashboard/live_payload.json`。
指定 `--feed FILE` 可使用隔离回放；回放必须加 `--label REPLAY`，不得作为实时游戏验收。
`--preview FILE.png` 仅输出电脑缩放预览，不证明物理屏幕实际显示。

## 配网

串口 115200，发送 `WIFI\t网络名\t密码\n`，网络配置存入独立 `asurada-display` NVS 命名空间。
本机安全输入可运行 `~/.platformio/penv/bin/python esp32-display/provision.py --dialog`，密码不作为命令行参数，也不输出到日志。
`STATUS\n` 返回设备 IP、帧数和失联标志。不要把密码提交到仓库或打印进日志。
备用热点 `Asurada-Display` / `Asurada19750`，IP `192.168.4.1`，端口 19750。

## 回放

`replay_check.py --capture FILE.jsonl --seconds 180` 将原始录制数据按接收时间送入本机 20779 UDP，再走原 Asurada 解码与 feed 输出。
日志与 feed 写入 `output/esp32-display/replay`，不覆盖原运行日志。

## 恢复与验收状态

`output/esp32-display/original-first16mb.bin` 是刷写前 ROM 读取的前 16 MB；哈希见 `backup-manifest.json`。
它覆盖本次刷写的全部区域、NVS、OTA 元数据与 app0。后 16 MB 未备份也未写入。
恢复时只写这个备份到 0，不能全片擦除。备份包含设备配置，不应公开发布。

已完成：固件编译、写入哈希校验、串口 STATUS、4 项传输协议测试、电脑端缩放预览；120 秒真实录制 UDP 回放共 24760 包，经原解码链路输出隔离 feed。证据见 `output/esp32-display/acceptance.json`。
实机进展：设备已连接现有 Wi-Fi，IP `192.168.71.19`；录制行驶数据已在实机显示，连续帧 ACK/CRC 通过，显示流重启后可重新连接。用户已确认无外框黑色仪表效果符合要求。

优化版已经部署，写入哈希验证通过。用户确认动态显示正常，没有残影或闪烁。行驶回放统计：动态更新中位数 7.13 FPS、141 ms，屏幕提交中位数 7 ms，13 个统计窗口中最大窗口 p95 为 201 ms；无帧 CRC 错误。详细数据见 `output/esp32-display/performance.json`。

完成后已切回原 Asurada 实时入口：UDP 20778，原 `live_payload.json`，屏幕 IP 为 `192.168.71.19`。当前没有新的游戏数据输入，显示 NO LIVE DATA。实机动态验收使用真实录制遥测，尚未进行一次新的游戏会话测试。

这块板上传后曾停在下载模式；使用下面的 Espressif 复位命令成功退出并自动恢复已保存的 Wi-Fi：

```sh
~/.platformio/penv/bin/python -m esptool --port /dev/cu.usbmodem101 --before no-reset --after watchdog-reset --connect-attempts 1 chip-id
```

当前系统重新启动时，先运行原 `asurada-core/main.py --live-udp`，再运行显示流。原 core 启动会重置 `session_log.jsonl`，需要保留旧会话时先备份。
