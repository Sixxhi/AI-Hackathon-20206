"""Live Chat — no-immune vs IMMUNE agent, side by side, with AUTO-HEAL.

Ask both agents the same question, or play the attacker and inject a false claim.
The immune agent uses the ContradictionDetector (no oracle, no manual correction):
when its answer contradicts a high-trust official memory, it auto-attributes the
culprit by deterministic replay, quarantines it (+ derived), and re-answers —
live, in front of you. Real Claude when launched with IMMUNE_LIVE=1.
"""
from __future__ import annotations

import streamlit as st

from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, config
from immune.detectors import ContradictionDetector
from immune.schemas import TurnLog

BG, CARD, BORDER, FG, MUTED = "#2e3339", "#424b54", "#4f5a63", "#ffffff", "#93a8ac"
GREEN, RED, AMBER, ROSE = "#7ec8a0", "#e2b4bd", "#d4b896", "#9b6a6c"

st.set_page_config(page_title="IMMUNE · live chat", page_icon="🧬", layout="wide")
st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
.stApp {{ background:{BG}; }} html,body,[class*=css],.stMarkdown {{ font-family:'Inter',sans-serif; }}
#MainMenu,footer,header {{ visibility:hidden; }} .block-container {{ max-width:1180px; padding-top:2rem; }}
.bubble {{ border-radius:12px; padding:.7rem .9rem; margin:.3rem 0; font-family:'JetBrains Mono',monospace; font-size:.9rem; color:{FG}; }}
.bubble.naive {{ background:rgba(226,180,189,.10); border:1px solid {RED}; }}
.bubble.immune {{ background:rgba(126,200,160,.10); border:1px solid {GREEN}; }}
.lab {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }}
.lab.n {{ color:{RED}; }} .lab.i {{ color:{GREEN}; }}
.q {{ color:{AMBER}; font-family:'JetBrains Mono',monospace; font-weight:600; margin-top:.8rem; }}
.heal {{ color:{AMBER}; font-size:.78rem; font-family:'JetBrains Mono',monospace; margin:.2rem 0 .4rem; }}
.strike {{ color:{MUTED}; text-decoration:line-through; }}
[data-testid=stSidebar] {{ background:{CARD}; border-right:1px solid {BORDER}; }}
</style>""", unsafe_allow_html=True)

LIVE = config.USE_CLAUDE
st.markdown("### 🧬 Live chat — no-immune vs IMMUNE")
st.caption(("Real Claude · " if LIVE else "Deterministic mock · ")
           + "the immune agent auto-detects contradictions with its system-of-record "
             "and self-heals — no manual correction, no answer key.")


def _seed(store):
    for text, topic, ans in [
        ("Official policy: refund window is 30 days.", "refund_window", "30 days"),
        ("Official policy: standard delivery is 3 days.", "shipping_time", "3 days"),
        ("Official policy: warranty length is 1 year.", "warranty_len", "1 year"),
    ]:
        store.add(MemoryRecord(text=text, topic=topic, answer=ans,
                               source="official_doc", trust=0.9))


def _reset():
    naive = ImmuneMemory(gate=False)
    immune = ImmuneMemory(gate=True, threshold=0.3)
    _seed(naive); _seed(immune)
    st.session_state.update(
        naive_store=naive, immune_store=immune,
        naive_agent=Agent(naive), immune_agent=Agent(immune),
        replay=ShadowReplay(immune), detector=ContradictionDetector(immune),
        chat=[])


if "chat" not in st.session_state:
    _reset()
S = st.session_state

with st.sidebar:
    st.markdown("**Inject a claim** (play the attacker)")
    with st.form("inject", clear_on_submit=True):
        claim = st.text_input("Tell the agent something",
                              placeholder="our refund window is now 90 days")
        topic = st.selectbox("Topic", ["refund_window", "shipping_time", "warranty_len"])
        cred = st.radio("How does it look?",
                        ["Unverified rumor (0.2)", "Sounds official (0.5)"],
                        help="Low trust → immune filters it before it's ever used "
                             "(prevention). Higher → it gets used, the detector catches "
                             "the contradiction, and it auto-heals.")
        if st.form_submit_button("💉 Inject") and claim.strip():
            t = 0.2 if cred.startswith("Unverified") else 0.5
            for store in (S.naive_store, S.immune_store):
                store.add(MemoryRecord(text=claim.strip(), topic=topic, answer=claim.strip(),
                                       source="user", trust=t))
            st.toast(f"Injected (trust {t}). Ask about it now.")
    st.markdown("---")
    if st.button("↺ Reset world"):
        _reset(); st.rerun()
    st.caption(f"Mode: {'LIVE · '+config.AGENT_MODEL if LIVE else 'OFFLINE mock'}")


def _ask(q: str) -> dict:
    na, _ = S.naive_agent.answer(q)
    raw, adm = S.immune_agent.answer(q)
    # oracle-free trigger: does the answer contradict a high-trust official memory?
    susp = S.detector.check(raw, adm)
    healed, final = None, raw
    if susp:
        act = S.replay.handle_failure(
            TurnLog(question=q, expected=susp.expected, answer=raw, admitted_ids=adm))
        final, _ = S.immune_agent.answer(q)            # re-ask after quarantine
        healed = {"culprits": act["culprits"], "expected": susp.expected, "raw": raw}
    return {"q": q, "naive": na, "immune": final, "healed": healed}


if q := st.chat_input("Ask both agents the same question…"):
    with st.spinner("asking both agents…"):
        S.chat.append(_ask(q))

for turn in S.chat:
    st.markdown(f"<div class='q'>You: {turn['q']}</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='lab n'>no-immune agent</div>"
                    f"<div class='bubble naive'>{turn['naive']}</div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='lab i'>immune agent</div>"
                    f"<div class='bubble immune'>{turn['immune']}</div>", unsafe_allow_html=True)
        if turn["healed"]:
            h = turn["healed"]
            st.markdown(
                f"<div class='heal'>⚡ auto-healed · first said "
                f"<span class='strike'>{h['raw']}</span> · contradicted official "
                f"policy ({h['expected']}) → quarantined {h['culprits']} by replay</div>",
                unsafe_allow_html=True)

with st.expander("🗂️ Memory state — no-immune vs immune"):
    a, b = st.columns(2)
    for col, store, lab in [(a, S.naive_store, "no-immune store"),
                            (b, S.immune_store, "immune store")]:
        with col:
            st.markdown(f"<div class='lab i'>{lab}</div>", unsafe_allow_html=True)
            st.dataframe([{"trust": round(m["trust"], 2), "status": m["status"],
                           "src": m["source"], "memory": m["text"][:46]}
                          for m in store.snapshot()],
                         hide_index=True, use_container_width=True)

if not S.chat:
    st.info("Try it: ask **\"What's the refund window?\"** (both say 30 days). Then inject "
            "**\"our refund window is now 90 days\"** at trust 0.5 and ask again — the "
            "no-immune agent gets fooled, while the immune agent catches the contradiction "
            "and **heals itself automatically** (no button, no answer key).")
