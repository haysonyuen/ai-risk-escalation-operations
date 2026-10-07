from __future__ import annotations

import pandas as pd
import streamlit as st

from common import ROUTE_LABEL, card, duration, GATE_LABEL, SPLIT_NAME, section, badge, conn, current_actor, flash, md, run_action, ver
from riskops import config, evaluation, monitoring, policies, workflow as wf
from riskops.assessment import CONTROLS_VERSION
from riskops.db import get_setting, rows
from riskops.rules import available_versions, load_rules


def _conds(r: dict) -> str:
    parts = []
    for k in ("all", "any", "none"):
        if k in r:
            parts.append(f"{k.upper()}({', '.join(r[k])})")
    return " AND ".join(parts)


def _policies() -> None:
    lib = policies.library()
    st.markdown(f"**Policy library** ({ver(lib['version'])}): one policy per harm area. The AI and the rules suggest a policy for each case; "
                "a person confirms it in the severity decision.")
    st.caption(lib["note"])
    q = st.text_input("Find a policy", placeholder="Name, code or team", label_visibility="collapsed", key="pol_q")
    for p in policies.all_policies():
        text = " ".join([p["name"], p["code"], p["definition"], ROUTE_LABEL.get(p["owning_team"], "")]).lower()
        if q and q.lower() not in text:
            continue
        with st.expander(f"{p['code']} · {p['name']}"):
            st.markdown(f"_{p['definition']}_")
            st.markdown(f"**Owning team:** {ROUTE_LABEL.get(p['owning_team'], p['owning_team'])}  \n**Severity guidance:** {p['severity_guidance']}")
            c1, c2, c3 = st.columns(3)
            c1.markdown("**What usually points to it**\n" + "\n".join(f"- {x}" for x in p["signals"]))
            c2.markdown("**Escalation contacts** (roles)\n" + "\n".join(f"- {x}" for x in p["escalation"]))
            c3.markdown("**Review checklist**\n" + "\n".join(f"- {x}" for x in p["checklist"]))


SEV_FRAMEWORK = [
    ("P0", "Critical", "Credible immediate danger, active harmful facilitation, or highly credible severe exposure",
     "Immediate targeted containment, evidence preservation, and same-hour human review"),
    ("P1", "High", "Serious safety, privacy, security, or loss-of-control concern without confirmed broad active harm",
     "Same-day investigation, specialist escalation, and a communication plan"),
    ("P2", "Medium", "Material user impact or a recurring product or workflow failure",
     "Pattern investigation, user guidance, and routing to the responsible product or technical team"),
    ("P3", "Low", "Confusion, duplication, expected launch noise, or a report with no current evidence of harm",
     "Support, trend monitoring, and quality sampling"),
]


def _severity_sla() -> None:
    sla = config.sla_config()
    t = sla["targets_minutes"]
    with card("ref", "Severity levels and SLA targets", "sev", "What each severity means, and how fast a person must act."):
        head = "".join(f"<th>{h}</th>" for h in ("Severity", "When to use it", "First human review within",
                                                    "Containment / escalation within", "Response posture"))
        body = "".join(
            f"<tr><td>{badge(s + ' · ' + name, 'b-' + s.lower())}</td><td>{std}</td><td><b>{duration(t[s]['first_human_review'])}</b></td>"
            f"<td><b>{duration(t[s]['containment_or_escalation']) if t[s]['containment_or_escalation'] else 'not set'}</b></td><td>{post}</td></tr>"
            for s, name, std, post in SEV_FRAMEWORK)
        md(f'<table class="sev-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')
        st.caption(f"Session auto-pause review: within {duration(sla['auto_hold_review_minutes'])}. "
                   "Before a person confirms severity, deadlines use the AI recommendation after safety checks; with no assessment, the P1 target. "
                   "SLA numbers are prototype assumptions (config/sla.json), not any company's policy. Severity standards come from docs/framework.md.")


