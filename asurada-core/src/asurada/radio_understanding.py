"""Interpret one racing utterance locally. Telemetry answers still come from registered capabilities."""
from __future__ import annotations

from http.client import HTTPException
import json

from .cancellable_http import request_json
from .capability_definitions import CAPABILITIES
from .radio_grounding import ground
from .semantic_normalizer import SemanticIntentResult
from .task_runtime import TaskContext

# Only capability names cross the routing boundary; Chinese labels are the model vocabulary.
QUESTIONS = {k: spec.default_query_text for k, spec in CAPABILITIES.items()
             if spec.lane in {"structured", "explainer"} and k not in {"open_fallback", "radio_reply"}}
QUESTIONS.update(front_gap="前车距离", rear_gap="后车距离", front_wing_damage_status="前翼损伤",
                 damage_status="全车损伤", tyre_status="轮胎状态", race_control_status="赛道旗号与管制",
                 fuel_status="剩余燃油", ers_status="电池余量", why_not_attack="解释进攻条件",
                 why_defend="解释防守理由", pit_status="进站状态", weather_status="天气",
                 why_not_pit="解释进站判断", attack_or_defend_summary="当前攻守形势")
ACTS = {"ask":"询问", "resume":"接回打断前的话", "hold":"暂缓决定", "commit":"明确执行或改为执行",
        "decline":"明确拒绝", "conditional":"假设或条件", "report":"陈述手感", "ack":"仅表示听见", "clarify":"指代不明"}
TOPICS = {"attack": "进攻", "defend": "防守", "pit": "进站", "fuel": "节油", "wing": "前翼",
          "tyre": "轮胎", "control": "赛道管制", "other": "其他"}


def enum(values):
    return {"type": "string", "enum": list(values)}


class RaceRadio:
    def __init__(self, *, model="qwen3:4b", latest=None):
        self.model = model
        self.latest = latest

    def interpret(self, text, state, conversation, radio, turn, parent=None):
        queries = conversation.snapshot()["recent_user_queries"][-4:]
        history = [{"text": q["transcript_text"][:120], "query": q["query_kind"],
                    "act": q["metadata"].get("radio_act"), "topic": q["metadata"].get("radio_topic")} for q in queries
                   if 0 <= state.source_timestamp_ms - q["timestamp_ms"] <= 120_000]
        heard = [row for row in radio if 0 <= state.source_timestamp_ms - row["source_ms"] <= 120_000
                 and row["started_ms"] <= turn.started_at_ms]
        last_answer = next((r for r in reversed(heard) if r["code"].startswith("QUERY_")), None)
        interrupted = (last_answer if last_answer and last_answer["status"] == "cancel"
                       and last_answer["code"][6:].lower() in QUESTIONS else None)
        unresolved = dict(act="clarify", topic="other", query="none", anchor=None, wing_side="unknown")
        grounded = ground(text, unresolved, interrupted)
        if grounded["act"] == "resume" or (grounded["act"] == "ask" and grounded["query"] == "front_wing_damage_status" and grounded["wing_side"] != "unknown" and not any(mark in text for mark in ("为什么", "要不要", "进站", "原因", "怎么办"))):
            return grounded
        refs = [0] + [r["ref"] for r in heard]
        acts = {label: key for key, label in ACTS.items()}
        topics = {label: key for key, label in TOPICS.items()}
        questions = {label: key for key, label in QUESTIONS.items()}
        sides = {"左": "front_left", "右": "front_right", "无": "unknown"}
        schema = {"type": "object", "properties": {
            "动作": enum(acts), "行动对象": enum(topics), "问题": enum(["无", *questions]),
            "前翼部位": enum(sides), "引用": {"type": "integer", "enum": refs}},
            "required": ["动作", "行动对象", "问题", "前翼部位", "引用"], "additionalProperties": False}
        instructions = ("你是中文车队无线电的语义分析器，只标注最后的车手原话。"
            "问题只填车手要查的遥测；不提问填无。动作区分询问、推迟、拒绝、明确执行、条件和主观感受。"
            "改主意后按最新决定。复合句分别识别车手决定和附带的问题。追兵是后车，车鼻是前翼。"
            "接回中断指继续黄旗之前在说的事。引用填写所指的已播电台序号，不明或新话题用0。"
            "历史不是本轮指令。只返回规定字段。可查项目：" + "、".join(questions))
        previous = [{"序号": r["ref"], "状态": r["status"], "内容": r["text"][:90]} for r in heard[-6:]]
        background = {"先前车手问题": history[-3:], "已播电台": previous,
                      "圈": state.lap_number, "裁判区旗号": state.raw.get("marshal_zone_flag")}
        messages = [{"role":"system", "content":instructions},
                    {"role":"user", "content":"参考背景："+json.dumps(background, ensure_ascii=False)
                     +"\n只判定这一句车手原话："+json.dumps(text[:300], ensure_ascii=False)}]
        budget = TaskContext.start(turn.turn_id, 3500)
        if parent:
            budget = TaskContext(parent.task_id, min(parent.deadline, budget.deadline), parent.cancellation)
        try:
            body = {"model": self.model, "messages": messages, "format": schema, "think": False,
                    "stream": False, "keep_alive": "10m",
                    "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 96}}
            result = request_json("http://127.0.0.1:11434/api/chat", method="POST", body=body,
                                  context=budget, timeout_ms=budget.remaining()*1000, max_response_bytes=8192,
                                  propagate_budget=False)
            parsed = json.loads(result["message"]["content"]) if result.get("done") else {}
            act, topic = acts[parsed["动作"]], topics[parsed["行动对象"]]
            query = "none" if parsed["问题"] == "无" else questions[parsed["问题"]]
            ref, side = parsed["引用"], sides[parsed["前翼部位"]]
            if type(ref) is not int or ref not in refs:
                raise ValueError("invalid_radio_reference")
            budget.remaining()
        except (ValueError, OSError, HTTPException, RuntimeError, KeyError, TypeError):
            return grounded if grounded["act"] != "clarify" else None
        anchor = next((r for r in heard if r["ref"] == ref), None)
        proposed = dict(act=act, topic=topic, query=query, anchor=anchor, wing_side=side)
        decision = ground(text, proposed, interrupted)
        if decision["act"] == "resume" and not interrupted:
            return unresolved
        return decision


def radio_intent(text, decision, state):
    act, topic, query, anchor = (decision[k] for k in ("act", "topic", "query", "anchor"))
    # A missing or changed rival cannot silently become the target of an old question.
    if anchor and anchor.get("rival") is not None and query in {"front_gap","rear_gap","why_not_attack","why_defend"}:
        position = state.player.position + (1 if query in {"rear_gap","why_defend"} else -1)
        if not any(r.position == position and r.car_index == anchor["rival"] for r in state.rivals):
            act, query = "clarify", "none"
    tactical_commit = topic == "attack" and act == "commit"
    attack_query = query in {"attack_or_defend_summary", "attack_outcome_projection",
                             "attack_defend_tradeoff", "why_not_attack"}
    if state.raw.get("marshal_zone_flag") == 3 and (tactical_commit or attack_query):
        act, topic, query = "ask", "control", "race_control_status"
    if act == "clarify":
        query = "none"
    if query == "none":
        query = "radio_reply"
    metadata = {"radio_act": act, "radio_topic": topic, "radio_wing_side": decision.get("wing_side"),
                "radio_reference": anchor["ref"] if anchor else None}
    return SemanticIntentResult("matched", query, text, "structured", 0., "local_radio_understanding", metadata)
