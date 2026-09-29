from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from common import CATEGORY_LABEL, conn, go, pretty
from riskops import config, monitoring
from riskops.db import get_setting, rows


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
            label = " (simulated degradation — fault-injection rule set)" if "fault" in active else " (synthetic evaluation data, not production drift)"
            if chk["alert"]:
                st.error(f"**Quality alert · {pretty(split)} split** — active rules {active} vs baseline {config.BASELINE_RULE_VERSION}: "
                         + "; ".join(f"{x['metric']} {x['baseline']:.0%} → {x['candidate']:.0%}" for x in chk["regressions"]) + label)
            else:
                st.success(f"{pretty(split)} split: active rules {active} show no regression vs {config.BASELINE_RULE_VERSION}{label}")
    if not shown:
        st.caption(f"Quality gate: active rules **{active}** — no comparison needed or no comparable runs yet.")


def render() -> None:
    st.title("Operations dashboard")
    st.caption("From the local database. Seeded synthetic history and actions taken in this demo are shown separately. "
               "SLA targets are prototype assumptions.")
    _quality_alerts()
    m = monitoring.ops_metrics(conn())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Open cases", m["queue_volume_open"])
    k2.metric("Overdue first review", m["overdue_open"])
    k3.metric("Waiting on a human decision", m["pending_human_decisions"])
    k4.metric("Median open age", f"{m['open_age_hours']['median_min'] / 60:.1f} h" if m["open_age_hours"]["median_min"] else "—")
    if m["overdue_open"] and st.button("View overdue cases in the queue"):
        st.session_state["q_view"] = "All open"
        st.session_state["q_overdue"] = True
        go("queue")

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

    st.subheader("Automatic pauses (C7)")
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
        st.dataframe(pd.DataFrame([{"Override reason": pretty(k), "Count": v} for k, v in o["by_reason"].items()] or [{"Override reason": "none", "Count": 0}]),
                     hide_index=True, use_container_width=True)
        st.caption("Direction: " + (", ".join(f"{k} {v}" for k, v in o["by_direction"].items()) or "—"))
    with b:
        st.subheader("Issue categories")
        st.caption("Counts only — there is no usage denominator, so no recurrence rates.")
        st.dataframe(pd.DataFrame([{"Category": CATEGORY_LABEL.get(k, k), "Cases": v} for k, v in sorted(m["category_counts"].items(), key=lambda x: -x[1])]),
                     hide_index=True, use_container_width=True)

    st.subheader("AI assessment health")
    f1, f2 = st.columns(2)
    with f1:
        st.markdown("**Failures** (routed to manual review)")
        st.dataframe(pd.DataFrame([{"Error": pretty(x["error_kind"]), "Source": pretty(x["provider_kind"]), "Count": x["n"]} for x in m["assessment_failures"]]
                                  or [{"Error": "none", "Source": "", "Count": 0}]), hide_index=True, use_container_width=True)
    with f2:
        st.markdown("**By version**")
        st.dataframe(pd.DataFrame([{"Rules": x["rule_version"], "Prompt": x["prompt_version"], "Source": pretty(x["provider_kind"]),
                                    "Assessments": x["n"], "Failed": x["failed"], "Flagged for review": x["flagged"]} for x in m["assessments_by_version"]]),
                     hide_index=True, use_container_width=True)
