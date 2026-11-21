"""Deterministic reply to a resolved driver speech act."""
from ..radio_understanding import TOPICS


def response(*, state, query_kind, primary_message=None, schema_metadata=None):
    meta = (schema_metadata or {}).get("semantic_metadata") or {}
    subject = TOPICS.get(meta.get("radio_topic"), "刚才的话题")
    line = {"ack": "收到。", "hold": f"明白，{subject}先等等。", "commit": f"明白，你决定{subject}。",
            "decline": f"收到，这次不考虑{subject}。", "conditional": "明白，还没定。",
            "report": "收到你的车感。", "resume": "你想接着听哪一项？",
            "ask": "你指的是哪一项？", "clarify": "你指的是哪一项？"}.get(meta.get("radio_act"), "你指的是哪一项？")
    return line, "QUERY_RADIO_REPLY"
