from __future__ import annotations

import pandas as pd
import streamlit as st

from common import (ACTORS, CATEGORY_LABEL, STATUS_LABEL, _set_actor, actor_name, conn, current_actor, go, go_case,
                    relative)
from riskops import monitoring, workflow as wf

VIEWS = ["Needs action", "My cases", "All open", "Closed", "All"]

# Guided tour for first-time visitors: (title, what you will see, case, role to act as)
TOUR = [
    ("⏸️ An automatic pause", "A P0 child-safety case paused its session by itself. Confirm or lift the pause as the Safety specialist.",
     "INC-1002", "priya.safety"),
    ("🛡️ AI vs. safety controls", "The AI under-called an API-key leak as P2. Deterministic controls raised it to P0 and kept the specialist route.",
     "INC-1004", "alex.riskops"),
    ("⚖️ Make a triage call", "Decide severity and routing for a jailbreak report. P0/P1 decisions must cite the evidence you reviewed.",
     "INC-1008", "alex.riskops"),
    ("🔗 Spot a related report", "A vague complaint that matches a confirmed injection incident. Confirm or reject the suggested link.",
     "INC-1015", "alex.riskops"),
]
SEV_STYLE = {"P0": "background-color:#fde2e1;color:#8a1c1c;font-weight:600", "P1": "background-color:#fdecd8;color:#8a4a0b;font-weight:600",
             "P2": "background-color:#fff6cc;color:#6b5600", "P3": "background-color:#eef1f5;color:#4a5160"}


def _tour(existing: set[str]) -> None:
    if st.session_state.get("tour_hidden"):
        return
    with st.container(border=True):
        a, b = st.columns([6, 1], vertical_alignment="top")
        a.markdown("**New here? Start with one of these.** Each report about an AI assistant is assessed by an AI, checked by "
                   "deterministic safety controls, and decided by people with recorded reasons. All data is synthetic; nothing is "
                   "sent or enforced. Use *Working as* in the sidebar to switch roles, or the buttons below, which pick the right role for you.")
        if b.button("Hide", key="tour_hide", use_container_width=True):
            st.session_state["tour_hidden"] = True
            st.rerun()
        steps = [t for t in TOUR if t[2] in existing]
        cols = st.columns(len(steps)) if steps else []
        for col, (title, text, iid, actor) in zip(cols, steps):
            with col:
                st.markdown(f"**{title}**")
                st.caption(text)
                name = ACTORS[actor].display.split(" (")[0].split(" —")[0]
                if st.button(f"Open {iid} as {name}", key=f"tour_{iid}", on_click=_set_actor, args=(actor,), use_container_width=True):
                    go_case(iid)


