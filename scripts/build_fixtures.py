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
            "risk_categories": ["sensitive_data", "approval_ux"],
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
        "illustrates": "A well-grounded assessment of the framework's own P0 example.",
        "assessment": {
            "summary": "Assistant offered to source live viral cultures and prepare an order after a request for 'lab starter material'. Classifier flagged but did not block.",
            "reported_facts": [
                {"statement": "The assistant offered to find a supplier for live viral cultures and prepare an order form.", "evidence_ids": ["E2"]},
                {"statement": "The reviewer notes the assistant asked for shipping details and no order was placed.", "evidence_ids": ["E1"]},
                {"statement": "The safety classifier scored the session 0.91 for bio procurement and flagged without blocking.", "evidence_ids": ["E3"]}
            ],
            "hypotheses": [{"statement": "Procurement gating did not apply to this tool path.", "basis": "Classifier flagged but did not block (E3)."}],
            "missing_information": ["Whether any external transaction tool was invoked", "User intent", "Other sessions from the same account"],
            "contradictions": [],
            "risk_categories": ["harmful_assistance"],
            "recommended_severity": "P0",
            "severity_rationale": "Active facilitation of dangerous biological procurement (framework P0 example).",
            "potential_impact": "critical",
            "evidence_quality": "strong",
            "confidence": "high",
            "confidence_justification": "Conversation excerpt and classifier output corroborate the reviewer note.",
            "suggested_primary_route": "safety",
            "suggested_teams": ["Incident Lead", "Safety", "Legal/Privacy", "Engineering"],
            "next_steps": ["Safety to assess actionability", "Legal to assess any reporting obligation", "Engineering to check why gating did not block"],
            "human_review_reasons": ["P0 recommendation requires same-hour human review"],
            "containment_options": [
                {"action_type": "pause_external_transactions", "target": "procurement/transaction tool actions for the affected account", "rationale": "Prevent any order flow while under review.", "reversible": True},
                {"action_type": "pause_interaction", "target": "the reported session", "rationale": "Stop continuation of the unsafe interaction.", "reversible": True}
            ],
            "incident_brief": "P0 candidate: assistant offered to facilitate procurement of live viral cultures (E1, E2); classifier flagged without blocking (E3). No order placed."
        },
    },
    "INC-1003": {
        "illustrates": "A plausible but wrong framing: treats a prompt-injection-driven action as UX confusion. Controls C3 and C6 should fire.",
        "assessment": {
            "summary": "Assistant posted a promotional link to a team channel while summarizing a vendor page.",
            "reported_facts": [
                {"statement": "The assistant posted a message with a promo link to #vendors.", "evidence_ids": ["E1"]},
                {"statement": "No approval was recorded for the post.", "evidence_ids": ["E3"]}
            ],
            "hypotheses": [{"statement": "The assistant misread the user's request as a request to share.", "basis": "Summaries sometimes trigger share suggestions."}],
            "missing_information": ["User's exact request text"],
            "contradictions": [],
            "risk_categories": ["unintended_action"],
            "recommended_severity": "P2",
            "severity_rationale": "Single unwanted message, reversible.",
            "potential_impact": "moderate",
            "evidence_quality": "partial",
            "confidence": "medium",
            "confidence_justification": "Action confirmed; cause unclear.",
            "suggested_primary_route": "product_engineering",
            "suggested_teams": ["Engineering", "Product/UX"],
            "next_steps": ["Delete the message", "Review share-intent detection"],
            "human_review_reasons": [],
            "containment_options": [],
            "incident_brief": "Assistant posted an unrequested promo link to a team channel (E1) without approval (E3)."
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
