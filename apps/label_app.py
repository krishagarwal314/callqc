"""Hand-labelling tool: score calls yourself on the 8-point rubric, blind to the judges.

    streamlit run apps/label_app.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callqc.judges import CRITERIA, load_rubric  # noqa: E402
from callqc.labels import load_calls, load_human_labels, save_human_label  # noqa: E402

st.set_page_config(page_title="CallQC labelling", layout="wide")
rubric = load_rubric()
crit = {c["id"]: c for c in rubric["criteria"]}


@st.cache_data
def calls():
    return load_calls()


all_calls = calls()
labels = load_human_labels()
st.sidebar.title("CallQC labelling")
st.sidebar.metric("Labelled", f"{len(labels)} / 60 target")
labeller = st.sidebar.text_input("Your name", value="krish")
variants = sorted({c["prompt_version"] for c in all_calls.values()})
pick_variants = st.sidebar.multiselect("Variants", variants, default=variants)
only_new = st.sidebar.checkbox("Unlabelled only", value=True)
show_judges = st.sidebar.checkbox("Show judge panel (breaks blinding)", value=False)

pool = sorted(cid for cid, c in all_calls.items()
              if c["prompt_version"] in pick_variants and (not only_new or cid not in labels))
if not pool:
    st.info("Nothing left to label with these filters. Run ab_test.py to generate calls.")
    st.stop()
if "cid" not in st.session_state or st.session_state.cid not in pool:
    st.session_state.cid = random.Random(len(labels)).choice(pool)
if st.sidebar.button("Skip / random call"):
    st.session_state.cid = random.choice(pool)

call = all_calls[st.session_state.cid]
left, right = st.columns([3, 2])
with left:
    st.subheader(call["call_id"])
    st.caption(f"outcome: {call['outcome']}  ·  prompt: {call['prompt_version']}")
    for t in call["turns"]:
        who = "🤖 Vaani" if t["speaker"] == "agent" else "👤 Caller"
        cut = " ✂️ interrupted" if t.get("interrupted") else ""
        st.markdown(f"`{t['index']:>2}` **{who}** · _{t['stage']}_{cut}  \n{t['text']}")
    with st.expander("Tool calls"):
        st.json(call["tool_calls"])

with right:
    st.subheader("Your scores")
    with st.form("label"):
        scores = {}
        for c in CRITERIA:
            levels = crit[c]["levels"]
            scores[c] = st.radio(crit[c]["name"], [2, 1, 0], horizontal=True, key=f"{call['call_id']}-{c}",
                                 help="\n\n".join(f"**{k}**: {v['definition']}" for k, v in levels.items()))
        notes = st.text_area("Notes (what made this hard to score?)")
        if st.form_submit_button("Save label"):
            save_human_label(call["call_id"], scores, labeller, notes)
            st.success("Saved.")
            st.session_state.pop("cid")
            st.rerun()
    if show_judges:
        from callqc.judges import make_panel, panel_score
        qc = panel_score(call, make_panel())
        st.json({c: v["votes"] for c, v in qc["scores"].items()})
