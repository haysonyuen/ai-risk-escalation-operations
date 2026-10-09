from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from common import (card, GATE_LABEL, GLOSSARY, OVERRIDE_DIRECTION, SPLIT_HELP, SPLIT_NAME, conn, flash, public_demo, section, ver)
import view_jev
from riskops import config, evaluation, monitoring, workflow as wf
from riskops.db import get_setting, rows
from riskops.rules import available_versions

FAULT_LABEL = {
    "under_severity": "AI under-calls severity", "timeout": "AI times out", "unavailable": "AI unavailable",
    "malformed_json": "AI returns malformed output", "schema_violation": "AI output breaks the schema",
    "invalid_evidence_refs": "AI cites evidence that doesn't exist",
    "obeys_embedded_instructions": "AI follows instructions hidden in the report",
}
RULES_LABEL = {"rules-v2.0": "Rules v2.0 (baseline)", "rules-v2.1": "Rules v2.1 (tuned)",
               "rules-v2.1-fault-demo": "Rules v2.1 fault demo (deliberately broken)"}
PROBLEM_LABEL = {"severity_outside_range": "Severity outside range", "route_not_acceptable": "Wrong route",
                 "missed_mandatory_review": "Missed mandatory review", "assessment_failed": "AI assessment failed",
                 "auto_pause_missed": "Auto-pause missed", "auto_pause_unwarranted": "Unwarranted auto-pause"}
VERDICT_LABEL = {"supported": "Supported", "partially_supported": "Partly supported", "unsupported": "Unsupported",
                 "cannot_determine": "Can't tell"}
TABS = ["Results", "Compare versions", "Run evaluation", "Human overrides", "About & glossary"]
PURPOSE = {
    "Results": "How one evaluation run scored.",
    "Compare versions": "Did a rules change improve or regress results?",
    "Run evaluation": "Run a rules version against the test cases.",
    "Human overrides": "Where people overrode the AI, and why.",
    "About & glossary": "Caveats, limitations and what the terms mean.",
}


# --------------------------------------------------------------------------- helpers

def fmt(m: dict | None) -> str:
    """'16 / 16 (100%)'; 'n/a' when undefined (e.g. no case needed it)."""
    if not m or m.get("value") is None:
        return "n/a"
    return f"{m['numerator']} / {m['denominator']} ({m['value']:.0%})"


def _runs() -> list[dict]:
    out = []
    for r in rows(conn(), "SELECT * FROM eval_runs ORDER BY created_at DESC"):
        s = json.loads(r["summary_json"])
        s["_origin"] = r["origin"]
        out.append(s)
    return out


def _is_fault(s: dict) -> bool:
    return s["evaluation_kind"] == "fault_injection"


def cases_label(s: dict) -> str:
    return f"{SPLIT_NAME[s['split']].lower()} ({s['metrics']['n_cases']})"


def run_name(s: dict, with_date: bool = False) -> str:
    rv = f"Rules {ver(s['rule_version'])}"
    if s["system"].startswith("fault:"):
        name = f"Fault injection: {FAULT_LABEL.get(s['system'].split(':', 1)[1], s['system'])} · {rv} · {cases_label(s)}"
    elif "fault" in s["rule_version"]:
        name = f"Fault injection: deliberately broken rules · {rv} · {cases_label(s)}"
    elif s["system"] == "live":
        name = f"Live model · {rv} · {cases_label(s)}"
    else:
        name = f"{rv} · {cases_label(s)}"
    name = name[0].upper() + name[1:]
    return name + (f" · {s['created_at'][:16].replace('T', ' ')}" if with_date else "")


def _ordered(runs: list[dict]) -> list[dict]:
    """Normal runs first (held-out, dev, all), then fault-injection runs."""
    order = {"held_out": 0, "dev": 1, "all": 2}
    return sorted(runs, key=lambda s: (_is_fault(s), order.get(s["split"], 3), s["rule_version"], s["created_at"]))


def _find(runs: list[dict], version: str, split: str = "held_out") -> dict | None:
    hits = [s for s in runs if s["rule_version"] == version and s["split"] == split and s["system"] == "rules"]
    return hits[0] if hits else None  # runs are newest first


