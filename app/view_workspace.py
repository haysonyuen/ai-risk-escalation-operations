from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from common import section, badge, conn, current_actor, flash, md, provider_for_mode, run_action, sev_badge, source_badge
from riskops import communications, dedup, workflow as wf
from riskops.db import rows
from riskops.schemas import REVERSIBLE_CONTAINMENT, ROUTES, SEVERITIES, Evidence

TEAMS = ["Incident Lead", "Risk Ops", "Safety", "Support", "Engineering", "Product Security", "Product/UX",
         "Legal/Privacy", "Enterprise/CS", "Data/Analytics"]
EVIDENCE_TYPES = ["reporter_statement", "conversation_excerpt", "tool_action_log", "file_diff", "approval_event",
                  "telemetry", "classifier_output", "account_settings", "screenshot_description", "reviewer_note"]


def _header(inc, a) -> None:
    sev, basis = wf.effective_severity(conn(), inc)
    st.title(f"{inc['incident_id']} · {inc['title']}")
    parts = [badge(wf.STAGE[inc["status"]], "b-muted"), badge(f"status {inc['status']}", "b-muted"),
             "AI after controls: " + (sev_badge(a["controlled_severity"]) if a else sev_badge(None)),
             source_badge(a["provider_kind"] if a else "none"),
             "Human decision: " + (sev_badge(inc["human_severity"]) + badge("human", "b-human") if inc["human_severity"] else badge("pending", "b-muted")),
             f"Owner: <b>{html.escape(inc['owner'] or 'unassigned')}</b>",
             badge(f"origin: {inc['origin']}", "b-muted")]
    md(" &nbsp; ".join(parts))
    if basis != "human":
        st.info(f"No human severity decision yet. Deadlines and routing use {sev} ({basis.replace('_', ' ')}). A person must confirm or correct it.")


def _report_tab(inc, intake) -> None:
    c = conn()
    st.subheader("Original report")
    st.caption("Incident text is untrusted data. Instructions inside it are flagged, never followed.")
    st.text(intake.reported_behavior)
    fields = ["reported_at", "product_surface", "customer_type", "reporter_channel", "reported_impact", "model_version",
              "file_action", "external_action_attempted", "user_approved", "sensitive_data", "scope", "recurrence", "reversibility"]
    cells = []
    for f in fields:
        v = getattr(intake, f)
        v = v.isoformat() if hasattr(v, "isoformat") else v
        cls = ' class="unknown"' if v == "unknown" else ""
        cells.append(f"<tr><td class='small'>{f}</td><td{cls}>{html.escape(str(v))}</td></tr>")
    md("<table class='kv'>" + "".join(cells) + "</table>")
    st.caption("Values marked in red are explicitly unknown — they were not guessed.")
    st.subheader("Evidence records")
    ev = rows(c, "SELECT evidence_id, source_type, source_description, content, added_at, added_by, origin FROM evidence WHERE incident_id=? ORDER BY rowid", (inc["incident_id"],))
    st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
    with st.form("add_evidence"):
        st.markdown("**Add evidence** (adding evidence to a closed case reopens it)")
        e1, e2 = st.columns(2)
        eid = e1.text_input("Evidence ID (stable, unique)", value=f"E{len(ev) + 1}")
        et = e2.selectbox("Source type", EVIDENCE_TYPES)
        desc = st.text_input("Source description")
        content = st.text_area("Content (synthetic only)")
        if st.form_submit_button("Add evidence"):
            run_action(lambda: wf.add_evidence(c, inc["incident_id"], Evidence(evidence_id=eid, source_type=et,
                       source_description=desc or "unspecified", content=content), current_actor()), "Evidence added")
            st.rerun()


