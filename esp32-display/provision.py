"""Configure this display over USB; never log or persist Wi-Fi credentials on the Mac."""
import argparse
import getpass
import subprocess
import time
import serial

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', default='/dev/cu.usbmodem101')
parser.add_argument('--dialog', action='store_true', help='Use local macOS dialogs, including hidden password input')
args = parser.parse_args()

def dialog(prompt, hidden=False):
    script = f'text returned of (display dialog "{prompt}" default answer ""' + (' with hidden answer' if hidden else '') + ' buttons {"取消", "连接"} default button "连接")'
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Configuration cancelled')
    return result.stdout.rstrip('\n')

if args.dialog:
    ssid = dialog('Asurada 屏幕：请输入 2.4 GHz Wi-Fi 名称')
    password = dialog('Asurada 屏幕：请输入 Wi-Fi 密码（仅写入设备）', True)
else:
    ssid = input('2.4 GHz Wi-Fi name: ')
    password = getpass.getpass('Wi-Fi password (hidden): ')
if not ssid or any(c in ssid + password for c in '\t\n\r') or len(ssid.encode()) > 32 or len(password.encode()) > 63:
    raise SystemExit('Invalid SSID/password length or delimiter')
with serial.Serial(args.port, 115200, timeout=0.2) as port:
    port.write(('WIFI\t' + ssid + '\t' + password + '\n').encode())
    password = ''
    end = time.monotonic() + 30
    last = 0
    while time.monotonic() < end:
        if time.monotonic() - last > 1:
            port.write(b'STATUS\n')
            last = time.monotonic()
        line = port.readline().decode('utf-8', 'replace').strip()
        if line.startswith('STATUS ') and 'ip=0.0.0.0' not in line:
            print(line)
            break
    else:
        raise SystemExit('Wi-Fi not connected after 30 seconds; check 2.4 GHz availability and credentials')
