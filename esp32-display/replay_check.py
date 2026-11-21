"""Send recorded F1 packets through the unchanged live UDP decoder into an isolated test feed."""
import argparse
import base64
import json
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'asurada-core/src'))
from asurada.app import AsuradaApp
from asurada.config import AppConfig, UdpConfig

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--capture', type=Path, required=True)
parser.add_argument('--seconds', type=float, default=180)
parser.add_argument('--skip-seconds', type=float, default=0)
parser.add_argument('--port', type=int, default=20779)
parser.add_argument('--output', type=Path, default=ROOT / 'output/esp32-display/replay')
args = parser.parse_args()
app = AsuradaApp(AppConfig(replay_log_dir=args.output))
thread = threading.Thread(target=app.run_live_udp, args=(UdpConfig(host='127.0.0.1', port=args.port),), daemon=True)
thread.start()
time.sleep(1)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
start = time.monotonic()
first = None
count = 0
with args.capture.open() as rows:
    for line in rows:
        row = json.loads(line)
        timestamp = row['received_at_ms'] / 1000
        if first is None:
            first = timestamp
        elapsed = timestamp - first - args.skip_seconds
        if elapsed < 0:
            continue
        if elapsed > args.seconds:
            break
        remaining = start + elapsed - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        sock.sendto(base64.b64decode(row['payload_base64']), ('127.0.0.1', args.port))
        count += 1
        if not thread.is_alive():
            raise RuntimeError('Core UDP runtime stopped')
time.sleep(1)
print(json.dumps({'event': 'recording_replay_complete', 'packets': count, 'feed': str(args.output / 'dashboard/live_payload.json')}))
