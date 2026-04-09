from __future__ import annotations

import json
import sys
from typing import Any


def _build_answer(query_kind: str, text: str) -> dict[str, Any]:
    if query_kind == "overall_situation":
        answer_text = "当前整体先守住后车，再观察处罚处理窗口。"
        reason_fields = ["rear_pressure", "penalty_window"]
    elif query_kind == "why_not_attack":
        answer_text = "当前不进攻，主要因为前车窗口还不够干净，后车压力更直接。"
        reason_fields = ["gap_ahead_s", "gap_behind_s"]
    else:
        answer_text = f"关于“{text}”，当前更适合先按已有策略窗口处理。"
        reason_fields = ["primary_message"]
    return {
        "status": "answerable",
        "answer_text": answer_text,
        "confidence": 0.78,
        "reason_fields": reason_fields,
        "requires_confirmation": False,
        "metadata": {"stub": True, "query_kind": query_kind},
    }


def main() -> int:
    payload = json.load(sys.stdin)
    query_kind = str(payload.get("query_kind") or "")
    normalized_query_text = str(payload.get("normalized_query_text") or "")
    print(json.dumps(_build_answer(query_kind, normalized_query_text), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
