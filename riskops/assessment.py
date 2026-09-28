"""Assessment pipeline: provider output -> schema validation -> evidence-reference check ->
deterministic controls.

Keeps four things separate on every record:
  * potential impact / urgency          (``impact``)
  * evidence quality and uncertainty    (``evidence_quality``, ``confidence``)
  * model (or simulation) recommendation (``model_severity``)
  * recommendation after deterministic controls (``controlled_severity``)
Human-confirmed severity lives on the incident, never here.

Controls are always on and independent of rule version:
  C1 provider failure / malformed / schema-invalid -> no AI assessment; manual review
  C2 evidence references must exist in the case; invalid refs flagged -> review
  C3 model severity below the rules recommendation -> controlled severity raised to the rules
     recommendation (a floor; controls never lower severity) -> review
  C4 embedded instructions in the report -> review (text is never obeyed)
  C5 low confidence on a potentially high/critical-impact case -> review (low confidence is
     never treated as low severity)
  C6 route disagreement on a specialist queue (safety / legal_privacy / product_security) ->
     the specialist route is kept and the case is flagged
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from pydantic import ValidationError

from . import rules as rules_mod
from .providers.base import AssessmentProvider
from .schemas import SEVERITY_ORDER, AssessmentOutput, IncidentIntake, severity_max

SPECIALIST_ROUTES = {"safety", "legal_privacy", "product_security"}
# Version of the always-on controls (C1-C6) and the embedded-instruction detector.
# controls-v1.0 -> v1.1: role labels inside conversation excerpts no longer count as
# impersonation (false positive observed on seeded demo case INC-1001).
CONTROLS_VERSION = "controls-v1.1"


def _reason(code: str, text: str, source: str = "control") -> dict:
    return {"id": code, "source": source, "reason": text}


def assess_incident(incident: IncidentIntake, provider: AssessmentProvider, rule_version: str,
                    prompt_version: str) -> dict:
    rr = rules_mod.evaluate(incident, rule_version)
    pres = provider.assess(incident, prompt_version, rr)

    record = {
        "assessment_id": f"AS-{uuid.uuid4().hex[:10]}",
        "incident_id": incident.incident_id,
        "provider_kind": pres.provider_kind,
        "provider_name": pres.provider_name,
        "model_name": pres.model_name,
        "prompt_version": prompt_version,
        "rule_version": rule_version,
        "controls_version": CONTROLS_VERSION,
        "latency_ms": pres.latency_ms,
        "input_tokens": pres.input_tokens,
        "output_tokens": pres.output_tokens,
        "cost_usd": pres.cost_usd,
        "provider_notes": pres.notes,
        "raw_text": pres.raw_text,
        "rule_result": asdict(rr),
    }
    reasons: list[dict] = list(rr.review_reasons)
    controls: list[dict] = []

    for f in rr.injection_findings:
        reasons.append(_reason("C4", f"Embedded instruction in {f['location']} ignored and flagged ({f['reason']})"))
    if rr.injection_findings:
        controls.append({"id": "C4", "effect": "flagged", "detail": f"{len(rr.injection_findings)} embedded-instruction finding(s)"})

    output: AssessmentOutput | None = None
    error_kind, error = pres.error_kind, pres.error
    if not error_kind:
        try:
            output = AssessmentOutput.model_validate(pres.candidate)
        except ValidationError as e:
            error_kind = "schema_invalid"
            error = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:6])

    impact, quality, confidence = rr.potential_impact, rr.evidence_quality, rr.confidence
    if output is None:
        record.update(status="failed", error_kind=error_kind, error=error, output=None,
                      model_severity=None, invalid_evidence_refs=[], fact_ref_status=[])
        reasons.append(_reason("C1", f"AI assessment failed ({error_kind}): case routed to manual review; no assessment was invented"))
        controls.append({"id": "C1", "effect": "manual_review", "detail": error})
        controlled_sev, controlled_route = rr.severity, rr.primary_route
        controls.append({"id": "C1", "effect": "fallback_to_rules_recommendation",
                         "detail": f"Deterministic {rule_version} recommendation shown instead ({rr.severity}); labeled as rules output"})
    else:
        valid_ids = {e.evidence_id for e in incident.evidence}
        invalid: list[str] = []
        fact_status = []
        for i, fact in enumerate(output.reported_facts):
            bad = [r for r in fact.evidence_ids if r not in valid_ids]
            invalid.extend(bad)
            fact_status.append({"fact_index": i, "invalid_refs": bad,
                                "status": "invalid_reference" if bad else "reference_exists_unverified_support"})
        for c in output.contradictions:
            invalid.extend(r for r in c.evidence_ids if r not in valid_ids)
        invalid = sorted(set(invalid))
        if invalid:
            reasons.append(_reason("C2", f"Assessment cites evidence IDs not in the case: {', '.join(invalid)}"))
            controls.append({"id": "C2", "effect": "flagged", "detail": f"invalid refs {invalid}"})

        model_sev = output.recommended_severity
        controlled_sev = severity_max(model_sev, rr.severity)
        if controlled_sev != model_sev:
            reasons.append(_reason("C3", f"Recommendation {model_sev} is below the {rule_version} rule floor {rr.severity}; raised to {rr.severity}"))
            controls.append({"id": "C3", "effect": "raised", "detail": f"{model_sev} -> {controlled_sev}"})

        controlled_route = output.suggested_primary_route
        if rr.primary_route in SPECIALIST_ROUTES and controlled_route != rr.primary_route:
            reasons.append(_reason("C6", f"Suggested route {controlled_route} differs from rules specialist route {rr.primary_route}; specialist route kept"))
            controls.append({"id": "C6", "effect": "route_kept", "detail": f"{controlled_route} -> {rr.primary_route}"})
            controlled_route = rr.primary_route

        for r in output.human_review_reasons:
            reasons.append(_reason("MODEL", r, source=pres.provider_kind))
        impact = output.potential_impact if output.potential_impact != "unknown" else rr.potential_impact
        # Use the more cautious of provider and rules views of uncertainty.
        quality_rank = {"none": 0, "weak": 1, "partial": 2, "strong": 3}
        quality = min(output.evidence_quality, rr.evidence_quality, key=lambda q: quality_rank[q])
        conf_rank = {"low": 0, "medium": 1, "high": 2}
        confidence = min(output.confidence, rr.confidence, key=lambda c: conf_rank[c])
        record.update(status="valid", error_kind=None, error=None, output=output.model_dump(mode="json"),
                      model_severity=model_sev, invalid_evidence_refs=invalid, fact_ref_status=fact_status)

    high_impact = impact in ("high", "critical") or rr.potential_impact in ("high", "critical")
    if high_impact and (confidence == "low" or quality in ("weak", "none")):
        reasons.append(_reason("C5", f"Potential impact {impact} with {confidence} confidence / {quality} evidence: do not downgrade without evidence review"))
        controls.append({"id": "C5", "effect": "flagged", "detail": "low confidence does not imply low severity"})

    # de-duplicate reasons while keeping order
    seen, uniq = set(), []
    for r in reasons:
        key = (r["id"], r["reason"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)

    record.update(
        rules_severity=rr.severity,
        controlled_severity=controlled_sev,
        controlled_route=controlled_route,
        impact=impact,
        evidence_quality=quality,
        confidence=confidence,
        mandatory_review=bool(uniq),
        review_reasons=uniq,
        controls=controls,
    )
    return record


def is_downgrade(from_sev: str, to_sev: str) -> bool:
    return SEVERITY_ORDER[to_sev] > SEVERITY_ORDER[from_sev]
