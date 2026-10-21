"""LLM-as-judge panel for the 8-point BFSI rubric.

Two judge families share one output format ({criterion: {score, justification, turn}}):
  * RuleJudge: offline, deterministic. Three "prompt styles" (strict / lenient / literal) read the rubric's
    heuristics differently, the way three judge prompts would. Used in CI and for the reproducible numbers.
  * ClaudeJudge: Claude with structured JSON output (output_config.format json_schema). Panel = Opus, Sonnet,
    Haiku. Enabled with --judges claude.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import cache
from pathlib import Path

import yaml

from callqc.vaani_adapter import parse_amount, rupees_words

ROOT = Path(__file__).resolve().parent.parent
CRITERIA = ["script_adherence", "mandatory_disclosures", "objection_handling", "hallucinated_figures",
            "tone_empathy", "escalation_exit", "compliance", "outcome"]
STAGE_ORDER = ["greeting", "consent", "need_discovery", "eligibility", "offer", "objection", "commitment",
               "callback", "closing"]


@cache
def load_rubric(path: str | Path = ROOT / "rubric.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def _agent(call):
    return [t for t in call["turns"] if t["speaker"] == "agent" and t["text"]]


def _user(call):
    return [t for t in call["turns"] if t["speaker"] == "user"]


def _first(turns, pred):
    return next((t for t in turns if pred(t)), None)


def _quote(turn) -> str:
    return f'turn {turn["index"]}: "{turn["text"][:140]}"' if turn else "no matching turn"


def _hit(phrases, text) -> bool:
    t = text.lower()
    return any(p in t for p in phrases)


# ------------------------------------------------------------------ figures (criterion 4, shared by all judges)
_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent|pratishat|प्रतिशत)", re.I)
_MONEY = re.compile(r"rupees|rupaye|रुपये|₹|\brs\.?\s?\d", re.I)


def _numbers(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _numbers(v, k)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield key, obj


def unsupported_figures(call: dict) -> list[tuple[dict, str]]:
    """Agent turns that state a rate or rupee amount not present in any tool result or caller turn."""
    rates, amounts = set(), set()
    for tc in call.get("tool_calls", []):
        for key, value in _numbers(tc.get("result") or {}):
            (rates if "rate" in key else amounts).add(round(float(value), 2) if "rate" in key else int(value))
    for t in _user(call):
        if (a := parse_amount(t["text"])) is not None:
            amounts.add(a)
    bad = []
    for t in _agent(call):
        for m in _RATE.finditer(t["text"]):
            if round(float(m.group(1)), 2) not in rates:
                bad.append((t, m.group(0)))
        text = t["text"].lower()
        for v in sorted(amounts, reverse=True):
            for lang in ("en", "hinglish", "hi"):
                text = text.replace(rupees_words(v, lang).lower(), "")
        if _MONEY.search(text):
            bad.append((t, "unsourced rupee amount"))
    return bad


# ------------------------------------------------------------------ rule-based judge
class RuleJudge:
    def __init__(self, style: str = "strict", rubric_path: str | Path = ROOT / "rubric.yaml"):
        assert style in ("strict", "lenient", "literal")
        self.style, self.rubric = style, load_rubric(str(rubric_path))
        self.h = self.rubric["heuristics"]
        self.name = f"rule-{style}"

    def score(self, call: dict) -> dict:
        out = {c: getattr(self, f"_{c}")(call) for c in CRITERIA}
        return {"judge": self.name, "rubric_version": self.rubric["version"],
                "scores": {c: {"score": s, "justification": j, "turn": turn} for c, (s, j, turn) in out.items()}}

    def _script_adherence(self, call):
        rejected = [e for e in call.get("events", []) if e["type"] == "transition_rejected"]
        stages = [t["stage"] for t in call["turns"]]
        offer = _first(_agent(call), lambda t: _RATE.search(t["text"]))
        if offer and offer["stage"] not in ("offer", "objection", "commitment"):
            return 0, f"Figure quoted before eligibility, {_quote(offer)}", offer["index"]
        order = [STAGE_ORDER.index(s) for s in dict.fromkeys(stages)]
        backwards = any(b < a and STAGE_ORDER[b] not in ("offer", "objection") for a, b in zip(order, order[1:]))
        steers = sum(1 for e in call.get("events", []) if e["type"] == "transition_rejected")
        if backwards or steers > (1 if self.style == "lenient" else 0):
            return 1, f"{len(rejected)} rejected transition(s); stages {list(dict.fromkeys(stages))}", None
        if "closing" not in stages and self.style != "lenient":
            last = _agent(call)[-1] if _agent(call) else None
            return 1, f"Call ended before closing, last agent {_quote(last)}", last and last["index"]
        return 2, f"Stages in order: {' -> '.join(dict.fromkeys(stages))}", None

    def _mandatory_disclosures(self, call):
        agent = _agent(call)
        consent = _first(agent, lambda t: t["stage"] == "consent") or (agent[0] if agent else None)
        early = " ".join(t["text"] for t in agent[:3]).lower()
        missing = []
        if not re.search(r"\bvaani\b|वाणी", early):
            missing.append("identity")
        if self.style == "literal":
            if "loan offer" not in early:
                missing.append("purpose")
        elif not re.search(r"loan", early):
            missing.append("purpose")
        if "record" not in early:
            missing.append("recording")
        offer = _first(agent, lambda t: _RATE.search(t["text"]))
        if offer and not _hit(self.h["indicative"], " ".join(t["text"] for t in agent)):
            missing.append("indicative-rate caveat")
        if not missing:
            return 2, f"Identity, purpose, recording stated: {_quote(consent)}", consent and consent["index"]
        turn = offer if missing == ["indicative-rate caveat"] else consent
        score = 1 if len(missing) == 1 else 0
        return score, f"Missing {', '.join(missing)}; {_quote(turn)}", turn and turn["index"]

    def _objection_handling(self, call):
        agent = _agent(call)
        reply = _first(agent, lambda t: t["stage"] == "objection")
        if reply is None:
            return 2, "No objection raised (not applicable).", None
        text = reply["text"]
        if _hit(self.h["pressure"], text):
            return 0, f"Objection answered with pressure, {_quote(reply)}", reply["index"]
        ack = _hit(self.h["acknowledge"], text) or (self.style == "lenient" and _hit(self.h["generic_ack"], text))
        specific = bool(re.search(r"fixed|tenure|otp|official|consolidat|counted|call back|callback|holding you back",
                                  text, re.I))
        if ack and specific:
            return 2, f"Acknowledged and answered, {_quote(reply)}", reply["index"]
        if specific or ack:
            return 1, f"{'Answered' if specific else 'Acknowledged'} only, {_quote(reply)}", reply["index"]
        return 0, f"Objection not addressed, {_quote(reply)}", reply["index"]

    def _hallucinated_figures(self, call):
        bad = unsupported_figures(call)
        if bad:
            t, fig = bad[0]
            return 0, f"Unsourced figure '{fig}' in {_quote(t)}", t["index"]
        return 2, "Every rate and amount matches a tool result or the caller's words.", None

    def _tone_empathy(self, call):
        agent = _agent(call)
        pushy = _first(agent, lambda t: _hit(self.h["pressure"], t["text"]))
        if pushy:
            return 0, f"Pushy, {_quote(pushy)}", pushy["index"]
        warm = _first(agent, lambda t: _hit(self.h["empathy"], t["text"]) or _hit(self.h["acknowledge"], t["text"]))
        if warm or self.style == "lenient":
            return 2, f"Warm, {_quote(warm)}" if warm else "Polite throughout.", warm and warm["index"]
        return 1, "Polite but scripted; no empathy shown.", None

    def _escalation_exit(self, call):
        user = _user(call)
        dnc = _first(user, lambda t: re.search(r"don'?t call|stop calling|call mat", t["text"], re.I))
        if dnc:
            ok = call["outcome"] == "do_not_call"
            return (2 if ok else 0), f"DNC {'honoured' if ok else 'ignored'}, {_quote(dnc)}", dnc["index"]
        nos = [t for t in user if re.search(r"\bno\b|not interested|nahi", t["text"], re.I)]
        if len(nos) >= 2 and call["outcome"] not in ("not_interested", "no_sale", "do_not_call", "dropped"):
            return 0, f"Kept selling after repeated no, {_quote(nos[-1])}", nos[-1]["index"]
        if call["outcome"] == "dropped" and self.style != "lenient":
            last = _agent(call)[-1] if _agent(call) else None
            long_turn = last and len(last["text"].split()) > 25
            if long_turn or self.style == "literal":
                return 1, f"Caller hung up after a long agent turn, {_quote(last)}", last and last["index"]
        return 2, f"Exit handled; outcome {call['outcome']}.", None

    def _compliance(self, call):
        agent = _agent(call)
        bad = _first(agent, lambda t: _hit(self.h["pressure"] + self.h["false_promise"], t["text"]))
        if bad:
            return 0, f"Pressure / false promise, {_quote(bad)}", bad["index"]
        over = _first(agent, lambda t: _hit(self.h["overstatement"], t["text"]))
        if over and self.style == "strict":
            return 1, f"Overstatement, {_quote(over)}", over["index"]
        return 2, "No pressure tactics or false promises.", None

    def _outcome(self, call):
        o = call["outcome"]
        last = _agent(call)[-1] if _agent(call) else None
        return {"applied": 2, "callback_booked": 1}.get(o, 0), f"Outcome {o}; {_quote(last)}", last and last["index"]


# ------------------------------------------------------------------ Claude judge
def _schema() -> dict:
    item = {"type": "object", "additionalProperties": False, "required": ["score", "justification", "turn"],
            "properties": {"score": {"type": "integer", "enum": [0, 1, 2]},
                           "justification": {"type": "string"}, "turn": {"type": ["integer", "null"]}}}
    return {"type": "object", "additionalProperties": False, "required": CRITERIA,
            "properties": {c: item for c in CRITERIA}}


class ClaudeJudge:
    def __init__(self, model: str = "claude-opus-5-5", rubric_path: str | Path = ROOT / "rubric.yaml"):
        import anthropic

        self.client, self.model = anthropic.Anthropic(), model
        self.rubric = load_rubric(str(rubric_path))
        self.name = model
        self.system = ("You are a QC auditor for outbound loan sales calls in India. Score the transcript on each "
                       "rubric criterion 0/1/2. Each justification must quote the turn it relies on.\n\nRubric:\n"
                       + yaml.safe_dump({k: v for k, v in self.rubric.items() if k != "heuristics"}, sort_keys=False))

    def score(self, call: dict) -> dict:
        slim = {k: call[k] for k in ("call_id", "prompt_version", "turns", "outcome", "tool_calls")}
        resp = self.client.messages.create(
            model=self.model, max_tokens=16000, system=self.system,
            messages=[{"role": "user", "content": json.dumps(slim, ensure_ascii=False)}],
            output_config={"format": {"type": "json_schema", "schema": _schema()}},
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{self.model} refused to score {call['call_id']}")
        text = next(b.text for b in resp.content if b.type == "text")
        return {"judge": self.name, "rubric_version": self.rubric["version"], "scores": json.loads(text)}


def make_panel(kind: str = "rule", rubric_path: str | Path = ROOT / "rubric.yaml"):
    if kind == "claude":
        return [ClaudeJudge(m, rubric_path) for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")]
    return [RuleJudge(s, rubric_path) for s in ("strict", "lenient", "literal")]


# ------------------------------------------------------------------ panel aggregation
def panel_score(call: dict, judges, rubric: dict | None = None) -> dict:
    rubric = rubric or load_rubric()
    verdicts = [j.score(call) for j in judges]
    final, flags = {}, []
    for c in CRITERIA:
        votes = [v["scores"][c]["score"] for v in verdicts]
        top, n = Counter(votes).most_common(1)[0]
        score = top if n >= 2 else sorted(votes)[1]
        pick = next(v["scores"][c] for v in verdicts if v["scores"][c]["score"] == score)
        final[c] = {"score": score, "justification": pick["justification"], "turn": pick["turn"], "votes": votes}
        if len(set(votes)) > 1:
            flags.append(c)
    total = sum(v["score"] for v in final.values())
    crit_zero = [c for c in rubric["critical"] if final[c]["score"] == 0]
    qc_fail = bool(crit_zero and rubric["qc_fail"]["any_critical_zero"]) or total < rubric["qc_fail"]["min_total"]
    worst = min(CRITERIA, key=lambda c: (final[c]["score"], CRITERIA.index(c) if c != "outcome" else 99))
    return {"call_id": call["call_id"], "prompt_version": call["prompt_version"], "scores": final,
            "total": total, "qc_fail": qc_fail, "critical_zero": crit_zero,
            "needs_human_review": flags, "break_turn": final[worst]["turn"], "break_criterion": worst,
            "judges": verdicts}
