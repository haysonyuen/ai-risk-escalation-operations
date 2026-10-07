import json

import pytest

from riskops import monitoring, policies, workflow as wf
from riskops.db import rows
from riskops.providers import OfflineSimulationProvider

from .conftest import P0_BIO, make_intake


def _case(conn, actors):
    wf.create_incident(conn, make_intake(**P0_BIO), actors["priya.safety"])
    wf.run_assessment(conn, "T-P0", OfflineSimulationProvider(), rule_version="rules-v2.0")
    return "T-P0"


def test_library_covers_every_taxonomy_category_with_required_fields():
    from typing import get_args
    from riskops.schemas import RiskCategory
    assert set(policies.keys()) == set(get_args(RiskCategory))
    codes = [p["code"] for p in policies.all_policies()]
    assert len(codes) == len(set(codes))
    for p in policies.all_policies():
        assert p["definition"] and p["severity_guidance"] and p["escalation"] and p["checklist"]


def test_primary_policy_follows_priority_and_drops_no_policy_issue():
    assert policies.primary(["privacy_pii", "child_safety"]) == "child_safety"
    assert policies.ordered(["benign_noise", "product_failure"]) == ["product_failure"]
    assert policies.ordered(["benign_noise"]) == ["benign_noise"]
    assert policies.label("child_safety") == "CS-01 · Child safety"
    assert policies.label("child_safety", code=False) == "Child safety" and policies.code("child_safety") == "CS-01"


def test_policy_defaults_to_ai_suggestion_and_confirming_is_not_an_override(conn, actors):
    iid = _case(conn, actors)
    inc = wf.get_incident(conn, iid)
    ai_pol, basis, _ = wf.effective_policy(conn, inc)
    assert ai_pol and basis == "ai_after_controls"
    a = wf.get_assessment(conn, inc["current_assessment_id"])
    out = wf.decide_severity(conn, iid, actors["sam.lead"], a["controlled_severity"], a["controlled_route"], ["Safety"],
                             evidence_reviewed=["E1"])
    assert not out["override"]
    assert wf.effective_policy(conn, wf.get_incident(conn, iid))[:2] == (ai_pol, "human")


def test_changing_policy_is_an_override_needing_reason_and_is_audited(conn, actors):
    iid = _case(conn, actors)
    inc = wf.get_incident(conn, iid)
    a = wf.get_assessment(conn, inc["current_assessment_id"])
    ai_pol = wf.effective_policy(conn, inc)[0]
    other = "harmful_inaccuracy" if ai_pol != "harmful_inaccuracy" else "privacy_pii"
    args = (conn, iid, actors["sam.lead"], a["controlled_severity"], a["controlled_route"], ["Safety"])
    with pytest.raises(wf.WorkflowError, match="reason code"):
        wf.decide_severity(*args, evidence_reviewed=["E1"], policy=other)
    with pytest.raises(wf.WorkflowError, match="Unknown policy"):
        wf.decide_severity(*args, evidence_reviewed=["E1"], policy="not_a_policy")
    out = wf.decide_severity(*args, evidence_reviewed=["E1"], policy=other, reason="E1 shows a policy interpretation issue",
                             override_reason_code="policy_interpretation")
    assert out["override"]
    inc = wf.get_incident(conn, iid)
    assert inc["human_policy"] == other and ai_pol in json.loads(inc["human_policies_json"])
    ev = rows(conn, "SELECT * FROM events WHERE event_type='human_override'")[0]
    assert json.loads(ev["new_value"])["policy"] == other
    assert json.loads(ev["details_json"])["ai_recommendation"]["policy"] == ai_pol
    o = monitoring.ops_metrics(conn)["overrides"]
    assert o["policy_changed"] == 1 and o["by_direction"] == {"policy_only": 1}


def test_queue_rows_carry_policy(conn, actors):
    iid = _case(conn, actors)
    row = monitoring.case_row(conn, iid)
    assert row["policy"] in policies.keys() and row["policy_basis"] == "ai_after_controls"
    assert monitoring.ops_metrics(conn)["policy_counts"] == {row["policy"]: 1}


def test_why_matched_explains_in_plain_words(conn, actors):
    iid = _case(conn, actors)
    inc = wf.get_incident(conn, iid)
    a = wf.get_assessment(conn, inc["current_assessment_id"])
    why = policies.why_matched(a, wf.effective_policy(conn, inc)[0])
    assert why and all("_" not in w.split("(")[0] for w in why)


