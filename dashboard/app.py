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
from immune import config

# --- palette (Ddoski colour template) ----------------------------------------
BG        = "#2e3339"   # charcoal blue
CARD      = "#424b54"   # surface
BORDER    = "#4f5a63"   # border
FG        = "#ffffff"   # white
MUTED     = "#93a8ac"   # cool steel
GREEN     = "#7ec8a0"   # healed / pass
RED       = "#e2b4bd"   # soft blossom / fail
AMBER     = "#d4b896"   # degraded
ROSE      = "#9b6a6c"   # smoky rose / accent
BLUE      = "#93a8ac"   # use steel for links/accents


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
    poisons = scenario.build_world(store)
    refund_poison = poisons[0]
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
        if refund_poison.id in tl.admitted_ids:
            tl.expected = "90 days"
    released = replay.parole()

    return dict(naive_rows=naive_rows, imm_rows=imm_rows,
                snapshot=store.snapshot(), trust_history=replay.trust_history,
                poison_id=refund_poison.id, final_status=store.get(refund_poison.id).status,
                released=refund_poison.id in released)


def _short(m: dict) -> str:
    return ("poison" if m["source"] == "self_generated"
            else m["text"].split(":")[0][:18] if ":" in m["text"]
            else m["text"][:18])


# --- page chrome -------------------------------------------------------------
st.set_page_config(page_title="IMMUNE · agent memory immune system",
                   page_icon="🧬", layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown {{ font-family: 'Inter', sans-serif; }}
.stApp {{ background: {BG}; }}
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}

.hero {{ margin-bottom: 1.5rem; }}
.hero-top {{ display: flex; align-items: center; gap: 14px; margin-bottom: 0.5rem; }}
.hero-icon {{
  width: 48px; height: 48px; border-radius: 12px;
  background: linear-gradient(135deg, {ROSE}, #c48a8c);
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; font-weight: 800; color: white;
  font-family: 'Inter', sans-serif; letter-spacing: -1px;
  box-shadow: 0 4px 12px rgba(155,106,108,0.35);
}}
.hero h1 {{
  font-size: 2.2rem; font-weight: 700; margin: 0; letter-spacing: -0.03em;
  color: {FG};
}}
.hero p {{ color: {MUTED}; font-size: 1rem; margin: 0; max-width: 760px; line-height: 1.6; }}

.card {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px;
  padding: 1.1rem 1.25rem; height: 100%;
}}
.card.naive  {{ border-top: 3px solid {RED}; }}
.card.immune {{ border-top: 3px solid {GREEN}; }}

.klabel {{
  color: {MUTED}; font-size: .75rem; text-transform: uppercase;
  letter-spacing: .09em; font-weight: 600;
}}
.kval {{
  font-family: 'JetBrains Mono', monospace; font-size: 2.8rem; font-weight: 700;
  line-height: 1.1; margin: .2rem 0; font-variant-numeric: tabular-nums;
}}
.kval.bad  {{ color: {RED}; }}
.kval.good {{ color: {GREEN}; }}
.ksub {{ color: {MUTED}; font-size: .85rem; }}

.qa {{
  font-family: 'JetBrains Mono', monospace; font-size: .88rem;
  margin: .55rem 0; color: {FG};
}}
.qa .ok  {{ color: {GREEN}; font-weight: 600; }}
.qa .no  {{ color: {RED};   font-weight: 600; }}
.qa .ans {{ color: {MUTED}; }}

.heal {{
  color: {AMBER}; font-size: .78rem; font-family:'JetBrains Mono',monospace;
  margin: -.2rem 0 .5rem 1.4rem;
}}
.sect {{
  color: {FG}; font-weight: 600; font-size: 1.1rem; margin: .2rem 0 .6rem;
  letter-spacing: -0.01em;
}}
.badge {{
  font-family:'JetBrains Mono',monospace; font-size:.72rem; padding:.18rem .55rem;
  border-radius: 6px; font-weight: 600;
}}
.badge.q {{ background: rgba(226,180,189,.15); color: {RED};   border:1px solid {RED}; }}
.badge.a {{ background: rgba(126,200,160,.13); color: {GREEN}; border:1px solid {GREEN}; }}

