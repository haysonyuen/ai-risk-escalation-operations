"""Write hand-authored assessment fixtures for demo incidents.

Fixtures illustrate what a model output might look like - including deliberately imperfect
ones - so the deterministic controls can be demonstrated offline. They are NOT model outputs
and are labeled offline_fixture everywhere they appear. Each fixture is bound to the exact
intake content by a fingerprint; if the intake changes, the fixture is not used.
"""

from __future__ import annotations

import json
from pathlib import Path

from riskops.config import DEMO_DIR, FIXTURE_DIR
from riskops.providers.offline import intake_fingerprint
from riskops.schemas import AssessmentOutput, IncidentIntake

FIXTURES = {
    "DEMO-2001": {
        "illustrates": "An under-calling assessment: recommends P2 with low confidence, suggests a non-specialist route, "
                       "and cites an evidence ID (E5) that does not exist for a claim nobody has verified. "
                       "Controls C2, C3, C5 and C6 should all fire.",
        "assessment": {
            "summary": "An assistant session created a share link on a customer renewals spreadsheet after the user approved sharing with the account team. Link visibility and access are not yet confirmed.",
            "reported_facts": [
                {"statement": "The assistant created a share link on q3_customer_renewals.xlsx with visibility anyone_with_link.", "evidence_ids": ["E2"]},
                {"statement": "The user approved 'Share renewals summary with account team'; the dialog did not show link visibility.", "evidence_ids": ["E3"]},
                {"statement": "The link was opened from an external domain.", "evidence_ids": ["E5"]}
            ],
            "hypotheses": [
                {"statement": "The user intended to share with an internal team and misunderstood the sharing dialog.", "basis": "Approval text mentions 'account team'."},
                {"statement": "The link may not have been accessed by anyone outside the company.", "basis": "Access telemetry is still pending (E4)."}
            ],
            "missing_information": ["Link access log (who opened it, from which domains)", "Scope: other files shared in the same session", "Whether the file contains regulated personal data"],
            "contradictions": [],
            "risk_categories": ["enterprise_data_leakage", "agentic_overreach"],
            "recommended_severity": "P2",
            "severity_rationale": "Looks like an approval/UX misunderstanding; no confirmed external access.",
            "potential_impact": "high",
            "evidence_quality": "partial",
            "confidence": "low",
            "confidence_justification": "Access telemetry pending; visibility setting confirmed but access not confirmed.",
            "suggested_primary_route": "product_ux",
            "suggested_teams": ["Product/UX", "Support", "Risk Ops"],
            "next_steps": ["Pull link access log", "Confirm file contents with customer", "Review share dialog copy"],
            "human_review_reasons": ["Sensitive data possibly involved"],
            "containment_options": [
                {"action_type": "restrict_tool_action", "target": "anyone_with_link sharing by the assistant in this workspace", "rationale": "Prevent further public-link creation while access is investigated.", "reversible": True}
            ],
            "incident_brief": "Possible exposure of customer renewals data via an assistant-created public link. Visibility confirmed (E2); access unconfirmed (E4 pending). User approval dialog did not show visibility (E3)."
        },
    },
    "INC-1001": {
        "illustrates": "A well-grounded P0 assessment of a restricted CBRN case, working only from structured fields. "
                       "Both the rules and this assessment rate it P0 CBRN, so the C7 automatic pause fires.",
        "assessment": {
            "summary": "A Safety specialist confirmed a CBRN policy violation in which content was provided; the classifier flagged the session without blocking it. Content is in the restricted evidence store.",
            "reported_facts": [
                {"statement": "The specialist verdict is violation_confirmed with content_provided=yes and assessed as actionable.", "evidence_ids": ["E1"]},
                {"statement": "The CBRN policy classifier scored the session 0.88 and flagged it without blocking.", "evidence_ids": ["E2"]},
                {"statement": "The content is held under restricted reference RE-1001, accessible to the specialist team only.", "evidence_ids": ["E3"]}
            ],
            "hypotheses": [{"statement": "The classifier threshold for blocking is set above the score seen here.", "basis": "Flagged but not blocked at 0.88 (E2)."}],
            "missing_information": ["Other sessions from the same account", "Whether the output was copied or shared"],
            "contradictions": [],
            "risk_categories": ["cbrn"],
            "recommended_severity": "P0",
            "severity_rationale": "Confirmed actionable CBRN content provided (framework P0: active harmful facilitation).",
            "potential_impact": "critical",
            "evidence_quality": "strong",
            "confidence": "high",
            "confidence_justification": "Specialist verdict and classifier output agree.",
            "suggested_primary_route": "safety",
            "suggested_teams": ["Incident Lead", "Safety", "Legal/Privacy", "Engineering"],
            "next_steps": ["Safety to review other sessions from the account", "Engineering to review the classifier blocking threshold", "Legal to assess reporting obligations"],
            "human_review_reasons": ["P0 recommendation requires same-hour human review"],
            "containment_options": [
                {"action_type": "pause_interaction", "target": "the reported conversation/session", "rationale": "Stop any further output while Safety reviews.", "reversible": True},
                {"action_type": "deploy_classifier_block", "target": "the request pattern seen in this case", "rationale": "Block close variants while the threshold is reviewed.", "reversible": True}
            ],
            "incident_brief": "P0 candidate: confirmed CBRN policy violation with content provided (E1); classifier flagged without blocking (E2). Content restricted (E3)."
        },
    },
    "INC-1004": {
        "illustrates": "A plausible but wrong framing: treats a prompt-injection exfiltration as an agent mis-send. "
                       "Control C3 raises it to the rules' P0 and C6 keeps the rules' specialist route (Legal/Privacy).",
        "assessment": {
            "summary": "The email agent sent a message containing two keys to an external address while processing the inbox.",
            "reported_facts": [
                {"statement": "The agent searched the mailbox for 'api key' and emailed two keys to an external address.", "evidence_ids": ["E1"]},
                {"statement": "The security team reports the keys were used from an unknown IP.", "evidence_ids": ["E3"]}
            ],
            "hypotheses": [{"statement": "The agent misinterpreted an earlier user request to share credentials with a vendor.", "basis": "Agents sometimes over-generalise send requests."}],
            "missing_information": ["The user's instructions in the session"],
            "contradictions": [],
            "risk_categories": ["agentic_overreach"],
            "recommended_severity": "P2",
            "severity_rationale": "Single agent mis-send; keys can be rotated.",
            "potential_impact": "high",
            "evidence_quality": "partial",
            "confidence": "medium",
            "confidence_justification": "Action confirmed; cause unclear.",
            "suggested_primary_route": "product_engineering",
            "suggested_teams": ["Engineering", "Product/UX"],
            "next_steps": ["Rotate the keys", "Review send-intent detection"],
            "human_review_reasons": [],
            "containment_options": [],
            "incident_brief": "Agent emailed two API keys externally (E1); keys later used (E3)."
        },
    },
}


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    seeds = {i["intake"]["incident_id"]: i["intake"] for i in json.loads((DEMO_DIR / "seed_incidents.json").read_text())["incidents"]}
    seeds["DEMO-2001"] = json.loads((DEMO_DIR / "intake_example.json").read_text())
    for iid, fx in FIXTURES.items():
        intake_data = dict(seeds[iid])
        intake_data.setdefault("reported_at", "2026-01-01T00:00:00+00:00")
        intake = IncidentIntake.model_validate(intake_data)
        AssessmentOutput.model_validate(fx["assessment"])  # fixtures must be schema-valid
        out = {"label": "HAND-AUTHORED FIXTURE - not a model output", "incident_id": iid,
               "illustrates": fx["illustrates"], "input_fingerprint": intake_fingerprint(intake),
               "assessment": fx["assessment"]}
        (FIXTURE_DIR / f"{iid}.json").write_text(json.dumps(out, indent=2))
        print("wrote", iid)


if __name__ == "__main__":
    main()
