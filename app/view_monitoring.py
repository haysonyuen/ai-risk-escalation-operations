from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from common import conn
from riskops import config, monitoring
from riskops.db import get_setting, rows


def _stat(d: dict) -> str:
    return f"n={d['n']}, median {d['median_min']} min, max {d['max_min']} min" if d["n"] else "n=0 (no data)"


def render() -> None:
    st.title("Operational monitoring")
    st.caption("Computed from the local database. 'seed' = synthetic historical timestamps created by the seed script; "
               "'demo' = actions performed in this app. SLA targets are prototype assumptions (config/sla.json).")
    m = monitoring.ops_metrics(conn())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open incidents", m["queue_volume_open"])
    c2.metric("Overdue first review", m["overdue_open"])
    c3.metric("Open with pending human decision", m["pending_human_decisions"])
    c4.metric("Median open age (h)", round(m["open_age_hours"]["median_min"] / 60, 1) if m["open_age_hours"]["median_min"] else "—")
    st.markdown("**Queue by status**")
    st.dataframe(pd.DataFrame([m["queue_by_status"]]), use_container_width=True, hide_index=True)

    st.markdown("**Timeliness**")
    st.dataframe(pd.DataFrame([
        {"measure": "Time to first human severity decision", "seeded history": _stat(m["time_to_first_human_review"]["seed"]),
         "this demo": _stat(m["time_to_first_human_review"]["demo"])},
        {"measure": "Time to recorded (simulated) containment approval", "seeded history": _stat(m["time_to_recorded_simulated_containment"]["seed"]),
         "this demo": _stat(m["time_to_recorded_simulated_containment"]["demo"])},
    ]), use_container_width=True, hide_index=True)
    s = m["sla"]
    st.caption(f"SLA breaches (prototype targets): first review {s['first_review_breaches']}/{s['first_review_evaluated']} decided cases; "
               f"containment {s['containment_breaches']}/{s['containment_evaluated']} cases with containment. Demo-session times measure clicks in a prototype, not operational performance.")

    a, b = st.columns(2)
    with a:
        st.markdown("**Human overrides of AI recommendations**")
        o = m["overrides"]
        st.write(f"{o['overrides']} overrides / {o['decisions_with_ai_recommendation']} decisions with an AI recommendation")
        st.dataframe(pd.DataFrame([{"reason": k, "count": v} for k, v in o["by_reason"].items()] or [{"reason": "none", "count": 0}]), hide_index=True, use_container_width=True)
        st.markdown("**Assessment failures**")
        st.dataframe(pd.DataFrame(m["assessment_failures"] or [{"error_kind": "none", "provider_kind": "", "n": 0}]), hide_index=True, use_container_width=True)
    with b:
        st.markdown("**Recurring issue categories — COUNTS only**")
        st.caption("No exposure denominator (active users / tool usage) exists in this prototype, so no recurrence *rates* are reported.")
        st.dataframe(pd.DataFrame(sorted(m["category_counts"].items(), key=lambda x: -x[1]), columns=["category", "incident count"]), hide_index=True, use_container_width=True)
        st.caption(f"Confirmed links: {m['confirmed_links'] or 'none'}")
    st.markdown("**Assessments by prompt / rule / provider version**")
    st.dataframe(pd.DataFrame(m["assessments_by_version"]), hide_index=True, use_container_width=True)

    st.markdown("**Quality alerts (from evaluation runs on synthetic data)**")
    active = get_setting(conn(), "active_rule_version")
    runs = [json.loads(r["summary_json"]) for r in rows(conn(), "SELECT summary_json FROM eval_runs ORDER BY created_at")]
    shown = False
    for split in ("held_out", "dev", "all"):
        base = [r for r in runs if r["split"] == split and r["rule_version"] == "rules-v1.0" and r["system"] == "rules"]
        cand = [r for r in runs if r["split"] == split and r["rule_version"] == active and r["system"] == "rules"]
        if base and cand and active != "rules-v1.0":
            chk = monitoring.regression_check(base[-1], cand[-1])
            shown = True
            fault = "fault" in active
            msg = f"[{split}] {base[-1]['rule_version']} → {active}: "
            if chk["alert"]:
                st.error(msg + "REGRESSION — " + "; ".join(f"{x['metric']} {x['baseline']:.1%} → {x['candidate']:.1%}" for x in chk["regressions"])
                         + (" · SIMULATED DEGRADATION (fault-injection rule set)" if fault else " · observed on synthetic evaluation data, not production drift"))
            else:
                st.success(msg + "no gated metric regressed")
    if not shown:
        st.caption(f"No comparable runs for the active version ({active}) vs rules-v1.0. Use Rules & playbooks → Change rules + regression check.")
