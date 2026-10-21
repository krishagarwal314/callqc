#!/usr/bin/env python3
"""Judge vs human agreement: % agreement and Cohen's kappa per criterion and overall, each single judge vs the
3-judge panel, plus a confusion matrix. Run once per rubric version to report before/after revisions.

    python eval/judge_agreement.py                                # rubric.yaml
    python eval/judge_agreement.py --rubrics rubric_v0.yaml rubric.yaml

Human labels come from apps/label_app.py (data/labels/human.jsonl). Until there are labels, the script
reports inter-judge agreement instead (each judge vs the other two), and says so in its output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import cohen_kappa_score, confusion_matrix

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callqc.judges import CRITERIA, make_panel, panel_score  # noqa: E402
from callqc.labels import load_calls, load_human_labels  # noqa: E402

LEVELS = [0, 1, 2]


def kappa(a, b) -> float:
    if len(set(a) | set(b)) < 2:
        return 1.0 if list(a) == list(b) else 0.0  # kappa is undefined when only one level is ever used
    return float(cohen_kappa_score(a, b, labels=LEVELS))


def agreement(a, b) -> dict:
    a, b = np.asarray(a), np.asarray(b)
    return {"n": int(len(a)), "pct": round(float((a == b).mean()) * 100, 1), "kappa": round(kappa(a, b), 3)}


def evaluate(calls: dict, reference: dict[str, dict[str, int]], rubric: Path, mode: str) -> dict:
    judges = make_panel("rule", rubric)
    names = [j.name for j in judges] + ["panel"]
    preds = {n: {c: [] for c in CRITERIA} for n in names}
    refs = {c: [] for c in CRITERIA}
    for cid, call in calls.items():
        qc = panel_score(call, judges)
        for c in CRITERIA:
            if mode == "human":
                refs[c].append(reference[cid][c])
            for v in qc["judges"]:
                preds[v["judge"]][c].append(v["scores"][c]["score"])
            preds["panel"][c].append(qc["scores"][c]["score"])

    out = {"rubric": rubric.name, "mode": mode, "n_calls": len(calls), "judges": {}}
    # Without human labels the panel would be compared with its own majority (always 100%), so it is skipped.
    scored = names if mode == "human" else names[:-1]
    for n in scored:
        per = {}
        for c in CRITERIA:
            ref = refs[c] if mode == "human" else _others_majority(preds, n, c, names)
            per[c] = agreement(preds[n][c], ref)
        pooled_p = sum((preds[n][c] for c in CRITERIA), [])
        pooled_r = sum((refs[c] if mode == "human" else _others_majority(preds, n, c, names) for c in CRITERIA), [])
        out["judges"][n] = {"overall": agreement(pooled_p, pooled_r), "per_criterion": per}
        if n == scored[-1]:
            out["confusion_matrix"] = {"judge": n,
                                       "matrix": confusion_matrix(pooled_r, pooled_p, labels=LEVELS).tolist()}
    return out


def _others_majority(preds, name, c, names):
    """Inter-judge reference: majority of the other single judges (ties broken by the lower score)."""
    others = [n for n in names if n not in (name, "panel")]
    if name == "panel":
        others = [n for n in names if n != "panel"]
    cols = list(zip(*(preds[o][c] for o in others)))
    return [max(sorted(set(col)), key=col.count) for col in cols]


def print_result(r: dict) -> None:
    ref = "human labels" if r["mode"] == "human" else "other judges (no human labels yet)"
    print(f"\n=== {r['rubric']}: {r['n_calls']} calls, reference = {ref}")
    print(f"{'judge':<14}{'overall %':>10}{'kappa':>8}   " + " ".join(f"{c[:10]:>11}" for c in CRITERIA))
    for n, j in r["judges"].items():
        cells = " ".join(f"{j['per_criterion'][c]['pct']:>5.0f}/{j['per_criterion'][c]['kappa']:>5.2f}" for c in CRITERIA)
        print(f"{n:<14}{j['overall']['pct']:>10.1f}{j['overall']['kappa']:>8.3f}   {cells}")
    cm = r["confusion_matrix"]
    print(f"{cm['judge']} confusion matrix (rows = reference 0/1/2, cols = {cm['judge']} 0/1/2):")
    for row in cm["matrix"]:
        print("   ", row)


def main(argv=None) -> list[dict]:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rubrics", nargs="+", default=["rubric.yaml"])
    ap.add_argument("--calls", default=str(ROOT / "data/calls"))
    ap.add_argument("--labels", default=str(ROOT / "data/labels/human.jsonl"))
    ap.add_argument("--sample", type=int, default=240, help="calls to use in inter-judge mode")
    ap.add_argument("--out", default=str(ROOT / "results/judge_agreement.json"))
    args = ap.parse_args(argv)

    calls = load_calls(Path(args.calls))
    human = load_human_labels(Path(args.labels))
    if human:
        mode, subset = "human", {cid: calls[cid] for cid in human if cid in calls}
    else:
        mode = "inter_judge"
        ids = sorted(calls)[:: max(1, len(calls) // args.sample)][: args.sample]
        subset = {cid: calls[cid] for cid in ids}
    results = [evaluate(subset, human, ROOT / r, mode) for r in args.rubrics]
    for r in results:
        print_result(r)
    Path(args.out).write_text(json.dumps({"n_human_labelled": len(human), "results": results}, indent=1))
    return results


if __name__ == "__main__":
    main()
