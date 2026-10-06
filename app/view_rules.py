from __future__ import annotations

import pandas as pd
import streamlit as st

from common import ROUTE_LABEL, GATE_LABEL, SPLIT_NAME, section, badge, conn, current_actor, flash, md, run_action, ver
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


def render() -> None:
    st.title("Rules & playbooks")
    c = conn()
    active = get_setting(c, "active_rule_version")
    versions = available_versions()
    if active not in versions:  # e.g. a database from an older demo-data version
        st.warning(f"The stored active rule version `{active}` is no longer available (archived). "
                   f"Showing `{versions[0]}`. Use **Reset demo data** in the sidebar to rebuild the demo data.")
        active = versions[0]
    md(f"Active: {badge('Rules ' + ver(active), 'b-rules')} · {badge('safety controls ' + ver(CONTROLS_VERSION), 'b-muted')} · "
       f"{badge('prompt ' + ver(get_setting(c, 'active_prompt_version')), 'b-muted')}")
    _labels = ["Readable rules", "Policies", "Change rules + regression check", "Controls, prompts & SLA", "Severity framework"]
    sec = section(_labels, key="r_section")
    if sec == _labels[0]:
        v = st.selectbox("Version", versions, index=versions.index(active))
        r = load_rules(v)
        md(badge(r["status"], "b-fault" if "FAULT" in r["status"] else "b-muted"))
        st.write(r["description"])
        if r.get("changelog"):
            st.markdown("**Changelog**")
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
    elif sec == _labels[1]:
        _policies()
    elif sec == _labels[2]:
        st.markdown("Changing the active version is governed (Incident Lead only), requires a rationale, is logged, and **does not modify** "
                    "any existing assessment or human decision. Cases keep the version they were assessed with until re-assessed.")
        with st.form("change_rules"):
            nv = st.selectbox("New active version", versions, index=versions.index(active))
            why = st.text_input("Rationale")
            if st.form_submit_button("Change active rule version"):
                run_action(lambda: wf.change_rule_version(c, nv, current_actor(), why), f"Active rules → {nv}")
                st.rerun()
        if "FAULT" in load_rules(active)["status"]:
            st.error("The active rule version is a FAULT-INJECTION demo set. Roll back.")
        st.markdown("**Regression evaluation** — run a baseline and a candidate on the same split and apply the regression gate.")
        a1, a2, a3 = st.columns(3)
        base_v = a1.selectbox("Baseline", versions, index=versions.index(config.BASELINE_RULE_VERSION) if config.BASELINE_RULE_VERSION in versions else 0)
        cand_v = a2.selectbox("Candidate", versions, index=versions.index(active))
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
            st.markdown("**Rule change log**")
            st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
    elif sec == _labels[3]:
        st.markdown(f"**Always-on safety controls ({ver(CONTROLS_VERSION)})**: fixed checks applied after the AI, independent of rules version")
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
        st.markdown("**Prompt versions** (used only in live mode)")
        pv = st.selectbox("Prompt", sorted(p.stem for p in config.PROMPT_DIR.glob("prompt-v*.md")))
        pf = config.PROMPT_DIR / f"{pv}.md"
        if pf.exists():
            st.code(pf.read_text()[:5000], language="markdown")
        st.markdown("**SLA targets — PROTOTYPE ASSUMPTIONS** (config/sla.json)")
        sla = config.sla_config()
        st.caption(sla["note"])
        st.dataframe(pd.DataFrame(sla["targets_minutes"]).T, use_container_width=True)
    elif sec == _labels[4]:
        st.markdown("""
| Tier | Decision standard | Response posture |
| --- | --- | --- |
| **P0 – Critical** | Credible immediate danger, active harmful facilitation, or highly credible severe exposure | Immediate targeted containment, evidence preservation, and same-hour human review |
| **P1 – High** | Serious safety, privacy, security, or loss-of-control concern without confirmed broad active harm | Same-day investigation, specialist escalation, and a communication plan |
| **P2 – Medium** | Material user impact or a recurring product or workflow failure | Pattern investigation, user guidance, and routing to the responsible product or technical team |
| **P3 – Low** | Confusion, duplication, expected launch noise, or a report with no current evidence of harm | Support, trend monitoring, and quality sampling |

Source: the original framework (docs/framework.md). AI recommends; people own final severity, consequential actions, policy/legal conclusions and closure.
""")
