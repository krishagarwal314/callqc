from callqc.personas import load_all
from callqc.simulator import simulate
from callqc.vaani_adapter import Variant

BASE = Variant.load("prompts/v1_baseline")


def test_eight_personas():
    assert len(load_all()) == 8


def test_same_seed_same_call():
    p = load_all()[0]
    a, b = simulate(BASE, p, 3), simulate(BASE, p, 3)
    assert [t["text"] for t in a["turns"]] == [t["text"] for t in b["turns"]]


def test_different_seed_can_differ():
    p = next(x for x in load_all() if x.id == "price_sensitive")
    outcomes = {simulate(BASE, p, i)["outcome"] for i in range(30)}
    assert len(outcomes) > 1


def test_polite_persona_rarely_converts():
    p = next(x for x in load_all() if x.id == "polite_uninterested")
    best = Variant.load("prompts/v5_combined")
    conv = sum(simulate(best, p, i)["outcome"] == "applied" for i in range(40))
    assert conv <= 6  # politeness is not intent


def test_distrustful_hangs_up_without_identity():
    p = next(x for x in load_all() if x.id == "distrustful")
    call = simulate(Variant.load("prompts/v0_sanity_bad"), p, 0)
    assert call["outcome"] == "dropped" and call["turns"][-1]["stage"] == "consent"


def test_turn_limit():
    p = load_all()[0]
    call = simulate(BASE, p, 0, max_turns=2)
    assert sum(t["speaker"] == "user" for t in call["turns"]) <= 2
