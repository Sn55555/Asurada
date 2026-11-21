"""Exercise cockpit controls through HTTP and the shared speech socket."""
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from regression_support import emit_result

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "live-dashboard"))
from server import DashboardHttpServer, DashboardStateSource, VoiceMeterSocketCache


def run():
    with TemporaryDirectory(dir="/tmp") as temp:
        root = Path(temp)
        speech = SpeechService(root / "voice.sock", output=ConsoleVoiceOutput(backend=NullSpeechBackend())).start()
        source = DashboardStateSource(root / "feed.json", VoiceMeterSocketCache(), speech_socket=speech.path)
        dashboard = DashboardHttpServer(0, source)
        dashboard.start()
        worker = Thread(target=dashboard.serve_forever, daemon=True)
        worker.start()

        def request(method="GET", query="", *, origin=None):
            http = HTTPConnection("127.0.0.1", dashboard.port, timeout=2)
            try:
                headers = {"Origin": origin} if origin else {}
                http.request(method, "/api/personality" + query, headers=headers)
                response = http.getresponse()
                return response.status, json.loads(response.read())
            finally:
                http.close()

        stopped = False
        try:
            exact = f"http://127.0.0.1:{dashboard.port}"
            initial = request()
            bad_origin = request("POST", "?quiet=true", origin="https://invalid.example")
            changed = request("POST", "?quiet=true&humor=low", origin=exact)
            client = SharedSpeechClient(speech.path)
            client.call("report_microphone", {"state": "listening", "ttl_s": 10})
            reconnected_browser = request()
            stopped = speech.close()
            disconnected = request()
            speech = SpeechService(root / "voice.sock", output=ConsoleVoiceOutput(backend=NullSpeechBackend())).start()
            recovered = request()
            return {
                "read_from_shared_owner": initial[0] == 200 and initial[1]["playback"] == "idle",
                "reject_non_local_origin": bad_origin[0] == 403,
                "write_and_read_matching_setting": changed[0] == 200 and changed[1]["quiet"] is True
                and changed[1]["humor"] == "low" and reconnected_browser[1]["quiet"] is True,
                "recognizer_status_crosses_socket": reconnected_browser[1]["microphone"] == "listening",
                "service_loss_and_restart": stopped and disconnected[0] == 503 and recovered[0] == 200
                and recovered[1]["quiet"] is False and recovered[1]["microphone"] == "unknown",
            }
        finally:
            dashboard.close()
            worker.join(2)
            speech.close()


if __name__ == "__main__":
    emit_result(run())