def _active_run(runs: list[dict]) -> dict | None:
    active = get_setting(conn(), "active_rule_version")
    return (_find(runs, active) or _find(runs, "rules-v2.1") or next((s for s in runs if not _is_fault(s)), None)
            or (runs[0] if runs else None))


def _sentence(s: dict) -> str:
    what = (f"Fault injection run ({FAULT_LABEL.get(s['system'].split(':', 1)[1], s['system']).lower()}). " if s["system"].startswith("fault:")
            else "Fault injection run (deliberately broken rules). " if "fault" in s["rule_version"] else "")
    return (f"{what}Rules {ver(s['rule_version'])} with safety checks {ver(s.get('controls_version', 'controls-v1.0'))}, "
            f"on the {SPLIT_NAME[s['split']].lower()} ({s['metrics']['n_cases']} cases, {SPLIT_HELP[s['split']]}).")


def _failure_rows(fails: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Case": f["incident_id"], "Expected": "/".join(f["acceptable"]), "Given": f["after_controls"] or "—",
        "What went wrong": "; ".join(PROBLEM_LABEL.get(p, p) for p in f["problems"])
        + (f" (given {f['after_controls']}, expected {'/'.join(f['acceptable'])})" if "severity_outside_range" in f["problems"] else ""),
    } for f in fails])


# --------------------------------------------------------------------------- headline

def _headline(runs: list[dict]) -> None:
    s = _active_run(runs)
    if not s:
        return
    m = s["metrics"]
    a = m["after_deterministic_controls"]
    st.markdown(f"{run_name(s)} &nbsp;·&nbsp; <span class='small'>active rules on the held-out set, after safety checks</span>", unsafe_allow_html=True)
    active = get_setting(conn(), "active_rule_version")
    if s["rule_version"] != active:
        st.caption(f"No held-out run for the active Rules {ver(active)} yet; showing {run_name(s)}. Run one under **Run evaluation**.")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("P0/P1 caught (recall)", fmt(a["p0p1_recall"]).split(" (")[0],
              help="Share of real P0/P1 cases that were rated P0 or P1. Misses here are the costliest errors.")
    k2.metric("Severity within range", fmt(a["within_acceptable_range"]).split(" (")[0],
              help="Final severity is one of the severities the case label accepts.")
    k3.metric("Route acceptable", fmt(m["routing"]["primary_route_acceptable"]).split(" (")[0],
              help="Case sent to a team the label accepts as owner.")
    c7 = m.get("auto_hold_c7", {}).get("recall")
    k4.metric("Valid auto pause", fmt(c7).split(" (")[0] if c7 else "n/a",
              help="P0 CBRN / child-safety cases that were paused automatically, out of those that should be.")


# --------------------------------------------------------------------------- tabs

