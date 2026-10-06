from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from common import (OVERRIDE_DIRECTION, PHASE_HELP, PHASES, STAGES, STATUS_LABEL, STATUS_PHASE, STATUS_STAGE,
                    actor_name, conn, go, go_case, phase, policy_label, pretty, stage, ver, GATE_LABEL, SOURCE_LABEL, SPLIT_NAME)
from riskops import config, monitoring, policies, workflow as wf
from riskops.db import get_setting, rows


SEV_COLORS = {"P0": "#c0392b", "P1": "#e67e22", "P2": "#d4ac0d", "P3": "#95a5a6"}


def _bar(counts: pd.DataFrame, field: str, order: list[str], height: int):
    import altair as alt
    return (alt.Chart(counts).mark_bar()
            .encode(x=alt.X(f"{field}:N", sort=order, scale=alt.Scale(domain=order), title=None,
                            axis=alt.Axis(labelAngle=0, labelLimit=120)),
                    y=alt.Y("sum(Tickets):Q", title="Tickets", axis=alt.Axis(tickMinStep=1)),
                    color=alt.Color("Severity:N", scale=alt.Scale(domain=list(SEV_COLORS), range=list(SEV_COLORS.values())),
                                    legend=alt.Legend(orient="top", title=None)),
                    order=alt.Order("Severity:N", sort="ascending"),
                    tooltip=[field, "Severity", "Tickets"])
            .properties(height=height))


