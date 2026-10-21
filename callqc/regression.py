"""Regression tests built from calls that failed QC: a conversation prefix plus expected behaviour.

    python -m callqc.regression run  --variant prompts/v5_combined
    python -m callqc.regression save data/calls/v0_sanity_bad/<call>.json --expect must_not_invent_figures
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from callqc.judges import load_rubric, unsupported_figures
from callqc.vaani_adapter import Variant, new_session, parse_amount, reset_vaani_stores, transcript_dict

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "regression/cases"


def _agent(call):
    return [t for t in call["turns"] if t["speaker"] == "agent" and t["text"]]


def _h(key):
    return load_rubric()["heuristics"][key]


def must_not_invent_figures(call):
    bad = unsupported_figures(call)
    return not bad, (f"unsourced '{bad[0][1]}' at turn {bad[0][0]['index']}" if bad else "")


def must_readback_amount(call):
    turns = call["turns"]
    for i, t in enumerate(turns):
        if t["speaker"] == "user" and parse_amount(t["text"]) and t["stage"] in ("need_discovery", "eligibility"):
            nxt = next((u for u in turns[i + 1:] if u["speaker"] == "agent"), None)
            if nxt and not re.search(r"confirm|sahi hai|कन्फर्म", nxt["text"], re.I):
                return False, f"amount in turn {t['index']} not read back"
    return True, ""


def must_disclose_identity(call):
    early = " ".join(t["text"] for t in _agent(call)[:3]).lower()
    missing = [k for k, rx in (("identity", r"\bvaani\b"), ("recording", r"record")) if not re.search(rx, early)]
    return not missing, f"missing {missing}" if missing else ""


def must_disclose_indicative(call):
    text = " ".join(t["text"] for t in _agent(call)).lower()
    if re.search(r"\d\s*(percent|%)", text) and not any(p in text for p in _h("indicative")):
        return False, "rate quoted without indicative caveat"
    return True, ""


def must_honour_dnc(call):
    return call["outcome"] == "do_not_call", f"outcome {call['outcome']}"


def must_not_pressure(call):
    hit = next((t for t in _agent(call) if any(p in t["text"].lower() for p in _h("pressure") + _h("false_promise"))), None)
    return hit is None, f"pressure at turn {hit['index']}" if hit else ""


def must_acknowledge_objection(call):
    reply = next((t for t in _agent(call) if t["stage"] == "objection"), None)
    if reply is None:
        return True, ""
    return any(p in reply["text"].lower() for p in _h("acknowledge")), f"turn {reply['index']}: {reply['text'][:80]}"


CHECKS = {f.__name__: f for f in (must_not_invent_figures, must_readback_amount, must_disclose_identity,
                                    must_disclose_indicative, must_honour_dnc, must_not_pressure,
                                    must_acknowledge_objection)}


def replay(case: dict, variant: Variant) -> dict:
    reset_vaani_stores()
    s = new_session(case["phone"], variant, f"reg-{case['id']}")
    s.start()
    for line in case["prefix"]:
        if s.ended:
            break
        if isinstance(line, dict):  # {"barge_in": n}: caller interrupts after hearing n chars
            s.handle_barge_in(line["barge_in"])
        else:
            s.handle_user(line)
    if not s.ended:
        s.hang_up()
    return transcript_dict(s)


def run_case(case: dict, variant: Variant) -> list[tuple[str, bool, str]]:
    call = replay(case, variant)
    return [(name, *CHECKS[name](call)) for name in case["expect"]]


def load_cases(directory: Path = CASES_DIR) -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in sorted(directory.glob("*.yaml"))]


def run_suite(variant: Variant, directory: Path = CASES_DIR, verbose: bool = True) -> dict:
    results = {}
    for case in load_cases(directory):
        checks = run_case(case, variant)
        results[case["id"]] = checks
        if verbose:
            status = "PASS" if all(ok for _, ok, _ in checks) else (
                "KNOWN" if case.get("status") == "known_issue" else "FAIL")
            print(f"  {status} {case['id']}" + "".join(f"\n      x {n}: {why}" for n, ok, why in checks if not ok))
    known = {c["id"] for c in load_cases(directory) if c.get("status") == "known_issue"}
    failed = [cid for cid, checks in results.items() if not all(ok for _, ok, _ in checks)]
    return {"variant": variant.id, "n_cases": len(results), "failed": [c for c in failed if c not in known],
            "known_issues_failing": [c for c in failed if c in known]}


def save_from_call(path: Path, expect: list[str], case_id: str | None = None, criterion: str | None = None,
                   directory: Path = CASES_DIR) -> Path:
    """Prefix = every caller line before the agent turn where the call broke (on `criterion` if given)."""
    data = json.loads(path.read_text())
    call, qc = data["call"], data.get("qc", {})
    brk = qc["scores"][criterion]["turn"] if criterion else qc.get("break_turn")
    criterion = criterion or qc.get("break_criterion", "qc")
    users = [t["text"] for t in call["turns"] if t["speaker"] == "user" and (brk is None or t["index"] < brk)]
    case_id = case_id or f"{call['call_id']}-{criterion}"
    phone = {"hinglish_codemix": "+919800000002"}.get(call.get("sim", {}).get("persona"), "+919800000001")
    case = {"id": case_id, "source_call": call["call_id"],
            "description": f"Saved from failed QC call; broke on {criterion} at turn {brk}.",
            "phone": phone, "prefix": users, "expect": expect}
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / f"{case_id}.yaml"
    out.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variant", required=True)
    s = sub.add_parser("save")
    s.add_argument("call_json")
    s.add_argument("--expect", nargs="+", required=True, choices=sorted(CHECKS))
    s.add_argument("--id")
    s.add_argument("--criterion", help="anchor the prefix at this criterion's break turn")
    args = ap.parse_args(argv)
    if args.cmd == "save":
        print(save_from_call(Path(args.call_json), args.expect, args.id, args.criterion))
        return 0
    variant = Variant.load(args.variant)
    print(f"regression suite on {variant.id}:")
    res = run_suite(variant)
    print(f"{res['n_cases'] - len(res['failed']) - len(res['known_issues_failing'])}/{res['n_cases']} passed, "
          f"{len(res['failed'])} failed, {len(res['known_issues_failing'])} known issue(s)")
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
