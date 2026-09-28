from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from common import EVIDENCE_TYPES, conn, section, current_actor, go_case, pretty, provider_for_mode, run_inline
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
        st.session_state.setdefault("_toasts", []).append(f"{n} possibly related report(s) suggested — see Related")
    if assess:
        provider, _ = provider_for_mode()
        run_inline(lambda: wf.run_assessment(c, iid, provider, wf.SYSTEM_ACTOR), "AI assessment recorded")
    go_case(iid)


def render() -> None:
    st.title("New report")
    st.caption("Use synthetic data only. Leave anything you don't know as **unknown** — it stays visibly unknown on the case. "
               "Report text is treated as untrusted and never followed as instructions.")
    hint = None if wf.can(current_actor(), "create_incident") else "Your role cannot create reports"
    sec = section(["Enter a report", "Import JSON"], key="intake_section")
    if sec == "Enter a report":
        with st.form("intake", border=False):
            st.markdown("##### What happened")
            title = st.text_input("Short title *", placeholder="e.g. Assistant emailed a contract to an outside address")
            behavior = st.text_area("What was reported *", height=110, placeholder="Describe what the assistant did, in the reporter's words")
            impact = st.text_input("Reported or potential impact", placeholder="unknown")

            st.markdown("##### Where and who")
            a1, a2, a3, a4 = st.columns(4)
            customer = a1.selectbox("Customer type", ["unknown", "consumer", "enterprise", "internal"])
            channel = a2.selectbox("Reported via", ["support_ticket", "enterprise_report", "safety_reviewer", "internal_observation", "telemetry_alert"], format_func=pretty)
            surface = a3.text_input("Product surface", placeholder="unknown")
            model = a4.text_input("Model / product version", placeholder="unknown")

            st.markdown("##### What the assistant did")
            b1, b2, b3 = st.columns(3)
            file_action = b1.selectbox("Files", ["unknown", "none", "read", "summarized", "edited", "deleted"])
            external = b2.selectbox("External action attempted?", TRI)
            approved = b3.selectbox("Did the user approve it?", TRI)

            st.markdown("##### Risk factors")
            c1, c2, c3, c4 = st.columns(4)
            sensitive = c1.selectbox("Sensitive data involved?", ["unknown", "yes", "possible", "no"])
            scope = c2.selectbox("Scope", ["unknown", "single_user", "multiple_users", "workspace", "multiple_customers"], format_func=pretty)
            recurrence = c3.selectbox("Seen before?", ["unknown", "first_report", "repeated"], format_func=pretty)
            reversibility = c4.selectbox("Reversible?", ["unknown", "reversible", "partially_reversible", "irreversible"], format_func=pretty)

            st.markdown("##### Evidence")
            st.caption("One row per record. IDs must be unique and are permanent.")
            ev_df = st.data_editor(
                pd.DataFrame([{"ID": "E1", "Type": "reporter_statement", "Source": "Reporter statement", "Content": ""}]),
                num_rows="dynamic", use_container_width=True, hide_index=True,
                column_config={"ID": st.column_config.TextColumn(width="small", required=True),
                               "Type": st.column_config.SelectboxColumn(options=EVIDENCE_TYPES, required=True),
                               "Source": st.column_config.TextColumn(width="medium"),
                               "Content": st.column_config.TextColumn(width="large")})

            o1, o2, o3 = st.columns([2, 2, 1])
            owners = ["(unassigned)"] + [x.actor_id for x in wf.SIMULATED_ACTORS]
            owner = o1.selectbox("Owner", owners)
            iid = o2.text_input("Incident ID", value=f"INC-{datetime.now(timezone.utc).strftime('%m%d%H%M')}")
            assess = o3.checkbox("Run AI assessment", value=True)
            if st.form_submit_button("Create report", type="primary", disabled=bool(hint)):
                evidence = [{"evidence_id": str(r["ID"]).strip(), "source_type": r["Type"], "source_description": (r["Source"] or "unspecified"),
                             "content": r["Content"]} for _, r in ev_df.iterrows() if str(r.get("Content") or "").strip()]
                data = {"incident_id": iid, "reported_at": datetime.now(timezone.utc).isoformat(), "title": title,
                        "product_surface": surface or "unknown", "customer_type": customer, "reporter_channel": channel,
                        "reported_behavior": behavior, "reported_impact": impact or "unknown", "model_version": model or "unknown",
                        "file_action": file_action, "external_action_attempted": external, "user_approved": approved,
                        "sensitive_data": sensitive, "scope": scope, "recurrence": recurrence, "reversibility": reversibility,
                        "evidence": evidence}
                if run_inline(lambda: wf.create_incident(conn(), IncidentIntake.model_validate(data), current_actor(),
                                                         owner=None if owner == "(unassigned)" else owner), f"Report {iid} created"):
                    _after_create(iid, assess)
    else:
        st.caption("Paste one incident object or a list. Invalid records are listed and skipped — never partially imported.")
        if st.button("Load the walkthrough example"):
            st.session_state["json_text"] = (config.DEMO_DIR / "intake_example.json").read_text()
        up = st.file_uploader("Or upload a .json file", type=["json"])
        if up is not None:
            st.session_state["json_text"] = up.getvalue().decode()
        text = st.text_area("JSON", key="json_text", height=300)
        assess = st.checkbox("Run AI assessment after import", value=True, key="imp_assess")
        if st.button("Import", type="primary", disabled=bool(hint)):
            created, errors = wf.import_json(conn(), text, current_actor())
            for e in errors:
                st.error(e)
            if created:
                st.session_state.setdefault("_toasts", []).append(f"Imported {', '.join(created)}")
                if len(created) == 1:
                    _after_create(created[0], assess)
                else:
                    for x in created:
                        if assess:
                            provider, _ = provider_for_mode()
                            run_inline(lambda x=x: wf.run_assessment(conn(), x, provider, wf.SYSTEM_ACTOR))
                    st.success(f"Imported {len(created)} reports.")
