from __future__ import annotations

import pandas as pd
import streamlit as st

from common import (alerts, drop_stale, policy_label, policy_with_more, POLICY_STATUS_WORD, SEVERITY_BASIS_WORD, PHASE_HELP, PHASES, STAGES, STATUS_LABEL, STATUS_PHASE, STATUS_STAGE, actor_name, conn,
                    current_actor, go, go_case, phase, relative, stage)
from riskops import monitoring, policies, workflow as wf

VIEWS = ["Needs action", "My cases", "All open", "Closed", "All"]
SORTS = {
    "Most urgent first": lambda x: x["urgency"],
    "Severity (P0 first)": lambda x: ({"P0": 0, "P1": 1, "P2": 2, "P3": 3}[x["effective_severity"]], x["urgency"]),
    "Status (Awaiting triage first)": lambda x: (STATUS_PHASE[x["status"]], STATUS_STAGE[x["status"]], x["urgency"]),
    "Status (Closed first)": lambda x: (-STATUS_PHASE[x["status"]], -STATUS_STAGE[x["status"]], x["urgency"]),
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

    for key, opts in (("q_sort", list(SORTS)), ("q_stage", STAGES), ("q_phase", PHASES), ("q_policy", policies.keys())):
        drop_stale(key, opts)
    head, btn = st.columns([5, 1], vertical_alignment="center")
    head.title("Incident queue")
    if btn.button("＋ New report", type="primary", use_container_width=True):
        go("intake")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Open", len(open_q))
    k2.metric("SLA overdue", sum(x["overdue"] for x in open_q))
    k3.metric("Open P0 / P1", sum(1 for x in open_q if x["effective_severity"] in ("P0", "P1")))
    k4.metric("Awaiting triage", sum(1 for x in open_q if not x["human_severity"]))
    k5.metric("Actions I can take", sum(1 for x in open_q for a in x["next_actions"] if wf.actor_can_do(c, me, a)))

    v, s, f = st.columns([3, 2, 1])
    view = v.segmented_control("View", VIEWS, default="Needs action", key="q_view", label_visibility="collapsed") or "Needs action"
    search = s.text_input("Search", placeholder="Search ID, title, policy code or name", label_visibility="collapsed", key="q_search")
    with f.popover("Filters", use_container_width=True):
        phases = st.multiselect("Status", PHASES, key="q_phase",
                                help=" · ".join(f"{k}: {v}" for k, v in PHASE_HELP.items()))
        sev = st.multiselect("Severity", ["P0", "P1", "P2", "P3"], key="q_sev")
        present = {p for x in q for p in [x["policy"], *x["other_policies"]] if p}
        pol = st.multiselect("Policy", [k for k in policies.keys() if k in present], format_func=policy_label, key="q_policy")
        pol_any = st.checkbox("Also match other policies on the case", key="q_policy_any",
                              help="Off: primary policy only. On: primary or any other policy on the case.")
        owners = sorted({x["owner"] for x in q if x["owner"]})
        owner = st.multiselect("Owner", ["(unassigned)"] + owners, format_func=lambda k: k if k == "(unassigned)" else actor_name(k), key="q_owner")
        review = st.radio("Mandatory review", ["Any", "Flagged", "Not flagged"], horizontal=True, key="q_review")
        overdue_only = st.checkbox("SLA overdue only", key="q_overdue")
        with st.expander("More filters"):
            stages = st.multiselect("Stage", STAGES, key="q_stage",
                                    help="Intake → AI assessment → Triage → Investigation → Containment → Response → Closure → QA review")

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
        if search and search.lower() not in " ".join([x["incident_id"], x["title"], policy_label(x["policy"])]
                                                     + [policy_label(p) for p in x["other_policies"]]).lower():
            return False
        if sev and x["effective_severity"] not in sev:
            return False
        if phases and phase(x["status"]) not in phases:
            return False
        if stages and stage(x["status"]) not in stages:
            return False
        if pol and not set(pol) & ({x["policy"]} | (set(x["other_policies"]) if pol_any else set())):
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
    for x in shown:
        nxt = x["next_actions"][0] if x["next_actions"] else None
        is_open = x["status"] in monitoring.OPEN
        due = ""
        if is_open and not x["human_severity"]:
            due = relative(x["minutes_to_deadline"]).capitalize()
        rows.append({
            "Severity": f"{x['effective_severity']} · {SEVERITY_BASIS_WORD[x['severity_basis']]}",
            "ID": x["incident_id"],
            "Title": x["title"],
            "Code": policies.code(x["policy"]) if x["policy"] else "—",
            "Policy": policy_with_more(x),
            "Policy status": POLICY_STATUS_WORD[x["policy_basis"]],
            "Status": phase(x["status"]),
            "Alerts": " · ".join(alerts(x)),
            "Stage": STATUS_LABEL[x["status"]],
            "Next action": (nxt["title"] + ("" if wf.actor_can_do(c, me, nxt) else f" (needs {wf.who_can_do(nxt)})")) if nxt else "—",
            "First review": due,
            "Owner": actor_name(x["owner"]).split(" —")[0] if x["owner"] else "—",
        })
    cap.caption(f"{len(rows)} case(s) · sorted by {sort_by[0].lower() + sort_by[1:]} · click a row to open it")
    with leg.popover("How to read this", use_container_width=True):
        st.markdown("""
- **Severity**: P0 critical · P1 high · P2 medium · P3 low. *Confirmed* means a person decided; *AI-suggested* means not yet confirmed.
- **Code / Policy**: the policy the case may violate. *+N more* means other policies also match. **Policy status** says whether a person confirmed it.
- **Status**: Awaiting triage → In progress → Closed. **Stage** is the detail.
- **Alerts**: *Paused (C7)* session paused automatically, a specialist must confirm or lift · *SLA overdue* first review is late · *Review required* a person must review before any decision · *Test data* fault-injection test.
- **Next action**: *(needs …)* means another role must do it. Switch roles with *Working as* in the sidebar.
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
            "Severity": st.column_config.TextColumn(width=150, help="P0 critical · P1 high · P2 medium · P3 low. Confirmed = decided by a person; AI-suggested = after safety controls, not yet confirmed."),
            "ID": st.column_config.TextColumn(width=78),
            "Title": st.column_config.TextColumn(width=210),
            "Code": st.column_config.TextColumn(width=62, help="Policy code, e.g. CS-01. See Rules & playbooks → Policies."),
            "Policy": st.column_config.TextColumn(width=200, help="Policy the case may violate. '+N more' = other policies also match this case."),
            "Policy status": st.column_config.TextColumn(width=104, help="Confirmed = a person confirmed the policy; AI-suggested = not yet confirmed."),
            "Status": st.column_config.TextColumn(width=118, help="Awaiting triage · In progress · Closed"),
            "Alerts": st.column_config.TextColumn(width=210, help="Paused (C7): session paused automatically, a specialist must confirm or lift · SLA overdue: first review is late · Review required: a person must review before any decision · Test data: fault-injection test"),
            "Stage": st.column_config.TextColumn(width=200, help="Detail within the status: Intake, AI assessment, Triage, Investigation, Containment, Response, Closure, QA review"),
            "Next action": st.column_config.TextColumn(width=280, help="What the case needs next. '(needs …)' = a different role must do it."),
            "First review": st.column_config.TextColumn(width=120, help="SLA: time to the first human review target (prototype assumptions)"),
            "Owner": st.column_config.TextColumn(width=60),
        })
    sel = event.selection.rows if event and hasattr(event, "selection") else []
    if sel:
        # new table key next time, so returning to the queue does not re-open the same case
        st.session_state["q_nonce"] = st.session_state.get("q_nonce", 0) + 1
        go_case(rows[sel[0]]["ID"])
