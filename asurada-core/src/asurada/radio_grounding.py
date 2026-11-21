"""Ground explicit subjects and modifiers before accepting a model-proposed radio interpretation."""
import re

# Racing entities and grammatical roles, not transcript aliases. In particular a
# question about an entity and a request to defer that entity are different acts.
SUBJECTS = {
    "front_wing_damage_status": r"前翼|鼻翼|鼻锥|车鼻|前定风翼",
    "rear_gap": r"后车|后方|身后|后头|后边|后面|追兵|追我的|追我那|后视镜",
    "front_gap": r"前车|前头|前面那|我追的",
    "fuel_status": r"燃油|油量|汽油|油箱|剩油",
    "ers_status": r"电池|电量|电能|电力|ERS",
    "race_control_status": r"黄旗|旗号|赛道管制|比赛管制|赛道管控|赛会管制",
}
QUESTION = re.compile(r"[？?]|多少|多[近远重]|几[秒圈成]|够不够|还能|有没|是否|如何|什么|咋样|啥|怎么样|吗|查|报一下|报下|看看|告诉|想知道")
ATTACK = re.compile(r"进攻|攻击|出手|动手|超车|跟车|跟着|跟住|发起攻")
DEFER = re.compile(r"(先|暂|缓|等|保持|不急|别急|推迟|延后|不着急|按兵|再等等|不要|别|不打算)")
COMMIT = re.compile(r"现在|决定|还是|改主意|开始|准备|我要|这就|马上|立刻|动手了")
CONDITIONAL = re.compile(r"如果|假如|假设|要是|要不要|会不会|能不能")
RETURN = re.compile(r"(继续|接着|接回|接上).{0,8}(说|讲|聊|听|刚才|前面|那句|上句|上个话题)|说完|讲完|没说完|没听完|说一半|刚才.*(说|讲)")
BARE_RETURN = re.compile(r"(请|那就|好，?)?(继续|接着)[。！？，,.!?]*$")
FEELING = re.compile(r"我(感觉|觉得)|手感|车感|打滑|发滑|抓地|有点滑|不太稳")


def resumed_answer(interrupted):
    query = interrupted["code"][6:].lower()
    side = "unknown"
    if query == "front_wing_damage_status":
        for name, label in (("front_right", "右前翼"), ("front_left", "左前翼")):
            if label in interrupted["text"]:
                side = name
    return dict(act="resume", query=query, anchor=interrupted, wing_side=side, topic="other")


def ground(text, proposed, interrupted):
    """Resolve explicit contradictions; implicit references remain with the interpreter."""
    result = dict(proposed)
    clauses = [s for s in re.split(r"[，,。；;]", text) if s.strip()]
    questions = [s for s in clauses if QUESTION.search(s)]
    resume_requested = RETURN.search(text) or BARE_RETURN.fullmatch(text.strip())
    if interrupted and (result["act"] == "resume" or resume_requested):
        target = interrupted["code"][6:].lower()
        named = {k for k, pat in SUBJECTS.items() if re.search(pat, text, re.I)}
        # A safety interjection may be named while returning to another subject.
        new_tactic = ATTACK.search(text) or "防守" in text
        if target in named or not (named - {"race_control_status"}) and not new_tactic:
            return resumed_answer(interrupted)
    # Explicit nouns only constrain a query within its read domain. Detailed
    # existing capabilities (e.g. opponent DRS or fuel outlook) remain eligible.
    if questions:
        focus = questions[-1]
        query = result["query"]
        simple = {"none", "open_fallback", "current_strategy", "overall_situation", "damage_status",
                  "floor_damage_status", "tyre_status", *SUBJECTS}
        named = [k for k, pat in SUBJECTS.items() if re.search(pat, focus, re.I)]
        if not named:
            named = [k for k, pat in SUBJECTS.items() if re.search(pat, text, re.I)]
        detail = bool(re.search(r"为什么|为何|原因|怎么修|要不要进站|DRS|预测|预计|怎么办|怎么防", text, re.I))
        if len(named) == 1 and (query in simple or not detail or result["act"] != "ask"):
            result["query"] = named[0]
        if len(named) == 1 and not any(ATTACK.search(s) and DEFER.search(s) for s in clauses):
            result["act"] = "ask"
    if result["query"] == "front_wing_damage_status":
        if "右" in text and "左" not in text:
            result["wing_side"] = "front_right"
        elif "左" in text and "右" not in text:
            result["wing_side"] = "front_left"
    # Keep compound utterances compositional: only an assertive action clause
    # establishes a stance; a hypothetical or interrogative cannot do so.
    for clause in clauses:
        if not ATTACK.search(clause) or QUESTION.search(clause) or CONDITIONAL.search(clause):
            continue
        if DEFER.search(clause):
            result.update(act="hold", topic="attack")
        elif COMMIT.search(clause):
            result.update(act="commit", topic="attack")
        if result["topic"] == "attack" and result["act"] in {"hold","commit"} and not questions:
            result["query"] = "none"
    if not questions and FEELING.search(text) and not ATTACK.search(text) and not CONDITIONAL.search(text):
        result.update(act="report", query="none")
    if CONDITIONAL.search(text) and result["act"] in {"commit","decline","hold"}:
        result["act"] = "conditional"
    return result

def explicit_advice_choice(text, topic, choice):
    """A model label alone cannot write adoption evidence. Require a decisive clause."""
    clauses = [c.strip() for c in re.split(r"[，,。；;]", text) if c.strip()]
    if not clauses or CONDITIONAL.search(text) or any(QUESTION.search(c) for c in clauses):
        return False
    clause = clauses[-1]
    action = r"进站|换胎|进维修区|进坑|这圈(就)?进|进去了|进去" if topic == "pit" else r"收油|省油|节油"
    negative = re.search(r"不|别|放弃", clause)
    if choice == "defer":
        return bool(re.search(r"先|再|下圈|下一圈|等|暂缓|缓一", clause))
    if not re.search(action, clause):
        return False
    if choice == "decline":
        return bool(negative)
    return not negative and bool(re.search(r"我(会|要|决定)|同意|这圈|现在|马上|这就|就进|按你说", clause))
