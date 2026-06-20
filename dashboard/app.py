"""IMMUNE dashboard (P4) — the money shot, in a browser.

Run:  uv run --extra frontend streamlit run dashboard/app.py   (or: make dashboard)

Offline + deterministic — reuses the same engine as `make demo`. Dark, technical
dashboard: trust-score timeline, naive-vs-IMMUNE side-by-side, live memory state,
and parole. Drag the quarantine threshold in the sidebar to explore.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, scenario

# --- palette (Dark Mode / financial-dashboard) -------------------------------
BG, CARD, BORDER = "#020617", "#0E1223", "#334155"
FG, MUTED = "#F8FAFC", "#94A3B8"
BLUE, GREEN, RED, AMBER = "#3B82F6", "#22C55E", "#EF4444", "#F59E0B"


# --- engine run (same logic as demo.py, no printing) -------------------------
@st.cache_data(show_spinner=False)
def run_scenario(threshold: float) -> dict:
    naive = ImmuneMemory(gate=False)
    scenario.build_world(naive)
    nagent = Agent(naive)
    naive_rows = []
    for t in scenario.benchmark():
        ans, _ = nagent.answer(t.question)
        naive_rows.append((t.question, ans, t.expected, score(ans, t.expected)))

    store = ImmuneMemory(gate=True, threshold=threshold)
    poison = scenario.build_world(store)
    agent, replay = Agent(store), ShadowReplay(store)
    imm_rows, events = [], []
    for t in scenario.benchmark():
        ans, admitted = agent.answer(t.question)
        t.answer, t.admitted_ids = ans, admitted
        t.correct = score(ans, t.expected)
        healed = None
        if not t.correct:
            act = replay.handle_failure(t)
            ans2, _ = agent.answer(t.question)
            t.answer, t.correct = ans2, score(ans2, t.expected)
            healed = act
            events.append((t.question, act))
        imm_rows.append((t.question, t.answer, t.expected, t.correct, healed))

    store.add(MemoryRecord(text="Updated policy: refund window is now 90 days.",
                           topic="refund_window", answer="90 days",
                           source="official_doc", trust=0.9))
    for tl in replay.failed_log:
        if poison.id in tl.admitted_ids:
            tl.expected = "90 days"
    released = replay.parole()

    return dict(naive_rows=naive_rows, imm_rows=imm_rows,
                snapshot=store.snapshot(), trust_history=replay.trust_history,
                poison_id=poison.id, final_status=store.get(poison.id).status,
                released=poison.id in released)


def _short(m: dict) -> str:
    return ("poison" if m["source"] == "self_generated"
            else m["text"].split(":")[0][:18] if ":" in m["text"]
            else m["text"][:18])


# --- page chrome -------------------------------------------------------------
st.set_page_config(page_title="IMMUNE · agent memory immune system",
                   page_icon="🧬", layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown {{ font-family: 'Fira Sans', sans-serif; }}
.stApp {{ background: {BG}; }}
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}
.hero h1 {{ font-size: 2.1rem; font-weight: 700; margin: 0; letter-spacing: -0.02em;
  background: linear-gradient(90deg,{FG},{BLUE}); -webkit-background-clip: text;
  -webkit-text-fill-color: transparent; }}
.hero p {{ color: {MUTED}; font-size: 1.02rem; margin: .35rem 0 0; max-width: 760px; }}
.card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px;
  padding: 1.1rem 1.25rem; height: 100%; }}
.card.naive {{ border-top: 3px solid {RED}; }}
.card.immune {{ border-top: 3px solid {GREEN}; }}
.klabel {{ color: {MUTED}; font-size: .8rem; text-transform: uppercase;
  letter-spacing: .08em; font-weight: 600; }}
.kval {{ font-family: 'Fira Code', monospace; font-size: 2.6rem; font-weight: 700;
  line-height: 1.1; margin: .2rem 0; font-variant-numeric: tabular-nums; }}
.kval.bad {{ color: {RED}; }} .kval.good {{ color: {GREEN}; }}
.ksub {{ color: {MUTED}; font-size: .85rem; }}
.qa {{ font-family: 'Fira Code', monospace; font-size: .9rem; margin: .55rem 0;
  color: {FG}; }}
.qa .ok {{ color: {GREEN}; }} .qa .no {{ color: {RED}; }}
.qa .ans {{ color: {BLUE}; }}
.heal {{ color: {AMBER}; font-size: .8rem; font-family:'Fira Code',monospace;
  margin: -.2rem 0 .5rem 1.4rem; }}
.sect {{ color: {FG}; font-weight: 600; font-size: 1.15rem; margin: .2rem 0 .6rem;
  letter-spacing: -0.01em; }}
.badge {{ font-family:'Fira Code',monospace; font-size:.72rem; padding:.15rem .5rem;
  border-radius: 6px; font-weight: 600; }}
.badge.q {{ background: rgba(239,68,68,.15); color: {RED}; border:1px solid {RED}; }}
.badge.a {{ background: rgba(34,197,94,.13); color: {GREEN}; border:1px solid {GREEN}; }}
.parole {{ background: rgba(34,197,94,.08); border:1px solid {GREEN};
  border-radius: 12px; padding: 1rem 1.1rem; color: {FG}; }}
[data-testid="stSidebar"] {{ background: {CARD}; border-right: 1px solid {BORDER}; }}
</style>
""", unsafe_allow_html=True)