def _results(runs: list[dict]) -> None:
    ordered = _ordered(runs)
    ids = [s["run_id"] for s in ordered]
    default = _active_run(runs)
    if st.session_state.get("q_pick") not in ids:
        st.session_state["q_pick"] = default["run_id"]
    by_id = {s["run_id"]: s for s in ordered}
    pick = st.selectbox("Run", ids, key="q_pick", format_func=lambda r: run_name(by_id[r], with_date=True))
    s = by_id[pick]
    st.markdown(_sentence(s))
    hi = s["held_out_integrity"]
    if s["split"] in ("held_out", "all"):
        if hi["matches_freeze"]:
            st.caption("✓ Held-out set unchanged since it was frozen. Disclosures are listed under About & glossary.")
        else:
            st.warning(f"Held-out set differs from its frozen copy (status: {hi['status']}).")
    if _is_fault(s):
        st.info("This run breaks the AI on purpose to check the safety controls still hold. It is not a measure of normal quality.")

    m = s["metrics"]
    a, b = m["after_deterministic_controls"], m["recommendation_before_controls"]
    c7 = m.get("auto_hold_c7")
    tbl = [
        ("P0/P1 recall", "Share of real P0/P1 cases caught", b["p0p1_recall"], a["p0p1_recall"]),
        ("P0/P1 precision", "Share of P0/P1 calls that were correct", b["p0p1_precision"], a["p0p1_precision"]),
        ("Severity within range", "Severity is one the label accepts", b["within_acceptable_range"], a["within_acceptable_range"]),
        ("Severity exact match", "Severity equals the label's expected one", b["exact_match"], a["exact_match"]),
        ("Route acceptable", "Sent to a team the label accepts", None, m["routing"]["primary_route_acceptable"]),
        ("Mandatory review: flagged when needed", "Cases needing review that were flagged", None, m["mandatory_review"]["compliance_flagged_when_required"]),
        ("Mandatory review: flagged when not needed", "Lower is better (over-flagging)", None, m["mandatory_review"]["flagged_when_not_required"]),
        ("Harm category recall", "Cases where every labelled harm category was tagged", None, m.get("category_recall")),
        ("Auto-pause recall", "Paused when it should have been", None, c7["recall"] if c7 else None),
        ("Auto-pause precision", "Pauses that were warranted", None, c7["precision"] if c7 else None),
    ]
    st.dataframe(pd.DataFrame([{"Metric": n, "What it measures": d, "AI recommendation": fmt(x) if x else "",
                                "After safety checks": fmt(y)} for n, d, x, y in tbl]),
                 use_container_width=True, hide_index=True,
                 column_config={"AI recommendation": st.column_config.TextColumn(help="The AI's suggestion before any checks (valid outputs only)"),
                                "After safety checks": st.column_config.TextColumn(help="Final result after the fixed safety checks (all cases)")})

    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("**Severity: expected vs given**")
        st.caption("Rows: expected severity. Columns: severity given after safety checks. The diagonal is correct.")
        cm = pd.DataFrame(a["confusion_matrix_expected_rows_predicted_cols"]).T.reindex(columns=["P0", "P1", "P2", "P3", "none"], fill_value=0)
        cm = cm.rename(columns={"none": "no result"})
        cm.index.name = "Expected"

        def shade(df: pd.DataFrame) -> pd.DataFrame:
            out = pd.DataFrame("", index=df.index, columns=df.columns)
            for r in df.index:
                for col in df.columns:
                    if df.loc[r, col]:
                        out.loc[r, col] = ("background-color:#e3f6ec;font-weight:600" if r == col
                                           else "background-color:#fde2e1")
            return out
        st.dataframe(cm.style.apply(shade, axis=None), use_container_width=True)
    with c2:
        st.markdown("**By scenario group** (after safety checks)")
        st.dataframe(pd.DataFrame([{"Group": k.replace("_", " ").title(), "Cases": v["n"],
                                    "Severity within range": fmt(v["severity_within_range_after_controls"]),
                                    "Route acceptable": fmt(v["route_acceptable_after_controls"]),
                                    "Mandatory review flagged": fmt(v["mandatory_review_flagged_when_required"])}
                                   for k, v in m["by_category"].items()]), use_container_width=True, hide_index=True)

    st.markdown(f"**Cases scored wrong ({len(s['failures'])} of {m['n_cases']})**")
    if s["failures"]:
        st.dataframe(_failure_rows(s["failures"]), use_container_width=True, hide_index=True)
    else:
        st.caption("None. Every case was within range, routed acceptably and flagged for review when needed.")

    with st.expander("Technical details"):
        lat, cost = m["latency_ms"]["mean"], m["cost_usd_estimate"]["total"]
        st.dataframe(pd.DataFrame([
            {"Metric": "Valid AI output (schema)", "Value": fmt(m["schema_valid_rate"])},
            {"Metric": "Facts citing evidence that doesn't exist", "Value": fmt(m["invalid_evidence_reference_rate_by_fact"])},
            {"Metric": "Claim-support accuracy", "Value": "not reported (0 human reviews)"},
            {"Metric": "Mean latency", "Value": f"{lat:.2f} ms" if lat is not None else "n/a"},
            {"Metric": "Cost", "Value": f"${cost:.4f}" if cost else "none (offline)"},
        ]), use_container_width=True, hide_index=True)
        st.caption(f"{s['interpretation']} {s['labels_disclaimer']}")
        st.caption(f"Run ID `{s['run_id']}` · rules `{s['rule_version']}` · controls `{s.get('controls_version', 'controls-v1.0')}` · "
                   f"system `{s['system']}` · split `{s['split']}`")
        if s["failures"]:
            st.markdown("Raw failure records")
            st.dataframe(pd.DataFrame([{k: (", ".join(v) if isinstance(v, list) else v) for k, v in f.items()} for f in s["failures"]]),
                         use_container_width=True, hide_index=True)
        if s.get("artifact_dir") and Path(s["artifact_dir"]).exists():
            st.caption(f"Artifacts: {s['artifact_dir']}")
            w = Path(s["artifact_dir"]) / "claim_review_worksheet.csv"
            if w.exists():
                st.download_button("Download claim-support review worksheet (CSV)", w.read_bytes(), file_name=f"{s['run_id']}_claims.csv")


