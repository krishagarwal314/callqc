from callqc.judges import CRITERIA, make_panel, panel_score, unsupported_figures
from callqc.personas import load_all
from callqc.simulator import simulate
from callqc.vaani_adapter import Variant

PANEL = make_panel()
PRICE = next(p for p in load_all() if p.id == "price_sensitive")


def score(variant, i=0, persona=PRICE):
    return panel_score(simulate(Variant.load(f"prompts/{variant}"), persona, i), PANEL)


def test_structured_output_has_all_criteria_with_quotes():
    qc = score("v1_baseline")
    assert set(qc["scores"]) == set(CRITERIA)
    for c in CRITERIA:
        assert qc["scores"][c]["score"] in (0, 1, 2)
        assert len(qc["scores"][c]["votes"]) == 3
        assert qc["scores"][c]["justification"]


def test_invented_rate_is_automatic_fail():
    qc = score("v0_sanity_bad")
    assert qc["scores"]["hallucinated_figures"]["score"] == 0
    assert qc["qc_fail"] and "hallucinated_figures" in qc["critical_zero"]


def test_tool_sourced_figures_pass():
    call = simulate(Variant.load("prompts/v1_baseline"), PRICE, 0)
    assert any("percent" in t["text"] for t in call["turns"])
    assert unsupported_figures(call) == []


def test_indicative_caveat_scored():
    assert score("v1_baseline")["scores"]["mandatory_disclosures"]["score"] == 1
    assert score("v3_indicative")["scores"]["mandatory_disclosures"]["score"] == 2


def test_sanity_bad_prompt_scores_clearly_worse():
    personas = load_all()
    good = [panel_score(simulate(Variant.load("prompts/v1_baseline"), p, i), PANEL)["total"] for p in personas for i in range(3)]
    bad = [panel_score(simulate(Variant.load("prompts/v0_sanity_bad"), p, i), PANEL)["total"] for p in personas for i in range(3)]
    assert sum(good) / len(good) - sum(bad) / len(bad) > 3


def test_disagreement_flagged():
    qc = score("v1_baseline")
    flagged = qc["needs_human_review"]
    assert all(len(set(qc["scores"][c]["votes"])) > 1 for c in flagged)
