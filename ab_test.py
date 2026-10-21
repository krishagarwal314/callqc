#!/usr/bin/env python3
"""A/B test prompt variants against the 8 personas.

    python ab_test.py --variants prompts/v1_baseline prompts/v2_ack_objection --calls-per-persona 25

The first variant is the control. For each variant: conversion rate, positive-outcome rate (applied or
callback), average rubric score per criterion, QC failure rate and average call length, each with a 95%
bootstrap CI. Each treatment is compared with the control (Fisher exact test on conversion, permutation test
on the rubric total) with Holm correction across treatments.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

from callqc.judges import CRITERIA, load_rubric, make_panel, panel_score
from callqc.personas import load_all
from callqc.simulator import simulate
from callqc.stats import bootstrap_ci, bootstrap_diff_ci, fisher_p, holm, permutation_p
from callqc.vaani_adapter import Variant

ROOT = Path(__file__).resolve().parent


def run_variant(variant: Variant, personas, n: int, seed: int, judges, save_dir: Path | None) -> list[dict]:
    rows = []
    for persona in personas:
        for i in range(n):
            call = simulate(variant, persona, i, base_seed=seed)
            qc = panel_score(call, judges)
            if save_dir:
                d = save_dir / variant.id
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{call['call_id']}.json").write_text(json.dumps({"call": call, "qc": qc}, ensure_ascii=False))
            agent_words = sum(len(t["text"].split()) for t in call["turns"] if t["speaker"] == "agent")
            rows.append({
                "call_id": call["call_id"], "variant": variant.id, "persona": persona.id, "outcome": call["outcome"],
                "converted": int(call["outcome"] == "applied"),
                "positive": int(call["outcome"] in ("applied", "callback_booked")),
                "total": qc["total"], "qc_fail": int(qc["qc_fail"]), "turns": len(call["turns"]),
                "agent_words": agent_words, "needs_review": int(bool(qc["needs_human_review"])),
                "break_turn": qc["break_turn"], "break_criterion": qc["break_criterion"],
                **{c: qc["scores"][c]["score"] for c in CRITERIA},
                "_call": call, "_qc": qc,
            })
    return rows


def summarise(rows: list[dict], seed: int) -> dict:
    def ci(key):
        m, lo, hi = bootstrap_ci([r[key] for r in rows], seed=seed)
        return {"mean": round(m, 4), "lo": round(lo, 4), "hi": round(hi, 4)}

    personas = sorted({r["persona"] for r in rows})
    return {
        "n_calls": len(rows),
        "conversion": ci("converted"), "positive_outcome": ci("positive"), "qc_fail_rate": ci("qc_fail"),
        "rubric_total": ci("total"), "call_turns": ci("turns"), "agent_words": ci("agent_words"),
        "criteria": {c: round(st.mean(r[c] for r in rows), 3) for c in CRITERIA},
        "needs_human_review_rate": round(st.mean(r["needs_review"] for r in rows), 3),
        "by_persona": {p: {"conversion": round(st.mean(r["converted"] for r in rows if r["persona"] == p), 3),
                           "positive": round(st.mean(r["positive"] for r in rows if r["persona"] == p), 3),
                           "rubric_total": round(st.mean(r["total"] for r in rows if r["persona"] == p), 2)}
                       for p in personas},
    }


def compare(control: list[dict], treatment: list[dict], seed: int) -> dict:
    out = {}
    for key, test in (("converted", "fisher"), ("positive", "fisher"), ("total", "permutation")):
        a, b = [r[key] for r in control], [r[key] for r in treatment]
        d, lo, hi = bootstrap_diff_ci(a, b, seed=seed)
        p = fisher_p(sum(a), len(a), sum(b), len(b)) if test == "fisher" else permutation_p(a, b, seed=seed)
        out[key] = {"diff": round(d, 4), "lo": round(lo, 4), "hi": round(hi, 4), "p": round(p, 5), "test": test}
    # per-persona conversion lift, for persona-specific hypotheses
    out["by_persona"] = {}
    for p in sorted({r["persona"] for r in control}):
        a = [r["converted"] for r in control if r["persona"] == p]
        b = [r["converted"] for r in treatment if r["persona"] == p]
        pa, pb = [r["positive"] for r in control if r["persona"] == p], [r["positive"] for r in treatment if r["persona"] == p]
        out["by_persona"][p] = {"conv_diff": round(st.mean(b) - st.mean(a), 3),
                                "conv_p": round(fisher_p(sum(a), len(a), sum(b), len(b)), 5),
                                "pos_diff": round(st.mean(pb) - st.mean(pa), 3),
                                "pos_p": round(fisher_p(sum(pa), len(pa), sum(pb), len(pb)), 5)}
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", nargs="+", required=True, help="prompt variant folders; first is the control")
    ap.add_argument("--calls-per-persona", type=int, default=25)
    ap.add_argument("--personas", nargs="*", help="persona ids to include (default: all 8)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--judges", choices=["rule", "claude"], default="rule")
    ap.add_argument("--out", default=str(ROOT / "results/ab/latest.json"))
    ap.add_argument("--save-calls", default=str(ROOT / "data/calls"), help="'' to skip writing transcripts")
    args = ap.parse_args(argv)

    personas = [p for p in load_all() if not args.personas or p.id in args.personas]
    judges = make_panel(args.judges)
    variants = [Variant.load(v) for v in args.variants]
    save_dir = Path(args.save_calls) if args.save_calls else None
    rows = {v.id: run_variant(v, personas, args.calls_per_persona, args.seed, judges, save_dir) for v in variants}

    control = variants[0].id
    comps = {v.id: compare(rows[control], rows[v.id], args.seed) for v in variants[1:]}
    for key in ("converted", "positive", "total"):
        adj = holm([comps[v][key]["p"] for v in comps])
        for v, p_adj in zip(comps, adj):
            comps[v][key]["p_holm"] = round(p_adj, 5)
            comps[v][key]["significant"] = bool(p_adj < 0.05)

    worst = {}
    for v in variants:
        ranked = sorted(rows[v.id], key=lambda r: (r["total"], r["call_id"]))[:5]
        worst[v.id] = [{"call": r["_call"], "qc": r["_qc"]} for r in ranked]

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"variants": [v.id for v in variants], "calls_per_persona": args.calls_per_persona,
                   "personas": [p.id for p in personas], "seed": args.seed, "judges": args.judges,
                   "rubric_version": load_rubric()["version"]},
        "hypotheses": {v.id: v.hypothesis for v in variants},
        "control": control,
        "variants": {v.id: summarise(rows[v.id], args.seed) for v in variants},
        "comparisons": comps,
        "rows": [{k: val for k, val in r.items() if not k.startswith("_")} for v in variants for r in rows[v.id]],
        "worst_calls": worst,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print_report(result)
    return result


def print_report(res: dict) -> None:
    fmt = lambda c: f"{c['mean']:.3f} [{c['lo']:.3f}, {c['hi']:.3f}]"
    print(f"\n{'variant':<20}{'conversion':<26}{'positive':<26}{'rubric /16':<26}{'QC fail':<24}turns")
    for vid, s in res["variants"].items():
        print(f"{vid:<20}{fmt(s['conversion']):<26}{fmt(s['positive_outcome']):<26}{fmt(s['rubric_total']):<26}"
              f"{fmt(s['qc_fail_rate']):<24}{s['call_turns']['mean']:.1f}")
    print(f"\nvs control {res['control']} (Holm-adjusted):")
    for vid, c in res["comparisons"].items():
        cv, t = c["converted"], c["total"]
        print(f"  {vid:<18} conv {cv['diff']:+.3f} [{cv['lo']:+.3f}, {cv['hi']:+.3f}] p_holm={cv['p_holm']:.4f}"
              f"{' *' if cv['significant'] else '  '}   rubric {t['diff']:+.2f} [{t['lo']:+.2f}, {t['hi']:+.2f}]"
              f" p_holm={t['p_holm']:.4f}{' *' if t['significant'] else ''}")


if __name__ == "__main__":
    main()
