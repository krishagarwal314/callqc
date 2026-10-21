"""Runs one full text conversation between a persona caller and Vaani's CallSession."""
from __future__ import annotations

import hashlib

from callqc.personas import HANG_UP, Persona, PersonaCaller
from callqc.vaani_adapter import Variant, new_session, reset_vaani_stores, transcript_dict

MAX_TURNS = 24


def call_seed(persona_id: str, index: int, base_seed: int = 0) -> int:
    """Same seed for the same (persona, index) across variants: common random numbers make A/B paired."""
    return int(hashlib.sha256(f"{base_seed}:{persona_id}:{index}".encode()).hexdigest()[:8], 16)


def simulate(variant: Variant, persona: Persona, index: int, base_seed: int = 0,
             max_turns: int = MAX_TURNS, caller=None, base_llm=None) -> dict:
    seed = call_seed(persona.id, index, base_seed)
    reset_vaani_stores()
    call_id = f"{variant.id}-{persona.id}-{index:03d}"
    caller = caller or PersonaCaller(persona, seed)
    session = new_session(persona.phone, variant, call_id, base_llm)

    reply = session.start()
    user_turns = 0
    while not session.ended and user_turns < max_turns:
        if (heard := caller.wants_to_interrupt()) is not None and len(reply.text) > heard:
            session.handle_barge_in(heard)
            reply_text = session.transcript.turns[-1].text
        else:
            reply_text = reply.text
        line = caller.reply(reply_text, reply.stage.value, bool(session.pending))
        if line == HANG_UP:
            session.hang_up()
            break
        reply = session.handle_user(line)
        user_turns += 1
    if not session.ended:
        session.hang_up()

    call = transcript_dict(session)
    call["sim"] = {"persona": persona.id, "variant": variant.id, "seed": seed, "index": index,
                   "turn_limit_hit": user_turns >= max_turns}
    return call