def _readable(versions: list[str], active: str) -> None:
    with card("ref", "Rules", "rules", "The fixed checklist that sets a minimum severity, flags mandatory review and picks the owning team."):
        v = st.selectbox("Version", versions, index=versions.index(active), format_func=lambda x: f"Rules {ver(x)}" + (" (active)" if x == active else ""))
        r = load_rules(v)
        md(f"<b>{len(r['severity_rules'])}</b> severity rules · <b>{len(r['severity_floors'])}</b> severity floors · "
           f"<b>{len(r['mandatory_review'])}</b> mandatory-review conditions · routing for <b>{len(r['route_priority'])}</b> harm areas &nbsp; "
           + badge(r["status"], "b-fault" if "FAULT" in r["status"] else "b-muted"))
        st.write(r["description"])
        if r.get("changelog"):
            with st.expander("What changed in this version"):
                for line in r["changelog"]:
                    st.markdown(f"- {line}")
            st.markdown("**Severity rules** (first match wins)")
            st.dataframe(pd.DataFrame([{"id": x["id"], "severity": x["severity"], "when": _conds(x), "meaning": x["description"]} for x in r["severity_rules"]]
                                      + [{"id": "DEFAULT", "severity": r["default_severity"], "when": "no rule matched", "meaning": ""}]),
                         use_container_width=True, hide_index=True)
            st.markdown("**Severity floors** (raise only; run after impact and evidence quality are known)")
            st.dataframe(pd.DataFrame([{"id": x["id"], "floor": x["floor"], "when": _conds(x), "meaning": x["description"]} for x in r["severity_floors"]]
                                      or [{"id": "—", "floor": "", "when": "none in this version", "meaning": ""}]), use_container_width=True, hide_index=True)
            st.markdown("**Mandatory human-review conditions**")
            st.dataframe(pd.DataFrame([{"id": x["id"], "when": _conds(x), "meaning": x["description"]} for x in r["mandatory_review"]]),
                         use_container_width=True, hide_index=True)
            st.markdown("**Routing** (first matching category sets the primary route)")
            st.dataframe(pd.DataFrame([{"category": cat, "primary route": route, "teams": ", ".join(r["teams"].get(cat, []))} for cat, route in r["route_priority"]]),
                         use_container_width=True, hide_index=True)
            if r.get("p3_routing"):
                st.caption(f"{r['p3_routing']['id']}: {r['p3_routing']['description']}")
            with st.expander("Lexicons (keyword signals)"):
                st.json(r["lexicons"])
            with st.expander("Impact rules and category rules"):
                st.dataframe(pd.DataFrame([{"level": x["level"], "when": _conds(x)} for x in r["impact_rules"]]), hide_index=True)
                st.dataframe(pd.DataFrame([{"category": x["category"], "when": _conds(x)} for x in r["category_rules"]]), hide_index=True)


def _controls_prompts() -> None:
    with card("ref", f"Safety checks ({ver(CONTROLS_VERSION)})", "controls",
              "Fixed checks applied after the AI, whatever the rules version. They can raise severity or force review, never lower anything."):
            st.markdown("""
    | Control | What it does |
    | --- | --- |
    | **Unusable AI output** (C1) | AI failure, malformed output or schema-invalid output → no assessment is invented; case routed to manual review (rules recommendation shown, labeled) |
    | **Missing evidence** (C2) | Every cited evidence ID must exist in the case; invalid references are flagged |
    | **Severity floor** (C3) | AI severity below the rules recommendation is raised to it (controls never lower severity) |
    | **Embedded instructions** (C4) | Instructions embedded in report text are flagged for review and never followed |
    | **Low-confidence review** (C5) | Low confidence on a potentially high/critical-impact case → mandatory review (low confidence ≠ low severity) |
    | **Specialist route** (C6) | A different route than a specialist route (Safety, Child Safety, Threat Intel, Legal/Privacy, Product Security) → specialist route kept and flagged |
    | **Auto-pause** (C7) | P0 recommendation in **CBRN or child safety** (from the rules *or* the AI) → the reported session is paused automatically (simulated). A Safety specialist or the Incident Lead must confirm or lift it; lifting needs a written reason. It never lifts itself: past its review time it escalates to the Incident Lead. Anything stronger (account suspension, mandatory external report) stays a human decision |
    """)
    with card("ref", "Prompt versions", "prompts", "Used only when a live model is configured."):
            pv = st.selectbox("Prompt", sorted(p.stem for p in config.PROMPT_DIR.glob("prompt-v*.md")))
            pf = config.PROMPT_DIR / f"{pv}.md"
            if pf.exists():
                st.code(pf.read_text()[:5000], language="markdown")


