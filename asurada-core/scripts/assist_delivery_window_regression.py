from copy import deepcopy
from types import SimpleNamespace
from regression_support import emit_result
from phase3_voice_brake_point_assist_regression import _make_state
from asurada.speech_applicability import validate_assist_applicability


def run():
    checks = {}
    for kind, limit in [('brake_point_assist', .35), ('corner_gear_assist', .75)]:
        state = _make_state(lap_distance_m=100, speed_kph=180)
        state.source_timestamp_ms = 1000000
        job = SimpleNamespace(source_kind=kind, metadata={'target':{'braking_zone_start_m':110, 'apex_distance_m':110}})
        for phase in ('valid', 'expired', 'passed_target', 'advanced', 'rewind', 'new_lap', 'missing_position', 'missing_speed'):
            current = deepcopy(state)
            clock = 1000+.1
            current.player.lap_distance_m = 102
            if phase == 'expired': clock=1000+limit+.001
            if phase == 'passed_target': current.player.lap_distance_m=111
            if phase == 'advanced':
                current.player.lap_distance_m=100+50*limit+1
                job.metadata['target']={'braking_zone_start_m':1000,'apex_distance_m':1000}
            if phase == 'rewind': current.player.lap_distance_m=99
            if phase == 'new_lap': current.lap_number+=1
            if phase == 'missing_position':
                current.player.lap_distance_m=None
                current.raw.pop('lap_distance_m',None)
            if phase == 'missing_speed': current.player.speed_kph=float('nan')
            try:
                validate_assist_applicability(job,state,current,wall_clock=lambda:clock)
                checks[kind+'_'+phase]=phase=='valid'
            except ValueError:
                checks[kind+'_'+phase]=phase!='valid'
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
