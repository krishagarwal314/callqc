"""What a caller hears in the agent's words. Personas use these to decide; judges use the rubric phrase lists."""
from __future__ import annotations

import re

SIGNALS: dict[str, re.Pattern] = {k: re.compile(v, re.I) for k, v in {
    "identity": r"\bvaani\b|वाणी",
    "lender": r"sahayak finance",
    "purpose": r"loan offer|personal loan|loan ke|लोन",
    "recording": r"record",
    "indicative": r"indicative|subject to final approval|final terms depend",
    "acknowledged": r"fair concern|valid (concern|point)|completely understand|you're right to|jaayaz|sahi sawaal",
    "emi_reduction": r"tenure brings the emi down|emi kam|lower (your )?emi|emi down",
    "fixed_rate": r"\bfixed\b",
    "no_otp": r"\botp\b",
    "official_app": r"official",
    "consolidation": r"consolidat",
    "pressure": r"expires today|last chance|regret|only today|aaj hi|everyone is taking|hurry",
    "false_promise": r"guarantee|100% approval|no documents needed",
    "never": r"(?!x)x",
}.items()}


def present(text: str) -> set[str]:
    return {name for name, rx in SIGNALS.items() if rx.search(text)}


def words(text: str) -> int:
    return len(text.split())