def _compare(runs: list[dict]) -> None:
    ordered = _ordered(runs)
    by_id = {s["run_id"]: s for s in ordered}
    base = _find(runs, config.BASELINE_RULE_VERSION) or ordered[0]
    a, b = st.columns(2)
    if st.session_state.get("q_before") not in by_id:
        st.session_state["q_before"] = base["run_id"]
    before = by_id[a.selectbox("Before", list(by_id), key="q_before", format_func=lambda r: run_name(by_id[r], with_date=True))]
    after_opts = [r for r, s in by_id.items() if s["split"] == before["split"] and r != before["run_id"]]
    if not after_opts:
        b.selectbox("After", ["(no other run on the same case set)"], disabled=True)
        st.info(f"No other run uses the {cases_label(before)}. Compare runs on the same case set, or run one under **Run evaluation**.")
        return
    preferred = sorted([r for r in after_opts if by_id[r]["system"] == "rules" and by_id[r]["rule_version"] == "rules-v2.1"],
                       key=lambda r: by_id[r]["created_at"], reverse=True)
    if st.session_state.get("q_after") not in after_opts:
        st.session_state["q_after"] = (preferred or after_opts)[0]
    after = by_id[b.selectbox("After", after_opts, key="q_after", format_func=lambda r: run_name(by_id[r], with_date=True),
                              help="Only runs on the same case set are offered")]

    chk = monitoring.regression_check(before, after)
    if chk["alert"]:
        st.error("**Regression:** " + "; ".join(
            f"{GATE_LABEL.get(r['metric'], r['metric'])} {r['baseline']:.0%} → {r['candidate']:.0%}" for r in chk["regressions"]))
    else:
        st.success("**No regression** on the gated metrics.")
    st.caption("Regression gate: fails if P0/P1 recall, mandatory-review flagging, valid AI output or auto-pause recall drop at all, "
               "or if severity-within-range or route acceptability drop by more than 5 points. Synthetic test cases, not production monitoring.")

    def val(s: dict, fn) -> float | None:
        try:
            return fn(s["metrics"])
        except (KeyError, TypeError):
            return None
    metrics = [
        ("P0/P1 recall", lambda m: m["after_deterministic_controls"]["p0p1_recall"]["value"]),
        ("P0/P1 precision", lambda m: m["after_deterministic_controls"]["p0p1_precision"]["value"]),
        ("Severity within range", lambda m: m["after_deterministic_controls"]["within_acceptable_range"]["value"]),
        ("Severity exact match", lambda m: m["after_deterministic_controls"]["exact_match"]["value"]),
        ("Route acceptable", lambda m: m["routing"]["primary_route_acceptable"]["value"]),
        ("Mandatory review flagged when needed", lambda m: m["mandatory_review"]["compliance_flagged_when_required"]["value"]),
        ("Auto-pause recall", lambda m: m["auto_hold_c7"]["recall"]["value"]),
        ("Auto-pause precision", lambda m: m["auto_hold_c7"]["precision"]["value"]),
        ("Valid AI output", lambda m: m["schema_valid_rate"]["value"]),
    ]
    tbl = []
    for name, fn in metrics:
        x, y = val(before, fn), val(after, fn)
        if x is None and y is None:
            continue
        d = None if x is None or y is None else (y - x) * 100
        tbl.append({"Metric": name, "Before": "n/a" if x is None else f"{x:.0%}", "After": "n/a" if y is None else f"{y:.0%}",
                    "Change": "" if d is None else ("—" if abs(d) < 0.05 else f"{'▲' if d > 0 else '▼'} {abs(d):.0f} pts")})
    df = pd.DataFrame(tbl)
    st.dataframe(df.style.map(lambda v: "color:#1b6b3f;font-weight:600" if str(v).startswith("▲")
                              else "color:#9b1111;font-weight:600" if str(v).startswith("▼") else "", subset=["Change"]),
                 use_container_width=True, hide_index=True)

    fixed_ids = {f["incident_id"] for f in chk["fixed_cases"]}
    worse, better = chk["newly_failing_cases"], [f for f in before["failures"] if f["incident_id"] in fixed_ids]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Now failing ({len(worse)})**")
        if worse:
            st.dataframe(_failure_rows(worse), use_container_width=True, hide_index=True)
        else:
            st.caption("None.")
    with c2:
        st.markdown(f"**Now passing ({len(better)})**")
        if better:
            st.dataframe(_failure_rows(better)[["Case", "Expected", "What went wrong"]].rename(columns={"What went wrong": "Was wrong because"}),
                         use_container_width=True, hide_index=True)
        else:
            st.caption("None.")


