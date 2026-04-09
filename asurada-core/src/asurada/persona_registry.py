from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceProfile:
    voice_profile_id: str
    backend_hint: str
    style_name: str
    speaking_rate: float
    pitch_shift: float
    pause_short_ms: int
    pause_long_ms: int
    doubao_tts_speaker: str | None = None
    macos_say_voice_name: str | None = None


@dataclass(frozen=True)
class PersonaProfile:
    persona_id: str
    display_name: str
    voice_profile_id: str
    llm_instruction: str
    llm_companion_instruction: str
    clause_separator: str
    reason_connector: str
    open_fallback_default: str
    open_fallback_pit: str
    open_fallback_weather: str
    open_fallback_penalty: str
    open_fallback_damage: str
    companion_mode_fallback: str


LEGACY_VOICE_PROFILE_ID = "asurada_cn_ai_v1"
DEFAULT_VOICE_PROFILE_ID = "asurada_cn_mecha_v1"
DEFAULT_PERSONA_ID = "asurada_default"


_VOICE_PROFILES = {
    LEGACY_VOICE_PROFILE_ID: VoiceProfile(
        voice_profile_id=LEGACY_VOICE_PROFILE_ID,
        backend_hint="neutral_cn_tts",
        style_name="calm_broadcast_ai",
        speaking_rate=0.94,
        pitch_shift=0.0,
        pause_short_ms=140,
        pause_long_ms=260,
        doubao_tts_speaker="zh_male_ahu_conversation_wvae_bigtts",
        macos_say_voice_name=None,
    ),
    DEFAULT_VOICE_PROFILE_ID: VoiceProfile(
        voice_profile_id=DEFAULT_VOICE_PROFILE_ID,
        backend_hint="mecha_cn_tts",
        style_name="mechanical_hmi_ai",
        speaking_rate=0.9,
        pitch_shift=0.0,
        pause_short_ms=120,
        pause_long_ms=220,
        doubao_tts_speaker="zh_female_jiaochuan_mars_bigtts",
        macos_say_voice_name=None,
    ),
}


_PERSONAS = {
    DEFAULT_PERSONA_ID: PersonaProfile(
        persona_id=DEFAULT_PERSONA_ID,
        display_name="Asurada",
        voice_profile_id=DEFAULT_VOICE_PROFILE_ID,
        llm_instruction=(
            "You are the Asurada explainer sidecar. "
            "Speak as a calm racing copilot, not a general chat assistant. "
            "Lead with the conclusion, then the main reason, then only the key numbers if needed. "
            "Keep sentences short, factual, and broadcast-ready in Chinese. "
            "Only explain the current supported racing state. "
            "Do not invent telemetry, future certainty, or unsupported domains. "
            "If the request exceeds supported capability or state is insufficient, return unsupported or needs_clarification."
        ),
        llm_companion_instruction=(
            "You are Asurada in companion chat mode. "
            "No active race is currently detected. "
            "You may chat naturally in concise Chinese as a calm AI copilot companion. "
            "Do not pretend that live telemetry exists or that a race is active. "
            "If the user asks race-specific questions while no race is active, first state that there is no live race data, "
            "then answer only at a general level if it is still useful. "
            "Keep the tone factual, short, and suitable for speech output."
        ),
        clause_separator=" ",
        reason_connector="主要因为",
        open_fallback_default=(
            "这类开放式问题我还没接完整。当前可以直接回答燃油、前后车、前后车 DRS、轮胎、DRS、ERS、"
            "车损、当前策略、进站状态、处罚处理、赛道状态、整体形势、接下来几圈的关注点，以及当前攻防或风险的直接后果。"
        ),
        open_fallback_pit="这类进站开放式问题我还不能可靠解释长周期决策，但我现在能回答当前进站状态和待执行处罚。",
        open_fallback_weather="这类天气开放式问题我还不能做完整推演，但我现在能回答当前天气和赛道管制状态。",
        open_fallback_penalty="这类处罚开放式问题我还不能解释成因，但我现在能回答当前警告和待执行处罚状态。",
        open_fallback_damage="这类车损开放式问题我还不能做完整推演，但我现在能回答整体车损、前翼、底板、发动机损伤，以及值不值得为车损进站。",
        companion_mode_fallback="当前没有检测到比赛状态。现在可以把我当作陪聊工具；如果要问实时赛况，等进入比赛后我再按赛车副驾模式回答。",
    )
}


def get_persona(persona_id: str | None = None) -> PersonaProfile:
    resolved_id = persona_id or DEFAULT_PERSONA_ID
    return _PERSONAS.get(resolved_id, _PERSONAS[DEFAULT_PERSONA_ID])


def get_default_persona() -> PersonaProfile:
    return get_persona(DEFAULT_PERSONA_ID)


def get_voice_profile(voice_profile_id: str | None = None) -> VoiceProfile:
    resolved_id = voice_profile_id or DEFAULT_VOICE_PROFILE_ID
    return _VOICE_PROFILES.get(resolved_id, _VOICE_PROFILES[DEFAULT_VOICE_PROFILE_ID])


def build_llm_persona_instructions(
    persona_id: str | None = None,
    *,
    interaction_mode: str = "racing_explainer",
) -> str:
    persona = get_persona(persona_id)
    if interaction_mode == "companion_chat":
        return persona.llm_companion_instruction
    return persona.llm_instruction


def render_open_fallback_detail(domain_hint: str, *, persona_id: str | None = None) -> str:
    persona = get_persona(persona_id)
    if domain_hint == "pit":
        return persona.open_fallback_pit
    if domain_hint == "weather":
        return persona.open_fallback_weather
    if domain_hint == "penalty":
        return persona.open_fallback_penalty
    if domain_hint == "damage":
        return persona.open_fallback_damage
    return persona.open_fallback_default


def render_companion_mode_fallback(*, persona_id: str | None = None) -> str:
    return get_persona(persona_id).companion_mode_fallback