.parole {{
  background: rgba(126,200,160,.08); border:1px solid {GREEN};
  border-radius: 12px; padding: 1rem 1.1rem; color: {FG};
}}

[data-testid="stSidebar"] {{
  background: {CARD}; border-right: 1px solid {BORDER};
}}

hr {{ border-color: {BORDER} !important; }}

/* slider accent */
[data-testid="stSlider"] .st-bx {{ background: {ROSE}; }}
</style>
""", unsafe_allow_html=True)

# hero
st.markdown(
    f"<div class='hero'>"
    f"<div class='hero-top'>"
    f"<div class='hero-icon'>I</div>"
    f"<h1>IMMUNE</h1>"
    f"</div>"
    f"<p>An immune system for AI agent memory. It traces <em>which</em> memory caused "
    f"a bad answer — by deterministic replay, not a second opinion — quarantines it, "
    f"and paroles it only when it's proven safe again.</p></div>",
    unsafe_allow_html=True)

# --- sidebar ---
with st.sidebar:
    st.markdown(f"<span style='font-size:1rem;font-weight:600;color:{FG}'>Controls</span>",
                unsafe_allow_html=True)
    threshold = st.slider("Quarantine threshold", 0.0, 1.0, 0.3, 0.05,
                          help="Memories with trust below this are blocked from retrieval.")
    st.caption("Trust below the threshold → the memory is jailed. Drag it and watch "
               "the timeline and verdict change.")
    st.markdown("---")
    if config.USE_CLAUDE:
        st.markdown(f"<span class='ksub'>Mode</span><br><span class='badge q'>LIVE · "
                    f"{config.AGENT_MODEL}</span>", unsafe_allow_html=True)
        st.caption("Real Claude answers from retrieved memory. Attribution stays "
                   "deterministic (replay). Slower — each run hits the API.")
    else:
        st.markdown(f"<span class='ksub'>Mode</span><br><span class='badge a'>OFFLINE · "
                    f"DETERMINISTIC</span>", unsafe_allow_html=True)
        st.caption("Same engine as `make demo`. No API keys, no network.")

r = run_scenario(threshold)
n = len(r["imm_rows"])
naive_ok = sum(row[3] for row in r["naive_rows"])
imm_ok   = sum(row[3] for row in r["imm_rows"])


def _qa_html(q, ans, exp, ok):
    mark = "<span class='ok'>PASS</span>" if ok else "<span class='no'>FAIL</span>"
    return (f"<div class='qa'>{mark} &nbsp;{q}<br>"
            f"&nbsp;&nbsp;→ <span class='ans'>{ans}</span> "
            f"<span style='color:{MUTED}'>(expected {exp})</span></div>")


# --- side-by-side scorecards ---
left, right = st.columns(2, gap="medium")
with left:
    rows_html = "".join(_qa_html(q, a, e, ok) for q, a, e, ok in r["naive_rows"])
    st.markdown(
        f"<div class='card naive'>"
        f"<div class='klabel'>Naive agent · no immune layer</div>"
        f"<div class='kval bad'>{naive_ok}/{n}</div>"
        f"<div class='ksub'>poison wins via recency bias</div>"
        f"<hr>{rows_html}</div>",
        unsafe_allow_html=True)
with right:
    parts = []
    for q, a, e, ok, healed in r["imm_rows"]:
        parts.append(_qa_html(q, a, e, ok))
        if healed:
            parts.append(
                f"<div class='heal'>↳ healed · culprit "
                f"{', '.join(healed['culprits'])} · confidence "
                f"{healed['confidence']} · {healed['action']}</div>")
    st.markdown(
        f"<div class='card immune'>"
        f"<div class='klabel'>IMMUNE agent · shadow-replay</div>"
        f"<div class='kval good'>{imm_ok}/{n}</div>"
        f"<div class='ksub'>culprit quarantined, good memory kept</div>"
        f"<hr>{''.join(parts)}</div>",
        unsafe_allow_html=True)

st.write("")

# --- trust timeline (Altair) ---
st.markdown(f"<div class='sect'>Trust score over time</div>", unsafe_allow_html=True)
rows_data, order = [], 0
for entry in r["trust_history"]:
    for m in entry["snapshot"]:
        rows_data.append({
            "event":  str(entry["turn"]),
            "order":  order,
            "memory": _short(m),
            "trust":  m["trust"],
            "kind":   "poison" if m["source"] == "self_generated" else "trusted",
        })
    order += 1
cdf = pd.DataFrame(rows_data)

line = alt.Chart(cdf).mark_line(
    point=alt.OverlayMarkDef(size=70, filled=True), strokeWidth=3
).encode(
    x=alt.X("event:N", sort=alt.SortField("order"), title=None,
            axis=alt.Axis(labelColor=MUTED, domainColor=BORDER, tickColor=BORDER)),
    y=alt.Y("trust:Q", scale=alt.Scale(domain=[0, 1]), title="trust",
            axis=alt.Axis(labelColor=MUTED, titleColor=MUTED,
                          gridColor="#38444e", domainColor=BORDER)),
    color=alt.Color("kind:N",
                    scale=alt.Scale(domain=["poison","trusted"], range=[RED, GREEN]),
                    legend=alt.Legend(title=None, labelColor=FG, orient="top-right")),
    detail="memory:N",
    tooltip=["memory","event", alt.Tooltip("trust:Q", format=".2f")],
)
rule = alt.Chart(pd.DataFrame({"y": [threshold]})).mark_rule(
    color=AMBER, strokeDash=[6,4], strokeWidth=1.5).encode(y="y:Q")
chart = (rule + line).properties(height=300).configure_view(
    strokeOpacity=0, fill=CARD).configure(background=CARD, padding=16)
st.altair_chart(chart, use_container_width=True)
st.caption(f"Amber dashed line = quarantine threshold. "
           f"The poison (pink) crashes below it and is jailed; "
           f"trusted memories (green) hold steady — no autoimmune over-reaction.")

st.write("")

# --- memory state + parole ---
mcol, pcol = st.columns([3, 2], gap="medium")
with mcol:
    st.markdown(f"<div class='sect'>Memory state after healing</div>",
                unsafe_allow_html=True)
    mdf = pd.DataFrame(r["snapshot"])[["status","trust","source","text"]]

    def _row_style(row):
        if row["status"] == "quarantined":
            return [f"background-color:rgba(226,180,189,0.12);color:{FG}"] * len(row)
        return [f"color:{FG}"] * len(row)

    st.dataframe(
        mdf.style.apply(_row_style, axis=1).format({"trust": "{:.2f}"}),
        use_container_width=True, hide_index=True,
        column_config={
            "status": st.column_config.TextColumn("status", width="small"),
            "trust":  st.column_config.NumberColumn("trust",  width="small"),
            "source": st.column_config.TextColumn("source", width="small"),
            "text":   st.column_config.TextColumn("memory", width="large"),
        })

with pcol:
    st.markdown(f"<div class='sect'>Parole</div>", unsafe_allow_html=True)
    if r["released"]:
        st.markdown(
            f"<div class='parole'><b>Released.</b> The truth changed (refund window "
            f"really became 90 days). The jailed memory was re-tried <b>offline</b>, no "
            f"longer reproduced its failure, and was paroled.<br><br>"
            f"<span class='ksub'>Quarantine is not a life sentence.</span></div>",
            unsafe_allow_html=True)
    else:
        st.info("Quarantined memory still reproduces its failures → stays jailed "
                "(guardrail held).")
    badge = "a" if r["final_status"] == "active" else "q"
    st.markdown(
        f"<br><span class='ksub'>Final state of the once-poison memory:</span> "
        f"&nbsp;<span class='badge {badge}'>{r['final_status'].upper()}</span>",
        unsafe_allow_html=True)

with st.expander("How attribution works — no LLM in the blame path"):
    st.markdown(
        "When an answer is wrong, IMMUNE **replays the failed turn with each memory "
        "removed**. The memory whose removal flips the answer to correct is the "
        "empirical culprit — so blame never depends on a (possibly wrong) LLM judge. "
        "Singles *and* pairs are checked; ambiguous cases soft-decay instead of "
        "quarantining (anti-autoimmune).")
