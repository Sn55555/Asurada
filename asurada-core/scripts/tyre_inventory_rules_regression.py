"""Check player ownership, temporal boundaries and F1 25 race tyre obligations."""
import struct

from asurada.long_horizon import LongHorizonStrategyBaseline, PitWindowSupport
from asurada.session_router import SessionRoute
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu import PacketEnvelope, RawPacket
from asurada.pdu_decoder import F125PacketDecoder
from phase1_long_horizon_forecast_history_regression import _build_state
from regression_support import emit_result


def inventory_packet(owner=3):
    decoder = F125PacketDecoder()
    wire = bytearray(231)
    struct.pack_into(decoder.HEADER_FORMAT, wire, 0, 2025, 25, 1, 25, 1, 12, 1, 1., 50, 50, 3, 255)
    wire[29], wire[230] = owner, 5
    for i in range(20):
        struct.pack_into("<7BhB", wire, 30 + 10*i, 17, 16, i, 1, 15, 23, 22, -150, i == 5)
    return decoder.decode_raw(RawPacket(1000, bytes(wire), "", 0))


def run():
    checks = {}
    asm = CaptureSnapshotAssembler()
    packet = inventory_packet()
    body = packet.payload["body"]
    row = body["sets"][5]
    checks["wire_owner_signed_delta_and_last_record"] = (
        body["car_index"] == 3 and body["fitted_idx"] == 5 and row["fitted"]
        and row["lap_delta_time_ms"] == -150 and body["sets"][19]["wear_pct"] == 19
        and "requested_fitted_idx" not in body)
    asm.push(packet)
    asm.push(inventory_packet(owner=2))
    header = dict(packet.payload["header"])
    checks["foreign_packet_cannot_replace_own"] = asm._player_context("1", "TyreSets", header) == body
    checks["future_inventory_hidden"] = not asm._player_context("1", "TyreSets", dict(header, overall_frame_identifier=49))
    checks["different_player_hidden"] = not asm._player_context("1", "TyreSets", dict(header, player_car_index=4))
    older = inventory_packet()
    older.payload["header"].update(frame_identifier=49, overall_frame_identifier=49, received_at_ms=1001)
    older.payload["body"]["fitted_idx"] = 11
    asm.push(older)
    checks["out_of_order_ignored"] = asm._player_context("1", "TyreSets", header)["fitted_idx"] == 5
    asm.push(PacketEnvelope("Motion", 51, "1", {"header": dict(header, received_at_ms=6100,
                            overall_frame_identifier=51, frame_identifier=51), "body": {}}))
    checks["inventory_expires"] = not asm._player_context("1", "TyreSets", header)
    packet.payload["header"].update(received_at_ms=6101, overall_frame_identifier=52, frame_identifier=52)
    asm.push(packet)
    rewind = dict(header, received_at_ms=6102, overall_frame_identifier=53, frame_identifier=15)
    asm.push(PacketEnvelope("Motion", 15, "1", {"header": rewind, "body": {}}))
    checks["rewind_clears_inventory"] = not asm._player_context("1", "TyreSets", rewind)

    state = _build_state()
    state.player.car_index = 3
    state.raw["tyre_sets"] = body
    planner = LongHorizonStrategyBaseline()
    options = planner._available_set_options(state)
    checks["actual_compound_and_only_spare_sets"] = (
        set(options) == {"C4"} and {r["set_index"] for r in options["C4"]} == set(range(20)) - {5})
    state.raw["tyre_sets"] = dict(body, car_index=2)
    checks["foreign_inventory_unavailable_to_planner"] = planner._available_set_options(state) == {}
    state.raw["tyre_sets"] = {"sets": body["sets"]}
    checks["legacy_ownerless_inventory_unknown"] = planner._available_set_options(state) == {}

    settings = dict(session_type=16, session_length=4, formula=0, game_mode=28, rule_set=1,
                    weekend_structure=[1, 13, 15, 8, 16], num_red_flag_periods=0)
    state.raw["tyre_rule_settings"] = settings
    state.player.tyre.compound = "C4"
    support = PitWindowSupport()

    def rule():
        return support._compound_rule_state(state=state, current_compound=state.player.tyre.compound)

    state.weather = "LightRain"
    checks["rain_on_slicks_keeps_requirement"] = rule() == ("unmet", 1)
    state.player.tyre.compound = "Intermediate"
    checks["mounted_intermediate_waives_two_slicks"] = rule() == ("satisfied", 0)
    state.player.tyre.compound = "C4"
    state.raw["num_pit_stops"] = 1
    history = {"car_index": 3, "num_tyre_stints": 2, "tyre_stints_history_data": [
        {"end_lap": 11, "tyre_actual_compound": 7}, {"end_lap": 255, "tyre_actual_compound": 17}]}
    state.raw["session_history"] = history
    checks["wet_stint_still_counts_after_drying"] = rule() == ("satisfied", 0)
    history["tyre_stints_history_data"][0]["tyre_actual_compound"] = 18
    checks["two_actual_compounds"] = rule() == ("satisfied", 0)
    history["tyre_stints_history_data"][0]["tyre_actual_compound"] = 17
    checks["same_compound_stop_not_enough"] = rule() == ("unmet", 1)
    history["car_index"] = 4
    checks["foreign_history_cannot_confirm_requirement"] = rule() == ("unknown", 0)
    history["car_index"] = 3
    settings["session_length"] = 3
    checks["five_lap_race_no_obligation"] = rule() == ("not_applicable", 0)
    settings.update(session_length=4, session_type=15)
    checks["sprint_no_obligation"] = rule() == ("not_applicable", 0)
    settings["weekend_structure"] = [1, 5, 15]
    checks["ordinary_race_can_be_session_15"] = rule() == ("unmet", 1)
    state.track = "Monaco"
    state.raw["num_pit_stops"] = 0
    state.player.tyre.compound = "Wet"
    checks["monaco_wets_keep_two_stop_rule"] = rule() == ("sets_unmet", 2)
    settings["num_red_flag_periods"] = 1
    checks["monaco_red_flag_needs_evidence"] = rule() == ("unknown", 0)
    settings["game_mode"] = 7
    checks["unverified_custom_rules_unknown"] = rule() == ("unknown", 0)
    state.track = "Shanghai"
    state.weather = "Clear"
    state.player.tyre.compound = "C4"
    state.lap_number = state.total_laps - 1
    settings.update(game_mode=28, num_red_flag_periods=0)
    state.raw["tyre_sets"] = body  # Every spare in the fixture is also C4.
    route = SessionRoute("race", {"BOX_WINDOW"}, True, True, "test")
    support_state = support.evaluate(state=state, session_route=route, context=None, resource_models={},
                                     rival_pressure_models={}, tyre_degradation_trend_models={})
    plan = planner.plan(state=state, session_route=route, support=support_state, resource_models={}, rival_pressure_models={})
    checks["last_legal_lap_requires_a_distinct_compound"] = (
        plan.recommended_pit_lap == state.lap_number and plan.recommended_compound != "C4"
        and plan.recommended_set_index is None and not plan.recommended_set_available)
    settings["session_length"] = 3
    state.player.tyre.wear_pct = 5.59
    state.player.tyre.age_laps = 1
    support_state = support.evaluate(state=state, session_route=route, context=None, resource_models={},
                                     rival_pressure_models={}, tyre_degradation_trend_models={})
    support_state.pit_window_open_prob = 0.12
    support_state.undercut_defence_score = 0.
    plan = planner.plan(state=state, session_route=route, support=support_state, resource_models={}, rival_pressure_models={})
    checks["stay_out_cannot_publish_this_lap_as_its_window"] = (
        plan.candidates[0].code == "stay_out" and plan.recommended_pit_lap is None
        and plan.recommended_compound is None and plan.recommended_set_index is None)
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    emit_result(run())
