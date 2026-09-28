"""Offline providers. Nothing here is a model.

* ``OfflineFixtureProvider`` returns hand-authored assessment JSON from ``fixtures/assessments``
  for specific demo incidents. Fixtures illustrate what a model output could look like,
  including imperfect ones. They are labeled ``offline_fixture`` everywhere.
* ``OfflineSimulationProvider`` deterministically restates the rules-engine result in the
  assessment schema (with evidence-linked facts copied from the case). Labeled
  ``offline_simulation``. Its outputs must never be reported as model performance.
* ``OfflineProvider`` uses a fixture when one exists for the exact incident content,
  otherwise the simulation.
"""

from __future__ import annotations

import hashlib
import json
import time

from ..config import FIXTURE_DIR
from ..rules import RuleResult
from ..schemas import IncidentIntake
from .base import ProviderResult

FIELD_LABELS = {
    "file_action": "file action", "external_action_attempted": "whether an external action was attempted",
    "user_approved": "whether the user approved the action", "sensitive_data": "sensitive-data involvement",
    "scope": "scope / blast radius", "recurrence": "recurrence", "reversibility": "reversibility",
    "model_version": "model/product version",
}


def intake_fingerprint(incident: IncidentIntake) -> str:
    payload = incident.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class OfflineSimulationProvider:
    kind = "offline_simulation"
    name = "deterministic-simulation"

    def assess(self, incident: IncidentIntake, prompt_version: str, rr: RuleResult) -> ProviderResult:
        t0 = time.perf_counter()
        facts = []
        for ev in incident.evidence:
            prefix = "Reporter states" if ev.source_type == "reporter_statement" else f"{ev.source_description} records"
            facts.append({"statement": f"{prefix}: {ev.content[:220]}", "evidence_ids": [ev.evidence_id]})
        missing = [f"Unknown: {FIELD_LABELS[f]}" for f in rr.unknown_fields]
        if not any(e.source_type != "reporter_statement" for e in incident.evidence):
            missing.append("No system evidence (logs, diffs, approval events) attached yet")
        contradictions = []
        if rr.signals.get("contradiction"):
            ids = [e.evidence_id for e in incident.evidence if e.source_type != "reporter_statement"]
            contradictions.append({"description": "Evidence text indicates records that do not match the report (lexicon match, needs human reading).", "evidence_ids": ids})
        reasons = [r["reason"] for r in rr.review_reasons]
        candidate = {
            "summary": f"[SIMULATED] {incident.title}. Rules {rr.rule_version} matched {rr.severity_rule_id}; categories: {', '.join(rr.categories)}.",
            "reported_facts": facts,
            "hypotheses": [{"statement": f"Possible {c.replace('_', ' ')} issue", "basis": "Rule/lexicon match only; not verified."} for c in rr.categories if c != "benign_noise"],
            "missing_information": missing,
            "contradictions": contradictions,
            "risk_categories": rr.categories,
            "recommended_severity": rr.severity,
            "severity_rationale": f"Deterministic rule {rr.severity_rule_id} ({rr.rule_version}).",
            "potential_impact": rr.potential_impact,
            "evidence_quality": rr.evidence_quality,
            "confidence": rr.confidence,
            "confidence_justification": f"Evidence quality {rr.evidence_quality}; {len(rr.unknown_fields)} key field(s) unknown.",
            "suggested_primary_route": rr.primary_route,
            "suggested_teams": rr.teams,
            "next_steps": ["Human reviewer to read source evidence before confirming severity"]
                          + ([f"Retrieve missing information: {', '.join(FIELD_LABELS[f] for f in rr.unknown_fields)}"] if rr.unknown_fields else []),
            "human_review_reasons": reasons,
            "containment_options": rr.containment_options,
            "incident_brief": f"[SIMULATED BRIEF] {incident.title}. Recommended {rr.severity} by rules; confidence {rr.confidence}. Evidence items: {len(incident.evidence)}.",
        }
        return ProviderResult(
            provider_kind=self.kind, provider_name=self.name, candidate=candidate,
            raw_text=json.dumps(candidate), latency_ms=(time.perf_counter() - t0) * 1000,
            notes=["Offline deterministic simulation - not a model output."],
        )


class OfflineFixtureProvider:
    kind = "offline_fixture"
    name = "authored-fixture"

    def available(self, incident: IncidentIntake) -> bool:
        p = FIXTURE_DIR / f"{incident.incident_id}.json"
        if not p.exists():
            return False
        return json.loads(p.read_text()).get("input_fingerprint") == intake_fingerprint(incident)

    def assess(self, incident: IncidentIntake, prompt_version: str, rr: RuleResult) -> ProviderResult:
        p = FIXTURE_DIR / f"{incident.incident_id}.json"
        data = json.loads(p.read_text())
        raw = json.dumps(data["assessment"])
        return ProviderResult(
            provider_kind=self.kind, provider_name=self.name, model_name=None, raw_text=raw,
            candidate=data["assessment"], latency_ms=0.0,
            notes=["Hand-authored fixture illustrating a possible model output. Not a model output."],
        )


class OfflineProvider:
    """Fixture when available for the exact intake content; otherwise deterministic simulation."""

    kind = "offline"
    name = "offline"

    def __init__(self) -> None:
        self.fixture = OfflineFixtureProvider()
        self.sim = OfflineSimulationProvider()

    def assess(self, incident: IncidentIntake, prompt_version: str, rr: RuleResult) -> ProviderResult:
        if self.fixture.available(incident):
            return self.fixture.assess(incident, prompt_version, rr)
        return self.sim.assess(incident, prompt_version, rr)