def _run_tab() -> None:
    versions = available_versions()
    a, b = st.columns(2)
    version = a.selectbox("Rules version", versions, format_func=lambda v: RULES_LABEL.get(v, f"Rules {ver(v)}"),
                          index=versions.index("rules-v2.1") if "rules-v2.1" in versions else 0)
    split = b.radio("Case set", ["dev", "held_out", "all"], horizontal=True,
                    format_func=lambda k: {"dev": "Dev set (44, used for tuning)", "held_out": "Held-out set (36, run sparingly)",
                                           "all": "All (80)"}[k])
    live_ok = not public_demo()
    modes = ["rules"] + (["live"] if live_ok else []) + [f"fault:{k}" for k in
                                                         ["under_severity", "timeout", "malformed_json", "invalid_evidence_refs",
                                                          "obeys_embedded_instructions"]]
    system = st.selectbox("Mode", modes, format_func=lambda k: "Normal" if k == "rules" else
                          ("Live model" + ("" if config.live_credentials_available() else " (needs an API key)")) if k == "live" else
                          f"Fault injection: {FAULT_LABEL[k.split(':', 1)[1]].lower()}")
    if not live_ok:
        st.caption("Live model: not available on the public demo (needs an API key; local only).")
    if split == "held_out":
        st.caption("The held-out set was frozen before tuning. Don't change rules because of held-out failures without recording a disclosure.")
    if system == "live" and not config.live_credentials_available():
        st.error("Live evaluation needs ANTHROPIC_API_KEY. It never falls back to offline results.")
    if st.button("Run evaluation", type="primary"):
        try:
            with st.spinner("Evaluating…"):
                s = evaluation.run_eval(system, version, "prompt-v3", split, out_dir=config.RESULTS_DIR / "ui_runs")
                wf.record_eval_run(conn(), s, origin="demo")
            flash("success", f"Run recorded: {run_name(s)}")
            st.session_state["q_pick"] = s["run_id"]
            st.session_state["_q_goto"] = "Results"  # applied before the tab widget is built on the next run
        except evaluation.LiveEvaluationUnavailable as e:
            flash("error", str(e))
        st.rerun()
    with st.expander("Technical details"):
        st.caption("Uses the same harness as the command line. Results are written to `evaluation/results/`.")
        st.code(f"python -m riskops.cli eval --system {system} --rules {version} --prompt prompt-v3 --split {split} --record-in-db")


