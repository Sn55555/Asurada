from __future__ import annotations

from asurada.voice_sidecar_server import VoiceSidecarServer


def main() -> int:
    server = VoiceSidecarServer.from_env()
    print(
        f"voice sidecar listening on http://{server.config.host}:{server.config.port} "
        f"llm_backend={server.llm_explainer.backend.name} "
        f"asr_backend={getattr(server.asr_backend, 'name', 'none')} "
        f"tts_enabled={server.config.tts_enabled}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
