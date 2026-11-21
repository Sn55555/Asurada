"""Read-only architecture probes. Fake backends only; no microphone/network/playback."""
from pathlib import Path
import json
import sys
import time
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'asurada-core/src'), str(ROOT / 'asurada-core/scripts')]

from asurada.llm_explainer import LlmExplainer, LlmExplainerRequest, _extract_json_or_text_payload
from asurada.llm_response_schema import validate_llm_response
from asurada.arbiter import StrategyArbiterV2, ArbiterInput, RuleCandidate
from asurada.state import UnifiedStateStore
from asurada.output import ConsoleVoiceOutput
from asurada.conversation_context import ConversationContext
from asurada.state_summary_for_llm import build_state_summary_for_llm
from asurada.config import StrategyThresholds
from asurada.strategy import StrategyEngine
from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision


class SlowBackend:
    name = 'local_slow_fake'

    def explain(self, request):
        time.sleep(0.25)
        return dict(status='answerable', answer_text='late', confidence=0.9)


def main():
    results = {}
    request = LlmExplainerRequest('session', 'turn', 'request', 'overall_situation', 'test', 'test', 20, {})
    start = time.perf_counter()
    result = LlmExplainer(backend=SlowBackend()).run(request=request)
    results['timeout'] = dict(configured_ms=20, backend_delay_ms=250,
                              elapsed_ms=round((time.perf_counter()-start)*1000, 2), result=result.to_dict())
    payload = _extract_json_or_text_payload('现在后车差距只有 0.2 秒，立即全力进攻。')
    results['plain_text_response'] = dict(payload=payload, validation=validate_llm_response(payload))
    results['nan_response_confidence'] = dict(validation=validate_llm_response(
        dict(status='answerable', answer_text='example', confidence=float('nan'))))

    candidates = [RuleCandidate('LOW_FUEL', 95, 'fuel', ''),
                  RuleCandidate('DYNAMICS_UNSTABLE', 72, 'dynamics', ''),
                  RuleCandidate('ATTACK_WINDOW', 56, 'attack', '')]
    output = StrategyArbiterV2().arbitrate(ArbiterInput(rule_candidates=candidates))
    results['absent_model_scores'] = dict(input_priorities={x.code:x.priority for x in candidates},
                                          output_priorities={x.code:x.priority for x in output.ordered_actions})
    state_a = make_state()
    state_b = replace(state_a, session_uid='new-session', track='Monza')
    store = UnifiedStateStore()
    store.update(state_a)
    store.update(state_b)
    results['session_history'] = dict(current_session=state_b.session_uid,
                                      history_sessions=[x.session_uid for x in store.recent(12)])

    race = replace(state_a, raw={**state_a.raw, 'fuel_laps_remaining_source':'derived_from_sample_consumption',
        'fuel_in_tank':20.0, 'fuel_capacity':50.0, 'timing_mode':'race_like',
        'timing_support_level':'official_preferred', 'session_type':'FeatureRaceLike(16)'})
    engine = StrategyEngine(StrategyThresholds(), model_policy=ModelAdmissionPolicy(
        modes={name:'disabled' for name in MODEL_NAMES}))
    decision = engine.evaluate(race, [race])
    answer, _ = compose_structured_query_response(state=race, query_kind='fuel_status',
                                                 primary_message=decision.messages[0])
    results['fuel_answer_disagreement'] = dict(fuel_laps=race.player.fuel_laps_remaining,
        remaining_race_laps=race.total_laps-race.lap_number+1,
        core_assessment=decision.debug['assessment']['fuel_state'],
        core_primary=decision.messages[0].code, query_answer=answer)

    backend = FakeSpeechBackend()
    voice = ConsoleVoiceOutput(backend=backend)
    first = make_strategy_decision(state=state_a, code='ERS_LOW', priority=60, title='normal', detail='')
    second = make_strategy_decision(state=state_a, code='SAFETY_CAR', priority=130, title='urgent', detail='')
    second.debug['arbiter_v2']['output']['final_voice_action']['interrupt'] = True
    voice.emit(first, render=False)
    urgent = voice.emit(second, render=False)
    results['voice_interrupt'] = dict(requested_interrupt=True, event=urgent['event']['event_type'],
                                      active=voice._active_envelope.job.action_code,
                                      pending=voice._pending_envelope.job.action_code)

    context = ConversationContext()
    context.observe_strategy_message(first.messages[0], state=state_a)
    summary = build_state_summary_for_llm(state=state_a, primary_message=first.messages[0], conversation_context=context).to_dict()
    results['stale_context'] = dict(snapshot_stale=summary['metadata']['runtime_context']['stale_snapshot'],
                                     current_ers=summary['state_snapshot']['ers_pct'],
                                     primary_strategy=summary['strategy_snapshot']['primary_message']['code'],
                                     historical_strategy=context.last_strategy_code())
    destination = Path(__file__).with_name('probes.json')
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
