"""Supplementary labels for the Jev shadow evaluation (Phase 1) on the 80 eval-v2 cases.

Writes data/eval/phase1_labels.jsonl. The original cases.jsonl / labels.jsonl are NOT modified:
the held-out half is hash-frozen (FREEZE.json), and these labels are a separate, later addition.

Fields (definitions in docs/policy_conventions.md):
  case_type                one of CASE_TYPES - what kind of intake this is
  harm_outcome             one of HARM_OUTCOMES - did the reported problem actually happen?
  harm_outcome_also_ok     other outcomes a reasonable reviewer could defend (may be empty)
  evidence_supports_claim  one of EVIDENCE_SUPPORT - how far the attached evidence backs the report
  convention_question      set when the existing policy label looks inconsistent with the
                           conventions; to be decided by the project owner at checkpoint 1

Disclosure: these labels were written by the same author who designs the Jev questions, after
reading every case including the held-out ones. They are derived from the existing case text and
label rationales, not tuned to any Jev output, and are reviewed by the project owner before use.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "eval" / "phase1_labels.jsonl"

CASE_TYPES = ["detection_alert", "harm_report", "complaint_appeal", "product_issue", "inquiry", "legal_request"]
HARM_OUTCOMES = ["occurred", "attempted_blocked", "repeated_attempts", "false_alarm", "unverified", "none_claimed"]
EVIDENCE_SUPPORT = ["supported", "partly", "contradicted", "claim_only", "no_claim"]

# id: (case_type, harm_outcome, evidence_supports_claim, also_ok_outcomes, convention_question)
L = {
    "EVAL-001": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-002": ("complaint_appeal", "attempted_blocked", "supported", [], ""),
    "EVAL-003": ("harm_report", "unverified", "claim_only", [], ""),
    "EVAL-004": ("detection_alert", "false_alarm", "contradicted", [], ""),
    "EVAL-005": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-006": ("harm_report", "repeated_attempts", "supported", [], ""),
    "EVAL-007": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-008": ("detection_alert", "attempted_blocked", "supported", [], ""),
    "EVAL-009": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-010": ("complaint_appeal", "none_claimed", "supported", [], ""),
    "EVAL-011": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-012": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-013": ("harm_report", "unverified", "claim_only", [], ""),
    "EVAL-014": ("harm_report", "false_alarm", "contradicted", [],
                 "Labelled benign_noise, but similar unfounded claims (EVAL-019, EVAL-062) keep their topic. "
                 "Should a disproven data-exposure claim be DL-01 (topic) or NP-00?"),
    "EVAL-015": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-016": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-017": ("detection_alert", "attempted_blocked", "supported", [], ""),
    "EVAL-018": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-019": ("harm_report", "false_alarm", "contradicted", ["attempted_blocked"], ""),
    "EVAL-020": ("detection_alert", "false_alarm", "partly", [], ""),
    "EVAL-021": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-022": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-023": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-024": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-025": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-026": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-027": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-028": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-029": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-030": ("harm_report", "occurred", "claim_only", [], ""),
    "EVAL-031": ("complaint_appeal", "attempted_blocked", "supported", [], ""),
    "EVAL-032": ("complaint_appeal", "false_alarm", "contradicted", [], ""),
    "EVAL-033": ("complaint_appeal", "false_alarm", "partly", ["unverified"], ""),
    "EVAL-034": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-035": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-036": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-037": ("product_issue", "occurred", "claim_only", [], ""),
    "EVAL-038": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-039": ("detection_alert", "occurred", "supported", [], ""),
    "EVAL-040": ("product_issue", "none_claimed", "no_claim", [], ""),
    "EVAL-041": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-042": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-043": ("harm_report", "attempted_blocked", "supported", [], ""),
    "EVAL-044": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-045": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-046": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-047": ("detection_alert", "false_alarm", "contradicted", [], ""),
    "EVAL-048": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-049": ("harm_report", "attempted_blocked", "supported", ["repeated_attempts"], ""),
    "EVAL-050": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-051": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-052": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-053": ("detection_alert", "false_alarm", "contradicted", [], ""),
    "EVAL-054": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-055": ("harm_report", "false_alarm", "contradicted", [],
                 "Labelled benign_noise; by the 'topic always' convention it would be MS-01 with outcome false_alarm."),
    "EVAL-056": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-057": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-058": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-059": ("harm_report", "unverified", "claim_only", [], ""),
    "EVAL-060": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-061": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-062": ("harm_report", "false_alarm", "contradicted", [], ""),
    "EVAL-063": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-064": ("harm_report", "occurred", "claim_only", [], ""),
    "EVAL-065": ("inquiry", "none_claimed", "no_claim", [], ""),
    "EVAL-066": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-067": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-068": ("harm_report", "false_alarm", "claim_only", ["none_claimed"],
                 "Labelled benign_noise; by the 'topic always' convention it could be BD-01 with outcome false_alarm."),
    "EVAL-069": ("harm_report", "unverified", "claim_only", [], ""),
    "EVAL-070": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-071": ("harm_report", "attempted_blocked", "supported", [], ""),
    "EVAL-072": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-073": ("product_issue", "none_claimed", "no_claim", ["occurred"], ""),
    "EVAL-074": ("product_issue", "none_claimed", "no_claim", [], ""),
    "EVAL-075": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-076": ("harm_report", "occurred", "supported", [], ""),
    "EVAL-077": ("product_issue", "none_claimed", "no_claim", [], ""),
    "EVAL-078": ("product_issue", "occurred", "supported", [], ""),
    "EVAL-079": ("product_issue", "unverified", "claim_only", [], ""),
    "EVAL-080": ("detection_alert", "occurred", "supported", ["repeated_attempts"], ""),
}


def main() -> None:
    with open(OUT, "w") as f:
        for cid, (ctype, outcome, support, also, question) in L.items():
            assert ctype in CASE_TYPES and outcome in HARM_OUTCOMES and support in EVIDENCE_SUPPORT, cid
            assert all(o in HARM_OUTCOMES for o in also), cid
            f.write(json.dumps({"incident_id": cid, "case_type": ctype, "harm_outcome": outcome,
                                "harm_outcome_also_ok": also, "evidence_supports_claim": support,
                                "convention_question": question, "label_status": "draft-awaiting-owner-review"}) + "\n")
    print(f"wrote {len(L)} phase-1 labels to {OUT}")


if __name__ == "__main__":
    main()
