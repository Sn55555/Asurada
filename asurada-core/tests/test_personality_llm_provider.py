import json
import threading
import time

import pytest

from asurada import personality_llm
from asurada.personality_llm import OllamaProvider, PersonalityLlm, PersonalityLlmRequest, validate_fragment
from asurada.task_runtime import TaskContext


REQUEST = PersonalityLlmRequest("fake-request-id", "snap:simulation/Driver-16f.122", "overtake", 2, "excited")


@pytest.mark.parametrize("correct_echo", [True, False])
def test_ollama_uses_opaque_binding_and_exact_echo(monkeypatch, correct_echo):
    def response(url, *, body, **kwargs):
        assert url == "http://127.0.0.1:11434/api/generate"
        assert body["model"] == "qwen3:8b"
        assert body["stream"] is False and body["think"] is False
        assert REQUEST.decision_ref not in json.dumps(body)
        assert REQUEST.request_id not in json.dumps(body)
        wire_ref = body["format"]["properties"]["decision_ref"]["enum"][0]
        assert len(wire_ref) == 16 and wire_ref in body["prompt"]
        assert kwargs["max_response_bytes"] == 16_384 and not kwargs["propagate_budget"]
        payload = {"decision_ref": wire_ref if correct_echo else "wrong", "fragment": "干得漂亮。"}
        return {"done": True, "response": json.dumps(payload)}

    monkeypatch.setattr(personality_llm, "request_json", response)
    result = OllamaProvider().generate(REQUEST, TaskContext.start("test", 600))
    assert result == ({"decision_ref": REQUEST.decision_ref, "fragment": "干得漂亮。"} if correct_echo else {})


def test_unsafe_ollama_url_disables_generation(monkeypatch):
    monkeypatch.setenv("ASURADA_PERSONALITY_LLM_MODE", "enabled")
    monkeypatch.setenv("ASURADA_PERSONALITY_LLM_BASE_URL", "https://example.com")
    controller = PersonalityLlm.from_env()
    assert controller.mode == "disabled"
    assert not controller.start(REQUEST)
    assert controller.snapshot()["counts"] == {"invalid_config": 1}


@pytest.mark.parametrize("fragment", ["前翼没事。", "踩油门。", "漂亮，领先1秒。", "干得漂亮。进站。", "干得漂亮。\x00"])
def test_optional_text_guard_rejects_facts_instructions_and_extra_sentences(fragment):
    assert validate_fragment({"decision_ref": REQUEST.decision_ref, "fragment": fragment}, REQUEST) is None


def test_worker_capacity_stays_occupied_after_cancellation():
    entered, unblock = threading.Event(), threading.Event()

    class WaitProvider:
        def generate(self, request, context):
            entered.set()
            unblock.wait(1)
            return {"decision_ref": request.decision_ref, "fragment": "干得漂亮。"}

    controller = PersonalityLlm(mode="enabled", provider=WaitProvider())
    try:
        assert controller.start(REQUEST) and entered.wait(0.5)
        assert controller.poll() is None
        controller.cancel()
        assert not controller.pending
        assert not controller.start(REQUEST)
    finally:
        unblock.set()

    limit = time.monotonic() + 0.5
    while not controller.start(REQUEST):
        assert time.monotonic() < limit
        time.sleep(0.001)
    while (result := controller.poll()) is None:
        assert time.monotonic() < limit
        time.sleep(0.001)
    assert (result.status, result.fragment) == ("ok", "干得漂亮。")
    assert controller.snapshot()["counts"]["cancelled"] == 1
    controller.close()
    assert not controller.start(REQUEST)