def _assessment_tab(inc, intake, a) -> None:
    c = conn()
    provider, mode = provider_for_mode()
    col1, col2 = st.columns([3, 2])
    with col2:
        st.caption(f"Provider mode: `{mode}`")
        if st.button("Run AI assessment" if not a else "Re-run AI assessment (keeps history, never changes human decisions)"):
            with st.spinner("Assessing…"):
                run_action(lambda: wf.run_assessment(c, inc["incident_id"], provider, current_actor()), "Assessment recorded")
            st.rerun()
    if not a:
        st.warning("No assessment yet.")
        return
    with col1:
        md(source_badge(a["provider_kind"]) + badge(f"rules {a['rule_version']}", "b-muted")
           + badge(f"prompt {a['prompt_version']}", "b-muted") + badge(json.loads(a['controls_json']).get('controls_version') or 'controls-v1.0', "b-muted")
           + badge(f"model {a['model_name'] or 'n/a'}", "b-muted") + badge(a["assessment_id"], "b-muted"))
        st.caption(f"Created {a['created_at']} · latency {a['latency_ms'] or 0:.1f} ms"
                   + (f" · tokens {a['input_tokens']}/{a['output_tokens']} · est. ${a['cost_usd']:.4f}" if a["cost_usd"] else ""))
    ctl = json.loads(a["controls_json"])
    for note in ctl.get("provider_notes") or []:
        st.caption(f"Provider note: {note}")
    if a["status"] == "failed":
        st.error(f"AI assessment FAILED ({a['error_kind']}): {a['error']}. No assessment was invented. Case is routed to manual review.")
        st.markdown(f"Deterministic rules recommendation (clearly **rules output, not AI**): {a['controlled_severity']} → `{a['controlled_route']}`")
    o = a["output"]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.markdown("**Potential impact**<br>" + ctl["impact"], unsafe_allow_html=True)
    m2.markdown("**Evidence quality**<br>" + ctl["evidence_quality"], unsafe_allow_html=True)
    m3.markdown("**Confidence**<br>" + ctl["confidence"], unsafe_allow_html=True)
    m4.markdown("**Recommended (provider)**<br>" + sev_badge(a["model_severity"]), unsafe_allow_html=True)
    m5.markdown("**After deterministic controls**<br>" + sev_badge(a["controlled_severity"]) + f" → `{a['controlled_route']}`", unsafe_allow_html=True)
    st.caption("Impact, evidence quality and confidence are assessed separately from severity. Low confidence never lowers severity.")

    if o:
        st.markdown("**Summary**")
        st.write(o["summary"])
        st.markdown("**Reported facts** (each cites evidence; a valid reference is not proof — use the support review)")
        refs = {f["fact_index"]: f for f in ctl["fact_ref_status"]}
        reviews = rows(c, "SELECT fact_index, verdict, reviewer, reviewed_at FROM claim_reviews WHERE assessment_id=? ORDER BY review_id", (a["assessment_id"],))
        latest = {r["fact_index"]: r for r in reviews}
        for i, f in enumerate(o["reported_facts"]):
            st_ref = refs.get(i, {})
            ref_txt = ", ".join(f["evidence_ids"])
            bad = st_ref.get("invalid_refs")
            tag = badge(f"INVALID REF: {', '.join(bad)}", "b-fault") if bad else badge("refs exist · support unverified", "b-muted")
            if i in latest:
                tag += badge(f"support: {latest[i]['verdict']} ({latest[i]['reviewer']})", "b-human")
            md(f"{i}. {html.escape(f['statement'])} <span class='small'>[{ref_txt}]</span> {tag}")
        with st.form("claim_review"):
            cc1, cc2, cc3 = st.columns([1, 2, 3])
            fi = cc1.selectbox("Fact #", list(range(len(o["reported_facts"]))))
            verdict = cc2.selectbox("Does the cited evidence support it?", wf.CLAIM_VERDICTS)
            note = cc3.text_input("Note")
            if st.form_submit_button("Record support review"):
                run_action(lambda: wf.record_claim_review(c, a["assessment_id"], fi, verdict, current_actor(), note), "Support review recorded")
                st.rerun()
        h1, h2 = st.columns(2)
        with h1:
            st.markdown("**Hypotheses (not facts)**")
            for h in o["hypotheses"] or [{"statement": "None", "basis": ""}]:
                st.markdown(f"- _{h['statement']}_ — basis: {h['basis']}")
            st.markdown("**Missing information**")
            for mi in o["missing_information"] or ["None listed"]:
                st.markdown(f"- {mi}")
        with h2:
            st.markdown("**Contradictions**")
            for co in o["contradictions"] or [{"description": "None listed", "evidence_ids": []}]:
                st.markdown(f"- {co['description']} {co['evidence_ids'] or ''}")
            st.markdown("**Risk categories:** " + ", ".join(o["risk_categories"]))
            st.markdown(f"**Severity rationale:** {o['severity_rationale']}")
            st.markdown(f"**Confidence justification:** {o['confidence_justification']}")
        st.markdown("**Recommended next steps**")
        for s in o["next_steps"]:
            st.markdown(f"- {s}")
        with st.expander("Draft incident brief (from assessment)"):
            st.write(o["incident_brief"])
    st.markdown("**Mandatory human-review reasons**")
    if ctl["review_reasons"]:
        st.dataframe(pd.DataFrame(ctl["review_reasons"]), use_container_width=True, hide_index=True)
    else:
        st.caption("None flagged (standard triage; P2/P3 closures are QA-sampled).")
    st.markdown("**Deterministic controls applied**")
    st.dataframe(pd.DataFrame(ctl["controls"] or [{"id": "-", "effect": "none", "detail": ""}]), use_container_width=True, hide_index=True)
    rr = a["rule_result"]
    with st.expander(f"Triggered rules ({a['rule_version']}) and signals"):
        st.dataframe(pd.DataFrame(rr["triggered_rules"]), use_container_width=True, hide_index=True)
        if rr["injection_findings"]:
            st.warning("Embedded instructions detected (ignored): " + "; ".join(f"{x['location']}: {x['reason']}" for x in rr["injection_findings"]))
        st.write({k: v for k, v in rr["signals"].items() if v and not k.endswith("_in_system_evidence")})
        st.caption(f"Matched lexicon terms: {rr['matched_terms']}")
    if ctl.get("raw_text"):
        with st.expander("Raw provider output"):
            st.code(ctl["raw_text"][:6000])
    hist = wf.list_assessments(c, inc["incident_id"])
    if len(hist) > 1:
        with st.expander(f"Assessment history ({len(hist)} runs, all preserved)"):
            st.dataframe(pd.DataFrame([{k: h[k] for k in ("assessment_id", "created_at", "provider_kind", "rule_version", "prompt_version",
                                                           "status", "error_kind", "model_severity", "controlled_severity", "controlled_route")}
                                       for h in hist]), use_container_width=True, hide_index=True)


