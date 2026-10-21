#!/usr/bin/env python3
"""CI gate for prompt changes. Fails (exit 1) if:
  * any non-known-issue regression case fails on a changed variant, or
  * a small A/B smoke run shows its average rubric total dropping more than --max-drop below
    results/baseline.json, or its QC fail rate rising more than --max-qc-rise, or
  * the harness self-test fails: v0_sanity_bad must score clearly worse than production.

    python eval/ci_gate.py                                   # the production variant
    python eval/ci_gate.py --variants prompts/v6_new_idea     # changed variants (CI passes these from git diff)
    python eval/ci_gate.py --write-baseline      # refresh results/baseline.json from production
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ab_test import run_variant  # noqa: E402
from callqc.judges import make_panel  # noqa: E402
from callqc.personas import load_all  # noqa: E402
from callqc.regression import run_suite  # noqa: E402
from callqc.vaani_adapter import Variant  # noqa: E402

BASELINE = ROOT / "results/baseline.json"
SANITY = "v0_sanity_bad"


def smoke(variant: Variant, n: int) -> dict:
    rows = run_variant(variant, load_all(), n, seed=0, judges=make_panel("rule"), save_dir=None)
    return {"variant": variant.id, "calls": len(rows), "rubric_total": round(st.mean(r["total"] for r in rows), 3),
            "qc_fail_rate": round(st.mean(r["qc_fail"] for r in rows), 3),
            "conversion": round(st.mean(r["converted"] for r in rows), 3)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", nargs="*")
    ap.add_argument("--calls-per-persona", type=int, default=5)
    ap.add_argument("--max-drop", type=float, default=0.5, help="allowed drop in mean rubric total (out of 16)")
    ap.add_argument("--max-qc-rise", type=float, default=0.05)
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args(argv)

    production = Variant.load(ROOT / "prompts" / yaml.safe_load((ROOT / "prompts/production.yaml").read_text())["production"])
    if args.write_baseline:
        base = smoke(production, args.calls_per_persona)
        BASELINE.write_text(json.dumps(base, indent=1) + "\n")
        print(f"wrote {BASELINE.relative_to(ROOT)}: {base}")
        return 0

    base = json.loads(BASELINE.read_text())
    paths = [p for p in (args.variants or [ROOT / "prompts" / production.id]) if Path(p).name != SANITY]
    failures = []
    for path in paths:
        v = Variant.load(path)
        print(f"\n== {v.id}")
        reg = run_suite(v)
        if reg["failed"]:
            failures.append(f"{v.id}: regression cases failed: {reg['failed']}")
        s = smoke(v, args.calls_per_persona)
        drop = base["rubric_total"] - s["rubric_total"]
        print(f"  smoke: rubric {s['rubric_total']:.2f} (baseline {base['rubric_total']:.2f}, drop {drop:+.2f}), "
              f"QC fail {s['qc_fail_rate']:.3f} (baseline {base['qc_fail_rate']:.3f}), conversion {s['conversion']:.3f}")
        if drop > args.max_drop:
            failures.append(f"{v.id}: rubric total dropped {drop:.2f} > {args.max_drop}")
        if s["qc_fail_rate"] - base["qc_fail_rate"] > args.max_qc_rise:
            failures.append(f"{v.id}: QC fail rate rose to {s['qc_fail_rate']:.3f}")

    bad = smoke(Variant.load(ROOT / "prompts" / SANITY), args.calls_per_persona)
    print(f"\n== harness self-test: {SANITY} rubric {bad['rubric_total']:.2f} vs baseline {base['rubric_total']:.2f}")
    if base["rubric_total"] - bad["rubric_total"] < 3.0:
        failures.append("harness self-test: deliberately bad prompt did not score clearly worse")

    print("\n" + ("GATE FAILED:\n  " + "\n  ".join(failures) if failures else "GATE PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
