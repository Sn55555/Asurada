"""Evidence-bound race radio. Times are seconds on the session clock."""
from .attack_outcome import relative_position


def phrase_seconds(text):
    # Initial consonant, pauses and the end of the last word count toward the deadline.
    return .35 + .32 * sum(ch.isalnum() for ch in text)


def front_runway(state, rival, forecast=None):
    """Earliest of braking point and estimated nose-to-tail contact, using current facts."""
    f = forecast or {}
    room = f.get("eta_s", float("inf"))
    geo = relative_position(state.player, rival, state.raw.get("world_forward_dir") or {})
    distance = geo[0] if geo else None
    if distance is None and state.player.lap == rival.lap:
        a, b = state.player.lap_distance_m, rival.lap_distance_m
        if a is not None and b is not None and 0 <= a and 0 <= b and abs(b - a) < 300:
            distance = b - a
    if distance is not None:
        if distance <= 4:
            return 0.
        player_speed, other_speed = state.player.speed_kph, rival.speed_kph
        if player_speed and other_speed and player_speed > other_speed:
            room = min(room, (distance - 4) * 3.6 / (player_speed - other_speed))
    slope = f.get("trend_s_per_s") or 0
    if slope > 0 and f.get("gap_s") is not None:
        room = min(room, f["gap_s"] / slope)
    return room


def battle_line(state, direction, meta, fallback, last, hint):
    rear = direction == "defence"
    forecast = meta.get("forecast") or {}
    approach = meta.get("approach") or {}
    closing = meta.get("closing") or {}
    target = meta.get("target") if rear else meta.get("front_car_index")
    rival = next((car for car in state.rivals if car.car_index == target), None)
    if rival is None:
        return fallback, {}
    name = forecast.get("name") or rival.name or ("后车" if rear else "前车")
    if name.startswith("Car ") and name[4:].isdigit():
        name = "后车" if rear else "前车"
    location = forecast.get("label", "").removeprefix("前面")
    now = state.raw["session_time_s"]
    same = last and last["target"] == target and 0 <= now - last["clock_s"] <= 45
    phase = meta.get("phase")
    if phase == "forecast" and "key_phrase" in meta:
        return fallback, dict(battle=direction, target=target, clock_s=now, key_phrase=meta["key_phrase"],
                              key_seconds=meta["key_seconds"], runway_s=meta["speech_deadline"] - now,
                              previous_target=target if same else None, stage=hint.stage if hint else None,
                              tone="calm")
    if rear and "contact_s" in meta:
        return fallback, dict(battle=direction, target=target, clock_s=now, key_phrase=meta["key_phrase"],
                              key_seconds=meta["key_seconds"], runway_s=meta["contact_s"],
                              previous_target=target if same else None, stage=hint.stage if hint else None,
                              tone="firm" if hint and hint.tone=="excited" else hint.tone if hint else "calm")
    if approach:
        core = approach["text"].rstrip("。")
        detail = f"{name}追上来了"
        room = approach["earliest_s"]
    elif rear and not forecast:
        core = f"{name}在追"
        detail = ""
        room = closing["earliest_s"]
    elif forecast:
        # Generated segment indices are not necessarily official corner numbers.
        place = "直道末端" if location == "长直道尽头" else location or "直道尽头"
        core = f"守{place}" if rear else f"{place}找机会"
        slope = forecast.get("trend_s_per_s") or 0
        if rear:
            detail = f"{name}还在逼近" if same and slope > .02 else (
                f"{name}在逼近" if slope > .02 else f"后面是{name}")
            room = min(forecast["eta_s"], closing.get("earliest_s", float("inf")))
            if forecast.get("gap_s", 10) < .35 and slope > 0:
                # Close behind: give the actionable location before identification.
                detail = "" if same else name
        else:
            room = front_runway(state, rival, forecast)
            gain = forecast.get("section_gain_s")
            if hint and hint.stage >= 1 and gain is not None and gain > .1:
                detail = f"上几圈这段比{name}快" if len(forecast.get("section_times", [])) >= 2 else f"上一段计时比{name}快"
            elif forecast.get("drs_allowed") is True:
                detail = f"对{name}可以用尾翼"
            elif slope > .02:
                detail = f"还在追近{name}" if same else f"你在追近{name}"
            else:
                detail = f"前面是{name}"
    else:
        # Preserve the result/withdrawal verdict and its uncertainty.
        core = fallback.rstrip("。")
        detail = f"对手是{name}"
        room = meta["latest_useful_s"] - now
        if phase in {"forming", "actionable"}:
            room = min(room, front_runway(state, rival))
    # With room for only one clause, deliver the action first. A brief generic
    # alarm can point out closure without spending the entire deadline on a long name.
    if rear and not forecast and not approach and phrase_seconds(core) + .3 > room:
        core = "后车逼近"
    core_s = phrase_seconds(core)
    if phase not in {"outcome", "withdrawal"} and room < core_s + .3:
        return None, {}
    if detail and phrase_seconds(core + detail) + .65 <= room:
        text = f"{core}，{detail}。"
    else:
        text = core + "。"
    tone = hint.tone if hint else "calm"
    if rear and tone == "excited":
        tone = "firm"
    return text, dict(battle=direction, target=target, clock_s=now, key_phrase=core,
                      key_seconds=core_s, runway_s=min(room, 600), previous_target=last["target"] if same else None,
                      stage=hint.stage if hint else None, tone=tone)


def defence_line(meta):
    """Choose a line whose actionable clause leaves at least one second for the driver."""
    room = meta["contact_s"] - 1.
    threats = meta["threats"]
    count = len(threats)
    numerals = "零一两三四五六七八九十"
    name = meta.get("name") or "后车"
    if name.startswith("Car ") and name[4:].isdigit():
        name = "后车"
    if count > 1 and name == "后车":
        return None

    place = meta["place"]
    position = meta.get("position_phrase", "后方")
    if count == 1:
        options = []
        if place and name != "后车":
            options.append(f"{position}{name}，守{place}")
        if place:
            options.append(f"{place}防{name}")
            if place == "主直道":
                options.append(f"直道防{name}")
        elif name != "后车":
            options.extend((f"{name}在{position}", f"{name}在后"))
        else:
            return None
        for key in options:
            if phrase_seconds(key) <= room:
                return key + "。", key, phrase_seconds(key)
        return None

    if not place:
        return None
    quantity = numerals[count] if count <= 10 else str(count)
    reason = "他没被挡" if meta.get("clear_lane") else ""
    if not reason and threats[1]["contact_s"] - threats[0]["contact_s"] >= .2:
        reason = "他会先到"
    keys = [f"{location}防{name}。{quantity}辆"
            for location in dict.fromkeys((place, "直道" if place == "主直道" else place))]
    feasible = [key for key in keys if phrase_seconds(key) <= room]
    if reason:
        for key in feasible:
            if phrase_seconds(key + reason) + .3 <= meta["contact_s"]:
                return key + "，" + reason + "。", key, phrase_seconds(key)
    if feasible:
        key = feasible[0]
        return key + "。", key, phrase_seconds(key)
    return None
