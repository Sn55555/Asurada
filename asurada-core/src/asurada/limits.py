"""Resource bounds by protocol, in bytes unless explicitly named otherwise.

Equal values are not interchangeable: audio, NDJSON frames and IPC messages
have different consumers and may evolve independently.
"""
IPC_MAX_MESSAGE_BYTES = 4 << 20
SIDECAR_JSON_BODY_MAX = 16 << 20
SIDECAR_STREAM_FRAME_MAX = 4 << 20
SIDECAR_STREAM_BODY_MAX = 16 << 20
TTS_AUDIO_MAX_BYTES = 16 << 20
DASHBOARD_PAYLOAD_MAX = 2 << 20
DASHBOARD_HANDSHAKE_MAX = 16 << 10
INGRESS_QUEUE_CAPACITY = 512
ANALYSIS_STEP_SIZE_LIMIT = 16 << 10
TOOL_PAYLOAD_MAX_BYTES = 128 << 10
