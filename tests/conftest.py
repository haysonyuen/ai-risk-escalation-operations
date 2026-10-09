import json
from datetime import datetime, timezone

import pytest

from riskops import workflow as wf
from riskops.db import connect
from riskops.schemas import IncidentIntake

ACTORS = {a.actor_id: a for a in wf.SIMULATED_ACTORS}


@pytest.fixture(autouse=True)
def _no_live_providers(monkeypatch):
    """Tests never call Jev or Anthropic, even when the developer's shell has keys set."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def actors():
    return ACTORS


def make_intake(**overrides) -> IncidentIntake:
    base = {
        "incident_id": "T-1",
        "reported_at": datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc).isoformat(),
        "title": "Assistant changed a file",
        "product_surface": "chat_app",
        "customer_type": "consumer",
        "reporter_channel": "support_ticket",
        "reported_behavior": "User says the assistant changed a document.",
        "reported_impact": "unknown",
        "model_version": "assistant-test",
        "file_action": "edited",
        "external_action_attempted": "no",
        "user_approved": "yes",
        "sensitive_data": "no",
        "scope": "single_user",
        "recurrence": "first_report",
        "reversibility": "reversible",
        "evidence": [{"evidence_id": "E1", "source_type": "reporter_statement", "source_description": "Ticket",
                      "content": "The assistant changed my document."}],
    }
    base.update(overrides)
    return IncidentIntake.model_validate(base)


# A confirmed CBRN policy case recorded the way a restricted triage system shows it: structured
# fields only, content held in a restricted store (never described in tests or fixtures).
P0_CBRN = dict(
    incident_id="T-P0", title="CBRN policy: specialist confirmed violation, content provided", reporter_channel="safety_reviewer",
    reported_behavior="Safety specialist escalated a CBRN policy case. Details are held in the restricted evidence store.",
    file_action="none", external_action_attempted="unknown", user_approved="unknown", reversibility="unknown",
    evidence=[{"evidence_id": "E1", "source_type": "reviewer_note", "source_description": "Specialist review",
               "content": "policy_area=cbrn; verdict=violation_confirmed; content_provided=yes; content held in restricted evidence store"},
              {"evidence_id": "E2", "source_type": "classifier_output", "source_description": "Classifier",
               "content": "classifier=cbrn_policy; score=0.88; action=flagged_not_blocked"}],
)
P0_CHILD = dict(P0_CBRN, incident_id="T-P0C", title="Child safety policy: violation confirmed",
                reported_behavior="Trust & Safety escalated a child safety policy case. Details are held in the restricted evidence store.",
                evidence=[{"evidence_id": "E1", "source_type": "reviewer_note", "source_description": "Specialist review",
                           "content": "policy_area=child_safety; verdict=violation_confirmed; content_provided=yes"},
                          {"evidence_id": "E2", "source_type": "classifier_output", "source_description": "Classifier",
                           "content": "classifier=child_safety_policy; score=0.93; action=interrupted_late"}])
P0_BIO = P0_CBRN  # backwards-compatible name used by older tests


def dumps(x):
    return json.dumps(x)
