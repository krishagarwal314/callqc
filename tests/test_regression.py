import json

import yaml

from callqc.regression import load_cases, run_suite, save_from_call
from callqc.vaani_adapter import Variant

PROD = yaml.safe_load(open("prompts/production.yaml"))["production"]


def test_production_passes_suite():
    res = run_suite(Variant.load(f"prompts/{PROD}"), verbose=False)
    assert res["n_cases"] >= 8 and res["failed"] == []


def test_bad_prompt_fails_suite():
    res = run_suite(Variant.load("prompts/v0_sanity_bad"), verbose=False)
    assert len(res["failed"]) >= 4


def test_known_issue_does_not_fail_ci():
    res = run_suite(Variant.load(f"prompts/{PROD}"), verbose=False)
    assert "consent-barge-in-disclosure" in res["known_issues_failing"]


def test_save_failed_call_as_case(tmp_path):
    from callqc.judges import make_panel, panel_score
    from callqc.personas import load_all
    from callqc.simulator import simulate

    call = simulate(Variant.load("prompts/v0_sanity_bad"), load_all()[-1], 0)
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"call": call, "qc": panel_score(call, make_panel())}))
    out = save_from_call(f, ["must_not_invent_figures"], "t1", "hallucinated_figures", directory=tmp_path / "cases")
    case = yaml.safe_load(out.read_text())
    assert case["prefix"] and case["expect"] == ["must_not_invent_figures"]
    assert load_cases(tmp_path / "cases")[0]["id"] == "t1"