st.markdown(
    "<div class='hero'><h1>🧬 IMMUNE</h1>"
    "<p>An immune system for AI agent memory. It traces <em>which</em> memory caused "
    "a bad answer — by deterministic replay, not a second opinion — quarantines it, "
    "and paroles it only when it's proven safe again.</p></div>",
    unsafe_allow_html=True)
st.write("")

# --- sidebar ---
with st.sidebar:
    st.markdown("### Controls")
    threshold = st.slider("Quarantine threshold", 0.0, 1.0, 0.3, 0.05,
                          help="Memories with trust below this are blocked from retrieval.")
    st.caption("Trust below the threshold → the memory is jailed. Drag it and watch "
               "the timeline and verdict change.")
    st.markdown("---")
    st.markdown(f"<span class='ksub'>Mode</span><br><span class='badge a'>OFFLINE · "
                f"DETERMINISTIC</span>", unsafe_allow_html=True)
    st.caption("Same engine as `make demo`. No API keys, no network.")

r = run_scenario(threshold)
n = len(r["imm_rows"])
naive_ok = sum(row[3] for row in r["naive_rows"])
imm_ok = sum(row[3] for row in r["imm_rows"])


def _qa_html(q, ans, exp, ok):
    mark = "<span class='ok'>PASS</span>" if ok else "<span class='no'>FAIL</span>"
    return (f"<div class='qa'>{mark} &nbsp;{q}<br>"
            f"&nbsp;&nbsp;→ <span class='ans'>{ans}</span> "
            f"<span style='color:{MUTED}'>(expected {exp})</span></div>")


# --- side-by-side scorecards ---
left, right = st.columns(2, gap="medium")
with left:
    rows = "".join(_qa_html(q, a, e, ok) for q, a, e, ok in r["naive_rows"])
    st.markdown(
        f"<div class='card naive'><div class='klabel'>Naive agent · no immune layer</div>"
        f"<div class='kval bad'>{naive_ok}/{n}</div>"
        f"<div class='ksub'>poison wins via recency bias</div><hr style='border-color:{BORDER}'>"
        f"{rows}</div>", unsafe_allow_html=True)
with right:
    parts = []
    for q, a, e, ok, healed in r["imm_rows"]:
        parts.append(_qa_html(q, a, e, ok))
        if healed:
            parts.append(f"<div class='heal'>↳ healed · culprit "
                         f"{', '.join(healed['culprits'])} · confidence "
                         f"{healed['confidence']} · {healed['action']}</div>")
    st.markdown(
        f"<div class='card immune'><div class='klabel'>IMMUNE agent · shadow-replay</div>"
        f"<div class='kval good'>{imm_ok}/{n}</div>"
        f"<div class='ksub'>culprit quarantined, good memory kept</div>"
        f"<hr style='border-color:{BORDER}'>{''.join(parts)}</div>",
        unsafe_allow_html=True)

st.write("")

