"""Deterministic expression and disposable, context-bound speech opportunities."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
import os
import time

from .battle_speech import battle_line
from .interaction import SpeechJob
from .output_contracts import CAUTION_SPEECH_CODES, _SpeechEnvelope
from .personality_runtime import POSITIVE_EVENTS, personality_enabled
from .personality_setback import SETBACK_LINES
from .personality_pit_advice import PersonalityPitAdvice, TyreObservation, safe_pit_follow_up, tyre_observation
from .persona_registry import get_default_persona

TONE_LINES = {
    "firm": "注意。",
    "concerned": "稳住。",
}
HUMOR_LINES = {
    "banter": ("我负责算清楚，你负责让我重新计算。", "我有幽默感，只是默认静音。"),
    "memory_overtake": ("还记得我们之前那次超车吗？那时我也算得很忙。",),
    "memory_fastest_lap": ("我们之前刷过最快圈。我的计时器还记得。",),
    "timer_joke": ("计时器申请休息。我驳回了。",),
    "calculation_joke": ("好，下次我争取先算完。",),
}
EVENT_LINES = {
    "overtake": (
        ("超车成功，节奏很好。", "完成超车。干得好。"),
        ("漂亮。超车成功，稳住节奏。", "超过去了。漂亮。"),
        ("漂亮。我的计算总算跟上你的动作了。", "超过去了。好，少算一辆。"),
        ("这次我承认，你动作够快。", "漂亮，隼人。这次我报得比你还慢。"),
    ),
    "fastest_lap": (
        ("最快圈。干得好。", "刷出最快圈。漂亮。"),
        ("漂亮，最快圈。这个节奏很好。", "最快圈拿到了。好样的。"),
        ("最快圈。看来计时器也同意。", "漂亮，最快圈。这回计时器可以服气了。"),
        ("最快圈，隼人。计时器这回没话说了。", "干得好，隼人。最快圈归你，计时归我。"),
    ),
    "minor_offtrack": (
        ("刚才跑宽了，注意路线。", "注意赛道边界。刚才出去了。"),
        ("我规划的路线里，没有赛道边界外那一段。", "刚才跑宽了。白线的位置没变。"),
        ("看来你在探索赛道边界。记录完毕。", "赛道边界没跑，是我们跑宽了。"),
        ("赛道边界的位置确认了。测量任务结束，回正题。", "隼人，边界检查结束。那条白线还在。"),
    ),
    "finish": (
        ("比赛结束。干得好。", "完赛了，做得好。"),
        ("到终点了。今天辛苦。", "收工。跑完了，干得好。"),
        ("跑完了。我的计算终于可以休息了。", "到终点了。我把计算留给下一场。"),
        ("完赛了，隼人。你可以休息了，我还得看数据。", "收工，隼人。今天最后一句，干得漂亮。"),
    ),
}
PIT_WINDOW_LINES = (
    "建议评估本圈进站。",
    "留意本圈，进站条件值得评估。",
    "我的判断是，值得评估本圈进站。",
    "我倾向评估本圈进站。先把条件确认清楚。",
)
PIT_FOLLOW_UP_LINES = {
    "insist": (
        "轮胎磨损偏高。还是建议进站。",
        "这套胎磨损还是高，建议进站。",
        "隼人，这套胎磨损还高。找机会进站。",
        "隼人，这套胎别再撑了。建议进站。",
    ),
    "revise": (
        "新胎磨损正常。进站提醒取消。",
        "换好了，新胎读数正常。刚才的进站提醒不用管了。",
        "隼人，新胎磨损正常。刚才的进站提醒取消。",
        "新胎磨损正常，隼人。进站提醒取消，回到你的节奏。",
    ),
    "admit": (
        "刚才判错了。磨损正常，先不进站。",
        "刚才是我看错了。这套胎还能跑，先不进站。",
        "隼人，刚才我判错了。磨损正常，留在赛道上。",
        "这次算我的，隼人。磨损正常，先别进站。",
    ),
}
PIT_FOLLOW_UP_CODES = {
    "insist": "PERSONALITY_PIT_INSIST",
    "revise": "PERSONALITY_PIT_REVISE",
    "admit": "PERSONALITY_PIT_ADMIT",
}

BANTER_PROMPTS = {"开个玩笑", "讲个笑话", "吐槽一下", "我们配合怎么样"}
JOKE_OPT_OUT = {"这个别再提", "这个梗别再提", "这个玩笑别再提"}
DRIVER_JOKES = {"计时器累了": "timer_joke", "你算慢了": "calculation_joke"}


def _banter_text(text: str | None) -> str:
    return (text or "").strip().strip("，。！？,.!?").strip()


def banter_requested(text: str | None) -> bool:
    spoken = _banter_text(text)
    return spoken in BANTER_PROMPTS or spoken in DRIVER_JOKES or spoken in JOKE_OPT_OUT


def joke_opt_out_requested(text: str | None) -> bool:
    return _banter_text(text) in JOKE_OPT_OUT


class PersonalityDialogue:
    def __init__(self, clock=time.monotonic, wall_clock=time.time) -> None:
        self.enabled = personality_enabled()
        self.profile = get_default_persona()
        self.humor_allowed = (self.enabled and self.profile.humor_affinity > 0
                              and os.getenv("ASURADA_HUMOR_ENABLED", "1") != "0")
        self.quiet = False
        self.humor_level = "normal"
        self.clock = clock
        self.wall_clock = wall_clock
        self.battle_history = {}
        self.last_humor = None
        self.last_optional = None
        self.last_by_kind: dict[str, float] = {}
        self.next_line: dict[str, int] = {}
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.pit_advice = PersonalityPitAdvice()
        self.last_joke: str | None = None
        self.muted_jokes: set[str] = set()

    @property
    def humor_enabled(self) -> bool:
        return self.humor_allowed and not self.quiet and self.humor_level != "off"

    def configure(self, params: dict) -> dict:
        if not isinstance(params, dict) or set(params) - {"quiet", "humor"}:
            raise ValueError("invalid_personality_preferences")
        quiet = params.get("quiet", self.quiet)
        humor = params.get("humor", self.humor_level)
        if type(quiet) is not bool or humor not in ("off", "low", "normal"):
            raise ValueError("invalid_personality_preferences")
        self.quiet, self.humor_level = quiet, humor
        return {"quiet": self.quiet, "humor": self.humor_level, "humor_enabled": self.humor_enabled}

    def suppresses_job(self, job: SpeechJob) -> bool:
        metadata = job.metadata
        if self.quiet:
            return bool(metadata.get("optional_personality") or metadata.get("pit_follow_up") == "insist")
        return not self.humor_enabled and bool(metadata.get("humor"))

    def battle(self, state, direction, meta, fallback):
        if not self.enabled or self.quiet:
            return fallback, {}
        hint = state.personality
        return battle_line(state, direction, meta, fallback, self.battle_history.get(direction),
                           hint if hint and hint.matches(state) else None)

    def personalize(self, state, text: str, *, protected: bool = False, strategy_code: str | None = None) -> tuple[str, dict]:
        hint = state.personality if state is not None else None
        if not self.enabled:
            return text, {}
        if self.quiet:
            return text, {"tone": "calm", "reason": "personality_quiet"}
        if hint is None or not hint.matches(state):
            return text, {"reason": "personality_snapshot_unavailable"}
        separator = " " if text.endswith(("。", "！", "？", ".", "!", "?")) else "。 "
        if strategy_code == "BOX_WINDOW":
            return f"{text}{separator}{PIT_WINDOW_LINES[hint.stage]}", {"tone": "firm", "stage": hint.stage}
        if strategy_code in {"PIT_NOW", "BOX_NOW"}:
            return f"{text}{separator}当前是推荐进站窗口，建议本圈进站。", {"tone": "firm", "stage": hint.stage}
        tone = hint.tone
        if tone == "excited":
            # Residual emotion from a lap or pass should not congratulate an unrelated query.
            tone = "firm" if protected or strategy_code in CAUTION_SPEECH_CODES else "calm"
        personality = {"tone": tone, "stage": hint.stage, "event_id": hint.event_id, "trigger": hint.trigger}
        if protected:
            return text, {**personality, "reason": "protected_speech"}
        line = TONE_LINES.get(tone)
        return (f"{line} {text}" if line is not None else text), personality

    def context_current(self, state, *, live: bool) -> bool:
        hint = state.personality if state is not None else None
        if hint is None or not hint.matches(state) or not hint.low_load:
            return False
        return not live or 0 <= self.wall_clock() * 1000 - state.source_timestamp_ms <= 1000

    def opportunity(self, state, *, live: bool, event: dict, task: dict, output_id,
                    persona, direct: bool = False) -> _SpeechEnvelope | None:
        if not self.enabled or self.quiet or not self.context_current(state, live=live):
            return None
        hint = state.personality
        if direct:
            if (not self.humor_enabled or hint.stage < 2 or hint.opportunity in SETBACK_LINES
                    or hint.concern * self.profile.empathy >= .25):
                return None
            kind = DRIVER_JOKES.get(_banter_text(event.get("query_text")), "banter")
            identity = str(event["request_id"])
            if (kind == "banter" and self.humor_level == "normal"
                    and hint.stage >= 3 and hint.memory_kind in {"overtake", "fastest_lap"}):
                kind = "memory_" + hint.memory_kind
        else:
            kind = hint.opportunity
            identity = hint.event_id
            if (kind not in EVENT_LINES and kind not in SETBACK_LINES or not identity or hint.opportunity_age_s is None
                    or not 0 <= hint.opportunity_age_s <= 2):
                return None
            if kind == "finish" and not self.humor_enabled:
                return None
        if identity in self.seen:
            return None
        if len(self.seen) >= 512:
            self.seen.popitem(last=False)
        self.seen[identity] = None
        now = self.clock() if live else hint.clock_s
        event_stage = hint.stage if self.humor_enabled else 0
        humor_interval, repeat_interval = 45, 120
        if self.humor_level == "low":
            event_stage = min(event_stage, 1)
            humor_interval, repeat_interval = 90, 240
        setback = kind in SETBACK_LINES
        humorous = not setback and (kind not in EVENT_LINES or event_stage >= (2 if kind == "finish" else 1))
        if self.last_optional is not None and now - self.last_optional < 8:
            return None
        if humorous and (self.last_humor is not None and now - self.last_humor < humor_interval
                or kind in self.last_by_kind and now - self.last_by_kind[kind] < repeat_interval):
            return None
        lines = (SETBACK_LINES[kind],) if setback else (
            EVENT_LINES[kind][event_stage] if kind in EVENT_LINES else HUMOR_LINES[kind])
        if kind == "finish" and self.profile.pride < .5:
            lines = ("完赛了，做得好。",)
        if humorous:
            lines = tuple(line for line in lines if line not in self.muted_jokes)
            if not lines:
                return None
        tone = "concerned" if setback else "excited" if kind in POSITIVE_EVENTS else "calm"
        variant_key = f"{kind}:H{event_stage}"
        line_index = self.next_line.get(variant_key, 0)
        line = lines[line_index % len(lines)]
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=output_id(),
                interaction_session_id=str(event.get("interaction_session_id") or f"runtime:{state.session_uid}"),
                turn_id=str(event.get("turn_id") or identity),
                request_id=identity,
                snapshot_binding_id=str(event.get("snapshot_binding_id") or hint.snapshot_id),
                source_kind="query_response" if direct else "personality_optional",
                action_code="PERSONALITY_BANTER" if direct else "PERSONALITY_" + kind.upper(),
                priority=0,
                speak_text=line,
                cancelable=True,
                persona_id=persona.persona_id,
                voice_profile_id=persona.voice_profile_id,
                metadata={"personality": {"opportunity": kind, "humorous": humorous, "stage": hint.stage,
                                          "event_id": identity, "tone": tone},
                          "optional_personality": True, "personality_clock": now,
                          "personality_variant_key": variant_key,
                          "joke_line": line if humorous else None,
                          "humor": (kind, now) if humorous else None, "repeatable": False},
            ),
            interaction_input_event=event,
            task_handle=task,
        )

    def mute_last_joke(self) -> str | None:
        line = self.last_joke
        if line is not None:
            self.muted_jokes.add(line)
            self.last_joke = None
        return line

    def observe_pit_advice(self, state, *, live: bool) -> None:
        if not self.enabled:
            return
        hint = state.personality
        fresh = not live or 0 <= self.wall_clock() * 1000 - state.source_timestamp_ms <= 1000
        self.pit_advice.observe(tyre_observation(state) if hint is not None and hint.matches(state) and fresh else None)

    def pit_original_metadata(self) -> dict:
        observation = self.pit_advice.current
        if observation is None or observation.verdict != "box_now":
            return {}
        return {"tyre_pit_original": asdict(observation)}

    def record_pit_response(self, output_event_id: str) -> bool:
        return self.pit_advice.acknowledge(output_event_id)

    def pit_follow_up(self, state, *, event: dict, task: dict, output_id, persona) -> _SpeechEnvelope | None:
        kind = self.pit_advice.due()
        if kind is None or (self.quiet and kind == "insist") or not safe_pit_follow_up(state):
            return None
        hint = state.personality
        stage = 0 if self.quiet else hint.stage
        code = PIT_FOLLOW_UP_CODES[kind]
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=output_id(),
                interaction_session_id=str(event.get("interaction_session_id") or f"runtime:{state.session_uid}"),
                turn_id=str(event.get("turn_id") or "pit-follow-up"),
                request_id=f"{code}:{hint.snapshot_id}",
                snapshot_binding_id=hint.snapshot_id,
                source_kind="strategy_broadcast",
                action_code=code,
                priority=50,
                speak_text=PIT_FOLLOW_UP_LINES[kind][stage],
                cancelable=True,
                persona_id=persona.persona_id,
                voice_profile_id=persona.voice_profile_id,
                metadata={"pit_follow_up": kind, "repeatable": False,
                          "personality": {"tone": "firm", "stage": stage}},
            ),
            interaction_input_event=event,
            task_handle=task,
        )

    def completed(self, job: SpeechJob) -> None:
        spoken = job.metadata.get("personality") or {}
        if spoken.get("battle"):
            self.battle_history[spoken["battle"]] = spoken
        if job.metadata.get("joke_line") and job.metadata["joke_line"] not in self.muted_jokes:
            self.last_joke = job.metadata["joke_line"]
        evidence = job.metadata.get("tyre_pit_original")
        if evidence:
            self.pit_advice.original_completed(TyreObservation(**evidence), job.output_event_id)
        kind = job.metadata.get("pit_follow_up")
        if kind in {"revise", "admit"}:
            self.pit_advice.retire()

    def started(self, job: SpeechJob) -> None:
        if job.metadata.get("pit_follow_up") == "insist":
            self.pit_advice.insisted = True
        if job.metadata.get("optional_personality"):
            self.last_optional = job.metadata["personality_clock"]
            variant_key = job.metadata["personality_variant_key"]
            self.next_line[variant_key] = self.next_line.get(variant_key, 0) + 1
        humor = job.metadata.get("humor")
        if humor is not None:
            kind, now = humor
            # A newer, still-playing joke makes a previous clip an ambiguous referent.
            self.last_joke = None
            self.last_humor = now
            self.last_by_kind[kind] = now

    def bind(self, *, replay: bool) -> None:
        self.battle_history.clear()
        self.pit_advice = PersonalityPitAdvice()
        self.last_joke = None
        # Live cooldown spans races. Capture time restarts at a scope boundary.
        if replay:
            self.last_optional = None
            self.last_humor = None
            self.last_by_kind.clear()
            self.next_line.clear()
            self.seen.clear()
