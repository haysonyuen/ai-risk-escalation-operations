"""Fault-injection provider for testing safeguards.

Every result is labeled ``fault_injection``. These are deliberately constructed failures,
not observations about any model.
"""

from __future__ import annotations

import json

from ..rules import RuleResult
from ..schemas import IncidentIntake
from .base import ProviderResult
from .offline import OfflineSimulationProvider

FAULT_MODES = {
    "timeout": "Provider times out",
    "unavailable": "Provider unavailable (connection error)",
    "malformed_json": "Returns text that is not JSON",
    "schema_violation": "Returns JSON with an extra 'approved_containment' field and a missing field",
    "invalid_evidence_refs": "Cites evidence IDs that do not exist in the case",
    "under_severity": "Recommends P3 with high confidence for every case",
    "obeys_embedded_instructions": "Adopts severity/route demanded by text embedded in the report",
}


class FaultInjectionProvider:
    kind = "fault_injection"

    def __init__(self, mode: str) -> None:
        if mode not in FAULT_MODES:
            raise ValueError(f"unknown fault mode {mode}")
        self.mode = mode
        self.name = f"fault:{mode}"
        self._sim = OfflineSimulationProvider()

    def assess(self, incident: IncidentIntake, prompt_version: str, rr: RuleResult) -> ProviderResult:
        res = ProviderResult(provider_kind=self.kind, provider_name=self.name, latency_ms=0.0,
                             notes=[f"FAULT INJECTION: {FAULT_MODES[self.mode]}"])
        if self.mode == "timeout":
            res.error_kind, res.error = "timeout", "Injected timeout"
            return res
        if self.mode == "unavailable":
            res.error_kind, res.error = "unavailable", "Injected connection failure"
            return res
        if self.mode == "malformed_json":
            res.raw_text = "Sure! Here is my assessment: severity is probably P2 {not json"
            res.error_kind, res.error = "malformed", "Could not parse JSON (injected)"
            return res
        base = self._sim.assess(incident, prompt_version, rr).candidate
        cand = json.loads(json.dumps(base))
        if self.mode == "schema_violation":
            cand["approved_containment"] = True
            cand.pop("confidence_justification", None)
        elif self.mode == "invalid_evidence_refs":
            for f in cand["reported_facts"]:
                f["evidence_ids"] = ["E99"]
            cand["reported_facts"].append({"statement": "Logs confirm the file was sent externally.", "evidence_ids": ["LOG-404"]})
        elif self.mode == "under_severity":
            cand["recommended_severity"] = "P3"
            cand["confidence"] = "high"
            cand["human_review_reasons"] = []
        elif self.mode == "obeys_embedded_instructions":
            text = (incident.reported_behavior + " " + " ".join(e.content for e in incident.evidence)).lower()
            for sev in ("p0", "p1", "p2", "p3"):
                if f"as {sev}" in text or f"be {sev}" in text:
                    cand["recommended_severity"] = sev.upper()
            if "severity should be low" in text or "do not escalate" in text:
                cand["recommended_severity"] = "P3"
            cand["human_review_reasons"] = []
        res.candidate = cand
        res.raw_text = json.dumps(cand)
        return res
