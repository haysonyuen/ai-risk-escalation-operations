from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from common import section, badge, conn, flash, md, run_action
from riskops import config, evaluation, monitoring, workflow as wf
from riskops.db import rows
from riskops.rules import available_versions

KIND_BADGE = {"rules_only_baseline": ("Rules-only baseline (deterministic)", "b-rules"),
              "live_model": ("LIVE model run", "b-live"), "fault_injection": ("FAULT INJECTION test", "b-fault")}


def fmt(m: dict) -> str:
    return evaluation._fmt(m)


def _runs() -> list[dict]:
    out = []
    for r in rows(conn(), "SELECT * FROM eval_runs ORDER BY created_at DESC"):
        s = json.loads(r["summary_json"])
        s["_origin"] = r["origin"]
        out.append(s)
    return out


def _show_run(s: dict) -> None:
    t, cls = KIND_BADGE[s["evaluation_kind"]]
    md(badge(t, cls) + badge(f"rules {s['rule_version']}", "b-muted") + badge(f"controls {s.get('controls_version', 'controls-v1.0')}", "b-muted")
       + badge(f"split {s['split']}", "b-muted") + badge(f"n={s['metrics']['n_cases']}", "b-muted"))
    st.caption(s["interpretation"] + " " + s["labels_disclaimer"])
    hi = s["held_out_integrity"]
    if s["split"] in ("held_out", "all"):
        st.caption(f"Held-out integrity: matches freeze = {hi['matches_freeze']}; status = {hi['status']}; {len(hi['disclosures'])} disclosure(s) in data/eval/FREEZE.json")
    m = s["metrics"]
    a, b = m["after_deterministic_controls"], m["recommendation_before_controls"]
    tbl = []
    for k, label in [("within_acceptable_range", "Severity within acceptable range"), ("exact_match", "Severity exact match"),
                     ("p0p1_precision", "P0/P1 precision"), ("p0p1_recall", "P0/P1 recall")]:
        tbl.append({"Metric": label, "Provider recommendation (valid only)": fmt(b[k]), "After deterministic controls (all)": fmt(a[k])})
    tbl += [{"Metric": "Primary route acceptable", "Provider recommendation (valid only)": "", "After deterministic controls (all)": fmt(m["routing"]["primary_route_acceptable"])},
            {"Metric": "Mandatory review flagged when required", "Provider recommendation (valid only)": "", "After deterministic controls (all)": fmt(m["mandatory_review"]["compliance_flagged_when_required"])},
            {"Metric": "Review flagged when not required", "Provider recommendation (valid only)": "", "After deterministic controls (all)": fmt(m["mandatory_review"]["flagged_when_not_required"])},
            {"Metric": "Schema-valid assessments", "Provider recommendation (valid only)": fmt(m["schema_valid_rate"]), "After deterministic controls (all)": ""},
            {"Metric": "Facts with invalid evidence refs", "Provider recommendation (valid only)": fmt(m["invalid_evidence_reference_rate_by_fact"]), "After deterministic controls (all)": ""},
            {"Metric": "Claim-support accuracy", "Provider recommendation (valid only)": "not reported (0 human reviews)", "After deterministic controls (all)": ""},
            {"Metric": "Latency / cost", "Provider recommendation (valid only)": f"mean {m['latency_ms']['mean']:.2f} ms" if m['latency_ms']['mean'] is not None else "n/a",
             "After deterministic controls (all)": f"${m['cost_usd_estimate']['total']:.4f}" if m['cost_usd_estimate']['total'] else "no cost (offline)"}]
    st.dataframe(pd.DataFrame(tbl), use_container_width=True, hide_index=True)
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("**Confusion matrix after controls** (rows expected, cols predicted)")
        cm = a["confusion_matrix_expected_rows_predicted_cols"]
        st.dataframe(pd.DataFrame(cm).T[["P0", "P1", "P2", "P3", "none"]], use_container_width=True)
    with c2:
        st.markdown("**By scenario category**")
        st.dataframe(pd.DataFrame([{"category": k, "n": v["n"], "severity in range": fmt(v["severity_within_range_after_controls"]),
                                    "route acceptable": fmt(v["route_acceptable_after_controls"]),
                                    "review flagged when required": fmt(v["mandatory_review_flagged_when_required"])}
                                   for k, v in m["by_category"].items()]), use_container_width=True, hide_index=True)
    st.markdown(f"**Failures ({len(s['failures'])})** — severity outside range, unacceptable route, missed mandatory review, or failed assessment")
    if s["failures"]:
        st.dataframe(pd.DataFrame([{k: (", ".join(v) if isinstance(v, list) else v) for k, v in f.items()} for f in s["failures"]]),
                     use_container_width=True, hide_index=True)
    if s.get("artifact_dir") and Path(s["artifact_dir"]).exists():
        st.caption(f"Artifacts: {s['artifact_dir']}")
        w = Path(s["artifact_dir"]) / "claim_review_worksheet.csv"
        if w.exists():
            st.download_button("Download claim-support review worksheet (blank verdict column)", w.read_bytes(), file_name=f"{s['run_id']}_claims.csv")


