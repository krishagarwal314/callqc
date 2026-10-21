"""Bridge to the Vaani agent. CallQC imports Vaani's CallSession; it never re-implements the agent.

Vaani is found via $VAANI_PATH (default: ../vaani next to this repo). A prompt variant is a folder under
prompts/ with a variant.yaml. Each variant has two parts:
  * `system_addendum`: text appended to Vaani's system prompt. With a real LLM backend this is the variant.
  * `policy`: switches applied by VariantLLM on top of Vaani's offline MockLLM, so the full A/B pipeline
    runs deterministically without API keys. Each switch is the offline stand-in for the addendum's effect.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VAANI_PATH = Path(os.environ.get("VAANI_PATH", ROOT.parent / "vaani")).resolve()
if str(VAANI_PATH) not in sys.path:
    sys.path.insert(0, str(VAANI_PATH))

from agent.engine import CallSession  # noqa: E402
from agent.llm.mock import MockLLM  # noqa: E402
from agent.numbers import parse_amount, rupees_words  # noqa: E402,F401
from agent.schema import Intent, LLMRequest, LLMTurnOutput  # noqa: E402
from agent.stages import Stage  # noqa: E402
from agent.timeparse import IST  # noqa: E402
from tools import crm, scheduler  # noqa: E402

SIM_NOW = datetime(2026, 10, 21, 11, 0, tzinfo=IST)


@dataclass
class Variant:
    id: str
    hypothesis: str
    system_addendum: str = ""
    policy: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Variant":
        path = Path(path)
        data = yaml.safe_load((path / "variant.yaml").read_text())
        return cls(id=data.get("id", path.name), hypothesis=data.get("hypothesis", ""),
                   system_addendum=data.get("system_addendum", ""), policy=data.get("policy") or {})


_ACK = {
    "en": "That's a completely fair concern, and you're right to ask.",
    "hinglish": "Bilkul jaayaz sawaal hai, aapka poochna sahi hai.",
    "hi": "बिल्कुल जायज़ सवाल है।",
}
_INDICATIVE = {
    "en": "This rate is indicative and subject to final approval after verification.",
    "hinglish": "Yeh rate indicative hai, final approval verification ke baad hoga.",
    "hi": "यह रेट indicative है, final approval verification के बाद होगा।",
}
_CONCISE_CONSENT = {
    "en": "Hi {name}, Vaani from Sahayak Finance about your pre-approved loan offer. This call is recorded. Two minutes?",
    "hinglish": "{name} ji, Vaani, Sahayak Finance se, aapke pre-approved loan offer ke liye. Call record ho rahi hai. Do minute?",
}
_BAD_CONSENT = "Hi {name}! Great news, you have been specially selected for an exclusive loan offer today!"
_BAD_OFFER_TAIL = " That's only 9.99 percent, the best in the market, and you'll save up to fifty thousand rupees. This offer expires today!"
_BAD_OBJECTION = "Everyone is taking this offer, you'll regret it if you miss it. Approval is guaranteed. Shall I go ahead?"


class VariantLLM:
    """Wraps any Vaani LLM backend. Real backends get the addendum; the mock gets the offline policy."""

    def __init__(self, variant: Variant, base=None):
        self.variant, self.base = variant, base or MockLLM()
        self.name = f"{getattr(self.base, 'name', 'llm')}+{variant.id}"

    def generate(self, req: LLMRequest) -> LLMTurnOutput:
        if self.variant.system_addendum:
            req = req.model_copy(update={"system_prompt": req.system_prompt + "\n\n## Variant\n" + self.variant.system_addendum})
        out = self.base.generate(req)
        if not isinstance(self.base, MockLLM) or out.tool_calls:
            return out
        return out.model_copy(update={"reply_text": self._apply_policy(req, out)})

    def _apply_policy(self, req: LLMRequest, out: LLMTurnOutput) -> str:
        p, text, lang = self.variant.policy, out.reply_text, req.lang if req.lang in _ACK else "en"
        first = (req.customer.get("name") or "").split(" ")[0]
        stage, entering = req.stage, req.event != "user"
        if stage == Stage.CONSENT and entering:
            if p.get("bad"):
                return _BAD_CONSENT.format(name=first)
            if p.get("concise") and lang in _CONCISE_CONSENT:
                return _CONCISE_CONSENT[lang].format(name=first)
        if stage == Stage.OFFER and entering and text:
            if p.get("bad"):
                return text.replace("Shall we go ahead?", "").strip() + _BAD_OFFER_TAIL
            if p.get("indicative_disclosure"):
                return f"{text} {_INDICATIVE[lang]}"
        if stage == Stage.OBJECTION and text:
            if p.get("bad"):
                return _BAD_OBJECTION
            if p.get("acknowledge_objection") and req.last_intent and req.last_intent.value.startswith("objection_"):
                return f"{_ACK[lang]} {text.split('. ', 1)[-1] if '. ' in text else text}"
        return text


def new_session(phone: str, variant: Variant, call_id: str, base_llm=None) -> CallSession:
    ticks = count(0, 700)
    s = CallSession(phone, VariantLLM(variant, base_llm), call_id=call_id,
                    clock=lambda: next(ticks), now_fn=lambda: SIM_NOW)
    s.transcript.prompt_version = variant.id
    return s


def reset_vaani_stores() -> None:
    """Vaani's mock CRM is a module-level dict; DNC writes must not leak between simulated calls."""
    for record in crm.CUSTOMERS.values():
        record["dnc"] = False
    crm.CUSTOMERS["+919800000004"]["dnc"] = True
    scheduler.CALLBACKS.clear()


def transcript_dict(session: CallSession) -> dict:
    return session.transcript.model_dump(mode="json")
