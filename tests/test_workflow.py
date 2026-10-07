"""Approval enforcement, closure sign-off, reassessment, linking, audit history, persistence."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from riskops import communications, dedup, workflow as wf
from riskops.db import connect, rows
from riskops.providers import FaultInjectionProvider, OfflineProvider, OfflineSimulationProvider
from riskops.schemas import Evidence

from .conftest import P0_BIO, make_intake

SYS = wf.SYSTEM_ACTOR


def _p0_case(conn, actors):
    wf.create_incident(conn, make_intake(**P0_BIO), actors["priya.safety"])
    wf.run_assessment(conn, "T-P0", OfflineSimulationProvider(), rule_version="rules-v2.0")
    return "T-P0"


def _closure(sev, evidence=("E1",), **kw):
    base = {"closure_category": "confirmed_safety_incident", "final_severity": sev, "violation_confirmed": "yes", "root_cause": "Gating gap in tool path",
            "user_customer_impact": "No order placed", "evidence_reviewed": list(evidence), "teams_involved": ["Safety"],
            "actions_taken": "Paused transactions (simulated)", "response_status": "Draft approved, not sent",
            "remaining_mitigation": "Gating fix", "monitoring_required": True, "sign_off_statement": "Reviewed all evidence and actions."}
    base.update(kw)
    return base


def test_ai_actor_cannot_decide_severity_approve_or_close(conn, actors):
    iid = _p0_case(conn, actors)
    with pytest.raises(wf.PermissionDenied):
        wf.decide_severity(conn, iid, SYS, "P3", "support", ["Support"], reason="x" * 30, override_reason_code="other", evidence_reviewed=["E1"])
    ca = wf.propose_containment(conn, iid, SYS, "pause_interaction", "session", "stop it", source="ai")
    with pytest.raises(wf.PermissionDenied):
        wf.decide_containment(conn, ca, SYS, True, "approving myself")
    with pytest.raises(wf.PermissionDenied):
        wf.close_incident(conn, iid, _closure("P0"), SYS)


def test_p0_containment_requires_incident_lead_via_direct_service_call(conn, actors):
    iid = _p0_case(conn, actors)
    ca = wf.propose_containment(conn, iid, SYS, "pause_external_transactions", "account tools", "prevent orders", source="ai")
    with pytest.raises(wf.PermissionDenied):
        wf.decide_containment(conn, ca, actors["alex.riskops"], True, "looks right")
    with pytest.raises(wf.PermissionDenied):
        wf.decide_containment(conn, ca, actors["casey.support"], True, "looks right")
    wf.decide_containment(conn, ca, actors["sam.lead"], True, "Approve narrow reversible pause")
    act = rows(conn, "SELECT * FROM containment_actions WHERE action_id=?", (ca,))[0]
    assert act["status"] == "active" and act["simulated"] == 1 and act["review_by"] and act["expires_at"]
    with pytest.raises(wf.WorkflowError):
        wf.decide_containment(conn, ca, actors["sam.lead"], True, "again")


def test_account_lockout_needs_human_confirmed_p0(conn, actors):
    iid = _p0_case(conn, actors)
    ca = wf.propose_containment(conn, iid, actors["sam.lead"], "account_lockout", "account", "active abuse suspected")
    with pytest.raises(wf.WorkflowError):
        wf.decide_containment(conn, ca, actors["sam.lead"], True, "Lock the account now because it is bad")
    wf.decide_severity(conn, iid, actors["sam.lead"], "P0", "safety", ["Safety"], reason="confirmed", evidence_reviewed=["E1", "E2"])
    with pytest.raises(wf.WorkflowError):
        wf.decide_containment(conn, ca, actors["sam.lead"], True, "short")
    wf.decide_containment(conn, ca, actors["sam.lead"], True, "High-confidence active abuse confirmed in E1 and E2 by Safety.")


def test_containment_expiry_and_reversal(conn, actors):
    iid = _p0_case(conn, actors)
    ca = wf.propose_containment(conn, iid, SYS, "pause_interaction", "session", "stop", source="ai")
    now = datetime.now(timezone.utc)
    wf.decide_containment(conn, ca, actors["sam.lead"], True, "approve", review_by=now + timedelta(minutes=5), expires_at=now + timedelta(minutes=10))
    assert wf.expire_due_containment(conn, now + timedelta(minutes=11)) == 1
    assert rows(conn, "SELECT status FROM containment_actions WHERE action_id=?", (ca,))[0]["status"] == "expired"
    # the C7 automatic pause on this P0 CBRN case has no expiry: it never lifts itself
    assert rows(conn, "SELECT status FROM containment_actions WHERE proposed_source='auto_hold'")[0]["status"] == "active"
    ca2 = wf.propose_containment(conn, iid, SYS, "pause_interaction", "session", "stop", source="ai")
    wf.decide_containment(conn, ca2, actors["sam.lead"], True, "approve")
    with pytest.raises(wf.PermissionDenied):
        wf.end_containment(conn, ca2, actors["casey.support"], "no longer needed")
    wf.end_containment(conn, ca2, actors["alex.riskops"], "False positive confirmed")
    assert rows(conn, "SELECT status FROM containment_actions WHERE action_id=?", (ca2,))[0]["status"] == "reversed"


def test_override_requires_reason_and_code(conn, actors):
    iid = _p0_case(conn, actors)
    with pytest.raises(wf.WorkflowError, match="evidence"):
        wf.decide_severity(conn, iid, actors["sam.lead"], "P0", "safety", ["Safety"])
    with pytest.raises(wf.WorkflowError, match="reason code"):
        wf.decide_severity(conn, iid, actors["sam.lead"], "P1", "safety", ["Safety"], evidence_reviewed=["E1"], reason="long enough reason")
    with pytest.raises(wf.WorkflowError, match="20 characters"):
        wf.decide_severity(conn, iid, actors["sam.lead"], "P2", "safety", ["Safety"], evidence_reviewed=["E1"],
                           reason="too short ok", override_reason_code="false_positive")
    with pytest.raises(wf.WorkflowError, match="Unknown evidence"):
        wf.decide_severity(conn, iid, actors["sam.lead"], "P0", "safety", ["Safety"], evidence_reviewed=["E9"])
    out = wf.decide_severity(conn, iid, actors["sam.lead"], "P1", "safety", ["Safety"], evidence_reviewed=["E1"],
                             reason="Offer was not actionable per E1", override_reason_code="policy_interpretation")
    assert out["override"]
    ev = rows(conn, "SELECT * FROM events WHERE event_type='human_override'")[0]
    assert ev["actor_id"] == "sam.lead" and '"P0"' not in ev["previous_value"] and '"P1"' in ev["new_value"]
    assert "policy_interpretation" in ev["details_json"]


def test_closure_requires_signoff_role_fields_and_state(conn, actors):
    iid = _p0_case(conn, actors)
    with pytest.raises(wf.WorkflowError):  # no human severity yet
        wf.close_incident(conn, iid, _closure("P0"), actors["sam.lead"])
    wf.decide_severity(conn, iid, actors["sam.lead"], "P0", "safety", ["Safety"], reason="ok", evidence_reviewed=["E1"])
    with pytest.raises(wf.WorkflowError, match="not allowed"):  # still TRIAGED
        wf.close_incident(conn, iid, _closure("P0"), actors["sam.lead"])
    wf.transition(conn, iid, "INVESTIGATING", actors["sam.lead"])
    wf.transition(conn, iid, "RESPONSE", actors["sam.lead"])
    with pytest.raises(wf.PermissionDenied):  # P0 closure needs Incident Lead
        wf.close_incident(conn, iid, _closure("P0"), actors["alex.riskops"])
    with pytest.raises(Exception):  # missing required fields
        wf.close_incident(conn, iid, {**_closure("P0"), "root_cause": ""}, actors["sam.lead"])
    with pytest.raises(wf.WorkflowError, match="differs"):
        wf.close_incident(conn, iid, _closure("P2"), actors["sam.lead"])
    with pytest.raises(wf.WorkflowError, match="Unknown evidence"):
        wf.close_incident(conn, iid, _closure("P0", evidence=("E7",)), actors["sam.lead"])
    ca = wf.propose_containment(conn, iid, SYS, "pause_interaction", "session", "stop", source="ai")
    with pytest.raises(wf.WorkflowError, match="pending containment"):
        wf.close_incident(conn, iid, _closure("P0"), actors["sam.lead"])
    wf.decide_containment(conn, ca, actors["sam.lead"], True, "approve for now")
    with pytest.raises(wf.WorkflowError, match="Active"):
        wf.close_incident(conn, iid, _closure("P0"), actors["sam.lead"])
    cid = communications.generate(conn, iid, "user_ack", actors["casey.support"])
    with pytest.raises(wf.WorkflowError, match="specialist review"):
        wf.close_incident(conn, iid, _closure("P0", acknowledge_active_containment=True), actors["sam.lead"])
    with pytest.raises(wf.PermissionDenied):
        wf.review_communication(conn, cid, actors["alex.riskops"], True)
    assert wf.review_communication(conn, cid, actors["jordan.legal"], True) == "draft"  # Safety still needed
    assert wf.review_communication(conn, cid, actors["priya.safety"], True) == "approved"
    wf.close_incident(conn, iid, _closure("P0", acknowledge_active_containment=True), actors["sam.lead"])
    assert wf.get_incident(conn, iid)["status"] == "CLOSED"


def test_reassessment_preserves_human_decision_and_history(conn, actors):
    iid = _p0_case(conn, actors)
    wf.decide_severity(conn, iid, actors["alex.riskops"], "P1", "safety", ["Safety"], evidence_reviewed=["E1"],
                       reason="Offer was not actionable per E1", override_reason_code="policy_interpretation")
    first = wf.get_incident(conn, iid)["current_assessment_id"]
    wf.run_assessment(conn, iid, FaultInjectionProvider("under_severity"), rule_version="rules-v2.1")
    inc = wf.get_incident(conn, iid)
    assert inc["human_severity"] == "P1" and inc["status"] == "TRIAGED"
    assert inc["current_assessment_id"] != first
    assert len(wf.list_assessments(conn, iid)) == 2  # earlier result kept
    assert rows(conn, "SELECT * FROM events WHERE event_type='ai_human_disagreement'")
    # a rule change does not touch incidents either
    wf.change_rule_version(conn, "rules-v2.0", actors["sam.lead"], "Rollback for regression review")
    assert wf.get_incident(conn, iid)["human_severity"] == "P1"
    with pytest.raises(wf.PermissionDenied):
        wf.change_rule_version(conn, "rules-v2.1", actors["alex.riskops"], "try to change rules")


def test_failed_assessment_goes_to_manual_review_and_can_be_triaged(conn, actors):
    wf.create_incident(conn, make_intake(), actors["casey.support"])
    rec = wf.run_assessment(conn, "T-1", FaultInjectionProvider("malformed_json"))
    assert rec["status"] == "failed"
    assert wf.get_incident(conn, "T-1")["status"] == "ASSESSMENT_FAILED"
    wf.decide_severity(conn, "T-1", actors["alex.riskops"], "P3", "support", ["Support"], reason="Manual triage after failure",
                       override_reason_code="other")
    assert wf.get_incident(conn, "T-1")["status"] == "TRIAGED"


def test_duplicate_linking_preserves_evidence_and_status(conn, actors):
    a = make_intake(incident_id="D-1", title="Assistant changed planning_2026.docx", product_surface="enterprise_workspace",
                    reported_behavior="The assistant changed our planning doc planning_2026.docx.")
    b = make_intake(incident_id="D-2", title="planning_2026.docx now has customer contacts", product_surface="enterprise_workspace",
                    sensitive_data="yes", customer_type="enterprise",
                    reported_behavior="Assistant change to planning doc planning_2026.docx inserted customer contacts.",
                    evidence=[{"evidence_id": "E1", "source_type": "file_diff", "source_description": "diff", "content": "40 customer rows"},
                              {"evidence_id": "E2", "source_type": "reporter_statement", "source_description": "r", "content": "visible to all"}])
    for x in (a, b):
        wf.create_incident(conn, x, actors["casey.support"])
        wf.run_assessment(conn, x.incident_id, OfflineProvider(), rule_version="rules-v2.1")
    sugg = dedup.suggest(wf.get_intake(conn, "D-1"), [wf.get_intake(conn, "D-2")])
    assert sugg and "planning_2026.docx" in sugg[0]["explanation"]
    wf.record_link_suggestions(conn, "D-1", sugg)
    link = wf.links_for(conn, "D-1")[0]
    before = {i: (wf.get_incident(conn, i)["status"], len(wf.get_intake(conn, i).evidence)) for i in ("D-1", "D-2")}
    with pytest.raises(wf.PermissionDenied):
        wf.decide_link(conn, link["link_id"], actors["casey.support"], True, "duplicate", "same doc")
    wf.decide_link(conn, link["link_id"], actors["alex.riskops"], True, "duplicate", "Same planning doc edit")
    after = {i: (wf.get_incident(conn, i)["status"], len(wf.get_intake(conn, i).evidence)) for i in ("D-1", "D-2")}
    assert before == after
    warn = rows(conn, "SELECT * FROM events WHERE event_type='linked_higher_severity_warning'")
    assert warn and warn[0]["incident_id"] == "D-1"


def test_new_evidence_reopens_closed_case(conn, actors):
    wf.create_incident(conn, make_intake(), actors["casey.support"])
    wf.run_assessment(conn, "T-1", OfflineSimulationProvider(), rule_version="rules-v2.1")
    wf.decide_severity(conn, "T-1", actors["alex.riskops"], "P3", "support", ["Support"], reason="ok")
    wf.transition(conn, "T-1", "RESPONSE", actors["alex.riskops"])
    wf.close_incident(conn, "T-1", _closure("P3", closure_category="user_misunderstanding_no_defect", violation_confirmed="no"), actors["alex.riskops"])
    wf.add_evidence(conn, "T-1", Evidence(evidence_id="E2", source_type="tool_action_log", source_description="log",
                                          content="delete_file executed"), actors["lee.eng"])
    inc = wf.get_incident(conn, "T-1")
    assert inc["status"] == "REOPENED" and inc["closure_json"]  # prior closure record kept
    with pytest.raises(wf.WorkflowError):
        wf.add_evidence(conn, "T-1", Evidence(evidence_id="E2", source_type="reviewer_note", source_description="x", content="y"),
                        actors["lee.eng"])
    wf.decide_severity(conn, "T-1", actors["alex.riskops"], "P2", "product_engineering", ["Engineering"], reason="New log E2 shows deletion",
                       override_reason_code="missing_context")
    assert wf.get_incident(conn, "T-1")["status"] == "TRIAGED"


def test_invalid_transitions_rejected(conn, actors):
    wf.create_incident(conn, make_intake(), actors["casey.support"])
    with pytest.raises(wf.WorkflowError):
        wf.transition(conn, "T-1", "CLOSED", actors["alex.riskops"])
    with pytest.raises(wf.WorkflowError):
        wf.transition(conn, "T-1", "INVESTIGATING", actors["alex.riskops"])  # not triaged


def test_audit_events_are_append_only_and_persist(tmp_path, actors):
    p = tmp_path / "persist.db"
    c = connect(p)
    wf.create_incident(c, make_intake(), actors["casey.support"])
    wf.add_note(c, "T-1", "checked logs", actors["alex.riskops"])
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE events SET actor_id='someone-else'")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM events")
    c.close()
    c2 = connect(p)
    evs = wf.timeline(c2, "T-1")
    assert [e["event_type"] for e in evs] == ["intake_created", "investigation_note"]
    assert all(e["ts"] and e["actor_id"] and e["actor_role"] for e in evs)


def test_json_import_reports_invalid_records_without_partial_import(conn, actors):
    good = make_intake(incident_id="J-1").model_dump_json()
    created, errors = wf.import_json(conn, f'[{good}, {{"incident_id": "J-2", "title": "no fields"}}]', actors["casey.support"])
    assert created == ["J-1"] and len(errors) == 1
    assert not rows(conn, "SELECT * FROM incidents WHERE incident_id='J-2'")
    _, errors = wf.import_json(conn, "not json", actors["casey.support"])
    assert errors


def test_communication_edit_creates_version_and_resets_approval(conn, actors):
    wf.create_incident(conn, make_intake(), actors["casey.support"])
    wf.run_assessment(conn, "T-1", OfflineSimulationProvider(), rule_version="rules-v2.1")
    cid = communications.generate(conn, "T-1", "handoff", SYS)
    assert wf.review_communication(conn, cid, actors["alex.riskops"], True) == "approved"
    wf.save_communication(conn, "T-1", "handoff", "edited body [E1]", ["E1"], [], actors["alex.riskops"], "human_edit", comm_id=cid)
    versions = rows(conn, "SELECT version, status, body FROM communications WHERE comm_id=? ORDER BY version", (cid,))
    assert [v["version"] for v in versions] == [1, 2] and versions[1]["status"] == "draft"
    assert "DRAFT — NOT SENT" in versions[0]["body"]


def test_executive_brief_contains_required_sections(conn, actors):
    iid = _p0_case(conn, actors)
    body, refs, req = communications.render(conn, iid, "executive_brief")
    for s in ("Severity:", "Impact", "Facts from evidence", "Uncertainty", "Actions", "Next decision"):
        assert s in body
    assert "NOT YET CONFIRMED" in body and "Legal/Privacy" in req and "Safety" in req and refs


def test_future_reported_at_is_rejected(conn, actors):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with pytest.raises(wf.WorkflowError, match="future"):
        wf.create_incident(conn, make_intake(reported_at=future), actors["casey.support"])


def test_next_actions_guide_by_status_and_role(conn, actors):
    iid = _p0_case(conn, actors)
    acts = wf.next_actions(conn, iid)
    assert acts[0]["title"].startswith("Confirm or lift the automatic pause") and acts[0]["urgent"]
    acts = acts[1:]
    assert acts[0]["title"] == "Decide severity and routing" and acts[0]["urgent"]
    # P0 in a severe-harm policy area (CBRN): the specialist or the Incident Lead decides, not Risk Ops alone
    assert wf.actor_can_do(conn, actors["sam.lead"], acts[0]) and wf.actor_can_do(conn, actors["priya.safety"], acts[0])
    assert not wf.actor_can_do(conn, actors["alex.riskops"], acts[0])
    assert not wf.actor_can_do(conn, actors["casey.support"], acts[0])
    ca = wf.propose_containment(conn, iid, SYS, "pause_interaction", "session", "stop", source="ai")
    cont = [x for x in wf.next_actions(conn, iid) if x["title"] == "Decide on proposed containment"][0]
    assert wf.who_can_do(cont) == "Incident Lead"  # P0 by AI recommendation
    assert not wf.actor_can_do(conn, actors["alex.riskops"], cont)
    wf.decide_containment(conn, ca, actors["sam.lead"], True, "approve for now")
    wf.decide_severity(conn, iid, actors["sam.lead"], "P0", "safety", ["Safety"], reason="ok", evidence_reviewed=["E1"])
    wf.transition(conn, iid, "RESPONSE", actors["sam.lead"])
    close = [x for x in wf.next_actions(conn, iid) if x["title"].startswith("Close")][0]
    assert close["permission"] == "close_p0p1"
    assert wf.closure_blockers(conn, iid) == ["The automatic session pause has not been confirmed or lifted"]
    hold = wf.pending_auto_holds(conn, iid)[0]["action_id"]
    wf.review_auto_hold(conn, hold, actors["priya.safety"], True, "Specialist confirmed")
    assert wf.closure_blockers(conn, iid) == []  # active containment is acknowledged in the dialog, not a blocker


def test_closure_blockers_match_close_incident_checks(conn, actors):
    iid = _p0_case(conn, actors)
    wf.decide_severity(conn, iid, actors["sam.lead"], "P0", "safety", ["Safety"], reason="ok", evidence_reviewed=["E1"])
    wf.transition(conn, iid, "RESPONSE", actors["sam.lead"])
    wf.propose_containment(conn, iid, SYS, "pause_interaction", "session", "stop", source="ai")
    communications.generate(conn, iid, "user_ack", actors["casey.support"])
    blockers = wf.closure_blockers(conn, iid)
    assert any("containment" in b for b in blockers) and any("awaits" in b for b in blockers)
    with pytest.raises(wf.WorkflowError):
        wf.close_incident(conn, iid, _closure("P0"), actors["sam.lead"])


def test_concurrent_first_load_seeds_once_without_collision(tmp_path):
    """Regression: on a hosted app, simultaneous first page loads raced to seed the same file
    and crashed with 'Incident INC-1001 already exists'."""
    import threading

    from riskops.demo_db import ensure_seeded

    target = tmp_path / "shared.db"
    errors = []
    start = threading.Barrier(8)  # release all "page loads" at the same instant

    def load():
        start.wait()
        try:
            ensure_seeded(target)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=load) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    c = connect(target)
    assert rows(c, "SELECT COUNT(*) n FROM incidents")[0]["n"] == 16
    assert not list(tmp_path.glob("*.tmp"))


# --- C7 automatic pause ---------------------------------------------------------------------

def test_auto_hold_fires_for_p0_cbrn_and_child_safety_only(conn, actors):
    from .conftest import P0_CHILD
    iid = _p0_case(conn, actors)
    holds = wf.pending_auto_holds(conn, iid)
    assert len(holds) == 1 and holds[0]["action_type"] == "pause_interaction" and holds[0]["expires_at"] is None
    wf.create_incident(conn, make_intake(**P0_CHILD), actors["priya.safety"])
    wf.run_assessment(conn, "T-P0C", OfflineSimulationProvider(), rule_version="rules-v2.1")
    assert len(wf.pending_auto_holds(conn, "T-P0C")) == 1
    # a P0 outside the two categories (cross-tenant data exposure) does not pause anything
    wf.create_incident(conn, make_intake(incident_id="T-X", customer_type="enterprise", sensitive_data="yes", file_action="read",
                                         evidence=[{"evidence_id": "E1", "source_type": "tool_action_log", "source_description": "log",
                                                    "content": "returned another tenant's document (cross-tenant)"}]), actors["alex.riskops"])
    rec = wf.run_assessment(conn, "T-X", OfflineSimulationProvider(), rule_version="rules-v2.1")
    assert rec["controlled_severity"] == "P0" and not wf.pending_auto_holds(conn, "T-X")


def test_auto_hold_is_idempotent_on_reassessment(conn, actors):
    iid = _p0_case(conn, actors)
    wf.run_assessment(conn, iid, OfflineSimulationProvider(), rule_version="rules-v2.1")
    assert len(rows(conn, "SELECT 1 FROM containment_actions WHERE proposed_source='auto_hold'")) == 1


def test_auto_hold_fires_even_when_the_ai_fails(conn, actors):
    wf.create_incident(conn, make_intake(**P0_BIO), actors["priya.safety"])
    rec = wf.run_assessment(conn, "T-P0", FaultInjectionProvider("timeout"), rule_version="rules-v2.1")
    assert rec["status"] == "failed" and wf.pending_auto_holds(conn, "T-P0")


def test_auto_hold_fires_when_the_ai_under_calls(conn, actors):
    wf.create_incident(conn, make_intake(**P0_BIO), actors["priya.safety"])
    rec = wf.run_assessment(conn, "T-P0", FaultInjectionProvider("under_severity"), rule_version="rules-v2.1")
    assert rec["model_severity"] != "P0" and rec["controlled_severity"] == "P0" and wf.pending_auto_holds(conn, "T-P0")


def test_auto_hold_review_permissions_and_reasons(conn, actors):
    iid = _p0_case(conn, actors)
    hold = wf.pending_auto_holds(conn, iid)[0]["action_id"]
    with pytest.raises(wf.PermissionDenied):
        wf.review_auto_hold(conn, hold, actors["alex.riskops"], False, "Looks like a false alarm to me, lifting")
    with pytest.raises(wf.WorkflowError):
        wf.end_containment(conn, hold, actors["sam.lead"], "bypass the review")  # must go through confirm/lift
    with pytest.raises(wf.WorkflowError):
        wf.review_auto_hold(conn, hold, actors["sam.lead"], False, "too short")  # lifting needs 20+ characters
    wf.review_auto_hold(conn, hold, actors["sam.lead"], False, "Specialist verdict reversed on appeal; not a violation.")
    act = rows(conn, "SELECT * FROM containment_actions WHERE action_id=?", (hold,))[0]
    assert act["status"] == "reversed" and act["hold_review_outcome"] == "lifted"
    assert rows(conn, "SELECT 1 FROM events WHERE event_type='auto_hold_lifted'")
    with pytest.raises(wf.WorkflowError):
        wf.review_auto_hold(conn, hold, actors["sam.lead"], True, "again")


def test_overdue_auto_hold_stays_on_and_escalates(conn, actors):
    iid = _p0_case(conn, actors)
    hold = wf.pending_auto_holds(conn, iid)[0]
    assert wf.expire_due_containment(conn, datetime.now(timezone.utc) + timedelta(days=30)) == 0
    conn.execute("UPDATE containment_actions SET review_by=? WHERE action_id=?",
                 ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"), hold["action_id"]))
    first = wf.next_actions(conn, iid)[0]
    assert "OVERDUE" in first["title"] and "Incident Lead" in first["title"]
    from riskops import monitoring
    assert monitoring.ops_metrics(conn)["auto_hold"]["awaiting_review_overdue"] == 1


def test_old_demo_database_is_rebuilt(tmp_path):
    import sqlite3 as sq
    from riskops.demo_db import ensure_seeded
    from riskops.seed import DEMO_DATA_VERSION
    old = tmp_path / "old.db"
    with sq.connect(old) as c:
        c.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT INTO settings VALUES ('demo_data_version', 'demo-v1')")
    ensure_seeded(old)
    c = connect(old)
    assert rows(c, "SELECT value FROM settings WHERE key='demo_data_version'")[0]["value"] == DEMO_DATA_VERSION


def test_reload_guard_drops_stale_project_modules():
    # Hosted apps can hot-reload new files while old riskops modules stay cached (seen after
    # deploys as ImportError / schema ValidationError). The guard drops them when code changes.
    import importlib
    import os
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    guard = importlib.import_module("_reload_guard")
    saved = {k: v for k, v in sys.modules.items() if k == "riskops" or k.startswith("riskops.")}
    sys.modules.pop(guard._STATE, None)
    importlib.import_module("riskops.config")
    guard.refresh_if_code_changed()               # first run: anything preloaded is untrusted
    assert "riskops.config" not in sys.modules
    importlib.import_module("riskops.config")
    assert guard.refresh_if_code_changed() is False  # unchanged code: nothing dropped
    f = Path(guard.ROOT / "riskops" / "config.py")
    st = f.stat()
    try:
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        assert guard.refresh_if_code_changed() is True
        assert "riskops.config" not in sys.modules
    finally:
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
        sys.modules.update(saved)  # keep other tests on the module objects they imported


def test_intake_validation_errors_are_shown_in_plain_language():
    import sys
    from pathlib import Path
    import pytest as _pytest
    from pydantic import ValidationError
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    common = _pytest.importorskip("common")
    with _pytest.raises(ValidationError) as ei:
        make_intake(title="", reported_behavior="")
    msg = common.friendly_error(ei.value)
    assert "Short title" in msg and "What was reported" in msg and "is required" in msg
    assert "pydantic" not in msg and "string_too_short" not in msg
