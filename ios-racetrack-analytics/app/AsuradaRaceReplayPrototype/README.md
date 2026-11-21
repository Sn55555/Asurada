# Asurada Race Replay Prototype

This folder contains a SwiftUI-first prototype scaffold for the iOS racetrack analytics and replay app.

## Included Screens

- Home
- Sessions
- Session Detail
- Replay
- Compare
- Profile

## How To Use

1. Create a new iOS App project in Xcode
2. Copy these files into the project
3. Add the `Charts` framework if needed
4. Set `AsuradaRaceReplayPrototypeApp` as the app entry if you want to run this structure directly

## Prototype Goal

This is not a production architecture yet. It is a native iOS UI prototype meant to help validate:

- information hierarchy
- tab structure
- replay layout
- comparison layout
- telemetry-focused component patterns

## USB Real Data Feed

The app reads an external NDJSON stream written into its Documents directory. There is no generated in-app fake telemetry path in the current build.

- `USB Bridge`: external telemetry stream injected into app runtime

### App-side Setup

1. Open `Profile`
2. Enable `Real USB Feed`
3. Set `Source` to `USB Bridge`
4. Keep `Feed Rate` around `15-30 Hz`
5. Open `Replay` and press Play

### USB Bridge Relay (Simulator)

Use the relay script to write telemetry into the app container stream file:

`scripts/usb_bridge_relay.py`

Examples:

```bash
# 1) From USB serial stream (recommended)
python3 scripts/usb_bridge_relay.py --source serial --serial-port /dev/tty.usbmodem1 --baud 115200 --truncate

# 2) From stdin (pipe any local telemetry tool)
cat telemetry.ndjson | python3 scripts/usb_bridge_relay.py --source stdin --truncate

# 3) From TCP source (if your bridge tool pushes socket lines)
python3 scripts/usb_bridge_relay.py --source tcp --tcp-port 9077 --truncate
```

Accepted packet formats:

- JSON with keys like `second/speedKph/throttlePct/brakePct/delta`
- Optional live racing fields: `gear/engineRPM/drs/steer/revLightsPercent/lapNumber/carPosition/totalLaps`
- CSV line: `second,speed,throttle,brake,delta`

When the relay is running, `Replay` reads packets in realtime from:

`<Simulator App Data>/Documents/usb_live_stream.ndjson`

## F1 25 PC Setup (No PC-Mac Network)

Use USB cable only:

`F1 25 -> UDP (localhost on PC) -> PC UDP-to-Serial bridge -> USB serial -> Mac relay -> App`

### 1) F1 25 telemetry settings (PC)

In game telemetry settings:

- `UDP Telemetry` = On
- `UDP Broadcast Mode` = Off
- `UDP IP Address` = `127.0.0.1`
- `UDP Port` = `20777`
- `UDP Send Rate` = `60Hz` (or highest available)
- `UDP Format` = `2025`

### 2) Run PC bridge

Script:
`scripts/f1_25_udp_to_serial_bridge.py`

Example (Windows PowerShell):

```powershell
python .\f1_25_udp_to_serial_bridge.py --listen-ip 127.0.0.1 --listen-port 20777 --serial-port COM5 --baud 115200
```

### 3) Run Mac relay

```bash
python3 scripts/usb_bridge_relay.py --source serial --serial-port /dev/tty.usbmodem1 --baud 115200 --truncate
```

### 4) App-side

- `Profile` -> `Enable Real USB Feed` -> `Source = USB Bridge`
- Go to `Replay` and press play

## iPhone USB Real-Device Bridge (No Wi-Fi)

Use this when running app on physical iPhone:

1. Enable File Sharing in app build (already configured in `project.yml`).
2. Install and run app once on iPhone.
3. Mount app Documents via USB (Mac):

```bash
# Install dependencies once
brew install --cask macfuse
brew install ifuse

# Mount app Documents (bundle id must match your signed id)
mkdir -p /tmp/asurada-ios-docs
ifuse --documents com.your.bundle.id /tmp/asurada-ios-docs
```

4. Start relay writing directly to mounted iPhone file:

```bash
python3 scripts/usb_bridge_relay.py --source serial --serial-port /dev/tty.usbmodem1 --baud 115200 --output-file /tmp/asurada-ios-docs/usb_live_stream.ndjson --truncate
```

5. In iPhone app, open `Profile` -> enable `Real USB Feed` -> `Source = USB Bridge` -> open `Replay`.
