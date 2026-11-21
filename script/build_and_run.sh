#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT_DIR/output/macos-voice/Asurada Voice.app"
MODE="${1:-run}"
if [[ "$MODE" != "run" && "$MODE" != "--build-only" && "$MODE" != "--verify" ]]; then
  echo "Usage: $0 [run|--build-only|--verify] [runtime-directory]" >&2
  exit 2
fi
RUNTIME_DIR="${2:-$ROOT_DIR/asurada-core/runtime_logs}"
mkdir -p "$APP/Contents/MacOS" "$ROOT_DIR/output/macos-voice/module-cache"
# Relaunch through LaunchServices so the app owns its TCC requests.
if pgrep -x AsuradaVoice >/dev/null; then
  osascript -e 'tell application id "com.asurada.voice" to quit'
fi
swiftc -module-cache-path "$ROOT_DIR/output/macos-voice/module-cache" "$ROOT_DIR/macos-voice/main.swift" -o "$APP/Contents/MacOS/AsuradaVoice"
"$ROOT_DIR/asurada-core/.venv/bin/python" - "$APP" "$ROOT_DIR" <<'PY'
import plistlib,sys
from pathlib import Path
app,root=sys.argv[1:]
info=dict(CFBundlePackageType='APPL',CFBundleExecutable='AsuradaVoice',CFBundleIdentifier='com.asurada.voice',CFBundleName='Asurada Voice',CFBundleVersion='1',CFBundleShortVersionString='0.1.0',NSPrincipalClass='NSApplication',LSMinimumSystemVersion='13.0',NSSpeechRecognitionUsageDescription='将您主动说出的赛车问句交给 Apple 语音识别，生成文字后由 Asurada 回答。',NSMicrophoneUsageDescription='仅在您开始聆听时采集赛车问句，用于语音识别和问答。',AsuradaRepositoryRoot=root)
(app:=Path(app)/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
PY
codesign --force --sign - --identifier com.asurada.voice "$APP"
codesign --verify --strict "$APP"
if [[ "$MODE" == "--build-only" ]]; then echo "$APP"; exit 0; fi
open -n "$APP" --args --runtime-dir "$RUNTIME_DIR"
if [[ "$MODE" == "--verify" ]]; then
  sleep 1
  pgrep -x AsuradaVoice
fi
