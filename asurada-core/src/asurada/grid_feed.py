"""Capture a player grid plan at the start lights and freeze its strictly pre-start inputs."""
from .frame_counter import newer, older
from .grid_strategy import grid_inputs, optimise


class GridPlanFeed:
    def __init__(self):
        self.entries = {}
        self.pending = set()
        self.selected_stops = None

    def observe(self, envelope, assembler):
        if getattr(envelope, "kind", None) != "Event" or assembler.accepted_epoch is None:
            return
        event = envelope.payload["body"].get("event_code")
        if event not in ("STLG", "LGOT"):
            return
        header = envelope.payload["header"]
        uid, frame = str(envelope.session_uid), header["overall_frame_identifier"]
        self.entries = {k:v for k,v in self.entries.items() if k in assembler.packet_epochs}
        self.pending.intersection_update(self.entries)
        previous = self.entries.get(uid)
        if previous and previous["event"] == "LGOT":
            return
        session = assembler.latest_session_by_uid.get(uid, {})
        sf = assembler.latest_session_header_by_uid.get(uid, {}).get("overall_frame_identifier")
        tf = assembler.player_packet_frames.get((uid, "TyreSets"))
        inventory = assembler._player_context(uid, "TyreSets", header)
        if sf is None or not newer(frame, sf):
            session = {}
        if tf is None or not newer(frame, tf):
            inventory = {}
        grid = grid_inputs(session, inventory, header["player_car_index"])
        plan = previous["plan"] if previous and previous["inputs"] == grid else optimise(grid)
        self.entries[uid] = dict(uid=uid, epoch=assembler.accepted_epoch, event=event, frame=frame,
                                 session_frame=sf if session else None, inventory_frame=tf if inventory else None,
                                 session_time_s=header.get("session_time_s"),
                                 inputs=grid, plan=plan, game=dict(ideal=session.get("pit_stop_window_ideal_lap"),
                                 latest=session.get("pit_stop_window_latest_lap")))
        self.pending.add(uid)

    def annotate(self, state, decision):
        uid = str(state.session_uid)
        entry = self.entries.get(uid)
        frame = state.raw.get("overall_frame_identifier")
        if not entry or frame is None or older(frame, entry["frame"]) or state.session_epoch < entry["epoch"]:
            return
        if entry["event"] == "STLG":
            clock = state.raw.get("session_time_s")
            if (state.session_epoch != entry["epoch"] or state.lap_number > 1 or state.player.speed_kph > 20
                    or clock is None or entry["session_time_s"] is None or clock - entry["session_time_s"] > 10):
                return
        if uid in self.pending:
            decision.debug["grid_strategy"] = entry
            self.pending.discard(uid)
        if entry["event"] == "STLG" and entry["plan"]["status"] == "conditional":
            plan = entry["plan"]
            shown = dict(plan["fitted_start"])
            free = plan["free_start"]
            if free["one_two_break_even_s"] != shown["one_two_break_even_s"] or set(free["routes"]) != set(shown["routes"]):
                shown["if_start_can_change"] = free
            decision.debug["starting_grid_routes"] = shown
        shadow = decision.debug.get("pit_timing_shadow")
        if shadow and entry["event"] == "LGOT" and entry["plan"]["status"] == "conditional":
            # Retain both options until the driver actually selects a stop count.
            routes = entry["plan"]["fitted_start"]["routes"]
            stops = state.raw.get("num_pit_stops")
            if type(stops) is int and stops >= 0:
                decision.debug["grid_plan_review"] = dict(grid_frame=entry["frame"], completed_stops=stops,
                    original_next_stop={count:route["stints"][stops]["end"] if stops < int(count) else None
                                        for count,route in routes.items()}, shadow_action=shadow["nominal"])
                if self.selected_stops is not None:
                    selected = routes.get(str(self.selected_stops))
                    proposal = shadow.get("options", {}).get(shadow["nominal"])
                    decision.debug["grid_plan_review"]["selected"] = dict(
                        stop_count=self.selected_stops, feasible=selected is not None,
                        next_stop_number=stops + 1,
                        planned_lap=selected["stints"][stops]["end"] if selected and stops < self.selected_stops else None,
                        shadow_lap=proposal["stop_lap"] if proposal else None,
                        shadow_verdict=shadow["verdict"], missing=shadow["missing"])
