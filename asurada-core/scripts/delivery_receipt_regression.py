from dataclasses import replace
from copy import deepcopy
from asurada.speech_events import SpeechEventStream
from asurada.delivery_receipt import delivery_receipt
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.task_runtime import TaskContext
from phase3_voice_input_regression import _make_state, _make_turn
from regression_support import emit_result, runtime_clock


class HoldingBackend(NullSpeechBackend):
    audible = True
    def start(self, job): return object()
    def is_active(self, handle): return handle is not None


@runtime_clock(1777100000000)
def run():
    coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    output = ConsoleVoiceOutput(backend=HoldingBackend())
    state = _make_state()
    def query(text, index):
        return coordinator.process_completed_turn(state=state,
            turn=replace(_make_turn(text), turn_id=f'delivery:{index}'), voice_output=output, render=False)
    first = query('后车差距', 1)
    second = query('轮胎状态', 2)
    third = query('后车差距', 3)
    checks = {
        'processing_not_playback_completion': first.status == second.status == third.status == 'processed',
        'first_started': first.delivery['status'] == 'started',
        'second_queued': second.delivery['status'] == 'queued',
        'older_pending_question_kept': third.delivery['status'] == 'suppressed'
            and third.delivery['reason'] == 'lower_priority_than_pending',
        'new_contract_version': first.contract_version == 'voice-input-v2',
        'only_started_answer_in_context': len(coordinator.conversation_context.snapshot()['recent_responses']) == 1,
    }
    request = first.bundle['input_event']['request_id']
    receipt = delivery_receipt({'output_lifecycle': {'event': {'request_id': 'other', 'event_type': 'complete'}}}, request)
    checks['another_request_completion_not_ours'] = receipt['status'] == 'unknown'
    checks['missing_receipt_not_success'] = delivery_receipt({}, request)['status'] == 'unknown'
    output.backend.is_active = lambda handle: False
    output.tick()
    coordinator.refresh_delivery(state=state, voice_output=output)
    history = coordinator.conversation_context.snapshot()['recent_responses']
    checks['queued_start_reconciled'] = len(history) == 2 and history[-1]['request_id'] == second.bundle['input_event']['request_id']
    checks['earlier_completion_upserted'] = history[0]['metadata']['delivery_status'] == 'completed'
    coordinator.refresh_delivery(state=state, voice_output=output)
    checks['repeated_poll_does_not_duplicate'] = coordinator.conversation_context.snapshot()['recent_responses'] == history
    output.tick()
    coordinator.refresh_delivery(state=state, voice_output=output)
    checks['later_completion_updates_same_response'] = (len(coordinator.conversation_context.snapshot()['recent_responses']) == 2
        and coordinator.conversation_context.snapshot()['last_response']['metadata']['delivery_status'] == 'completed')
    old_cursor = coordinator.delivery_context.cursor
    class FailedRead:
        def read_events(self, **kwargs): raise TimeoutError('fixture')
    coordinator.refresh_delivery(state=state, voice_output=FailedRead())
    checks['read_failure_preserves_cursor'] = coordinator.delivery_context.cursor == old_cursor
    output._event_stream = SpeechEventStream(capacity=1)
    coordinator.refresh_delivery(state=state, voice_output=output)
    checks['restart_clears_owned_pending'] = coordinator.delivery_context.health == 'stream_reset' and not coordinator.delivery_context.requests
    changed = deepcopy(state)
    changed.session_epoch += 1
    coordinator.refresh_delivery(state=changed, voice_output=output)
    checks['new_scope_clears_old_conversation'] = not coordinator.conversation_context.snapshot()['recent_responses']
    checks['foreign_control_receipt_rejected'] = delivery_receipt({'control_result': {
        'request_id': 'other', 'status': 'completed'}}, request)['control_result'] is None
    class ReadSpy(ConsoleVoiceOutput):
        reads = 0
        budgets = None
        def read_events(self, **kwargs):
            self.reads += 1
            self.budgets = kwargs['timeout_s']
            raise TimeoutError('event reader unavailable')
    control_output = ReadSpy(backend=HoldingBackend())
    control_coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    for index, text in enumerate(('停止', '取消')):
        result = control_coordinator.process_completed_turn(state=state,
            turn=replace(_make_turn(text), turn_id=f'skip-read:{index}'), voice_output=control_output, render=False)
        checks['control_skips_event_read_' + text] = result.status == 'processed' and control_output.reads == 0
    control_coordinator.process_completed_turn(state=state,
        turn=replace(_make_turn('后车差距'), turn_id='read-query'), voice_output=control_output, render=False)
    checks['ordinary_query_attempts_event_refresh'] = control_output.reads == 1
    control_coordinator.process_completed_turn(state=state,
        turn=replace(_make_turn('轮胎状态'), turn_id='budget-query'), voice_output=control_output,
        render=False, context=TaskContext.start('event-budget', 80))
    checks['refresh_obeys_remaining_turn_budget'] = 0 < control_output.budgets <= .08
    shutdown_coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    shutdown_output = ConsoleVoiceOutput(backend=HoldingBackend())
    for index, text in enumerate(('后车差距', '轮胎状态')):
        shutdown_coordinator.process_completed_turn(state=state,
            turn=replace(_make_turn(text), turn_id=f'shutdown:{index}'), voice_output=shutdown_output, render=False)
    checks['shutdown_waits_for_backend_confirmation'] = not shutdown_output.shutdown(timeout_s=0)
    shutdown_coordinator.refresh_delivery(state=state, voice_output=shutdown_output)
    shutdown_history = shutdown_coordinator.conversation_context.snapshot()['recent_responses']
    checks['shutdown_request_not_premature_completion'] = (len(shutdown_history) == 1
        and shutdown_history[0]['metadata']['delivery_status'] == 'started'
        and len(shutdown_coordinator.delivery_context.requests) == 1)
    shutdown_output.backend.is_active = lambda handle: False
    shutdown_output.tick()
    shutdown_coordinator.refresh_delivery(state=state, voice_output=shutdown_output)
    checks['shutdown_ack_reconciles_context'] = (shutdown_coordinator.conversation_context.snapshot()['last_response']['metadata']['delivery_status'] == 'cancelled'
        and not shutdown_coordinator.delivery_context.requests)
    class FailingStart(HoldingBackend):
        fail = True
        def start(self, job):
            if self.fail:
                raise OSError('fixture startup failure')
            return super().start(job)
    failed_backend = FailingStart()
    failed_output = ConsoleVoiceOutput(backend=failed_backend)
    failed_coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    def fail_query(text, index):
        return failed_coordinator.process_completed_turn(state=state,
            turn=replace(_make_turn(text), turn_id=f'failed:{index}'), voice_output=failed_output, render=False)
    failed = fail_query('后车差距', 1)
    checks['startup_failure_receipt'] = failed.delivery['status'] == 'failed' and failed.delivery['reason'] == 'backend_start_failed'
    checks['startup_failure_does_not_own_channel'] = failed_output._active_envelope is None and failed_output._active_handle is None
    failed_coordinator.refresh_delivery(state=state, voice_output=failed_output)
    checks['failed_start_not_spoken'] = (not failed_coordinator.delivery_context.requests
        and not failed_coordinator.conversation_context.snapshot()['recent_responses'])
    failed_backend.fail = False
    recovery = fail_query('后车差距', 2)
    checks['new_request_can_recover'] = recovery.delivery['status'] == 'started'
    queued_failure = fail_query('轮胎状态', 3)
    failed_backend.fail = True
    failed_backend.is_active = lambda handle: False
    tick_failure = failed_output.tick()
    checks['queued_start_failure_is_terminal'] = tick_failure['event']['event_type'] == 'failed' and failed_output._active_envelope is None
    failed_coordinator.refresh_delivery(state=state, voice_output=failed_output)
    checks['failed_queued_request_removed'] = (queued_failure.bundle['input_event']['request_id'] not in failed_coordinator.delivery_context.requests
        and len(failed_coordinator.conversation_context.snapshot()['recent_responses']) == 1)
    class FailingStop(HoldingBackend):
        broken = True
        stopped = False
        def stop(self, handle):
            if self.broken: raise OSError('fixture stop failed')
            self.stopped = True
        def is_active(self, handle): return handle is not None and not self.stopped
    stop_backend = FailingStop()
    stop_output = ConsoleVoiceOutput(backend=stop_backend)
    stop_coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    def stop_query(text, index):
        return stop_coordinator.process_completed_turn(state=state,
            turn=replace(_make_turn(text), turn_id=f'stop-error:{index}'), voice_output=stop_output, render=False)
    stop_query('后车差距', 1); stop_query('轮胎状态', 2)
    failed_stop = stop_query('停止', 3).delivery['control_result']
    checks['stop_exception_has_pending_receipt'] = (failed_stop['status'] == 'pending'
        and any(t['error_type'] == 'OSError' for t in failed_stop['targets']))
    checks['stop_exception_still_removes_pending'] = stop_output._pending_envelope is None and stop_output._active_envelope is not None
    stop_backend.broken = False
    retried_stop = stop_query('停止', 4).delivery['control_result']
    checks['stop_can_be_retried_after_exception'] = retried_stop['status'] == 'completed' and all(t['error_type'] is None for t in retried_stop['targets'])
    class BrokenConfirmation(HoldingBackend):
        probe_broken = False
        def stop(self, handle): self.probe_broken = True
        def is_active(self, handle):
            if self.probe_broken: raise OSError('fixture confirmation failed')
            return super().is_active(handle)
    for command in ('停止', '取消'):
        probe_output = ConsoleVoiceOutput(backend=BrokenConfirmation())
        probe_coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
        for index, text in enumerate(('后车差距', command)):
            probe_result = probe_coordinator.process_completed_turn(state=state,
                turn=replace(_make_turn(text), turn_id=f'probe-error:{command}:{index}'), voice_output=probe_output, render=False)
        checks['confirmation_failure_retains_owner_' + command] = (probe_result.delivery['control_result']['status'] == 'pending'
            and probe_result.delivery['control_result']['targets'][0]['error_type'] == 'OSError'
            and probe_output._active_envelope is not None)
    for cooperative in (True, False):
        class StopBackend(HoldingBackend):
            stopped = False
            def stop(self, handle): self.stopped = cooperative
            def is_active(self, handle): return handle is not None and not self.stopped
        controller = VoiceInputCoordinator(enable_llm_sidecar=False)
        speaker = ConsoleVoiceOutput(backend=StopBackend())
        def send(text, index):
            return controller.process_completed_turn(state=state,
                turn=replace(_make_turn(text), turn_id=f'control:{cooperative}:{index}'), voice_output=speaker, render=False)
        active = send('后车差距', 1)
        queued = send('轮胎状态', 2)
        stopped = send('停止', 3)
        operation = stopped.delivery['control_result']
        label = 'confirmed' if cooperative else 'delayed'
        checks[label + '_control_request_bound'] = operation['request_id'] == stopped.bundle['input_event']['request_id']
        checks[label + '_target_requests_retained'] = {t['request_id'] for t in operation['targets']} == {
            active.bundle['input_event']['request_id'], queued.bundle['input_event']['request_id']}
        checks[label + '_stop_status'] = operation['status'] == ('completed' if cooperative else 'pending')
        checks[label + '_control_not_target_speech'] = stopped.delivery['status'] == 'unknown'
        if cooperative:
            idle = send('停止', 4)
            checks['nothing_to_stop_no_op'] = idle.delivery['control_result']['status'] == 'no_op' and not idle.delivery['control_result']['targets']
        else:
            speaker.backend.stopped = True
            terminal = speaker.tick()['event']
            checks['late_stop_confirmation_retains_controller'] = (terminal['event_type'] == 'cancel'
                and terminal['request_id'] == active.bundle['input_event']['request_id']
                and terminal['metadata']['cancel_requested_by_request_id'] == operation['request_id'])
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())