def _triage_tab(inc, intake, a) -> None:
    c = conn()
    ev_ids = [e.evidence_id for e in intake.evidence]
    st.subheader("Human severity & routing decision")
    if a:
        md(f"AI recommendation after controls: {sev_badge(a['controlled_severity'])} → <code>{a['controlled_route']}</code> "
           f"{source_badge(a['provider_kind'])}")
    if inc["human_severity"]:
        md(f"Current human decision: {sev_badge(inc['human_severity'])} → <code>{inc['human_route']}</code> "
           f"by {inc['severity_decided_by']} at {inc['severity_decided_at']} {badge('human', 'b-human')}")
    default_sev = inc["human_severity"] or (a["controlled_severity"] if a else "P1")
    default_route = inc["human_route"] or (a["controlled_route"] if a else "risk_ops")
    default_teams = json.loads(inc["human_teams_json"] or "null") or (a["rule_result"]["teams"] if a else ["Risk Ops"])
    with st.form("decision"):
        d1, d2 = st.columns(2)
        sev = d1.selectbox("Severity", SEVERITIES, index=SEVERITIES.index(default_sev))
        route = d2.selectbox("Primary route", ROUTES, index=ROUTES.index(default_route) if default_route in ROUTES else 0)
        teams = st.multiselect("Teams involved", TEAMS, default=[t for t in default_teams if t in TEAMS])
        evr = st.multiselect("Source evidence I reviewed (required for P0/P1)", ev_ids)
        code = st.selectbox("Override reason (required if different from AI recommendation)", ["(none)"] + list(wf.OVERRIDE_REASONS),
                            format_func=lambda k: wf.OVERRIDE_REASONS.get(k, k))
        reason = st.text_area("Rationale")
        if st.form_submit_button("Record decision"):
            run_action(lambda: wf.decide_severity(c, inc["incident_id"], current_actor(), sev, route, teams, reason,
                                                  None if code == "(none)" else code, evr), "Decision recorded")
            st.rerun()
    st.subheader("Ownership & stage")
    o1, o2 = st.columns(2)
    with o1.form("owner"):
        people = [a_.actor_id for a_ in wf.SIMULATED_ACTORS]
        owner = st.selectbox("Owner", people, index=people.index(inc["owner"]) if inc["owner"] in people else 0)
        why = st.text_input("Reason (optional)")
        if st.form_submit_button("Assign owner"):
            run_action(lambda: wf.assign_owner(c, inc["incident_id"], owner, current_actor(), why), "Owner assigned")
            st.rerun()
    with o2:
        allowed = wf.allowed_manual_transitions(inc["status"])
        st.caption(f"Current: {inc['status']} ({wf.STAGE[inc['status']]}). Allowed manual moves: {', '.join(allowed) or 'none'}")
        if allowed:
            to = st.selectbox("Move to", allowed)
            tr = st.text_input("Transition note")
            if st.button("Apply transition"):
                run_action(lambda: wf.transition(c, inc["incident_id"], to, current_actor(), tr), f"Moved to {to}")
                st.rerun()
    st.subheader("Investigation notes")
    with st.form("note"):
        txt = st.text_area("Note")
        if st.form_submit_button("Add note"):
            run_action(lambda: wf.add_note(c, inc["incident_id"], txt, current_actor()), "Note added")
            st.rerun()
    notes = [e for e in wf.timeline(c, inc["incident_id"]) if e["event_type"] == "investigation_note"]
    for n in notes:
        st.markdown(f"- **{n['actor_id']}** ({n['ts']}): {n['new_value']}")