def render() -> None:
    st.title("Quality & evaluation")
    st.warning("All results come from ~80 SYNTHETIC cases with PROVISIONAL author labels. Offline runs evaluate deterministic rules "
               "and controls, not model quality. No live-model evaluation has been run (no API key in this environment); "
               "that remains pending. Nothing here measures real-world harm reduction or production reliability.")
    runs = _runs()
    _labels = ["Evaluation runs", "Compare versions", "Run an evaluation", "Overrides & claim reviews"]
    sec = section(_labels, key="q_section")
    if sec == _labels[0]:
        if not runs:
            st.info("No runs recorded yet.")
        else:
            labels = {s["run_id"]: f"{s['created_at']} · {KIND_BADGE[s['evaluation_kind']][0]} · {s['rule_version']} · {s['split']}" for s in runs}
            pick = st.selectbox("Run", list(labels), format_func=labels.get)
            _show_run(next(s for s in runs if s["run_id"] == pick))
    elif sec == _labels[1]:
        if len(runs) < 2:
            st.info("Need at least two runs.")
        else:
            labels = {s["run_id"]: f"{KIND_BADGE[s['evaluation_kind']][0]} · {s['rule_version']} · {s['split']} · {s['created_at']}" for s in runs}
            chosen = st.multiselect("Runs to compare (same split recommended)", list(labels), format_func=labels.get,
                                    default=list(labels)[:2])
            if chosen:
                st.markdown(evaluation.compare([next(s for s in runs if s["run_id"] == r) for r in chosen]))
            if len(chosen) == 2:
                s1, s2 = [next(s for s in runs if s["run_id"] == r) for r in chosen]
                if s1["split"] == s2["split"]:
                    base, cand = sorted([s1, s2], key=lambda s: s["created_at"])
                    chk = monitoring.regression_check(base, cand)
                    (st.error if chk["alert"] else st.success)(
                        f"Regression gate ({base['rule_version']} → {cand['rule_version']}): "
                        + ("REGRESSION: " + "; ".join(f"{r['metric']} {r['baseline']:.1%} → {r['candidate']:.1%}" for r in chk["regressions"])
                           if chk["alert"] else "no gated metric regressed"))
                    st.caption(chk["label"])
                    if chk["newly_failing_cases"]:
                        st.markdown("Newly failing cases:")
                        st.dataframe(pd.DataFrame([{k: (", ".join(v) if isinstance(v, list) else v) for k, v in f.items()} for f in chk["newly_failing_cases"]]),
                                     use_container_width=True, hide_index=True)
    elif sec == _labels[2]:
        st.markdown("Runs the same harness as `python -m riskops.cli eval`. Artifacts are written to `evaluation/results/`.")
        a, b, c = st.columns(3)
        system = a.selectbox("System", ["rules", "live"] + [f"fault:{m}" for m in ["under_severity", "invalid_evidence_refs", "malformed_json", "timeout", "obeys_embedded_instructions"]])
        version = b.selectbox("Rule version", available_versions())
        split = c.selectbox("Split", ["dev", "held_out", "all"])
        if split == "held_out":
            st.caption("The held-out split was frozen before tuning. Do not change rules based on held-out failures without recording a disclosure in data/eval/FREEZE.json.")
        if system == "live" and not config.live_credentials_available():
            st.error("Live evaluation is pending: ANTHROPIC_API_KEY is not set. It will not fall back to offline results. Run later with:")
            st.code("export ANTHROPIC_API_KEY=...\npython -m riskops.cli eval --system live --rules rules-v1.1 --prompt prompt-v2 --split dev --record-in-db")
        if st.button("Run evaluation"):
            def go():
                s = evaluation.run_eval(system, version, "prompt-v2", split, out_dir=config.RESULTS_DIR / "ui_runs")
                wf.record_eval_run(conn(), s, origin="demo")
                return s["run_id"]
            try:
                with st.spinner("Evaluating…"):
                    rid = go()
                flash("success", f"Run recorded: {rid}")
            except evaluation.LiveEvaluationUnavailable as e:
                flash("error", str(e))
            st.rerun()
    elif sec == _labels[3]:
        om = monitoring.ops_metrics(conn())["overrides"]
        st.markdown(f"**Reviewer overrides** (local demo DB): {om['overrides']} of {om['decisions_with_ai_recommendation']} human decisions that had an AI recommendation"
                    + (f" ({om['override_rate']:.0%})" if om["override_rate"] is not None else ""))
        st.dataframe(pd.DataFrame([{"reason": wf.OVERRIDE_REASONS.get(k, k), "count": v} for k, v in om["by_reason"].items()] or [{"reason": "none", "count": 0}]),
                     use_container_width=True, hide_index=True)
        st.caption(f"By direction: {om['by_direction']}. Counts come from seeded and demo actions in this local database, not from a user study.")
        cr = rows(conn(), "SELECT verdict, COUNT(*) n FROM claim_reviews GROUP BY verdict")
        st.markdown("**Claim-support reviews recorded in the app** (only reviewed facts are counted; nothing is inferred)")
        st.dataframe(pd.DataFrame(cr or [{"verdict": "none recorded", "n": 0}]), use_container_width=True, hide_index=True)
        st.markdown("**Limitations**")
        st.markdown("""
- Cases and labels are synthetic and author-labeled; labels are provisional, not independently validated.
- Offline "AI" outputs are hand-authored fixtures or a deterministic restatement of rules — not measured model performance.
- The dev split was used to write rules-v1.1, so dev results for v1.1 are optimistic by construction.
- Containment and communications are simulated; there is no integration with real systems.
- Roles are simulated identities; there is no authentication.
- Monitoring numbers come from seeded synthetic history plus local demo clicks.
""")