def _overrides() -> None:
    om = monitoring.ops_metrics(conn())["overrides"]
    rate = f" ({om['override_rate']:.0%})" if om["override_rate"] is not None else ""
    st.markdown(f"**Overrides: {om['overrides']} of {om['decisions_with_ai_recommendation']} human decisions** differed from the AI recommendation{rate}.")
    c1, c2 = st.columns([3, 2])
    c1.dataframe(pd.DataFrame([{"Reason": wf.OVERRIDE_REASONS.get(k, k), "Count": v} for k, v in om["by_reason"].items()]
                              or [{"Reason": "No overrides yet", "Count": 0}]), use_container_width=True, hide_index=True)
    c2.dataframe(pd.DataFrame([{"Direction": OVERRIDE_DIRECTION.get(k, k), "Count": v} for k, v in om["by_direction"].items()]
                              or [{"Direction": "—", "Count": 0}]), use_container_width=True, hide_index=True)
    st.caption("Counts come from the seeded history and actions in this demo, not from a user study.")
    cr = rows(conn(), "SELECT verdict, COUNT(*) n FROM claim_reviews GROUP BY verdict")
    st.markdown("**Claim reviews**")
    if cr:
        st.dataframe(pd.DataFrame([{"Verdict": VERDICT_LABEL.get(r["verdict"], r["verdict"]), "Facts": r["n"]} for r in cr]),
                     use_container_width=True, hide_index=True)
    else:
        st.caption("None yet. On a case's AI assessment, a reviewer can mark each AI claim as supported or not by the cited evidence; "
                   "the counts appear here. Nothing is inferred for unreviewed claims.")


def _about(runs: list[dict]) -> None:
    st.markdown("#### About these results")
    st.markdown("""
- All results come from about 80 **synthetic** cases with **provisional** labels written by the author, not independently validated.
- Offline runs test the rules and safety controls. The "AI" outputs are pre-written fixtures or a simulation, **not measured model performance**.
- **No live-model evaluation has been run** (no API key in this environment). It remains pending.
- Nothing here measures real-world harm reduction or production reliability.
""")
    st.markdown("#### Limitations")
    st.markdown("""
- The dev set was used to write Rules v2.1, so dev results for v2.1 are optimistic by construction (44/44 on dev, but 30/36 on held-out, the same as Rules v2.0).
- The same author wrote the rules and the dataset. Severe-harm cases (CBRN, child safety, self-harm, violent extremism) are recorded as structured restricted-evidence fields, which rules can match more easily than free-text reports (disclosed in FREEZE.json).
- Taxonomy v1 results are archived in `evaluation/archive_v1/` and are not comparable with these.
- Containment and communications are simulated; there is no integration with real systems.
- Roles are simulated identities; there is no authentication.
- Monitoring numbers come from seeded synthetic history plus local demo clicks.
""")
    s = next((x for x in runs if x["split"] in ("held_out", "all")), None)
    if s and s["held_out_integrity"]["disclosures"]:
        with st.expander(f"Held-out set disclosures ({len(s['held_out_integrity']['disclosures'])})"):
            for d in s["held_out_integrity"]["disclosures"]:
                st.markdown(f"- **{d['date'][:10]}**: {d['change']}")
    st.markdown("#### Glossary")
    for group, items in GLOSSARY.items():
        st.markdown(f"**{group}**")
        st.markdown("\n".join(f"- **{k}**: {v}" for k, v in items))


# --------------------------------------------------------------------------- page

TAB_KIND = {"Results": "test", "Compare versions": "test", "Run evaluation": "test", "Human overrides": "human", "About & glossary": "ref"}


def render() -> None:
    st.title("Quality & evaluation")
    st.caption("How well the triage pipeline performs on 80 synthetic cases with known answers. "
               "Synthetic test results, not real-world performance. Full caveats under **About & glossary**.")
    runs = _runs()
    with card("test", "Current results", "headline"):
        _headline(runs)
    if goto := st.session_state.pop("_q_goto", None):
        st.session_state["q_section"] = goto
    tabs = TABS + (["Jev shadow"] if view_jev.allowed() else [])
    sec = section(tabs, key="q_section")
    with card(TAB_KIND.get(sec, "test"), sec, "tab_" + sec.split()[0].lower(),
              PURPOSE.get(sec, "Admin only: Jev answers measured in shadow mode, never used in decisions.")):
        if sec == "Jev shadow":
            view_jev.report()
        elif sec == "About & glossary":
            _about(runs)
        elif sec == "Human overrides":
            _overrides()
        elif sec == "Run evaluation":
            _run_tab()
        elif not runs:
            st.info("No runs recorded yet. Start one under **Run evaluation**.")
        elif sec == "Results":
            _results(runs)
        elif len(runs) < 2:
            st.info("Need at least two runs to compare.")
        else:
            _compare(runs)