def _containment_tab(inc, a) -> None:
    c = conn()
    md(badge("ALL CONTAINMENT IS SIMULATED — nothing is executed against any system", "b-sim-action"))
    sev, basis = wf.effective_severity(c, inc)
    st.caption(f"Approval rule (enforced in the service layer): effective severity {sev} ({basis}) → "
               + ("Incident Lead approval required." if sev in ("P0", "P1") else "Risk Ops or Incident Lead may approve.")
               + " Account lockout requires human-confirmed P0 and a detailed rationale.")
    if a and a["output"] and a["output"]["containment_options"]:
        st.markdown("**AI-suggested options** (reversible, proposals only)")
        for i, opt in enumerate(a["output"]["containment_options"]):
            cc1, cc2 = st.columns([5, 1])
            cc1.markdown(f"- `{opt['action_type']}` on _{opt['target']}_ — {opt['rationale']} (reversible: {opt['reversible']})")
            if cc2.button("Propose", key=f"prop{i}"):
                run_action(lambda: wf.propose_containment(c, inc["incident_id"], wf.SYSTEM_ACTOR, opt["action_type"], opt["target"],
                                                          opt["rationale"], source="ai"), "Proposed (source: AI)")
                st.rerun()
    with st.form("custom_containment"):
        st.markdown("**Propose containment**")
        types = sorted(REVERSIBLE_CONTAINMENT) + ["account_lockout"]
        t = st.selectbox("Action type", types)
        target = st.text_input("Target (narrowest effective scope)")
        why = st.text_input("Rationale")
        if st.form_submit_button("Propose"):
            run_action(lambda: wf.propose_containment(c, inc["incident_id"], current_actor(), t, target, why), "Proposed")
            st.rerun()
    acts = rows(c, "SELECT * FROM containment_actions WHERE incident_id=? ORDER BY proposed_at", (inc["incident_id"],))
    for act in acts:
        with st.container(border=True):
            md(f"<b>{act['action_id']}</b> · <code>{act['action_type']}</code> on {html.escape(act['target'])} · "
               + badge(act["status"].upper(), "b-p1" if act["status"] == "active" else "b-muted")
               + badge("SIMULATED", "b-sim-action") + badge(f"proposed by {act['proposed_by']} ({act['proposed_source']})", "b-muted"))
            st.caption(f"Rationale: {act['rationale']}" + (f" · Decision by {act['decided_by']}: {act['decision_reason']}" if act["decided_by"] else "")
                       + (f" · Review by {act['review_by']} · Expires {act['expires_at']}" if act["review_by"] else "")
                       + (f" · Ended by {act['ended_by']}: {act['end_reason']}" if act["ended_by"] else ""))
            if act["status"] == "proposed":
                k = act["action_id"]
                r1, r2, r3 = st.columns(3)
                reason = r1.text_input("Decision reason", key=f"r{k}")
                rv = r2.number_input("Review in (hours)", 1, 168, 24, key=f"rv{k}")
                ex = r3.number_input("Expires in (hours)", 1, 720, 72, key=f"ex{k}")
                b1, b2 = st.columns(2)
                now = datetime.now(timezone.utc)
                if b1.button("Approve (simulated)", key=f"ap{k}"):
                    run_action(lambda: wf.decide_containment(c, k, current_actor(), True, reason, now + timedelta(hours=rv), now + timedelta(hours=ex)),
                               "Approved — simulated containment active")
                    st.rerun()
                if b2.button("Reject", key=f"rj{k}"):
                    run_action(lambda: wf.decide_containment(c, k, current_actor(), False, reason), "Rejected")
                    st.rerun()
            elif act["status"] == "active":
                k = act["action_id"]
                reason = st.text_input("Reason to reverse", key=f"end{k}")
                if st.button("Reverse (simulated)", key=f"endb{k}"):
                    run_action(lambda: wf.end_containment(c, k, current_actor(), reason), "Reversed")
                    st.rerun()


