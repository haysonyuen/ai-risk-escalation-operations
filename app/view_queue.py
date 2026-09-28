from __future__ import annotations

import pandas as pd
import streamlit as st

from common import conn, md, source_badge, sev_badge
from riskops import monitoring, workflow as wf


def render() -> None:
    st.title("Incident queue")
    st.caption("AI recommendations and human decisions are shown in separate columns. "
               "'Effective' severity = human decision if recorded, otherwise the AI recommendation after deterministic controls. "
               "Deadlines use prototype SLA assumptions (config/sla.json).")
    q = monitoring.queue(conn())
    wf.expire_due_containment(conn())
    open_q = [x for x in q if x["status"] in monitoring.OPEN]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open incidents", len(open_q))
    c2.metric("Overdue first human review", sum(x["overdue"] for x in open_q))
    c3.metric("Pending human decisions", sum(1 for x in open_q if x["pending"]))
    c4.metric("Awaiting severity decision", sum(1 for x in open_q if "severity decision" in x["pending"]))

    with st.expander("Filters", expanded=True):
        f1, f2, f3 = st.columns(3)
        sev = f1.multiselect("Effective severity", ["P0", "P1", "P2", "P3"])
        status = f2.multiselect("Status", wf.STATUSES)
        cats = sorted({c for x in q for c in x["categories"]})
        cat = f3.multiselect("Category", cats)
        f4, f5, f6, f7 = st.columns(4)
        owners = sorted({x["owner"] for x in q if x["owner"]})
        owner = f4.multiselect("Owner", ["(unassigned)"] + owners)
        review = f5.selectbox("Review requirement", ["Any", "Mandatory review flagged", "No mandatory flag"])
        pending_only = f6.checkbox("Pending human decision only")
        overdue_only = f7.checkbox("Overdue only")
        hide_closed = st.checkbox("Hide closed / QA-reviewed", value=False)

    rows = []
    for x in q:
        if sev and x["effective_severity"] not in sev:
            continue
        if status and x["status"] not in status:
            continue
        if cat and not set(cat) & set(x["categories"]):
            continue
        if owner and (x["owner"] or "(unassigned)") not in owner:
            continue
        if review == "Mandatory review flagged" and not x["mandatory_review"]:
            continue
        if review == "No mandatory flag" and x["mandatory_review"]:
            continue
        if pending_only and not x["pending"]:
            continue
        if overdue_only and not x["overdue"]:
            continue
        if hide_closed and x["status"] not in monitoring.OPEN:
            continue
        ai_src = {"offline_fixture": "fixture", "offline_simulation": "simulation", "live_model": "LIVE model",
                  "fault_injection": "FAULT-INJ", "none": "—"}.get(x["ai_source"], x["ai_source"])
        ai = x["ai_severity"] or "—"
        if x["ai_status"] == "failed":
            ai = f"{ai} (rules fallback; AI failed)"
        rows.append({
            "ID": x["incident_id"], "Title": x["title"], "Stage": wf.STAGE[x["status"]],
            "AI rec. (after controls)": ai, "AI source": ai_src,
            "Human decision": x["human_severity"] or "pending",
            "Effective": f"{x['effective_severity']} ({x['severity_basis'].replace('_', ' ')})",
            "Mandatory review": "yes" if x["mandatory_review"] else "",
            "Review deadline (UTC)": x["review_deadline"], "Overdue": "OVERDUE" if x["overdue"] else "",
            "Pending": ", ".join(x["pending"]), "Owner": x["owner"] or "(unassigned)",
            "Age h": x["age_hours"], "Categories": ", ".join(x["categories"]), "Data origin": x["origin"],
        })
    st.caption(f"{len(rows)} of {len(q)} incidents shown")
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True, height=min(38 * (len(rows) + 1), 520))
        pick = st.selectbox("Open in workspace", [r["ID"] for r in rows], key="queue_pick")
        if st.button("Open incident"):
            st.session_state["selected_incident"] = pick
            st.session_state["nav_to"] = "Incident workspace"
            st.rerun()
    st.divider()
    md("Legend: " + source_badge("offline_fixture") + source_badge("offline_simulation") + source_badge("live_model")
       + source_badge("fault_injection") + sev_badge("P0") + sev_badge("P1") + sev_badge("P2") + sev_badge("P3"))
