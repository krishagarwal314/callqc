"""CallQC dashboard: scores across prompt versions, per-criterion breakdown, worst calls with the breaking
turn highlighted, and side-by-side A/B comparison.

    streamlit run apps/dashboard.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results/ab/latest.json"
CRITERIA = ["script_adherence", "mandatory_disclosures", "objection_handling", "hallucinated_figures",
            "tone_empathy", "escalation_exit", "compliance", "outcome"]

st.set_page_config(page_title="CallQC", layout="wide")
if not RESULTS.exists():
    st.error("No results yet. Run: python ab_test.py --variants prompts/v1_baseline prompts/v2_ack_objection ...")
    st.stop()
res = json.loads(RESULTS.read_text())
rows = pd.DataFrame(res["rows"])
variants = res["config"]["variants"]
st.title("CallQC")
st.caption(f"{len(rows)} simulated calls · {len(variants)} variants · {len(res['config']['personas'])} personas · "
           f"rubric v{res['config']['rubric_version']} · generated {res['generated_at']}")

tab_over, tab_crit, tab_worst, tab_ab = st.tabs(["Over versions", "Per criterion", "Worst calls", "A/B compare"])

with tab_over:
    summary = pd.DataFrame([{
        "variant": v, "conversion": s["conversion"]["mean"], "conv_lo": s["conversion"]["lo"], "conv_hi": s["conversion"]["hi"],
        "positive": s["positive_outcome"]["mean"], "rubric_total": s["rubric_total"]["mean"],
        "qc_fail_rate": s["qc_fail_rate"]["mean"], "turns": s["call_turns"]["mean"]} for v, s in res["variants"].items()])
    c1, c2 = st.columns(2)
    c1.subheader("Rubric total (/16)")
    c1.bar_chart(summary.set_index("variant")["rubric_total"])
    c2.subheader("Conversion rate")
    c2.bar_chart(summary.set_index("variant")[["conversion", "positive"]])
    st.dataframe(summary, hide_index=True, width="stretch")

with tab_crit:
    crit = pd.DataFrame({v: s["criteria"] for v, s in res["variants"].items()}).T[CRITERIA]
    st.dataframe(crit, width="stretch")
    st.bar_chart(crit.T)
    persona = pd.DataFrame({v: {p: d["conversion"] for p, d in s["by_persona"].items()} for v, s in res["variants"].items()})
    st.subheader("Conversion by persona")
    st.dataframe(persona, width="stretch")

with tab_worst:
    v = st.selectbox("Variant", variants, index=len(variants) - 1)
    for item in res["worst_calls"][v]:
        call, qc = item["call"], item["qc"]
        with st.expander(f"{call['call_id']} · {qc['total']}/16 · broke on {qc['break_criterion']} at turn {qc['break_turn']}"):
            st.write({c: s["score"] for c, s in qc["scores"].items()})
            st.caption(qc["scores"][qc["break_criterion"]]["justification"])
            for t in call["turns"]:
                who = "Vaani" if t["speaker"] == "agent" else "Caller"
                line = f"`{t['index']:>2}` **{who}** · _{t['stage']}_ — {t['text']}"
                if t["index"] == qc["break_turn"]:
                    st.error(line)
                else:
                    st.markdown(line)

with tab_ab:
    a, b = st.columns(2)
    va = a.selectbox("A", variants, index=0)
    vb = b.selectbox("B", variants, index=min(1, len(variants) - 1))
    for col, vid in ((a, va), (b, vb)):
        s = res["variants"][vid]
        col.markdown(f"**{vid}** — {res['hypotheses'].get(vid, '')}")
        col.metric("Conversion", f"{s['conversion']['mean']:.1%}", help=f"95% CI {s['conversion']['lo']:.1%}–{s['conversion']['hi']:.1%}")
        col.metric("Rubric total", f"{s['rubric_total']['mean']:.2f}")
        col.metric("QC fail rate", f"{s['qc_fail_rate']['mean']:.1%}")
    if vb in res["comparisons"] and va == res["control"]:
        c = res["comparisons"][vb]
        st.write(f"Conversion lift {c['converted']['diff']:+.1%} (95% CI {c['converted']['lo']:+.1%} to "
                 f"{c['converted']['hi']:+.1%}), Holm p = {c['converted']['p_holm']:.4f} → "
                 f"{'significant' if c['converted']['significant'] else 'not significant'}")
        st.dataframe(pd.DataFrame(c["by_persona"]).T, width="stretch")
