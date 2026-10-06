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
    out = wf.decide_severity(conn, iid, actors["alex.riskops"], a["controlled_severity"], a["controlled_route"], ["Safety"],
                             evidence_reviewed=["E1"])
    assert not out["override"]
    assert wf.effective_policy(conn, wf.get_incident(conn, iid))[:2] == (ai_pol, "human")


def test_changing_policy_is_an_override_needing_reason_and_is_audited(conn, actors):
    iid = _case(conn, actors)
    inc = wf.get_incident(conn, iid)
    a = wf.get_assessment(conn, inc["current_assessment_id"])
    ai_pol = wf.effective_policy(conn, inc)[0]
    other = "harmful_inaccuracy" if ai_pol != "harmful_inaccuracy" else "privacy_pii"
    args = (conn, iid, actors["alex.riskops"], a["controlled_severity"], a["controlled_route"], ["Safety"])
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
