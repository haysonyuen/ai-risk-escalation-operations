from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from common import section, conn, current_actor, flash, provider_for_mode, run_action
from riskops import config, dedup, workflow as wf
from riskops.db import rows
from riskops.schemas import IncidentIntake

TRI = ["unknown", "yes", "no"]


def _after_create(iid: str, assess: bool) -> None:
    c = conn()
    target = wf.get_intake(c, iid)
    others = [wf.get_intake(c, r["incident_id"]) for r in rows(c, "SELECT incident_id FROM incidents")]
    n = wf.record_link_suggestions(c, iid, dedup.suggest(target, others))
    if n:
        flash("info", f"{n} possibly related report(s) suggested for review on the Related reports tab. Nothing was merged.")
    if assess:
        provider, mode = provider_for_mode()
        run_action(lambda: wf.run_assessment(c, iid, provider, wf.SYSTEM_ACTOR), f"AI assessment run ({mode})")
    st.session_state["selected_incident"] = iid
    st.session_state["nav_to"] = "Incident workspace"


def render() -> None:
    st.title("New intake")
    st.caption("Synthetic data only. Leave fields as 'unknown' when they are not known — they stay explicitly unknown. "
               "Report text is treated as untrusted data.")
    _labels = ["Manual entry", "JSON import"]
    sec = section(_labels, key="i_section")
    if sec == _labels[0]:
        with st.form("manual"):
            a, b = st.columns(2)
            iid = a.text_input("Incident ID", value=f"INC-{datetime.now(timezone.utc).strftime('%m%d%H%M')}")
            title = b.text_input("Title")
            behavior = st.text_area("Reported behavior")
            impact = st.text_input("Potential / reported impact", value="unknown")
            c1, c2, c3 = st.columns(3)
            surface = c1.text_input("Product surface", value="unknown")
            customer = c2.selectbox("Customer type", ["unknown", "consumer", "enterprise", "internal"])
            channel = c3.selectbox("Channel", ["support_ticket", "enterprise_report", "safety_reviewer", "internal_observation", "telemetry_alert"])
            c4, c5, c6 = st.columns(3)
            model = c4.text_input("Model / product version", value="unknown")
            file_action = c5.selectbox("File action", ["unknown", "none", "read", "summarized", "edited", "deleted"])
            external = c6.selectbox("External action attempted", TRI)
            c7, c8, c9 = st.columns(3)
            approved = c7.selectbox("User approved the action", TRI)
            sensitive = c8.selectbox("Sensitive data involved", ["unknown", "yes", "possible", "no"])
            scope = c9.selectbox("Scope", ["unknown", "single_user", "multiple_users", "workspace", "multiple_customers"])
            c10, c11, c12 = st.columns(3)
            recurrence = c10.selectbox("Recurrence", ["unknown", "first_report", "repeated"])
            reversibility = c11.selectbox("Reversibility", ["unknown", "reversible", "partially_reversible", "irreversible"])
            owners = ["(unassigned)"] + [x.actor_id for x in wf.SIMULATED_ACTORS]
            owner = c12.selectbox("Owner", owners)
            st.markdown("**Evidence** (one record per line: `ID | source_type | source description | content`)")
            ev_text = st.text_area("Evidence records", value="E1 | reporter_statement | Reporter statement | ")
            assess = st.checkbox("Run AI assessment after intake", value=True)
            if st.form_submit_button("Create incident"):
                evidence = []
                for line in ev_text.splitlines():
                    parts = [p.strip() for p in line.split("|", 3)]
                    if len(parts) == 4 and parts[3]:
                        evidence.append({"evidence_id": parts[0], "source_type": parts[1], "source_description": parts[2], "content": parts[3]})
                data = {"incident_id": iid, "reported_at": datetime.now(timezone.utc).isoformat(), "title": title,
                        "product_surface": surface, "customer_type": customer, "reporter_channel": channel,
                        "reported_behavior": behavior, "reported_impact": impact or "unknown", "model_version": model or "unknown",
                        "file_action": file_action, "external_action_attempted": external, "user_approved": approved,
                        "sensitive_data": sensitive, "scope": scope, "recurrence": recurrence, "reversibility": reversibility,
                        "evidence": evidence}
                ok = run_action(lambda: wf.create_incident(conn(), IncidentIntake.model_validate(data), current_actor(),
                                                           owner=None if owner == "(unassigned)" else owner), "Incident created")
                if ok:
                    _after_create(iid, assess)
                st.rerun()
    elif sec == _labels[1]:
        st.caption("Paste one incident object or a list. Invalid records are reported and skipped — never partially imported.")
        if st.button("Load walkthrough example (data/demo/intake_example.json)"):
            st.session_state["json_text"] = (config.DEMO_DIR / "intake_example.json").read_text()
        up = st.file_uploader("…or upload a .json file", type=["json"])
        if up is not None:
            st.session_state["json_text"] = up.getvalue().decode()
        text = st.text_area("JSON", key="json_text", height=320)
        assess = st.checkbox("Run AI assessment after import", value=True, key="imp_assess")
        if st.button("Import"):
            try:
                created, errors = wf.import_json(conn(), text, current_actor())
            except wf.PermissionDenied as e:
                created, errors = [], [str(e)]
            for e in errors:
                flash("error", e)
            for iid in created:
                flash("success", f"Imported {iid}")
                _after_create(iid, assess)
            st.rerun()
