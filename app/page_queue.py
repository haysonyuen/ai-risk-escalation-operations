from __future__ import annotations

import pandas as pd
import streamlit as st

from common import (CATEGORY_LABEL, STAGES, STATUS_LABEL, STATUS_STAGE, actor_name, conn, current_actor, go, go_case,
                    relative)
from riskops import monitoring, workflow as wf

VIEWS = ["Needs action", "My cases", "All open", "Closed", "All"]
SORTS = {
    "Most urgent first": lambda x: x["urgency"],
    "Severity (P0 first)": lambda x: ({"P0": 0, "P1": 1, "P2": 2, "P3": 3}[x["effective_severity"]], x["urgency"]),
    "Workflow stage (Intake → QA)": lambda x: (STATUS_STAGE[x["status"]], x["urgency"]),
    "Workflow stage (QA → Intake)": lambda x: (-STATUS_STAGE[x["status"]], x["urgency"]),
    "Newest first": lambda x: x["age_hours"],
    "Oldest first": lambda x: -x["age_hours"],
}

SEV_STYLE = {"P0": "background-color:#fde2e1;color:#8a1c1c;font-weight:600", "P1": "background-color:#fdecd8;color:#8a4a0b;font-weight:600",
             "P2": "background-color:#fff6cc;color:#6b5600", "P3": "background-color:#eef1f5;color:#4a5160"}


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
        stages = st.multiselect("Workflow stage", STAGES, key="q_stage",
                                help="Intake → AI enrichment → Triage → Investigation → Containment → Response → Closure → QA")
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
        if stages and STAGES[STATUS_STAGE[x["status"]]] not in stages:
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

    shown = [x for x in q if keep(x)]
    cap, srt, leg = st.columns([3.2, 2, 1.3], vertical_alignment="center")
    sort_by = srt.selectbox("Sort", list(SORTS), key="q_sort", label_visibility="collapsed", format_func=lambda k: f"Sort: {k}")
    shown = sorted(shown, key=SORTS[sort_by])
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
            "Stage · status": f"{STATUS_STAGE[x['status']] + 1} · {STATUS_LABEL[x['status']]}",
            "Next action": (("" if wf.actor_can_do(c, me, nxt) else "🔒 ") + nxt["title"]) if nxt else "—",
            "First review": due,
            "Owner": actor_name(x["owner"]).split(" —")[0] if x["owner"] else "—",
        })
    cap.caption(f"{len(rows)} case(s) · sorted by {sort_by[0].lower() + sort_by[1:]} · click a row to open it")
    with leg.popover("How to read this", use_container_width=True):
        st.markdown("""
**Severity**: P0 critical · P1 high · P2 medium · P3 low
- `P0 ✓` a person confirmed it
- `P0 · AI` the AI's recommendation after safety controls, not yet confirmed
- `P0 · rules` the AI failed, so the deterministic rules' view is shown
- `P1 · default` not assessed yet

**Flags**: ⏸️ session paused automatically, waiting for a person · ⚑ a person must review · 🧪 fault-injection test data

**Next action**: 🔒 means your current role can't do it. Switch roles with *Working as* in the sidebar.

**Stage**: where the case is in the eight-stage workflow. Filter by stage under **Filters**; change the order with the sort menu.
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
            "Title": st.column_config.TextColumn(width=250),
            "Stage · status": st.column_config.TextColumn(width=148, help="Workflow stage 1–8 (Intake, AI enrichment, Triage, Investigation, Containment, Response, Closure, QA) and current status"),
            "Next action": st.column_config.TextColumn(width=186),
            "First review": st.column_config.TextColumn(width=92, help="Time to the first-human-review target (prototype SLA assumptions)"),
            "Owner": st.column_config.TextColumn(width=52),
            "Flags": st.column_config.TextColumn(width=52, help="⏸️ session auto-paused (C7), confirm or lift · ⚑ mandatory human review pending · 🧪 fault-injection test data"),
        })
    sel = event.selection.rows if event and hasattr(event, "selection") else []
    if sel:
        # new table key next time, so returning to the queue does not re-open the same case
        st.session_state["q_nonce"] = st.session_state.get("q_nonce", 0) + 1
        go_case(rows[sel[0]]["ID"])