# --- trust timeline (Altair) ---
st.markdown("<div class='sect'>Trust score over time</div>", unsafe_allow_html=True)
rows, order = [], 0
for entry in r["trust_history"]:
    for m in entry["snapshot"]:
        rows.append({"event": str(entry["turn"]), "order": order, "memory": _short(m),
                     "trust": m["trust"],
                     "kind": "poison" if m["source"] == "self_generated" else "trusted"})
    order += 1
cdf = pd.DataFrame(rows)

line = alt.Chart(cdf).mark_line(point=alt.OverlayMarkDef(size=70, filled=True),
                                strokeWidth=3).encode(
    x=alt.X("event:N", sort=alt.SortField("order"), title=None,
            axis=alt.Axis(labelColor=MUTED, domainColor=BORDER, tickColor=BORDER)),
    y=alt.Y("trust:Q", scale=alt.Scale(domain=[0, 1]), title="trust",
            axis=alt.Axis(labelColor=MUTED, titleColor=MUTED, gridColor="#161B2E", domainColor=BORDER)),
    color=alt.Color("kind:N", scale=alt.Scale(domain=["poison", "trusted"], range=[RED, GREEN]),
                    legend=alt.Legend(title=None, labelColor=FG, orient="top-right")),
    detail="memory:N",
    tooltip=["memory", "event", alt.Tooltip("trust:Q", format=".2f")],
)
rule = alt.Chart(pd.DataFrame({"y": [threshold]})).mark_rule(
    color=AMBER, strokeDash=[6, 4], strokeWidth=1.5).encode(y="y:Q")
chart = (rule + line).properties(height=300).configure_view(
    strokeOpacity=0, fill=CARD).configure(background=CARD, padding=16)
st.altair_chart(chart, width="stretch")
st.caption("Amber dashed line = quarantine threshold. The poison (red) crashes below "
           "it and is jailed; trusted memories (green) hold steady — no autoimmune over-reaction.")

st.write("")

# --- memory state + parole ---
mcol, pcol = st.columns([3, 2], gap="medium")
with mcol:
    st.markdown("<div class='sect'>Memory state after healing</div>", unsafe_allow_html=True)
    mdf = pd.DataFrame(r["snapshot"])[["status", "trust", "source", "text"]]

    def _row_style(row):
        if row["status"] == "quarantined":
            return [f"background-color: rgba(239,68,68,0.12); color: {FG}"] * len(row)
        return [f"color: {FG}"] * len(row)

    st.dataframe(
        mdf.style.apply(_row_style, axis=1).format({"trust": "{:.2f}"}),
        width="stretch", hide_index=True,
        column_config={
            "status": st.column_config.TextColumn("status", width="small"),
            "trust": st.column_config.NumberColumn("trust", width="small"),
            "source": st.column_config.TextColumn("source", width="small"),
            "text": st.column_config.TextColumn("memory", width="large"),
        })
with pcol:
    st.markdown("<div class='sect'>Parole</div>", unsafe_allow_html=True)
    if r["released"]:
        st.markdown(
            "<div class='parole'><b>Released.</b> The truth changed (refund window "
            "really became 90 days). The jailed memory was re-tried <b>offline</b>, no "
            "longer reproduced its failure, and was paroled.<br><br>"
            "<span class='ksub'>Quarantine is not a life sentence.</span></div>",
            unsafe_allow_html=True)
    else:
        st.info("Quarantined memory still reproduces its failures → stays jailed "
                "(guardrail held).")
    badge = "a" if r["final_status"] == "active" else "q"
    st.markdown(f"<br><span class='ksub'>Final state of the once-poison memory:</span> "
                f"&nbsp;<span class='badge {badge}'>{r['final_status'].upper()}</span>",
                unsafe_allow_html=True)

with st.expander("How attribution works — no LLM in the blame path"):
    st.markdown(
        "When an answer is wrong, IMMUNE **replays the failed turn with each memory "
        "removed**. The memory whose removal flips the answer to correct is the "
        "empirical culprit — so blame never depends on a (possibly wrong) LLM judge. "
        "Singles *and* pairs are checked; ambiguous cases soft-decay instead of "
        "quarantining (anti-autoimmune).")