def _status_section() -> None:
    """Tickets by status (three phases), by severity, with filters and a case list. Stage detail is collapsed below."""
    st.subheader("Tickets by status")
    q = monitoring.queue(conn())
    picked = st.pills("Status", PHASES, selection_mode="multi", default=PHASES, key="d_phases",
                      help=" · ".join(f"{k}: {v}" for k, v in PHASE_HELP.items())) or []
    sv, pf = st.columns([2, 3], vertical_alignment="bottom")
    with sv:
        sevs = st.pills("Severity", ["P0", "P1", "P2", "P3"], selection_mode="multi", default=["P0", "P1", "P2", "P3"], key="d_sevs") or []
    present = {x["policy"] for x in q if x["policy"]}
    st.session_state["d_policy"] = [k for k in st.session_state.get("d_policy", []) if k in present]
    pols = pf.multiselect("Policy", [k for k in policies.keys() if k in present], format_func=policy_label, key="d_policy",
                          placeholder="All policies")
    items = [x for x in q if phase(x["status"]) in picked and x["effective_severity"] in sevs and (not pols or x["policy"] in pols)]
    open_items = [x for x in items if x["status"] in monitoring.OPEN]
    k1, k2, k3 = st.columns(3)
    k1.metric("⏸️ Auto-paused (C7)", sum(1 for x in items if x["auto_paused"]), help="Waiting for the Safety specialist or Incident Lead")
    k2.metric("⚠️ SLA overdue", sum(1 for x in open_items if x["overdue"]), help="Open cases past the first-review target")
    k3.metric("Closed · QA pending", sum(1 for x in items if x["status"] == "CLOSED"), help="Closed cases not yet QA reviewed")
    if not items:
        st.info("No tickets match these filters.")
        return
    df = pd.DataFrame([{"Status": phase(x["status"]), "Stage": stage(x["status"]), "Severity": x["effective_severity"]} for x in items])
    by_phase = df.groupby(["Status", "Severity"], as_index=False).size().rename(columns={"size": "Tickets"})
    st.altair_chart(_bar(by_phase, "Status", [p for p in PHASES if p in picked], 240), use_container_width=True)
    with st.expander("Breakdown by stage"):
        by_stage = df.groupby(["Stage", "Severity"], as_index=False).size().rename(columns={"size": "Tickets"})
        st.altair_chart(_bar(by_stage, "Stage", [s for s in STAGES if s in set(df["Stage"])], 240), use_container_width=True)

    table = pd.DataFrame([{
        "ID": x["incident_id"], "Severity": x["effective_severity"] + (" ✓" if x["severity_basis"] == "human" else " · AI"),
        "Status": phase(x["status"]) + (" ⏸️" if x["auto_paused"] else ""), "Stage": STATUS_LABEL[x["status"]],
        "Title": x["title"],
        "Code": (policies.code(x["policy"]) + (" ✓" if x["policy_basis"] == "human" else "")) if x["policy"] else "—",
        "Policy": policy_label(x["policy"], code=False),
        "Age (h)": x["age_hours"], "Owner": actor_name(x["owner"]).split(" —")[0] if x["owner"] else "—",
        "Next action": x["next_actions"][0]["title"] if x["next_actions"] else "—"} for x in sorted(
            items, key=lambda x: (STATUS_PHASE[x["status"]], STATUS_STAGE[x["status"]], {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[x["effective_severity"]]))])
    st.caption(f"{len(table)} ticket(s) · click a column header to sort · click a row to open the case")
    ev = st.dataframe(table, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                      key=f"d_table_{st.session_state.get('d_nonce', 0)}", height=min(36 * (len(table) + 1) + 4, 420),
                      column_config={"Age (h)": st.column_config.NumberColumn(format="%.1f", width=70),
                                     "ID": st.column_config.TextColumn(width=78), "Severity": st.column_config.TextColumn(width=70),
                                     "Title": st.column_config.TextColumn(width=220),
                                     "Code": st.column_config.TextColumn(width=80, help="Policy code. ✓ confirmed by a person"),
                                     "Policy": st.column_config.TextColumn(width=190)})
    sel = ev.selection.rows if ev and hasattr(ev, "selection") else []
    if sel:
        st.session_state["d_nonce"] = st.session_state.get("d_nonce", 0) + 1
        go_case(table.iloc[sel[0]]["ID"])


def _stat(d: dict) -> str:
    return f"median {d['median_min'] / 60:.1f} h · max {d['max_min'] / 60:.1f} h (n={d['n']})" if d["n"] else "no data yet"


def _quality_alerts() -> None:
    c = conn()
    active = get_setting(c, "active_rule_version")
    runs = [json.loads(r["summary_json"]) for r in rows(c, "SELECT summary_json FROM eval_runs ORDER BY created_at")]
    shown = False
    for split in ("held_out", "dev", "all"):
        base = [r for r in runs if r["split"] == split and r["rule_version"] == config.BASELINE_RULE_VERSION and r["system"] == "rules"]
        cand = [r for r in runs if r["split"] == split and r["rule_version"] == active and r["system"] == "rules"]
        if base and cand and active != config.BASELINE_RULE_VERSION:
            chk = monitoring.regression_check(base[-1], cand[-1])
            shown = True
            label = " (simulated degradation: fault-demo rule set)" if "fault" in active else " (synthetic test cases, not production drift)"
            where = f"{SPLIT_NAME[split]} · active Rules {ver(active)} vs baseline Rules {ver(config.BASELINE_RULE_VERSION)}"
            if chk["alert"]:
                st.error(f"**Quality alert · {where}**: "
                         + "; ".join(f"{GATE_LABEL.get(x['metric'], x['metric'])} {x['baseline']:.0%} → {x['candidate']:.0%}" for x in chk["regressions"]) + label)
            else:
                st.success(f"{where}: no regression{label}")
    if not shown:
        st.caption(f"Regression gate: active Rules **{ver(active)}**. No comparison needed, or no comparable runs yet.")


def render() -> None:
    st.title("Operations dashboard")
    st.caption("From the local database. Seeded synthetic history and actions taken in this demo are shown separately. "
               "SLA targets are prototype assumptions.")
    _quality_alerts()
    m = monitoring.ops_metrics(conn())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Open cases", m["queue_volume_open"])
    k2.metric("SLA overdue", m["overdue_open"])
    k3.metric("Awaiting a human decision", m["pending_human_decisions"])
    k4.metric("Median open age", f"{m['open_age_hours']['median_min'] / 60:.1f} h" if m["open_age_hours"]["median_min"] else "—")
    if m["overdue_open"] and st.button("View overdue cases in the queue"):
        st.session_state["q_view"] = "All open"
        st.session_state["q_overdue"] = True
        go("queue")

    _status_section()

    st.subheader("Timeliness")
    s = m["sla"]
    st.dataframe(pd.DataFrame([
        {"Measure": "Report → first human severity decision", "Seeded history": _stat(m["time_to_first_human_review"]["seed"]),
         "This demo": _stat(m["time_to_first_human_review"]["demo"]),
         "SLA breaches": f"{s['first_review_breaches']} of {s['first_review_evaluated']}"},
        {"Measure": "Report → simulated containment approved", "Seeded history": _stat(m["time_to_recorded_simulated_containment"]["seed"]),
         "This demo": _stat(m["time_to_recorded_simulated_containment"]["demo"]),
         "SLA breaches": f"{s['containment_breaches']} of {s['containment_evaluated']}"},
    ]), hide_index=True, use_container_width=True)

    st.subheader("Auto-pause (C7)")
    h = m["auto_hold"]
    st.caption("P0 CBRN and child-safety cases pause the reported session automatically; a person must confirm or lift the pause. "
               "Simulated — nothing is paused in any real system.")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Applied", h["applied"])
    h2.metric("Awaiting a person", h["awaiting_review"], delta=f"{h['awaiting_review_overdue']} overdue" if h["awaiting_review_overdue"] else None,
              delta_color="inverse")
    h3.metric("Confirmed / lifted", f"{h['confirmed']} / {h['lifted']}")
    ls = h["lifted_share_of_reviewed"]
    h4.metric("Lifted share (false-alarm proxy)", f"{ls['value']:.0%}" if ls["value"] is not None else "—",
              help=f"{ls['numerator']} of {ls['denominator']} reviewed pauses were lifted. {h['note']}")

    a, b = st.columns(2)
    with a:
        st.subheader("Human oversight")
        o = m["overrides"]
        st.markdown(f"**{o['overrides']}** of **{o['decisions_with_ai_recommendation']}** decisions overrode the AI recommendation")
        st.dataframe(pd.DataFrame([{"Override reason": wf.OVERRIDE_REASONS.get(k, pretty(k)), "Count": v} for k, v in o["by_reason"].items()]
                                  or [{"Override reason": "none", "Count": 0}]), hide_index=True, use_container_width=True)
        st.caption("Direction: " + (" · ".join(f"{OVERRIDE_DIRECTION.get(k, pretty(k))}: {v}" for k, v in o["by_direction"].items()) or "—"))
        st.metric("Policy changed by a person", o["policy_changed"],
                  help="Decisions where the confirmed policy differs from the AI/rules suggestion. A signal of where policy matching needs work.")
    with b:
        st.subheader("Cases by policy")
        open_only = st.toggle("Open cases only", value=False, key="d_pol_open")
        qq = [x for x in monitoring.queue(conn()) if x["policy"] and (not open_only or x["status"] in monitoring.OPEN)]
        pol_df = pd.DataFrame([{"Policy": policy_label(x["policy"]), "Severity": x["effective_severity"]} for x in qq])
        if pol_df.empty:
            st.info("No cases with a policy yet.")
        else:
            import altair as alt
            counts = pol_df.groupby(["Policy", "Severity"], as_index=False).size().rename(columns={"size": "Cases"})
            order = pol_df["Policy"].value_counts().index.tolist()
            chart = (alt.Chart(counts).mark_bar()
                     .encode(x=alt.X("sum(Cases):Q", axis=alt.Axis(tickMinStep=1, title="Cases")),
                             y=alt.Y("Policy:N", sort=order, title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False)),
                             color=alt.Color("Severity:N", scale=alt.Scale(domain=list(SEV_COLORS), range=list(SEV_COLORS.values())),
                                             legend=alt.Legend(orient="top", title=None)),
                             order=alt.Order("Severity:N", sort="ascending"),
                             tooltip=["Policy", "Severity", "Cases"])
                     .properties(height=40 + 30 * len(order)))
            st.altair_chart(chart, use_container_width=True)
            st.caption("Primary policy per case: confirmed by a person where decided, otherwise the AI/rules suggestion.")

    st.subheader("AI assessment health")
    f1, f2 = st.columns(2)
    with f1:
        st.markdown("**Failures** (routed to manual review)")
        st.dataframe(pd.DataFrame([{"Error": pretty(x["error_kind"]), "Source": SOURCE_LABEL.get(x["provider_kind"], (pretty(x["provider_kind"]),))[0], "Count": x["n"]} for x in m["assessment_failures"]]
                                  or [{"Error": "none", "Source": "", "Count": 0}]), hide_index=True, use_container_width=True)
    with f2:
        st.markdown("**By version**")
        st.dataframe(pd.DataFrame([{"Rules": ver(x["rule_version"]), "Prompt": ver(x["prompt_version"]), "Source": SOURCE_LABEL.get(x["provider_kind"], (pretty(x["provider_kind"]),))[0],
                                    "Assessments": x["n"], "Failed": x["failed"], "Flagged for review": x["flagged"]} for x in m["assessments_by_version"]]),
                     hide_index=True, use_container_width=True)