def _comms_tab(inc) -> None:
    c = conn()
    md(badge("DRAFTS ONLY — nothing is ever sent", "b-sim-action"))
    cols = st.columns(4)
    _, mode = provider_for_mode()
    for col, (ct, label) in zip(cols, communications.COMM_TYPES.items()):
        if col.button(f"Draft: {label}", key=f"gen{ct}"):
            run_action(lambda: communications.generate(c, inc["incident_id"], ct, current_actor(), use_live=(mode == "live")),
                       f"{label} drafted")
            st.rerun()
    st.caption("Offline mode uses templates. Live mode optionally tightens the template with the model; if that fails the template is kept and labeled.")
    for cm in wf.latest_communications(c, inc["incident_id"]):
        spec = json.loads(cm["specialist_review_json"])
        with st.container(border=True):
            md(f"<b>{communications.COMM_TYPES[cm['comm_type']]}</b> · {cm['comm_id']} v{cm['version']} · "
               + badge(cm["status"].upper(), "b-human" if cm["status"] == "approved" else "b-muted")
               + badge(f"generator: {cm['generator']}", "b-live" if cm["generator"] == "live_model" else "b-muted")
               + "".join(badge(f"needs {s} review" + (" ✓" if s in spec["approvals"] else ""), "b-p1") for s in spec["required"])
               + badge("NOT SENT", "b-sim-action"))
            key = f"{cm['comm_id']}v{cm['version']}"
            body = st.text_area("Body", cm["body"], height=260, key=f"body{key}")
            b1, b2, b3 = st.columns(3)
            if b1.button("Save edit as new version", key=f"save{key}"):
                run_action(lambda: wf.save_communication(c, inc["incident_id"], cm["comm_type"], body, json.loads(cm["evidence_refs_json"]),
                                                         spec["required"], current_actor(), "human_edit", comm_id=cm["comm_id"]),
                           "Saved new version (approvals reset)")
                st.rerun()
            note = b2.text_input("Review note", key=f"note{key}")
            if b3.button("Approve for (simulated) use", key=f"ok{key}"):
                run_action(lambda: wf.review_communication(c, cm["comm_id"], current_actor(), True, note), "Review recorded")
                st.rerun()
            if b3.button("Reject", key=f"no{key}"):
                run_action(lambda: wf.review_communication(c, cm["comm_id"], current_actor(), False, note), "Rejected")
                st.rerun()
            versions = rows(c, "SELECT version, status, generator, created_by, created_at, reviewed_by FROM communications WHERE comm_id=? ORDER BY version", (cm["comm_id"],))
            if len(versions) > 1:
                st.caption("Version history: " + "; ".join(f"v{v['version']} {v['generator']} by {v['created_by']} ({v['status']})" for v in versions))


