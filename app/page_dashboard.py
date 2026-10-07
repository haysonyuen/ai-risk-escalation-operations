"""Operations dashboard. Most urgent information first; each section is a coloured card whose label says
what kind of information it holds (live cases, human decisions, AI performance, synthetic test results)."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from common import (alerts, card, duration, policy_with_more, OVERRIDE_DIRECTION, POLICY_STATUS_WORD, SEVERITY_BASIS_WORD,
                    PHASE_HELP, PHASES, STAGES, STATUS_LABEL, STATUS_PHASE, STATUS_STAGE, actor_name, conn, go, go_case, md, phase,
                    policy_label, pretty, stage, ver, GATE_LABEL, SOURCE_LABEL, SPLIT_NAME)
from riskops import config, monitoring, policies, workflow as wf
from riskops.db import get_setting, rows

SEV_COLORS = {"P0": "#c0392b", "P1": "#e67e22", "P2": "#d4ac0d", "P3": "#95a5a6"}
SEV_NAME = {"P0": "Critical", "P1": "High", "P2": "Medium", "P3": "Low"}
SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _bar(counts: pd.DataFrame, field: str, order: list[str], height: int, horizontal: bool = False):
    import altair as alt
    cat = alt.Y(f"{field}:N", sort=order, title=None, axis=alt.Axis(labelLimit=240, labelOverlap=False)) if horizontal else \
        alt.X(f"{field}:N", sort=order, scale=alt.Scale(domain=order), title=None, axis=alt.Axis(labelAngle=0, labelLimit=120))
    val = alt.X("sum(Tickets):Q", title="Tickets", axis=alt.Axis(tickMinStep=1)) if horizontal else \
        alt.Y("sum(Tickets):Q", title="Tickets", axis=alt.Axis(tickMinStep=1))
    return (alt.Chart(counts).mark_bar()
            .encode(**({"y": cat, "x": val} if horizontal else {"x": cat, "y": val}),
                    color=alt.Color("Severity:N", scale=alt.Scale(domain=list(SEV_COLORS), range=list(SEV_COLORS.values())),
                                    legend=alt.Legend(orient="top", title=None)),
                    order=alt.Order("Severity:N", sort="ascending"),
                    tooltip=[field, "Severity", "Tickets"])
            .properties(height=alt.Step(30) if horizontal else height))


def _open_table(table: pd.DataFrame, key: str, height: int) -> None:
    ev = st.dataframe(table, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                      key=f"{key}_{st.session_state.get(key + '_nonce', 0)}", height=height,
                      column_config={"ID": st.column_config.TextColumn(width=78), "Severity": st.column_config.TextColumn(width=150),
                                     "Title": st.column_config.TextColumn(width=240), "Code": st.column_config.TextColumn(width=62),
                                     "Age (h)": st.column_config.NumberColumn(format="%.1f", width=70)})
    sel = ev.selection.rows if ev and hasattr(ev, "selection") else []
    if sel:
        st.session_state[key + "_nonce"] = st.session_state.get(key + "_nonce", 0) + 1
        go_case(table.iloc[sel[0]]["ID"])


# --------------------------------------------------------------------------- 1. needs attention now

def _attention(q: list[dict]) -> None:
    open_q = [x for x in q if x["status"] in monitoring.OPEN]
    with card("live", "Needs attention now", "attention", "Open cases that are late, paused or waiting for a person, most urgent first."):
        k = st.columns(5)
        k[0].metric("Open cases", len(open_q))
        k[1].metric("SLA overdue", sum(x["overdue"] for x in open_q), help="First human review is past its target (see SLA table below)")
        k[2].metric("Session auto-paused", sum(x["auto_paused"] for x in open_q), help="Waiting for a Safety specialist or the Incident Lead")
        k[3].metric("Awaiting triage", sum(1 for x in open_q if not x["human_severity"]), help="No human severity decision yet")
        k[4].metric("Needs manual triage", sum(1 for x in open_q if x["severity_basis"] == "rules_after_ai_failure"),
                    help="The AI assessment failed; a person must triage from the evidence")
        urgent = [x for x in sorted(open_q, key=lambda x: x["urgency"]) if alerts(x) or not x["human_severity"]][:5]
        if urgent:
            st.markdown("**Most urgent open cases** · click a row to open it")
            _open_table(pd.DataFrame([{
                "ID": x["incident_id"], "Severity": f"{x['effective_severity']} · {SEVERITY_BASIS_WORD[x['severity_basis']]}",
                "Title": x["title"], "Alerts": " · ".join(alerts(x)) or "—",
                "Next action": x["next_actions"][0]["title"] if x["next_actions"] else "—"} for x in urgent]),
                "d_urgent", 36 * (len(urgent) + 1) + 4)
        if st.button("Open the full queue →"):
            go("queue")


# --------------------------------------------------------------------------- 2. SLA

def _sla() -> None:
    tl = monitoring.timeliness_by_severity(conn())
    with card("live", "Timeliness against SLA targets", "sla",
              "How quickly a person makes the first severity decision, per severity. Targets are prototype assumptions (config/sla.json)."):
        md("<div class='small' style='margin-bottom:6px'><b>SLA legend</b> (first human review): "
           + " &nbsp; ".join(f"<span class='badge b-{t['severity'].lower()}'>{t['severity']} {SEV_NAME[t['severity']]} · "
                             f"{duration(t['first_target_min'])}</span>" for t in tl) + "</div>")
        rows_ = []
        for t in tl:
            rows_.append({
                "Severity": f"{t['severity']} · {SEV_NAME[t['severity']]}",
                "First review target": duration(t["first_target_min"]),
                "Decided on time": f"{t['met']} of {t['reviewed']}" + (f" ({t['met'] / t['reviewed']:.0%})" if t["reviewed"] else ""),
                "Typical time to decide": duration(t["median_min"]) if t["reviewed"] else "—",
                "Slowest": duration(t["max_min"]) if t["reviewed"] else "—",
                "Open · overdue": t["open_overdue"],
                "Open · within target": t["open_waiting"],
                "Containment target": duration(t["containment_target_min"]) if t["containment_target_min"] else "not set",
                "Contained on time": f"{t['contained_met']} of {t['contained']}" if t["contained"] else "—",
            })
        df = pd.DataFrame(rows_)
        styled = df.style.map(lambda v: "color:#9b1111;font-weight:700" if isinstance(v, int) and v > 0 else "", subset=["Open · overdue"])
        st.dataframe(styled, hide_index=True, use_container_width=True, column_config={
            "Typical time to decide": st.column_config.TextColumn(help="Median time from report to the first human severity decision"),
            "Decided on time": st.column_config.TextColumn(help="Cases with a human decision made within the first-review target"),
            "Containment target": st.column_config.TextColumn(help="Target time from report to approved (simulated) containment, where one applies"),
        })


# --------------------------------------------------------------------------- 3. workload

def _workload(q: list[dict]) -> None:
    with card("live", "Workload", "workload", "Where cases are, by status and policy. The filters drive both charts and the list."):
        f1, f2, f3 = st.columns([3, 2, 3], vertical_alignment="bottom")
        with f1:
            picked = st.pills("Status", PHASES, selection_mode="multi", default=PHASES, key="d_phases",
                              help=" · ".join(f"{k}: {v}" for k, v in PHASE_HELP.items())) or []
        with f2:
            sevs = st.pills("Severity", ["P0", "P1", "P2", "P3"], selection_mode="multi", default=["P0", "P1", "P2", "P3"], key="d_sevs") or []
        present = {x["policy"] for x in q if x["policy"]}
        st.session_state["d_policy"] = [k for k in st.session_state.get("d_policy", []) if k in present]
        pols = f3.multiselect("Policy", [k for k in policies.keys() if k in present], format_func=policy_label, key="d_policy",
                              placeholder="All policies")
        items = [x for x in q if phase(x["status"]) in picked and x["effective_severity"] in sevs and (not pols or x["policy"] in pols)]
        if not items:
            st.info("No cases match these filters.")
            return
        df = pd.DataFrame([{"Status": phase(x["status"]), "Stage": stage(x["status"]), "Severity": x["effective_severity"],
                            "Policy": policy_label(x["policy"]) if x["policy"] else "Not assessed"} for x in items])
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown("**By status**")
            by_phase = df.groupby(["Status", "Severity"], as_index=False).size().rename(columns={"size": "Tickets"})
            st.altair_chart(_bar(by_phase, "Status", [p for p in PHASES if p in picked], 250), use_container_width=True)
        with c2:
            st.markdown("**By policy**")
            by_pol = df.groupby(["Policy", "Severity"], as_index=False).size().rename(columns={"size": "Tickets"})
            order = df["Policy"].value_counts().index.tolist()
            st.altair_chart(_bar(by_pol, "Policy", order, 0, horizontal=True), use_container_width=True)
        with st.expander("Breakdown by stage"):
            by_stage = df.groupby(["Stage", "Severity"], as_index=False).size().rename(columns={"size": "Tickets"})
            st.altair_chart(_bar(by_stage, "Stage", [s for s in STAGES if s in set(df["Stage"])], 240), use_container_width=True)
        with st.expander(f"Case list ({len(items)})", expanded=False):
            table = pd.DataFrame([{
                "ID": x["incident_id"], "Severity": f"{x['effective_severity']} · {SEVERITY_BASIS_WORD[x['severity_basis']]}",
                "Status": phase(x["status"]), "Alerts": " · ".join(alerts(x)), "Stage": STATUS_LABEL[x["status"]], "Title": x["title"],
                "Code": policies.code(x["policy"]) if x["policy"] else "—", "Policy": policy_with_more(x),
                "Policy status": POLICY_STATUS_WORD[x["policy_basis"]], "Age (h)": x["age_hours"],
                "Owner": actor_name(x["owner"]).split(" —")[0] if x["owner"] else "—"}
                for x in sorted(items, key=lambda x: (STATUS_PHASE[x["status"]], STATUS_STAGE[x["status"]], SEV_ORDER[x["effective_severity"]]))])
            st.caption("Click a column header to sort · click a row to open the case")
            _open_table(table, "d_table", min(36 * (len(table) + 1) + 4, 420))


# --------------------------------------------------------------------------- 4. human decisions

def _human(m: dict) -> None:
    with card("human", "Human oversight", "human", "What people decided about the AI's suggestions and the system's automatic pauses."):
        a, b = st.columns(2, gap="large")
        with a:
            o = m["overrides"]
            st.markdown("**Decisions vs. the AI recommendation**")
            k1, k2 = st.columns(2)
            k1.metric("Overrode the AI", f"{o['overrides']} of {o['decisions_with_ai_recommendation']}",
                      help="Human severity / route / policy decisions that differed from the AI recommendation")
            k2.metric("Policy changed by a person", o["policy_changed"],
                      help="Decisions where the confirmed policy differs from the AI/rules suggestion")
            st.dataframe(pd.DataFrame([{"Override reason": wf.OVERRIDE_REASONS.get(k, pretty(k)), "Count": v} for k, v in o["by_reason"].items()]
                                      or [{"Override reason": "none yet", "Count": 0}]), hide_index=True, use_container_width=True)
            st.caption("Direction: " + (" · ".join(f"{OVERRIDE_DIRECTION.get(k, pretty(k))}: {v}" for k, v in o["by_direction"].items()) or "—"))
        with b:
            h = m["auto_hold"]
            st.markdown("**Automatic session pauses** (simulated)")
            k1, k2 = st.columns(2)
            k1.metric("Applied", h["applied"])
            k2.metric("Awaiting a person", h["awaiting_review"],
                      delta=f"{h['awaiting_review_overdue']} overdue" if h["awaiting_review_overdue"] else None, delta_color="inverse")
            k3, k4 = st.columns(2)
            k3.metric("Confirmed / lifted", f"{h['confirmed']} / {h['lifted']}")
            ls = h["lifted_share_of_reviewed"]
            k4.metric("Lifted (false alarms)", f"{ls['value']:.0%}" if ls["value"] is not None else "—",
                      help=f"{ls['numerator']} of {ls['denominator']} reviewed pauses were lifted. {h['note']}")
            st.caption(f"P0 CBRN and child-safety cases pause the reported session automatically; a person must confirm or lift it "
                       f"within {duration(config.sla_config()['auto_hold_review_minutes'])}.")


# --------------------------------------------------------------------------- 5. AI performance + tests

def _ai(m: dict) -> None:
    with card("ai", "AI assessment health", "ai", "Whether the AI assessments ran, and which versions produced them."):
        f1, f2 = st.columns(2, gap="large")
        with f1:
            st.markdown("**Failures** (each routed to manual triage)")
            st.dataframe(pd.DataFrame([{"Error": pretty(x["error_kind"]), "Source": SOURCE_LABEL.get(x["provider_kind"], (pretty(x["provider_kind"]),))[0],
                                        "Count": x["n"]} for x in m["assessment_failures"]] or [{"Error": "none", "Source": "", "Count": 0}]),
                         hide_index=True, use_container_width=True)
        with f2:
            st.markdown("**By version**")
            st.dataframe(pd.DataFrame([{"Rules": ver(x["rule_version"]), "Prompt": ver(x["prompt_version"]),
                                        "Source": SOURCE_LABEL.get(x["provider_kind"], (pretty(x["provider_kind"]),))[0],
                                        "Assessments": x["n"], "Failed": x["failed"], "Flagged for review": x["flagged"]}
                                       for x in m["assessments_by_version"]]), hide_index=True, use_container_width=True)


def _quality_alerts() -> None:
    c = conn()
    active = get_setting(c, "active_rule_version")
    runs = [json.loads(r["summary_json"]) for r in rows(c, "SELECT summary_json FROM eval_runs ORDER BY created_at")]
    with card("test", "Rules regression check", "regress", "Active rules compared with the baseline on the synthetic test cases. Details on the Quality page."):
        shown = False
        for split in ("held_out", "dev", "all"):
            base = [r for r in runs if r["split"] == split and r["rule_version"] == config.BASELINE_RULE_VERSION and r["system"] == "rules"]
            cand = [r for r in runs if r["split"] == split and r["rule_version"] == active and r["system"] == "rules"]
            if base and cand and active != config.BASELINE_RULE_VERSION:
                chk = monitoring.regression_check(base[-1], cand[-1])
                shown = True
                label = " (simulated degradation: fault-demo rule set)" if "fault" in active else ""
                where = f"{SPLIT_NAME[split]} · Rules {ver(active)} vs baseline {ver(config.BASELINE_RULE_VERSION)}"
                if chk["alert"]:
                    st.error(f"**Regression · {where}**: "
                             + "; ".join(f"{GATE_LABEL.get(x['metric'], x['metric'])} {x['baseline']:.0%} → {x['candidate']:.0%}" for x in chk["regressions"]) + label)
                else:
                    st.success(f"{where}: no regression{label}")
        if not shown:
            st.caption(f"Active Rules **{ver(active)}** is the baseline, or no comparable runs exist yet. Nothing to compare.")


# --------------------------------------------------------------------------- page

def render() -> None:
    st.title("Operations dashboard")
    st.caption("Synthetic demo data. Seeded history plus actions taken in this demo. SLA targets are prototype assumptions.")
    q = monitoring.queue(conn())
    m = monitoring.ops_metrics(conn())
    _attention(q)
    _sla()
    _workload(q)
    _human(m)
    _ai(m)
    _quality_alerts()
