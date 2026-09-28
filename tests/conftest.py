import json
from datetime import datetime, timezone

import pytest

from riskops import workflow as wf
from riskops.db import connect
from riskops.schemas import IncidentIntake

ACTORS = {a.actor_id: a for a in wf.SIMULATED_ACTORS}


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
        "product_surface": "desktop_assistant",
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


P0_BIO = dict(
    incident_id="T-P0", title="Assistant offered to arrange purchase of live viral cultures", reporter_channel="safety_reviewer",
    reported_behavior="Reviewer found the assistant offered to locate a supplier for live viral cultures.",
    file_action="none", external_action_attempted="unknown", user_approved="no", reversibility="unknown",
    evidence=[{"evidence_id": "E1", "source_type": "reviewer_note", "source_description": "Reviewer note",
               "content": "Assistant offered to source live viral cultures and asked for shipping details."},
              {"evidence_id": "E2", "source_type": "classifier_output", "source_description": "Classifier",
               "content": "bio_procurement: 0.91"}],
)


def dumps(x):
    return json.dumps(x)