def _links_tab(inc) -> None:
    c = conn()
    st.caption("Suggestions only. Confirming a link never merges records, deletes evidence, or changes either incident's status.")
    if st.button("Find related reports"):
        target = wf.get_intake(c, inc["incident_id"])
        others = [wf.get_intake(c, r["incident_id"]) for r in rows(c, "SELECT incident_id FROM incidents")]
        n = wf.record_link_suggestions(c, inc["incident_id"], dedup.suggest(target, others))
        flash("info", f"{n} new suggestion(s)")
        st.rerun()
    for lk in wf.links_for(c, inc["incident_id"]):
        other = lk["incident_b"] if lk["incident_a"] == inc["incident_id"] else lk["incident_a"]
        oi = wf.get_incident(c, other)
        osev, obasis = wf.effective_severity(c, oi)
        with st.container(border=True):
            md(f"<b>{other}</b> · {html.escape(oi['title'])} · {sev_badge(osev)} ({obasis}) · status {oi['status']} · "
               + badge(f"{lk['status']} {lk['link_type'] if lk['status'] != 'suggested' else ''}", "b-muted") + f" score {lk['score']}")
            st.caption(f"Why suggested: {lk['explanation']}" + (f" · Decision: {lk['reason']} ({lk['decided_by']})" if lk["decided_by"] else ""))
            if lk["status"] == "suggested":
                k = lk["link_id"]
                l1, l2 = st.columns(2)
                lt = l1.selectbox("Relationship", ["duplicate", "related"], key=f"lt{k}")
                why = l2.text_input("Reason", key=f"lw{k}")
                b1, b2 = st.columns(2)
                if b1.button("Confirm", key=f"lc{k}"):
                    run_action(lambda: wf.decide_link(c, k, current_actor(), True, lt, why), "Link confirmed")
                    st.rerun()
                if b2.button("Reject", key=f"lr{k}"):
                    run_action(lambda: wf.decide_link(c, k, current_actor(), False, lt, why), "Link rejected")
                    st.rerun()


def _timeline_tab(inc) -> None:
    ev = wf.timeline(conn(), inc["incident_id"])
    st.caption("Append-only application events (SQLite triggers reject UPDATE/DELETE). A local integrity guard — not tamper-proof: "
               "anyone with file access can alter the database. 'origin' distinguishes seeded history from actions taken in this demo.")
    df = pd.DataFrame([{k: e[k] for k in ("ts", "actor_id", "actor_role", "event_type", "field", "previous_value", "new_value", "reason", "origin")} for e in ev])
    st.dataframe(df, use_container_width=True, hide_index=True, height=min(38 * (len(ev) + 1), 600))


