"""Validate stream ordering and byte accounting before client consumption."""
import base64


class TtsStreamValidator:
    def __init__(self, max_audio_bytes=16*1024*1024, max_frames=65536):
        self.started = self.ended = False
        self.start_status = None
        self.frames = self.audio_bytes = 0
        self.max_audio_bytes, self.max_frames = max_audio_bytes, max_frames

    def accept(self, envelope):
        if not isinstance(envelope, dict) or not isinstance(envelope.get('payload'), dict):
            raise ValueError('invalid_tts_stream_envelope')
        kind, value = envelope.get('message_type'), envelope['payload']
        if self.ended:
            raise ValueError('tts_data_after_end')
        if kind == 'tts_stream_start':
            if self.started:
                raise ValueError('duplicate_tts_start')
            if value.get('status') not in {'completed', 'unsupported', 'error'}:
                raise ValueError('invalid_tts_start_status')
            self.started = True; self.start_status = value['status']
            return
        if not self.started:
            raise ValueError('tts_start_required')
        if kind == 'tts_audio_frame':
            if self.start_status != 'completed':
                raise ValueError('audio_after_failed_tts_start')
            sequence, size = value.get('sequence_id'), value.get('audio_bytes')
            if type(sequence) is not int or sequence != self.frames+1 or type(size) is not int or size <= 0:
                raise ValueError('invalid_tts_frame_accounting')
            encoded = value.get('audio_base64')
            if not isinstance(encoded, str):
                raise ValueError('invalid_tts_frame_encoding')
            decoded = base64.b64decode(encoded, validate=True)
            if len(decoded) != size:
                raise ValueError('tts_frame_size_mismatch')
            self.frames += 1; self.audio_bytes += size
            if self.frames > self.max_frames or self.audio_bytes > self.max_audio_bytes:
                raise ValueError('tts_stream_size_limit')
            return
        if kind == 'tts_stream_end':
            if (type(value.get('total_frames')) is not int or type(value.get('total_audio_bytes')) is not int
                    or value['total_frames'] != self.frames or value['total_audio_bytes'] != self.audio_bytes):
                raise ValueError('tts_stream_total_mismatch')
            status = value.get('status')
            if status not in {'completed', 'unsupported', 'error'}:
                raise ValueError('invalid_tts_end_status')
            if status == 'completed' and (self.start_status != 'completed' or self.audio_bytes == 0):
                raise ValueError('empty_or_failed_tts_completed')
            self.ended = True
            return
        raise ValueError('unknown_tts_stream_message')

    def finish(self):
        if not self.started or not self.ended:
            raise ValueError('tts_stream_incomplete')
