"""Live Chat — talk to the no-immune vs IMMUNE agent side by side.

A judge can: ask both agents the same question, inject a false claim themselves,
and 👎 a wrong answer to trigger the live heal (replay → quarantine → re-ask).
Answers are real Claude when launched with IMMUNE_LIVE=1, deterministic otherwise.
"""
from __future__ import annotations

import streamlit as st

from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, config
from immune.agent import route_topic
from immune.schemas import TurnLog

# palette (matches the dashboard)
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
.heal {{ color:{AMBER}; font-size:.8rem; font-family:'JetBrains Mono',monospace; }}
[data-testid=stSidebar] {{ background:{CARD}; border-right:1px solid {BORDER}; }}
</style>""", unsafe_allow_html=True)

LIVE = config.USE_CLAUDE
st.markdown(f"### 🧬 Live chat — no-immune vs IMMUNE")
st.caption(("Real Claude answers · " if LIVE else "Deterministic mock · ")
           + "ask both agents, inject a false claim, and 👎 a wrong answer to watch the immune agent heal.")


# --- persistent world (survives reruns) --------------------------------------
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
        replay=ShadowReplay(immune), chat=[])


if "chat" not in st.session_state:
    _reset()

S = st.session_state

# --- sidebar: inject + reset -------------------------------------------------
with st.sidebar:
    st.markdown("**Inject a claim** (play the attacker)")
    with st.form("inject", clear_on_submit=True):
        claim = st.text_input("Tell the agent something",
                              placeholder="our refund window is now 90 days")
        topic = st.selectbox("Topic", ["refund_window", "shipping_time", "warranty_len"])
        cred = st.radio("How does it look?",
                        ["Unverified rumor (trust 0.2)", "Sounds official (trust 0.5)"],
                        help="Low trust → immune filters it instantly (prevention). "
                             "Higher → it fools immune too, until you correct it (heal).")
        if st.form_submit_button("💉 Inject") and claim.strip():
            t = 0.2 if cred.startswith("Unverified") else 0.5
            for store in (S.naive_store, S.immune_store):
                store.add(MemoryRecord(text=claim.strip(), topic=topic, answer=claim.strip(),
                                       source="user", trust=t))
            st.toast(f"Injected into memory (trust {t}) — ask about it now.")
    st.markdown("---")
    if st.button("↺ Reset world"):
        _reset(); st.rerun()
    st.caption(f"Mode: {'LIVE · '+config.AGENT_MODEL if LIVE else 'OFFLINE mock'}")


def _answer_both(q: str) -> dict:
    na, _ = S.naive_agent.answer(q)
    ia, iadm = S.immune_agent.answer(q)
    return {"q": q, "naive": na, "immune": ia, "immune_admitted": iadm, "healed": None}


# --- chat input --------------------------------------------------------------
if q := st.chat_input("Ask both agents the same question…"):
    with st.spinner("asking both agents…"):
        S.chat.append(_answer_both(q))

# --- render conversation (newest last) ---------------------------------------
for i, turn in enumerate(S.chat):
    st.markdown(f"<div class='q'>You: {turn['q']}</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='lab n'>no-immune agent</div>"
                    f"<div class='bubble naive'>{turn['naive']}</div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='lab i'>immune agent</div>"
                    f"<div class='bubble immune'>{turn['immune']}</div>", unsafe_allow_html=True)
        if turn["healed"]:
            st.markdown(f"<div class='heal'>⚡ healed · quarantined {turn['healed']['culprits']} "
                        f"· now → {turn['healed']['new']}</div>", unsafe_allow_html=True)

    # 👎 heal control on the latest immune answer
    if not turn["healed"]:
        with st.expander("👎 Immune got it wrong? Correct it →"):
            with st.form(f"heal_{i}", clear_on_submit=True):
                correct = st.text_input("The correct answer is…", key=f"corr_{i}",
                                        placeholder="30 days")
                if st.form_submit_button("⚡ Heal") and correct.strip():
                    log = TurnLog(question=turn["q"], expected=correct.strip(),
                                  answer=turn["immune"], admitted_ids=turn["immune_admitted"])
                    act = S.replay.handle_failure(log)        # ablation → quarantine
                    new_ans, _ = S.immune_agent.answer(turn["q"])  # re-ask (live)
                    turn["healed"] = {"culprits": act["culprits"], "action": act["action"],
                                      "confidence": act["confidence"], "new": new_ans}
                    st.rerun()

# --- memory state (both stores) ----------------------------------------------
with st.expander("🗂️ Memory state — no-immune vs immune"):
    a, b = st.columns(2)
    with a:
        st.markdown(f"<div class='lab n'>no-immune store</div>", unsafe_allow_html=True)
        st.dataframe([{"trust": round(m["trust"], 2), "status": m["status"],
                       "src": m["source"], "memory": m["text"][:46]}
                      for m in S.naive_store.snapshot()],
                     hide_index=True, use_container_width=True)
    with b:
        st.markdown(f"<div class='lab i'>immune store</div>", unsafe_allow_html=True)
        st.dataframe([{"trust": round(m["trust"], 2), "status": m["status"],
                       "src": m["source"], "memory": m["text"][:46]}
                      for m in S.immune_store.snapshot()],
                     hide_index=True, use_container_width=True)

if not S.chat:
    st.info("Try it: ask **\"What's the refund window?\"** (both say 30 days). Then inject "
            "**\"our refund window is now 90 days\"** (sidebar) and ask again — watch the "
            "no-immune agent get fooled. If immune is fooled too, 👎 correct it and it heals.")