def _closure_tab(inc, intake) -> None:
    c = conn()
    if inc["closure_json"]:
        st.markdown("**Closure record**" + (" (from an earlier closure; case was reopened)" if inc["status"] not in ("CLOSED", "QA_REVIEWED") else ""))
        st.json(json.loads(inc["closure_json"]))
    if inc["status"] == "RESPONSE":
        st.markdown(f"**Close with human sign-off** — required role: {'Incident Lead' if inc['human_severity'] in ('P0', 'P1') else 'Risk Ops or Incident Lead'}")
        with st.form("close"):
            cat = st.selectbox("Closure category", wf.CLOSURE_CATEGORIES)
            fs = st.selectbox("Final severity (must match the human decision)", SEVERITIES,
                              index=SEVERITIES.index(inc["human_severity"]) if inc["human_severity"] else 0)
            rc = st.text_input("Root cause")
            imp = st.text_input("User / customer impact")
            evr = st.multiselect("Evidence reviewed", [e.evidence_id for e in intake.evidence])
            teams = st.multiselect("Teams involved", TEAMS, default=json.loads(inc["human_teams_json"] or "[]"))
            acts = st.text_area("Actions taken")
            resp = st.text_input("Response status", value="Drafts approved; not sent (simulation)")
            rem = st.text_input("Remaining mitigation / follow-up")
            mon = st.checkbox("Monitoring required")
            ack = st.checkbox("Acknowledge that simulated containment remains active (with review date)")
            sign = st.text_area("Sign-off statement")
            if st.form_submit_button("Sign off and close"):
                run_action(lambda: wf.close_incident(c, inc["incident_id"], {
                    "closure_category": cat, "final_severity": fs, "root_cause": rc, "user_customer_impact": imp,
                    "evidence_reviewed": evr, "teams_involved": teams, "actions_taken": acts, "response_status": resp,
                    "remaining_mitigation": rem, "monitoring_required": mon, "acknowledge_active_containment": ack,
                    "sign_off_statement": sign}, current_actor()), "Closed with human sign-off")
                st.rerun()
    elif inc["status"] not in ("CLOSED", "QA_REVIEWED"):
        st.info(f"Closure is available from the RESPONSE stage (current: {inc['status']}).")
    if inc["status"] == "CLOSED":
        with st.form("qa"):
            st.markdown("**Quality review (stage 8)** — sample closed cases to catch missed escalations")
            outcome = st.selectbox("Outcome", wf.QA_OUTCOMES)
            notes = st.text_area("QA notes")
            if st.form_submit_button("Record QA review"):
                run_action(lambda: wf.qa_review(c, inc["incident_id"], current_actor(), outcome, notes), "QA review recorded")
                st.rerun()
    if inc["status"] in ("CLOSED", "QA_REVIEWED"):
        with st.form("reopen"):
            why = st.text_input("Reason to reopen")
            if st.form_submit_button("Reopen"):
                run_action(lambda: wf.reopen(c, inc["incident_id"], current_actor(), why), "Reopened")
                st.rerun()


def render() -> None:
    c = conn()
    ids = [r["incident_id"] for r in rows(c, "SELECT incident_id FROM incidents ORDER BY reported_at DESC")]
    if not ids:
        st.info("No incidents. Create one in New intake or reset demo data.")
        return
    sel = st.session_state.get("selected_incident", ids[0])
    sel = st.selectbox("Incident", ids, index=ids.index(sel) if sel in ids else 0)
    st.session_state["selected_incident"] = sel
    inc = wf.get_incident(c, sel)
    intake = wf.get_intake(c, sel)
    a = wf.get_assessment(c, inc["current_assessment_id"])
    _header(inc, a)
    labels = ["Report & evidence", "AI assessment", "Triage, routing & notes", "Containment (simulated)",
              "Communications (drafts)", "Related reports", "Timeline & audit", "Closure & QA"]
    sec = section(labels, key="ws_section")
    if sec == labels[0]:
        _report_tab(inc, intake)
    elif sec == labels[1]:
        _assessment_tab(inc, intake, a)
    elif sec == labels[2]:
        _triage_tab(inc, intake, a)
    elif sec == labels[3]:
        _containment_tab(inc, a)
    elif sec == labels[4]:
        _comms_tab(inc)
    elif sec == labels[5]:
        _links_tab(inc)
    elif sec == labels[6]:
        _timeline_tab(inc)
    else:
        _closure_tab(inc, intake)