def _change(c, versions: list[str], active: str) -> None:
    with card("human", "Change the active rules", "change",
              "Incident Lead only. Needs a rationale, is logged, and never changes existing assessments or human decisions."):
            with st.form("change_rules"):
                nv = st.selectbox("New active version", versions, index=versions.index(active), format_func=lambda x: f"Rules {ver(x)}")
                why = st.text_input("Rationale")
                if st.form_submit_button("Change active rule version"):
                    run_action(lambda: wf.change_rule_version(c, nv, current_actor(), why), f"Active rules → {nv}")
                    st.rerun()
            if "FAULT" in load_rules(active)["status"]:
                st.error("The active rule version is a FAULT-INJECTION demo set. Roll back.")
    with card("test", "Regression check", "regcheck", "Run a baseline and a candidate on the same synthetic case set and apply the regression gate."):
            a1, a2, a3 = st.columns(3)
            base_v = a1.selectbox("Baseline", versions, index=versions.index(config.BASELINE_RULE_VERSION) if config.BASELINE_RULE_VERSION in versions else 0,
                                  format_func=lambda x: f"Rules {ver(x)}")
            cand_v = a2.selectbox("Candidate", versions, index=versions.index(active), format_func=lambda x: f"Rules {ver(x)}")
            split = a3.selectbox("Case set", ["held_out", "dev", "all"], format_func=SPLIT_NAME.get)
            if st.button("Run regression check"):
                with st.spinner("Running both versions…"):
                    sb = evaluation.run_eval("rules", base_v, split=split, label=f"regression baseline {base_v} on {split}", out_dir=config.RESULTS_DIR / "ui_runs")
                    sc = evaluation.run_eval("rules", cand_v, split=split, label=f"regression candidate {cand_v} on {split}", out_dir=config.RESULTS_DIR / "ui_runs")
                    wf.record_eval_run(c, sb, origin="demo")
                    wf.record_eval_run(c, sc, origin="demo")
                    st.session_state["last_regression"] = monitoring.regression_check(sb, sc)
                flash("info", "Regression runs recorded on the Quality page.")
                st.rerun()
            chk = st.session_state.get("last_regression")
            if chk:
                (st.error if chk["alert"] else st.success)(
                    ("Regression: " + "; ".join(f"{GATE_LABEL.get(x['metric'], x['metric'])} {x['baseline']:.0%} → {x['candidate']:.0%}" for x in chk["regressions"]))
                    if chk["alert"] else "No regression on the gated metrics.")
                st.caption("Synthetic test cases with provisional labels, not production monitoring. The fault-demo rule set degrades results on purpose.")
                if chk["improvements"]:
                    st.caption("Improved: " + "; ".join(f"{GATE_LABEL.get(x['metric'], x['metric'])} {x['baseline']:.0%} → {x['candidate']:.0%}" for x in chk["improvements"]))
                if chk["newly_failing_cases"]:
                    from view_quality import _failure_rows
                    st.markdown("Now failing")
                    st.dataframe(_failure_rows(chk["newly_failing_cases"]), use_container_width=True, hide_index=True)
                if chk["fixed_cases"]:
                    st.caption("Now passing: " + ", ".join(f["incident_id"] for f in chk["fixed_cases"]))
    ev = rows(c, "SELECT ts, actor_id, previous_value, new_value, reason FROM events WHERE event_type='rule_version_changed' ORDER BY event_id DESC")
    if ev:
        with card("human", "Rule change log", "changelog"):
            st.dataframe(pd.DataFrame([{"When": e["ts"].replace("T", " ")[:16], "Who": e["actor_id"], "From": e["previous_value"],
                                        "To": e["new_value"], "Rationale": e["reason"]} for e in ev]), use_container_width=True, hide_index=True)


def render() -> None:
    st.title("Rules & playbooks")
    c = conn()
    active = get_setting(c, "active_rule_version")
    versions = available_versions()
    if active not in versions:  # e.g. a database from an older demo-data version
        st.warning(f"The stored active rule version `{active}` is no longer available (archived). "
                   f"Showing `{versions[0]}`. Use **Reset demo data** in the sidebar to rebuild the demo data.")
        active = versions[0]
    md(f"Active: {badge('Rules ' + ver(active), 'b-rules')} · {badge('safety checks ' + ver(CONTROLS_VERSION), 'b-muted')} · "
       f"{badge('prompt ' + ver(get_setting(c, 'active_prompt_version')), 'b-muted')}")
    if "FAULT" in load_rules(active)["status"]:
        st.error("The active rule version is a fault-injection demo set (deliberately broken). Roll back under **Change rules**.")
    labels = ["Severity & SLA", "Policies", "Rules", "Safety checks & prompts", "Change rules"]
    sec = section(labels, key="r_section")
    if sec == "Severity & SLA":
        _severity_sla()
    elif sec == "Policies":
        with card("ref", "Policy library", "policies"):
            _policies()
    elif sec == "Rules":
        _readable(versions, active)
    elif sec == "Safety checks & prompts":
        _controls_prompts()
    else:
        _change(c, versions, active)
