"""Case page: left = the case file, right = what needs doing (only what the current role may do is enabled)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from common import (humanize, BASIS_LABEL, CATEGORY_LABEL, CONTROL_TEXT, EVIDENCE_TYPES, FIELD_LABEL, ROUTE_LABEL, STATUS_LABEL,
                    TEAMS, actor_name, ago, badge, conn, current_actor, describe_event, esc, feedback, go, md,
                    permission_hint, pretty, provider_for_mode, relative, run_action, run_inline, section, sev_badge,
                    source_badge, stepper)
from riskops import communications, dedup, monitoring, workflow as wf
from riskops.db import rows
from riskops.schemas import REVERSIBLE_CONTAINMENT, ROUTES, SEVERITIES, Evidence

TRANSITION_LABEL = {("TRIAGED", "INVESTIGATING"): "Start investigation", ("TRIAGED", "RESPONSE"): "Skip to response",
                    ("INVESTIGATING", "CONTAINMENT"): "Move to containment", ("INVESTIGATING", "RESPONSE"): "Move to response",
                    ("CONTAINMENT", "INVESTIGATING"): "Back to investigation", ("CONTAINMENT", "RESPONSE"): "Move to response",
                    ("RESPONSE", "INVESTIGATING"): "Back to investigation"}
CLOSED = ("CLOSED", "QA_REVIEWED")
VERDICT_LABEL = {"supported": "✓ Supported", "partially_supported": "~ Partly", "unsupported": "✗ Unsupported", "cannot_determine": "? Can't tell"}


# ============================================================================ dialogs

@st.dialog("Add evidence", width="large")
def add_evidence_dialog(iid: str, next_id: str) -> None:
    st.caption("Synthetic data only. Evidence IDs are permanent. Adding evidence to a closed case reopens it.")
    c1, c2 = st.columns([1, 2])
    eid = c1.text_input("Evidence ID", value=next_id)
    et = c2.selectbox("Source type", EVIDENCE_TYPES, format_func=pretty)
    desc = st.text_input("Source description", placeholder="e.g. Link access log export")
    content = st.text_area("Content", height=140)
    if st.button("Add evidence", type="primary"):
        if run_inline(lambda: wf.add_evidence(conn(), iid, Evidence(evidence_id=eid, source_type=et,
                      source_description=desc or "unspecified", content=content), current_actor()), f"Evidence {eid} added"):
            st.rerun()


@st.dialog("Communication draft", width="large")
def comm_dialog(comm_id: str) -> None:
    c = conn()
    me = current_actor()
    cm = rows(c, "SELECT * FROM communications WHERE comm_id=? ORDER BY version DESC LIMIT 1", (comm_id,))[0]
    spec = json.loads(cm["specialist_review_json"])
    md(badge(communications.COMM_TYPES[cm["comm_type"]]) + badge(f"v{cm['version']}") + badge(cm["status"].upper(), "b-human" if cm["status"] == "approved" else "b-muted")
       + "".join(badge(f"{s} review {'✓' if s in spec['approvals'] else 'needed'}", "b-human" if s in spec["approvals"] else "b-warn") for s in spec["required"])
       + badge("NOT SENT · simulation", "b-sim-action"))
    body = st.text_area("Draft", cm["body"], height=380, key=f"cmbody_{comm_id}_{cm['version']}")
    b1, b2, b3 = st.columns([2, 1, 1])
    if b1.button("Save edits as new version", disabled=body == cm["body"]):
        if run_inline(lambda: wf.save_communication(c, cm["incident_id"], cm["comm_type"], body, json.loads(cm["evidence_refs_json"]),
                                                    spec["required"], me, "human_edit", comm_id=comm_id), "New draft version saved"):
            st.rerun()
    required = [s for s in spec["required"] if s not in spec["approvals"]]
    may_review = (any(wf.SPECIALIST_REVIEW_ROLE[s] == me.role for s in required) if spec["required"]
                  else wf.can(me, "approve_communication_general"))
    hint = None if may_review else ("Needs review by " + ", ".join(required) if required else "Requires Risk Ops or Incident Lead")
    note = st.text_input("Review note (optional)")
    if b2.button("Approve", type="primary", disabled=bool(hint) or cm["status"] == "approved", help=hint):
        if run_inline(lambda: wf.review_communication(c, comm_id, me, True, note), "Review recorded"):
            st.rerun()
    if b3.button("Reject", disabled=bool(hint), help=hint):
        if run_inline(lambda: wf.review_communication(c, comm_id, me, False, note), "Draft rejected"):
            st.rerun()
    if hint:
        st.caption(hint)
    vers = rows(c, "SELECT version, generator, created_by, created_at, status FROM communications WHERE comm_id=? ORDER BY version", (comm_id,))
    st.caption("Versions: " + " · ".join(f"v{v['version']} {pretty(v['generator'])} by {actor_name(v['created_by'])} ({v['status']})" for v in vers))


@st.dialog("Close case", width="large")
def close_dialog(iid: str) -> None:
    c = conn()
    inc = wf.get_incident(c, iid)
    intake = wf.get_intake(c, iid)
    active = rows(c, "SELECT * FROM containment_actions WHERE incident_id=? AND status='active'", (iid,))
    md(f"Final severity {sev_badge(inc['human_severity'], 'from the human decision')} · signing as <b>{esc(current_actor().display)}</b>")
    with st.form("closure"):
        cat = st.selectbox("Closure category", wf.CLOSURE_CATEGORIES, format_func=pretty)
        rc = st.text_input("Root cause")
        imp = st.text_input("User / customer impact")
        evr = st.multiselect("Evidence reviewed", [e.evidence_id for e in intake.evidence], default=[e.evidence_id for e in intake.evidence])
        teams = st.multiselect("Teams involved", TEAMS, default=[t for t in json.loads(inc["human_teams_json"] or "[]") if t in TEAMS])
        acts = st.text_area("Actions taken", height=80)
        c1, c2 = st.columns(2)
        resp = c1.text_input("Response status", value="Drafts approved; not sent (simulation)")
        rem = c2.text_input("Remaining mitigation / follow-up", value="None")
        mon = st.checkbox("Monitoring required")
        ack = False
        if active:
            ack = st.checkbox(f"Keep {len(active)} simulated containment action(s) active after closure (review dates stay in force)")
        sign = st.text_area("Sign-off statement", placeholder="What you reviewed and why the case can close", height=70)
        if st.form_submit_button("Sign off and close", type="primary"):
            if run_inline(lambda: wf.close_incident(c, iid, {
                    "closure_category": cat, "final_severity": inc["human_severity"], "root_cause": rc, "user_customer_impact": imp,
                    "evidence_reviewed": evr, "teams_involved": teams, "actions_taken": acts, "response_status": resp,
                    "remaining_mitigation": rem, "monitoring_required": mon, "acknowledge_active_containment": ack,
                    "sign_off_statement": sign}, current_actor()), "Case closed with sign-off"):
                st.rerun()


@st.dialog("Reopen case")
def reopen_dialog(iid: str) -> None:
    why = st.text_area("Why is the case being reopened?")
    if st.button("Reopen", type="primary"):
        if run_inline(lambda: wf.reopen(conn(), iid, current_actor(), why), "Case reopened"):
            st.rerun()


# ============================================================================ left: case file

def _report(inc, intake) -> None:
    st.markdown("#### Report")
    md(f'<div class="quote">{esc(intake.reported_behavior)}</div>')
    if intake.reported_impact != "unknown":
        md(f"<b>Reported impact:</b> {esc(intake.reported_impact)}")
    cells = [f"<div><span>Reported</span>{esc(intake.reported_at.strftime('%d %b %H:%M UTC'))} · {ago(intake.reported_at.isoformat())}</div>"]
    for f, label in FIELD_LABEL.items():
        v = getattr(intake, f)
        val = '<span class="unknown">Unknown</span>' if v == "unknown" else esc(pretty(v))
        cells.append(f"<div><span>{label}</span>{val}</div>")
    md(f'<div class="kv">{"".join(cells)}</div>')


def _assessment(inc, intake, a) -> None:
    c = conn()
    me = current_actor()
    st.markdown("#### AI assessment")
    if not a:
        st.info("Not assessed yet.")
        _rerun_button(inc, "Run AI assessment")
        return
    md(source_badge(a["provider_kind"]) + f'<span class="small">rules {a["rule_version"]} · prompt {a["prompt_version"]} · '
       f'{json.loads(a["controls_json"]).get("controls_version", "controls-v1.0")} · {ago(a["created_at"])}</span>')
    ctl = json.loads(a["controls_json"])
    if a["status"] == "failed":
        st.error(f"The AI assessment failed ({pretty(a['error_kind'])}). No assessment was invented — triage from the evidence. "
                 f"For reference only, the deterministic rules suggest {a['controlled_severity']} → {ROUTE_LABEL[a['controlled_route']]}.")
    else:
        o = a["output"]
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            st.caption("AI recommends")
            md(sev_badge(a["model_severity"]) + f" → {ROUTE_LABEL[o['suggested_primary_route']]}")
        with c2.container(border=True):
            st.caption("After safety controls")
            md(sev_badge(a["controlled_severity"]) + f" → <b>{ROUTE_LABEL[a['controlled_route']]}</b>")
        changed = [x for x in ctl["controls"] if x["id"] in ("C3", "C6")]
        if changed:
            st.caption("Changed by controls: " + "; ".join(f"{CONTROL_TEXT[x['id']]} ({humanize(x['detail'])})" for x in changed))
        md(f'{badge("Potential impact: " + ctl["impact"])}{badge("Evidence: " + ctl["evidence_quality"])}'
           f'{badge("Confidence: " + ctl["confidence"], "b-warn" if ctl["confidence"] == "low" else "b-muted")}'
           + "".join(badge(CATEGORY_LABEL.get(x, x)) for x in o["risk_categories"]))
        st.write(o["summary"])
    if ctl["review_reasons"]:
        texts = []
        for r in ctl["review_reasons"]:
            t = humanize(r["reason"])
            if not any(t == x or x.startswith(t) or t.startswith(x) for x in texts):
                texts.append(t)
        with st.container(border=True):
            st.markdown(f"**Why a human must review this** ({len(texts)})")
            for t in texts[:4]:
                st.markdown(f"- {t}")
            if len(texts) > 4:
                with st.expander(f"{len(texts) - 4} more"):
                    for t in texts[4:]:
                        st.markdown(f"- {t}")
    if a["status"] != "valid":
        return
    o = a["output"]
    ev = {e.evidence_id: e for e in intake.evidence}
    st.markdown("**Facts the AI extracted** — each shown with the evidence it cites. Mark whether the evidence supports it.")
    latest = {r["fact_index"]: r["verdict"] for r in rows(c, "SELECT fact_index, verdict FROM claim_reviews WHERE assessment_id=? ORDER BY review_id", (a["assessment_id"],))}
    can_review = wf.can(me, "claim_review")
    for i, f in enumerate(o["reported_facts"]):
        md(f"<b>{i + 1}.</b> {esc(f['statement'])} " + "".join(badge(r, "b-fault" if r not in ev else "b-muted") for r in f["evidence_ids"]))
        cites = []
        for r in f["evidence_ids"]:
            if r in ev:
                cites.append(f"<b>{r}</b> · {esc(ev[r].source_description)}: {esc(ev[r].content)}")
            else:
                cites.append(f'<span class="unknown">{r} does not exist in this case — treat this fact as unsupported</span>')
        md('<div class="cite">' + "<br>".join(cites) + "</div>")

        def _save(i=i, key=f"cv_{a['assessment_id']}_{i}"):
            v = st.session_state.get(key)
            if v:
                run_action(lambda: wf.record_claim_review(conn(), a["assessment_id"], i, v, current_actor()), "Support review saved", area="claims")
        st.pills("Supported by evidence?", wf.CLAIM_VERDICTS, format_func=VERDICT_LABEL.get, key=f"cv_{a['assessment_id']}_{i}",
                 default=latest.get(i), on_change=_save, disabled=not can_review, label_visibility="collapsed")
    feedback("claims")
    h1, h2, h3 = st.columns(3)
    with h1:
        st.markdown("**Hypotheses** (unverified)")
        for h in o["hypotheses"] or [{"statement": "None", "basis": ""}]:
            st.markdown(f"- _{h['statement']}_" + (f" <span class='small'>({esc(h['basis'])})</span>" if h["basis"] else ""), unsafe_allow_html=True)
    with h2:
        st.markdown("**Missing information**")
        for m in o["missing_information"] or ["None listed"]:
            st.markdown(f"- {m}")
    with h3:
        st.markdown("**Contradictions**")
        for x in o["contradictions"] or [{"description": "None found", "evidence_ids": []}]:
            st.markdown(f"- {x['description']} {' '.join(x['evidence_ids'])}")
    if o["next_steps"]:
        st.markdown("**AI-suggested next steps**")
        for s in o["next_steps"]:
            st.markdown(f"- {s}")


def _rerun_button(inc, label: str) -> None:
    hint = permission_hint("run_assessment")
    provider, mode = provider_for_mode()
    if inc["status"] in CLOSED:
        return
    if st.button(label, disabled=bool(hint), help=hint or f"Provider: {mode}. Earlier assessments are kept; human decisions are never changed."):
        run_action(lambda: wf.run_assessment(conn(), inc["incident_id"], provider, current_actor()), "Assessment recorded", area="assess")
        st.rerun()
    feedback("assess")


def _evidence(inc, intake) -> None:
    head, btn = st.columns([3, 1.3], vertical_alignment="center")
    head.markdown(f"#### Evidence ({len(intake.evidence)})")
    hint = permission_hint("add_evidence")
    if btn.button("＋ Add evidence", disabled=bool(hint), help=hint, use_container_width=True):
        add_evidence_dialog(inc["incident_id"], f"E{len(intake.evidence) + 1}")
    meta = {r["evidence_id"]: r for r in rows(conn(), "SELECT * FROM evidence WHERE incident_id=?", (inc["incident_id"],))}
    for e in intake.evidence:
        m = meta[e.evidence_id]
        with st.container(border=True):
            md(f"{badge(e.evidence_id, 'b-p3')} <b>{esc(e.source_description)}</b> {badge(pretty(e.source_type))}"
               f"<span class='small'> added by {esc(actor_name(m['added_by']))} · {ago(m['added_at'])}</span>")
            st.text(e.content)


def _activity(inc) -> None:
    c = conn()
    hint = permission_hint("add_note")
    with st.form("note", clear_on_submit=True):
        txt = st.text_area("Add an investigation note", height=70, disabled=bool(hint))
        if st.form_submit_button("Add note", disabled=bool(hint)):
            run_action(lambda: wf.add_note(c, inc["incident_id"], txt, current_actor()), "Note added", area="note")
            st.rerun()
    feedback("note")
    ev = wf.timeline(c, inc["incident_id"])
    for e in reversed(ev):
        md(f'<div class="evt">{describe_event(e)}<br><span class="t">{e["ts"].replace("T", " ")[:16]} UTC · '
           f'{esc(wf.ROLE_LABELS.get(e["actor_role"], e["actor_role"]))} · {"seeded history" if e["origin"] == "seed" else e["origin"]}</span></div>')
    with st.expander("Raw audit log"):
        st.caption("Append-only in the application (database triggers block edits). Not tamper-proof: anyone with file access can change the file.")
        df = pd.DataFrame([{k: e[k] for k in ("ts", "actor_id", "actor_role", "event_type", "field", "previous_value", "new_value", "reason", "origin")} for e in ev])
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("Download CSV", df.to_csv(index=False).encode(), file_name=f"{inc['incident_id']}_audit.csv")


def _related(inc) -> None:
    c = conn()
    head, btn = st.columns([3, 1.3], vertical_alignment="center")
    head.markdown("#### Related reports")
    if btn.button("Find related", use_container_width=True):
        target = wf.get_intake(c, inc["incident_id"])
        others = [wf.get_intake(c, r["incident_id"]) for r in rows(c, "SELECT incident_id FROM incidents")]
        n = wf.record_link_suggestions(c, inc["incident_id"], dedup.suggest(target, others))
        st.session_state.setdefault("_toasts", []).append(f"{n} new suggestion(s)")
        st.rerun()
    st.caption("Suggestions only. Confirming a link never merges cases, removes evidence or changes either case's status.")
    hint = permission_hint("decide_link")
    links = wf.links_for(c, inc["incident_id"])
    if not links:
        st.caption("No related reports found.")
    for lk in links:
        other = lk["incident_b"] if lk["incident_a"] == inc["incident_id"] else lk["incident_a"]
        oi = wf.get_incident(c, other)
        osev, obasis = wf.effective_severity(c, oi)
        with st.container(border=True):
            top, open_b = st.columns([5, 1])
            top.markdown(f"{sev_badge(osev, BASIS_LABEL[obasis])} <b>{other}</b> · {esc(oi['title'])} · {STATUS_LABEL[oi['status']]} "
                         + badge(f"{lk['status']}{' as ' + lk['link_type'] if lk['status'] != 'suggested' else ''}"), unsafe_allow_html=True)
            if open_b.button("Open case", key=f"open_{lk['link_id']}"):
                from common import go_case
                go_case(other)
            st.caption(f"Why suggested (score {lk['score']}): {lk['explanation']}" + (f" · Decision by {actor_name(lk['decided_by'])}: {lk['reason']}" if lk["decided_by"] else ""))
            if lk["status"] == "suggested":
                k = lk["link_id"]
                l1, l2, l3, l4 = st.columns([1.2, 2.5, 1, 1])
                lt = l1.selectbox("Type", ["duplicate", "related"], key=f"lt{k}", label_visibility="collapsed")
                why = l2.text_input("Reason", key=f"lw{k}", placeholder="Reason (required)", label_visibility="collapsed")
                if l3.button("Confirm", key=f"lc{k}", disabled=bool(hint), help=hint):
                    run_action(lambda: wf.decide_link(c, k, current_actor(), True, lt, why), "Link confirmed", area=f"lk{k}")
                    st.rerun()
                if l4.button("Reject", key=f"lr{k}", disabled=bool(hint), help=hint):
                    run_action(lambda: wf.decide_link(c, k, current_actor(), False, lt, why), "Link rejected", area=f"lk{k}")
                    st.rerun()
                feedback(f"lk{k}")


def _ai_details(inc, a) -> None:
    _rerun_button(inc, "Re-run AI assessment")
    if not a:
        return
    rr, ctl = a["rule_result"], json.loads(a["controls_json"])
    st.markdown("**Safety controls applied**")
    st.dataframe(pd.DataFrame([{"control": x["id"], "what it means": CONTROL_TEXT.get(x["id"], ""), "effect": x["effect"], "detail": x["detail"]}
                               for x in ctl["controls"]] or [{"control": "—", "what it means": "none triggered", "effect": "", "detail": ""}]),
                 hide_index=True, use_container_width=True)
    st.markdown(f"**Rules triggered** ({a['rule_version']})")
    st.dataframe(pd.DataFrame(rr["triggered_rules"] or [{"id": "—", "kind": "", "description": "no rule matched (default)"}]), hide_index=True, use_container_width=True)
    if rr["injection_findings"]:
        st.warning("Instructions embedded in the report (ignored): " + "; ".join(f"{x['location']}: {x['reason']}" for x in rr["injection_findings"]))
    with st.expander("Signals and matched terms"):
        st.write({k: v for k, v in rr["signals"].items() if v and not k.endswith("_in_system_evidence")})
        st.caption(f"Matched terms: {rr['matched_terms']}")
    if ctl.get("raw_text"):
        with st.expander("Raw provider output"):
            st.code(ctl["raw_text"][:6000])
    hist = wf.list_assessments(conn(), inc["incident_id"])
    st.markdown(f"**Assessment history** ({len(hist)} — all kept)")
    st.dataframe(pd.DataFrame([{"when": h["created_at"], "source": h["provider_kind"], "rules": h["rule_version"], "prompt": h["prompt_version"],
                                "status": h["status"], "AI": h["model_severity"], "after controls": h["controlled_severity"],
                                "route": h["controlled_route"]} for h in hist]), hide_index=True, use_container_width=True)


# ============================================================================ right: actions

def _decision_card(inc, intake, a) -> None:
    with st.container(border=True):
        st.markdown("**Severity & routing decision**")
        if inc["human_severity"]:
            md(f"Current: {sev_badge(inc['human_severity'], 'confirmed')} → <b>{ROUTE_LABEL[inc['human_route']]}</b>"
               f"<span class='small'> · {esc(actor_name(inc['severity_decided_by']))}, {ago(inc['severity_decided_at'])}</span>")
        if inc["status"] in CLOSED:
            st.caption("Reopen the case to change the decision.")
            return
        hint = permission_hint("decide_severity")
        holder = st.expander("Change decision", expanded=False) if inc["human_severity"] else st.container()
        with holder:
            _decision_form(inc, intake, a, hint)


def _decision_form(inc, intake, a, hint) -> None:
    c = conn()
    iid = inc["incident_id"]
    ai_sev = a["controlled_severity"] if a else None
    ai_route = a["controlled_route"] if a else None
    d_sev = inc["human_severity"] or ai_sev or "P1"
    d_route = inc["human_route"] or ai_route or "risk_ops"
    d_teams = json.loads(inc["human_teams_json"] or "null") or (a["rule_result"]["teams"] if a else ["Risk Ops"])
    c1, c2 = st.columns(2)
    sev = c1.selectbox("Severity", SEVERITIES, index=SEVERITIES.index(d_sev), key=f"d_sev_{iid}", disabled=bool(hint))
    route = c2.selectbox("Owning team (route)", ROUTES, index=ROUTES.index(d_route), format_func=ROUTE_LABEL.get,
                         key=f"d_route_{iid}", disabled=bool(hint))
    teams = st.multiselect("Teams involved", TEAMS, default=[t for t in d_teams if t in TEAMS], key=f"d_teams_{iid}", disabled=bool(hint))
    need_ev = sev in ("P0", "P1") or ai_sev in ("P0", "P1")
    evr = st.multiselect("Source evidence I reviewed" + (" (required)" if need_ev else ""), [e.evidence_id for e in intake.evidence],
                         key=f"d_ev_{iid}", disabled=bool(hint))
    override = bool(a) and (sev != ai_sev or route != ai_route)
    code = None
    if override:
        md(f"<span class='small'>Differs from the AI recommendation after controls ({ai_sev} → {ROUTE_LABEL[ai_route]}). "
           "This is recorded as an override and needs a reason.</span>")
        code = st.selectbox("Override reason", list(wf.OVERRIDE_REASONS), format_func=wf.OVERRIDE_REASONS.get, key=f"d_code_{iid}", disabled=bool(hint))
    needs_text = override or (inc["human_severity"] and inc["human_severity"] != sev)
    reason = st.text_area("Rationale" + (" (required)" if needs_text else " (optional)"), height=80, key=f"d_reason_{iid}", disabled=bool(hint))
    label = "Record override" if override else ("Confirm AI recommendation" if a and not inc["human_severity"] else "Record decision")
    if st.button(label, type="primary", disabled=bool(hint), help=hint, key=f"d_btn_{iid}", use_container_width=True):
        run_action(lambda: wf.decide_severity(c, iid, current_actor(), sev, route, teams, reason, code, evr),
                   "Decision recorded", area=f"dec_{iid}")
        st.rerun()
    if hint:
        st.caption(hint)
    feedback(f"dec_{iid}")


def _stage_card(inc) -> None:
    c = conn()
    iid = inc["incident_id"]
    with st.container(border=True):
        st.markdown("**Owner & stage**")
        o1, o2 = st.columns([3, 1], vertical_alignment="bottom")
        people = [x.actor_id for x in wf.SIMULATED_ACTORS]
        hint_o = permission_hint("assign_owner")
        owner = o1.selectbox("Owner", ["(unassigned)"] + people, index=(people.index(inc["owner"]) + 1) if inc["owner"] in people else 0,
                             format_func=lambda k: k if k == "(unassigned)" else wf.SIMULATED_ACTORS[people.index(k)].display.replace(" (simulated)", ""),
                             key=f"own_{iid}", disabled=bool(hint_o))
        if o2.button("Assign", disabled=bool(hint_o) or owner == "(unassigned)" or owner == inc["owner"], help=hint_o, key=f"own_b_{iid}", use_container_width=True):
            run_action(lambda: wf.assign_owner(c, iid, owner, current_actor()), "Owner assigned", area=f"st_{iid}")
            st.rerun()
        allowed = wf.allowed_manual_transitions(inc["status"])
        if allowed:
            hint = permission_hint("transition") or (None if inc["human_severity"] else "Record a severity decision first")
            cols = st.columns(len(allowed))
            for col, to in zip(cols, allowed):
                if col.button(TRANSITION_LABEL.get((inc["status"], to), to), key=f"tr_{iid}_{to}", disabled=bool(hint), help=hint, use_container_width=True):
                    run_action(lambda: wf.transition(c, iid, to, current_actor()), f"Moved to {STATUS_LABEL[to]}", area=f"st_{iid}")
                    st.rerun()
            if hint:
                st.caption(hint)
        feedback(f"st_{iid}")


def _containment_card(inc, a) -> None:
    c = conn()
    iid = inc["incident_id"]
    acts = rows(c, "SELECT * FROM containment_actions WHERE incident_id=? ORDER BY proposed_at", (iid,))
    pending = [x for x in acts if x["status"] == "proposed"]
    active = [x for x in acts if x["status"] == "active"]
    with st.expander(f"Containment — {len(pending)} pending, {len(active)} active", expanded=bool(pending or active) or inc["status"] == "CONTAINMENT"):
        md(badge("SIMULATED — nothing is executed against any system", "b-sim-action"))
        perm = wf.containment_permission(c, inc)
        hint = permission_hint(perm)
        sev, basis = wf.effective_severity(c, inc)
        st.caption(f"Approval at {sev} ({BASIS_LABEL[basis]}) requires {wf.roles_for(perm)}.")
        now = datetime.now(timezone.utc)
        for x in pending:
            with st.container(border=True):
                who = "AI" if x["proposed_source"] == "ai" else actor_name(x["proposed_by"])
                md(f"<b>{pretty(x['action_type'])}</b> on {esc(x['target'])}<br><span class='small'>Proposed by {esc(who)}"
                   f" · {ago(x['proposed_at'])} · {esc(x['rationale'])}</span>")
                k = x["action_id"]
                reason = st.text_input("Decision reason", key=f"cr_{k}", placeholder="Decision reason (required)", label_visibility="collapsed", disabled=bool(hint))
                with st.popover("Timing: review 24h · expire 72h", disabled=bool(hint), use_container_width=True):
                    rv = st.number_input("Review in (hours)", 1, 168, 24, key=f"crv_{k}")
                    ex = st.number_input("Expires in (hours)", 1, 720, 72, key=f"cex_{k}")
                rv, ex = st.session_state.get(f"crv_{k}", 24), st.session_state.get(f"cex_{k}", 72)
                b1, b2 = st.columns(2)
                if b1.button("Approve", key=f"ca_{k}", type="primary", disabled=bool(hint), help=hint, use_container_width=True):
                    run_action(lambda: wf.decide_containment(c, k, current_actor(), True, reason, now + timedelta(hours=rv), now + timedelta(hours=ex)),
                               "Containment approved (simulated)", area=f"ct_{iid}")
                    st.rerun()
                if b2.button("Reject", key=f"cj_{k}", disabled=bool(hint), help=hint, use_container_width=True):
                    run_action(lambda: wf.decide_containment(c, k, current_actor(), False, reason), "Proposal rejected", area=f"ct_{iid}")
                    st.rerun()
        hint_end = permission_hint("end_containment")
        for x in active:
            with st.container(border=True):
                due = datetime.fromisoformat(x["review_by"])
                md(f"<b>{pretty(x['action_type'])}</b> on {esc(x['target'])} " + badge("ACTIVE · simulated", "b-p1")
                   + f"<br><span class='small'>Approved by {esc(actor_name(x['decided_by']))} · review {relative((due - now).total_seconds() / 60)}"
                   f" · expires {x['expires_at'][:16].replace('T', ' ')} UTC</span>")
                k = x["action_id"]
                why = st.text_input("Reason", key=f"ce_{k}", placeholder="Reason to reverse", label_visibility="collapsed", disabled=bool(hint_end))
                if st.button("Reverse containment", key=f"ceb_{k}", disabled=bool(hint_end), help=hint_end, use_container_width=True):
                    run_action(lambda: wf.end_containment(c, k, current_actor(), why), "Containment reversed", area=f"ct_{iid}")
                    st.rerun()
        feedback(f"ct_{iid}")
        past = [x for x in acts if x["status"] in ("rejected", "reversed", "expired")]
        if past:
            st.caption("History: " + " · ".join(f"{pretty(x['action_type'])} {x['status']}" for x in past))
        if inc["status"] not in CLOSED:
            with st.popover("＋ Propose containment", use_container_width=True, disabled=bool(permission_hint("propose_containment"))):
                if a and a["output"] and a["output"]["containment_options"]:
                    st.markdown("**AI-suggested (reversible)**")
                    for i, opt in enumerate(a["output"]["containment_options"]):
                        st.markdown(f"`{pretty(opt['action_type'])}` on _{opt['target']}_ — {opt['rationale']}")
                        if st.button("Propose this", key=f"aip_{iid}_{i}"):
                            run_action(lambda: wf.propose_containment(c, iid, wf.SYSTEM_ACTOR, opt["action_type"], opt["target"], opt["rationale"], source="ai"),
                                       "Proposed (source: AI)", area=f"ct_{iid}")
                            st.rerun()
                    st.divider()
                with st.form(f"cp_{iid}", clear_on_submit=True):
                    st.markdown("**Custom proposal**")
                    t = st.selectbox("Action", sorted(REVERSIBLE_CONTAINMENT) + ["account_lockout"], format_func=pretty)
                    target = st.text_input("Target (narrowest effective scope)")
                    why = st.text_input("Rationale")
                    if st.form_submit_button("Propose"):
                        run_action(lambda: wf.propose_containment(c, iid, current_actor(), t, target, why), "Proposed", area=f"ct_{iid}")
                        st.rerun()


def _comms_card(inc) -> None:
    c = conn()
    iid = inc["incident_id"]
    comms = wf.latest_communications(c, iid)
    waiting = [x for x in comms if x["status"] == "draft" and json.loads(x["specialist_review_json"])["required"]]
    with st.expander(f"Communications — {len(comms)} draft(s), {len(waiting)} awaiting review", expanded=bool(waiting)):
        md(badge("DRAFTS ONLY — nothing is ever sent", "b-sim-action"))
        for x in comms:
            spec = json.loads(x["specialist_review_json"])
            l, r = st.columns([3, 1.3], vertical_alignment="center")
            l.markdown(f"**{communications.COMM_TYPES[x['comm_type']]}** v{x['version']} "
                       + badge(x["status"], "b-human" if x["status"] == "approved" else "b-muted")
                       + "".join(badge(f"{s} {'✓' if s in spec['approvals'] else 'needed'}", "b-human" if s in spec["approvals"] else "b-warn") for s in spec["required"]),
                       unsafe_allow_html=True)
            if r.button("Open draft", key=f"cm_{x['comm_id']}", use_container_width=True):
                comm_dialog(x["comm_id"])
        hint = permission_hint("draft_communication")
        _, mode = provider_for_mode()
        with st.popover("＋ New draft", use_container_width=True, disabled=bool(hint)):
            for ct, label in communications.COMM_TYPES.items():
                if st.button(label, key=f"gen_{iid}_{ct}", use_container_width=True):
                    run_action(lambda: communications.generate(c, iid, ct, current_actor(), use_live=(mode == "live")), f"{label} drafted", area=f"cm_{iid}")
                    st.rerun()
            st.caption("Templates offline; live mode optionally tightens the template (labeled).")
        feedback(f"cm_{iid}")


def _closure_card(inc) -> None:
    c = conn()
    iid = inc["incident_id"]
    status = inc["status"]
    with st.expander("Closure & quality review", expanded=status in ("RESPONSE",) + CLOSED):
        if status == "RESPONSE":
            blockers = wf.closure_blockers(c, iid)
            hint = permission_hint(wf.closure_permission(inc))
            for b in blockers:
                st.markdown(f"- ⛔ {b}")
            if st.button("Close case…", type="primary", disabled=bool(blockers or hint), help=hint, use_container_width=True):
                close_dialog(iid)
            if hint:
                st.caption(hint)
        elif status in CLOSED:
            cl = json.loads(inc["closure_json"])
            md(f"{badge('Closed', 'b-human')} {sev_badge(cl['final_severity'])} {pretty(cl['closure_category'])}<br>"
               f"<span class='small'>Root cause: {esc(cl['root_cause'])}<br>Impact: {esc(cl['user_customer_impact'])}<br>"
               f"Remaining: {esc(cl['remaining_mitigation'])} · Monitoring: {'yes' if cl['monitoring_required'] else 'no'}</span>")
            b1, b2 = st.columns(2)
            if status == "CLOSED":
                with b1.popover("QA review", use_container_width=True, disabled=bool(permission_hint("qa_review"))):
                    with st.form(f"qa_{iid}"):
                        outcome = st.selectbox("Outcome", wf.QA_OUTCOMES, format_func=pretty)
                        notes = st.text_area("Notes")
                        if st.form_submit_button("Record QA review"):
                            run_action(lambda: wf.qa_review(c, iid, current_actor(), outcome, notes), "QA review recorded", area=f"cl_{iid}")
                            st.rerun()
            hint = permission_hint("reopen")
            if b2.button("Reopen…", disabled=bool(hint), help=hint, use_container_width=True):
                reopen_dialog(iid)
        else:
            if inc["closure_json"]:
                st.caption("A previous closure record exists (case was reopened).")
            st.caption("Closure becomes available in the Response stage.")
        feedback(f"cl_{iid}")


# ============================================================================ page

def render() -> None:
    c = conn()
    ids = [r["incident_id"] for r in rows(c, "SELECT incident_id FROM incidents ORDER BY reported_at DESC")]
    if not ids:
        st.info("No cases yet.")
        return
    iid = st.session_state.get("case_id") or st.query_params.get("id") or ids[0]
    if iid not in ids:
        iid = ids[0]
    st.session_state["case_id"] = iid
    st.query_params["id"] = iid

    nav_l, _, nav_r = st.columns([1, 3, 2])
    if nav_l.button("← Queue"):
        go("queue")
    pick = nav_r.selectbox("Switch case", ids, index=ids.index(iid), label_visibility="collapsed")
    if pick != iid:
        st.session_state["case_id"] = pick
        st.rerun()

    inc = wf.get_incident(c, iid)
    intake = wf.get_intake(c, iid)
    a = wf.get_assessment(c, inc["current_assessment_id"])
    row = monitoring.case_row(c, iid)
    sev, basis = wf.effective_severity(c, inc)

    md(f"{sev_badge(sev, BASIS_LABEL[basis])} <span class='muted'>{iid}</span>")
    st.markdown(f"## {esc(inc['title'])}")
    chips = [badge(STATUS_LABEL[inc["status"]]), badge("Owner: " + (actor_name(inc["owner"]) if inc["owner"] else "unassigned")),
             source_badge(a["provider_kind"] if a else "none")]
    if row["overdue"]:
        chips.append(badge("First review " + relative(row["minutes_to_deadline"]), "b-p0"))
    elif row["minutes_to_deadline"] is not None and not inc["human_severity"]:
        chips.append(badge("First review " + relative(row["minutes_to_deadline"]), "b-warn"))
    if row["mandatory_review"] and inc["status"] not in CLOSED and not inc["human_severity"]:
        chips.append(badge("⚑ Mandatory human review", "b-warn"))
    if inc["origin"] == "seed":
        chips.append(badge("synthetic seed data"))
    md(" ".join(chips))
    md(stepper(inc["status"]))

    me = current_actor()
    acts = row["next_actions"]
    if acts:
        items = []
        for x in acts:
            mine = wf.actor_can_do(c, me, x)
            items.append(f"<li><b>{esc(x['title'])}</b> — {esc(x['detail'])} "
                         + (badge("you can do this", "b-human") if mine else badge("needs " + wf.who_can_do(x), "b-muted")) + "</li>")
        md(f'<div class="next{" ok" if not any(x["urgent"] for x in acts) else ""}"><b>Next</b><ul style="margin:4px 0 0 0">{"".join(items)}</ul></div>')

    left, right = st.columns([3, 2], gap="large")
    with left:
        sec = section(["Overview", "Evidence", "Activity", "Related", "AI details"], key="case_section")
        if sec == "Overview":
            _report(inc, intake)
            st.divider()
            _assessment(inc, intake, a)
        elif sec == "Evidence":
            _evidence(inc, intake)
        elif sec == "Activity":
            _activity(inc)
        elif sec == "Related":
            _related(inc)
        else:
            _ai_details(inc, a)
    with right:
        _decision_card(inc, intake, a)
        _stage_card(inc)
        _containment_card(inc, a)
        _comms_card(inc)
        _closure_card(inc)