def render() -> None:
    c = conn()
    wf.expire_due_containment(c)
    me = current_actor()
    q = monitoring.queue(c)
    open_q = [x for x in q if x["status"] in monitoring.OPEN]

    head, btn = st.columns([5, 1], vertical_alignment="center")
    head.title("Incident queue")
    if btn.button("＋ New report", type="primary", use_container_width=True):
        go("intake")

    _tour({x["incident_id"] for x in q})

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Open", len(open_q))
    k2.metric("Overdue first review", sum(x["overdue"] for x in open_q))
    k3.metric("Open P0 / P1", sum(1 for x in open_q if x["effective_severity"] in ("P0", "P1")))
    k4.metric("Awaiting severity decision", sum(1 for x in open_q if not x["human_severity"]))
    k5.metric("Actions I can take", sum(1 for x in open_q for a in x["next_actions"] if wf.actor_can_do(c, me, a)))

    v, s, f = st.columns([3, 2, 1])
    view = v.segmented_control("View", VIEWS, default="Needs action", key="q_view", label_visibility="collapsed") or "Needs action"
    search = s.text_input("Search", placeholder="Search ID or title", label_visibility="collapsed", key="q_search")
    with f.popover("Filters", use_container_width=True):
        sev = st.multiselect("Severity", ["P0", "P1", "P2", "P3"], key="q_sev")
        cats = sorted({cat for x in q for cat in x["categories"]})
        cat = st.multiselect("Category", cats, format_func=lambda k: CATEGORY_LABEL.get(k, k), key="q_cat")
        owners = sorted({x["owner"] for x in q if x["owner"]})
        owner = st.multiselect("Owner", ["(unassigned)"] + owners, format_func=lambda k: k if k == "(unassigned)" else actor_name(k), key="q_owner")
        review = st.radio("Mandatory review", ["Any", "Flagged", "Not flagged"], horizontal=True, key="q_review")
        overdue_only = st.checkbox("Overdue only", key="q_overdue")

    def keep(x) -> bool:
        is_open = x["status"] in monitoring.OPEN
        if view == "Needs action" and not (is_open and x["next_actions"] and (x["pending"] or x["overdue"] or not x["human_severity"])):
            return False
        if view == "My cases" and not (x["owner"] == me.actor_id and is_open):
            return False
        if view == "All open" and not is_open:
            return False
        if view == "Closed" and is_open:
            return False
        if search and search.lower() not in (x["incident_id"] + " " + x["title"]).lower():
            return False
        if sev and x["effective_severity"] not in sev:
            return False
        if cat and not set(cat) & set(x["categories"]):
            return False
        if owner and (x["owner"] or "(unassigned)") not in owner:
            return False
        if review == "Flagged" and not x["mandatory_review"]:
            return False
        if review == "Not flagged" and x["mandatory_review"]:
            return False
        if overdue_only and not x["overdue"]:
            return False
        return True

    shown = sorted([x for x in q if keep(x)], key=lambda x: x["urgency"])
    rows = []
    basis_short = {"human": "✓", "ai_after_controls": "· AI", "rules_after_ai_failure": "· rules", "unassessed_default": "· default"}
    for x in shown:
        nxt = x["next_actions"][0] if x["next_actions"] else None
        is_open = x["status"] in monitoring.OPEN
        due = ""
        if is_open and not x["human_severity"]:
            due = ("⚠ " if x["overdue"] else "") + relative(x["minutes_to_deadline"])
        flags = []  # joined with spaces below
        if x["auto_paused"]:
            flags.append("⏸️")
        if x["mandatory_review"] and is_open and not x["human_severity"]:
            flags.append("⚑")
        if x["ai_source"] == "fault_injection":
            flags.append("🧪")
        rows.append({
            "Severity": f"{x['effective_severity']} {basis_short[x['severity_basis']]}",
            "Flags": " ".join(flags),
            "ID": x["incident_id"],
            "Title": x["title"],
            "Status": STATUS_LABEL[x["status"]],
            "Next action": (("" if wf.actor_can_do(c, me, nxt) else "🔒 ") + nxt["title"]) if nxt else "—",
            "First review": due,
            "Owner": actor_name(x["owner"]).split(" —")[0] if x["owner"] else "—",
        })
    cap, leg = st.columns([5, 1], vertical_alignment="center")
    cap.caption(f"{len(rows)} case(s) · most urgent first · click a row to open it")
    with leg.popover("How to read this", use_container_width=True):
        st.markdown("""
**Severity**: P0 critical · P1 high · P2 medium · P3 low
- `P0 ✓` a person confirmed it
- `P0 · AI` the AI's recommendation after safety controls, not yet confirmed
- `P0 · rules` the AI failed, so the deterministic rules' view is shown
- `P1 · default` not assessed yet

**Flags**: ⏸️ session paused automatically, waiting for a person · ⚑ a person must review · 🧪 fault-injection test data

**Next action**: 🔒 means your current role can't do it. Open the case to switch roles in one click.
""")
    if not rows:
        st.info("Nothing here. Try another view or clear the filters.")
        return
    df = pd.DataFrame(rows)
    styled = df.style.map(lambda v: SEV_STYLE.get(str(v)[:2], ""), subset=["Severity"])
    event = st.dataframe(
        styled, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
        key=f"q_table_{view}_{st.session_state.get('q_nonce', 0)}", height=min(36 * (len(rows) + 1) + 4, 640),
        column_config={
            "Severity": st.column_config.TextColumn(width=86, help="✓ = human-confirmed. AI = recommendation after safety controls, not yet confirmed."),
            "ID": st.column_config.TextColumn(width=72),
            "Title": st.column_config.TextColumn(width=262),
            "Status": st.column_config.TextColumn(width=128),
            "Next action": st.column_config.TextColumn(width=200),
            "First review": st.column_config.TextColumn(width=92, help="Time to the first-human-review target (prototype SLA assumptions)"),
            "Owner": st.column_config.TextColumn(width=52),
            "Flags": st.column_config.TextColumn(width=52, help="⏸️ session auto-paused (C7), confirm or lift · ⚑ mandatory human review pending · 🧪 fault-injection test data"),
        })
    sel = event.selection.rows if event and hasattr(event, "selection") else []
    if sel:
        # new table key next time, so returning to the queue does not re-open the same case
        st.session_state["q_nonce"] = st.session_state.get("q_nonce", 0) + 1
        go_case(rows[sel[0]]["ID"])
