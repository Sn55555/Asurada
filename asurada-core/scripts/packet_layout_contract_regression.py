"""Verified protocol layouts reject guesses and preserve per-car field boundaries."""
import struct
from regression_support import emit_result
from packet_decode_resilience_regression import wire_packet
from asurada.pdu import RawPacket
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError


def decode(wire):
    return F125PacketDecoder().decode_raw(RawPacket(1, bytes(wire), 'test', 1))


def run():
    checks = {}
    session = wire_packet(1).payload
    checks['session_verified_753_accepted'] = decode(session).kind == 'Session'
    for length in (29, 752, 754, 760, 800):
        try:
            decode(session[:length] + bytes(max(0, length - len(session))))
            checks[f'session_unknown_size_{length}_rejected'] = False
        except PacketDecodeError as exc:
            checks[f'session_unknown_size_{length}_rejected'] = (exc.reason == 'size_mismatch'
                and f'bytes={length}' in str(exc) and 'expected 753' in str(exc))
    for byte, value, reason in ((5, 2, 'unsupported_version'), (2, 24, 'unsupported_format')):
        wire = bytearray(session); wire[byte] = value
        try:
            decode(wire); checks[f'session_header_{byte}_rejected'] = False
        except PacketDecodeError as exc:
            checks[f'session_header_{byte}_rejected'] = exc.reason == reason
    # Game build version is not a wire-layout version; it remains accepted.
    wire = bytearray(session); wire[3] = 9; wire[4] = 99
    checks['same_wire_version_new_game_build_accepted'] = decode(wire).kind == 'Session'
    lap = bytearray(wire_packet(2).payload)
    for i in range(22):
        struct.pack_into('<fB', lap, 29 + i * 57 + 52, 200.5 + i, 255 if i == 0 else i)
    lap[-2:] = bytes([10, 11])
    for player in (0, 9, 21):
        lap[27] = player
        body = decode(lap).payload['body']
        checks[f'lap_speed_trap_player_{player}'] = (body['speed_trap_fastest_speed_kph'] == 200.5 + player
            and body['speed_trap_fastest_lap'] == (255 if player == 0 else player))
        checks[f'lap_speed_trap_all_cars_{player}'] = all(
            car['speed_trap_fastest_speed_kph'] == 200.5 + i and car['speed_trap_fastest_lap'] == (255 if i == 0 else i)
            for i, car in enumerate(body['all_cars']))
        checks[f'lap_packet_tail_unshifted_{player}'] = body['time_trial_personal_best_car_idx'] == 10 and body['time_trial_rival_car_idx'] == 11
    participants = bytearray(wire_packet(4).payload)
    participants[29] = 22
    for i in range(22):
        start = 30 + 57 * i
        name = ('隼人' + str(i)).encode()
        participants[start + 7:start + 39] = name + bytes(32 - len(name))
        participants[start + 39] = 1; participants[start + 40] = 0
        struct.pack_into('<HBB', participants, start + 41, 500 + i, 3, 4)
        participants[start + 45:start + 57] = bytes(range(1, 13))
    body = decode(participants).payload['body']
    checks['participant_name_32_byte_boundary'] = all(p['name'] == '隼人' + str(i) for i, p in enumerate(body['all_cars']))
    checks['participant_correct_metadata_offsets'] = all(p['telemetry_setting'] == 1 and not p['show_online_names']
        and p['tech_level'] == 500 + i and p['platform'] == 3 and p['num_colours'] == 4
        and p['livery_colours'][-1] == {'red': 10, 'green': 11, 'blue': 12} for i, p in enumerate(body['all_cars']))
    participants[37:69] = b'A' * 32  # Exact-width name with no zero terminator.
    checks['participant_unterminated_name_does_not_read_metadata'] = decode(participants).payload['body']['player']['name'] == 'A' * 32
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())