def test_risk_ops_cannot_decide_severe_p0_but_specialist_and_lead_can(conn, actors):
    iid = _case(conn, actors)
    a = wf.get_assessment(conn, wf.get_incident(conn, iid)["current_assessment_id"])
    with pytest.raises(wf.PermissionDenied, match="Specialist or the Incident Lead"):
        wf.decide_severity(conn, iid, actors["alex.riskops"], "P0", a["controlled_route"], ["Safety"], evidence_reviewed=["E1"])
    wf.decide_severity(conn, iid, actors["priya.safety"], "P0", a["controlled_route"], ["Safety"], evidence_reviewed=["E1"])
    assert wf.get_incident(conn, iid)["severity_decided_by"] == "priya.safety"


def test_specialist_cannot_decide_non_severe_cases(conn, actors):
    from riskops.providers import OfflineSimulationProvider
    wf.create_incident(conn, make_intake(incident_id="T-UX", title="Button is mislabeled", reported_behavior="Typo on a button."),
                       actors["casey.support"])
    wf.run_assessment(conn, "T-UX", OfflineSimulationProvider(), rule_version="rules-v2.0")
    with pytest.raises(wf.PermissionDenied, match="severe-harm cases"):
        wf.decide_severity(conn, "T-UX", actors["priya.safety"], "P3", "support", ["Support"], policy="product_failure",
                           reason="UI wording only, no harm", override_reason_code="other")


def test_failed_assessment_decision_is_manual_triage_not_override(conn, actors):
    from riskops.providers import FaultInjectionProvider
    wf.create_incident(conn, make_intake(incident_id="T-F"), actors["casey.support"])
    wf.run_assessment(conn, "T-F", FaultInjectionProvider("timeout"), rule_version="rules-v2.0")
    out = wf.decide_severity(conn, "T-F", actors["alex.riskops"], "P3", "support", ["Support"], policy="product_failure",
                             evidence_reviewed=["E1"])
    assert not out["override"]
    ev = rows(conn, "SELECT * FROM events WHERE event_type IN ('human_override','human_severity_confirmed')")[-1]
    d = json.loads(ev["details_json"])
    assert d["manual_triage"] and d["ai_recommendation"]["severity"] is None and d["rules_estimate"]["severity"]
    m = monitoring.ops_metrics(conn)["overrides"]
    assert m["manual_triage"] == 1 and m["decisions_with_ai_recommendation"] == 0


def test_no_suggestion_means_policy_must_be_chosen(conn, actors):
    wf.create_incident(conn, make_intake(incident_id="T-N"), actors["casey.support"])
    with pytest.raises(wf.WorkflowError, match="Choose the policy"):
        wf.decide_severity(conn, "T-N", actors["alex.riskops"], "P2", "support", ["Support"])
    wf.decide_severity(conn, "T-N", actors["alex.riskops"], "P2", "support", ["Support"], policy="product_failure")


def test_closure_outcome_must_match_category_and_clears_policy(conn, actors):
    from riskops.providers import OfflineSimulationProvider
    wf.create_incident(conn, make_intake(incident_id="T-C"), actors["casey.support"])
    wf.run_assessment(conn, "T-C", OfflineSimulationProvider(), rule_version="rules-v2.0")
    a = wf.get_assessment(conn, wf.get_incident(conn, "T-C")["current_assessment_id"])
    wf.decide_severity(conn, "T-C", actors["alex.riskops"], "P3", a["controlled_route"], ["Support"], evidence_reviewed=["E1"],
                       reason="Low risk per evidence E1", override_reason_code="false_positive")
    wf.transition(conn, "T-C", "RESPONSE", actors["alex.riskops"])
    base = {"closure_category": "classifier_false_positive", "final_severity": "P3", "root_cause": "Classifier over-triggered",
            "user_customer_impact": "None at all", "evidence_reviewed": ["E1"], "teams_involved": ["Support"],
            "actions_taken": "Added to false-positive set", "response_status": "None needed", "remaining_mitigation": "None",
            "monitoring_required": False, "sign_off_statement": "Reviewed E1; no violation found."}
    with pytest.raises(wf.WorkflowError, match="cannot confirm a policy violation"):
        wf.close_incident(conn, "T-C", {**base, "violation_confirmed": "yes"}, actors["alex.riskops"])
    wf.close_incident(conn, "T-C", {**base, "violation_confirmed": "no"}, actors["alex.riskops"])
    assert wf.effective_policy(conn, wf.get_incident(conn, "T-C"))[1] == "cleared"
    # QA must be someone other than the closer
    with pytest.raises(wf.PermissionDenied, match="someone other than"):
        wf.qa_review(conn, "T-C", actors["alex.riskops"], wf.QA_OUTCOMES[0], "self check")
    wf.qa_review(conn, "T-C", actors["sam.lead"], wf.QA_OUTCOMES[0], "independent check")
