"""Synthetic callers. A persona is a YAML file; PersonaCaller turns it into turn-by-turn replies.

The offline caller is rule-based with seeded randomness, so a (persona, seed) pair always produces the same
call for the same agent behaviour. Hidden `convert_if` conditions are checked against what the agent has
actually said, so politeness alone never converts anyone. An LLM-backed caller (ClaudeCaller) uses the same
YAML as its system prompt for open-ended runs.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import yaml

from callqc.signals import present, words

PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"

HANG_UP = "<hang_up>"


@dataclass
class Persona:
    id: str
    data: dict

    @property
    def phone(self) -> str:
        return self.data["phone"]

    @property
    def hidden(self) -> dict:
        return self.data.get("hidden", {})

    @property
    def behaviour(self) -> dict:
        return self.data.get("behaviour", {})

    @classmethod
    def load(cls, path: str | Path) -> "Persona":
        data = yaml.safe_load(Path(path).read_text())
        return cls(data["id"], data)


def load_all(directory: Path = PERSONA_DIR) -> list[Persona]:
    return [Persona.load(p) for p in sorted(directory.glob("*.yaml"))]


class PersonaCaller:
    def __init__(self, persona: Persona, seed: int):
        self.p, self.rng = persona, random.Random(seed)
        self.heard: set[str] = set()       # signals heard so far in the call
        self.objected = False
        self.decided = False

    def wants_to_interrupt(self) -> int | None:
        """Chars of the agent turn heard before barging in, or None."""
        if self.rng.random() < self.p.behaviour.get("interrupt_prob", 0.0):
            return self.rng.randint(15, 45)
        return None

    def reply(self, agent_text: str, stage: str, pending_readback: bool) -> str:
        a, h, b = self.p.data["answers"], self.p.hidden, self.p.behaviour
        self.heard |= present(agent_text)
        if self.heard & set(h.get("leave_on", [])) and self.rng.random() < h.get("p_leave_on_trigger", 0):
            return HANG_UP
        if words(agent_text) > b.get("patience_words", 999) and self.rng.random() < b.get("p_hangup_long_turn", 0):
            return HANG_UP
        if pending_readback:
            return "haan ji, sahi hai" if self.p.data["language_mix"] == "hinglish" else "yes, correct"

        t = agent_text.lower()
        if stage == "greeting":
            return a["greeting"]
        if stage == "consent":
            need = set(h.get("require_at_consent", []))
            if need and not need <= self.heard:
                return HANG_UP
            return a["consent"]
        if stage == "need_discovery":
            return a["need"]
        if stage == "eligibility":
            if "salaried" in t or "self-employed" in t or "naukri" in t:
                return a["employment"]
            if "income" in t or "aamdani" in t:
                return a["income"]
            if "emi" in t:
                return a["existing_emi"]
            return a["need"]
        if stage == "offer":
            if self.p.data.get("objection") and not self.objected:
                self.objected = True
                return self.p.data["objection"]
            return self._decide()
        if stage == "objection":
            return self._decide()
        if stage == "commitment":
            return a["commit"]
        if stage == "callback":
            return a["callback_time"]
        return HANG_UP

    def _decide(self) -> str:
        if self.decided:  # one decision per call; repeated pitches after a no do not flip it
            return self.p.data["answers"]["decline"]
        self.decided = True
        h = self.p.hidden
        met = set(h.get("convert_if", [])) <= self.heard
        p = h["p_convert_if_met"] if met else h["p_convert_otherwise"]
        if self.rng.random() < p:
            return self.p.data["answers"]["accept"]
        return self.p.data["answers"]["decline"]


class ClaudeCaller:
    """Open-ended persona LLM. Not used by the reproducible offline A/B runs; see README 'LLM mode'."""

    def __init__(self, persona: Persona, seed: int, model: str = "claude-haiku-5-5"):
        import anthropic

        self.p, self.model, self.client = persona, model, anthropic.Anthropic()
        self.messages: list[dict] = []
        self.system = (
            "You are role-playing a customer receiving an outbound loan sales call. Stay in character.\n"
            + yaml.safe_dump({k: v for k, v in persona.data.items() if k != "answers"})
            + f"\nOnly agree to apply if your hidden convert_if conditions are clearly met. "
              f"Reply with one short spoken line, or exactly {HANG_UP} to end the call. Seed: {seed}."
        )

    def wants_to_interrupt(self) -> int | None:
        return None

    def reply(self, agent_text: str, stage: str, pending_readback: bool) -> str:
        self.messages.append({"role": "user", "content": agent_text})
        resp = self.client.messages.create(model=self.model, max_tokens=256, system=self.system,
                                           messages=self.messages)
        text = next((b.text for b in resp.content if b.type == "text"), HANG_UP).strip()
        self.messages.append({"role": "assistant", "content": text})
        return text
