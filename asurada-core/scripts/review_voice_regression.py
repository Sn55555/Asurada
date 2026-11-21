import tempfile
from pathlib import Path
from types import SimpleNamespace
from asurada.review_voice import ReviewVoiceService
from asurada.voice_input import VoiceInputCoordinator
from asurada.workflow_store import WorkflowStore
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from phase3_companion_mode_regression import _make_state, _make_turn
from regression_support import emit_result, runtime_clock


@runtime_clock(1777200000000)
def run():
    checks = {}; calls = []
    with tempfile.TemporaryDirectory() as tmp:
        store = WorkflowStore(Path(tmp) / 'review.db')
        store.create('review', {'driver_id': 'driver', 'steps': ['index_official_laps']})
        laps = [{'session_uid': 'recorded', 'epoch': 0, 'track': 'Shanghai', 'lap': n, 'time_ms': t,
                 'evidence': {'source_sha256': 'fixture'}} for n, t in [(1, 100000), (2, 99000)]]
        store.run('review', (('index_official_laps', lambda r, s, c: laps),))
        def factory():
            def step(payload, *, context):
                calls.append(payload)
                return {'action': 'finish', 'result_ids': ['result-1']} if payload['observations'] else {
                    'action': 'call', 'tool': 'compare_review_laps', 'arguments': {'review_task_id': 'review', 'lap_numbers': [1, 2]}}
            return SimpleNamespace(next_step=step)
        service = ReviewVoiceService(store=store, driver_id='driver', review_task_id='review', planner_factory=factory, planner_identity='fixture')
        coordinator = VoiceInputCoordinator(review_service=service, enable_llm_sidecar=False)
        output = ConsoleVoiceOutput(backend=NullSpeechBackend())
        answer = coordinator.process_completed_turn(state=_make_state(source_timestamp_ms=0),
            turn=_make_turn('复盘前两圈', 'review-turn'), voice_output=output, render=False)
        checks['voice_to_durable_tools_to_answer'] = answer.status == 'processed' and '快 1.000 秒' in answer.bundle['response_override']['speak_text'] and len(calls) == 2
        checks['uses_review_scope_not_inactive_live_state'] = calls[0]['scope']['session_uid'] == 'recorded'
        checks['answer_submitted_to_existing_output'] = answer.output_debug is not None and answer.delivery is not None
        coordinator.process_completed_turn(state=_make_state(source_timestamp_ms=1777200000000),
            turn=_make_turn('复盘前两圈', 'racing-turn'), voice_output=output, render=False)
        checks['active_race_does_not_start_review'] = len(calls) == 2
        coordinator.process_completed_turn(state=_make_state(source_timestamp_ms=0),
            turn=_make_turn('停止', 'control-turn'), voice_output=output, render=False)
        checks['control_not_sent_to_analysis'] = len(calls) == 2
        def expired(**kwargs): raise TimeoutError('review budget')
        coordinator.review_service = SimpleNamespace(accepts=lambda text: True, analyze=expired)
        timeout = coordinator.process_completed_turn(state=_make_state(source_timestamp_ms=0),
            turn=_make_turn('复盘前两圈', 'expired-turn'), voice_output=output, render=False)
        checks['internal_deadline_has_no_delivery'] = timeout.status == 'expired' and timeout.output_debug is None
    return {'passed': all(checks.values()), 'checks': checks, 'scope': 'PTT transcript fixture, SQLite, scripted planner and null output; no microphone or audible playback'}


if __name__ == '__main__': emit_result(run())
