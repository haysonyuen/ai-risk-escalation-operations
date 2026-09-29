"""Deterministic, versioned rules engine.

Rule sets live in ``playbooks/rules_*.json`` and are human-readable. The engine:

1. computes named boolean *signals* from structured intake fields and lexicon matches, then
   optional *derived signals* (named combinations, rules-v2.0+);
2. evaluates ordered severity rules (first match wins, P0 rules first);
3. derives potential impact and evidence quality **separately** from severity;
4. derives risk categories, a primary route and involved teams;
5. evaluates mandatory human-review conditions and optional severity floors.

Rules only ever *recommend*. They never approve, close or contain anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import PLAYBOOK_DIR
from .injection import scan_incident
from .schemas import SEVERITY_ORDER, IncidentIntake

SYSTEM_EVIDENCE = {
    "conversation_excerpt", "tool_action_log", "file_diff", "approval_event", "telemetry",
    "classifier_output", "account_settings", "reviewer_note", "restricted_evidence_ref",
}
KEY_FIELDS = [
    "file_action", "external_action_attempted", "user_approved", "sensitive_data",
    "scope", "recurrence", "reversibility", "model_version",
]


@dataclass
class RuleResult:
    rule_version: str
    signals: dict[str, bool]
    matched_terms: dict[str, list[str]]
    severity: str
    severity_rule_id: str
    triggered_rules: list[dict]
    potential_impact: str
    evidence_quality: str
    confidence: str
    categories: list[str]
    primary_route: str
    teams: list[str]
    mandatory_review: bool
    review_reasons: list[dict]
    unknown_fields: list[str]
    injection_findings: list[dict] = field(default_factory=list)
    containment_options: list[dict] = field(default_factory=list)
    floor_applied: dict | None = None


def list_rule_files() -> list[Path]:
    return sorted(PLAYBOOK_DIR.glob("rules_*.json"))


def available_versions() -> list[str]:
    return [json.loads(p.read_text())["rule_version"] for p in list_rule_files()]


@lru_cache(maxsize=16)
def load_rules(version: str) -> dict:
    for p in list_rule_files():
        data = json.loads(p.read_text())
        if data["rule_version"] == version:
            return data
    raise KeyError(f"Unknown rule version: {version}")


def _phrase_regex(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])")


def _lexicon_hits(text: str, phrases: list[str]) -> list[str]:
    t = text.lower()
    return [p for p in phrases if _phrase_regex(p).search(t)]


def compute_signals(incident: IncidentIntake, rules: dict) -> tuple[dict[str, bool], dict[str, list[str]], list[dict]]:
    all_text = " \n".join(
        [incident.title, incident.reported_behavior, incident.reported_impact]
        + [e.content for e in incident.evidence]
    )
    system_text = " \n".join(e.content for e in incident.evidence if e.source_type in SYSTEM_EVIDENCE)

    signals: dict[str, bool] = {}
    matched: dict[str, list[str]] = {}
    for name, phrases in rules["lexicons"].items():
        hits = _lexicon_hits(all_text, phrases)
        signals[name] = bool(hits)
        if hits:
            matched[name] = hits
        sys_hits = _lexicon_hits(system_text, phrases)
        signals[f"{name}_in_system_evidence"] = bool(sys_hits)

    i = incident
    unknown = [f for f in KEY_FIELDS if getattr(i, f) == "unknown"]
    injection = scan_incident(i)
    signals.update({
        "sensitive_yes": i.sensitive_data == "yes",
        "sensitive_possible": i.sensitive_data == "possible",
        "sensitive_unknown": i.sensitive_data == "unknown",
        "sensitive_any": i.sensitive_data in ("yes", "possible"),
        "external_yes": i.external_action_attempted == "yes",
        "external_unknown": i.external_action_attempted == "unknown",
        "approved_no": i.user_approved == "no",
        "approved_yes": i.user_approved == "yes",
        "approved_unknown": i.user_approved == "unknown",
        "file_modified": i.file_action in ("edited", "deleted"),
        "file_deleted": i.file_action == "deleted",
        "irreversible": i.reversibility == "irreversible",
        "reversible": i.reversibility == "reversible",
        "enterprise": i.customer_type == "enterprise",
        "multi_scope": i.scope in ("multiple_users", "workspace", "multiple_customers"),
        "broad_scope": i.scope in ("workspace", "multiple_customers"),
        "repeated": i.recurrence == "repeated",
        "many_unknowns": len(unknown) >= 4,
        "has_system_evidence": any(e.source_type in SYSTEM_EVIDENCE for e in i.evidence),
        "no_system_evidence": not any(e.source_type in SYSTEM_EVIDENCE for e in i.evidence),
        "no_evidence": len(i.evidence) == 0,
        "telemetry_evidence": any(e.source_type == "telemetry" for e in i.evidence),
        "impact_stated": i.reported_impact.strip().lower() not in ("", "unknown"),
        "safety_reviewer_report": i.reporter_channel == "safety_reviewer",
        "report_manipulation": bool(injection),
    })
    # Derived signals (rules-v2.0+): named combinations of other signals, evaluated in order,
    # e.g. "child_sexual" = a minor is mentioned AND sexual content is mentioned.
    for name, cond in rules.get("derived_signals", {}).items():
        signals[name] = matches(cond, signals)
    return signals, matched, injection


def _cond_true(cond: str, signals: dict[str, bool]) -> bool:
    if cond.startswith("!"):
        return not signals.get(cond[1:], False)
    return signals.get(cond, False)


def matches(rule: dict, signals: dict[str, bool]) -> bool:
    if "all" in rule and not all(_cond_true(c, signals) for c in rule["all"]):
        return False
    if "any" in rule and not any(_cond_true(c, signals) for c in rule["any"]):
        return False
    if "none" in rule and any(_cond_true(c, signals) for c in rule["none"]):
        return False
    return True


def evaluate(incident: IncidentIntake, version: str) -> RuleResult:
    rules = load_rules(version)
    signals, matched, injection = compute_signals(incident, rules)
    triggered: list[dict] = []

    severity, sev_rule = rules["default_severity"], "DEFAULT"
    for r in rules["severity_rules"]:
        if matches(r, signals):
            severity, sev_rule = r["severity"], r["id"]
            triggered.append({"id": r["id"], "kind": "severity", "description": r["description"]})
            break

    impact = "low"
    for r in rules["impact_rules"]:
        if matches(r, signals):
            impact = r["level"]
            break

    if signals["no_evidence"]:
        quality = "none"
    elif not signals["has_system_evidence"]:
        quality = "weak"
    else:
        key_corroborated = any(signals.get(f"{s}_in_system_evidence") for s in rules["corroboration_signals"])
        quality = "strong" if key_corroborated else "partial"

    unknown = [f for f in KEY_FIELDS if getattr(incident, f) == "unknown"]
    if quality == "strong" and not signals.get("contradiction") and len(unknown) <= 2:
        confidence = "high"
    elif quality in ("none", "weak") or signals.get("contradiction") or len(unknown) >= 4:
        confidence = "low"
    else:
        confidence = "medium"

    # Floors run after impact/evidence are known, so they can encode
    # "low confidence must not imply low severity". Floors only ever raise severity.
    floor_signals = dict(signals, impact_high_or_critical=impact in ("high", "critical"),
                         impact_critical=impact == "critical",
                         evidence_weak_or_none=quality in ("weak", "none"), confidence_low=confidence == "low")
    floor_applied = None
    for f in rules.get("severity_floors", []):
        if matches(f, floor_signals) and SEVERITY_ORDER[f["floor"]] < SEVERITY_ORDER[severity]:
            floor_applied = {"id": f["id"], "from": severity, "to": f["floor"], "description": f["description"]}
            triggered.append({"id": f["id"], "kind": "severity_floor", "description": f["description"]})
            severity = f["floor"]
            break

    categories = list(dict.fromkeys(c["category"] for c in rules["category_rules"] if matches(c, signals))) or ["benign_noise"]
    route = rules["default_route"]
    for cat, r in rules["route_priority"]:
        if cat in categories:
            route = r
            break
    p3 = rules.get("p3_routing")
    if p3 and severity == "P3" and not set(categories) & set(p3["keep_route_for_categories"]):
        route = p3["route"]
        triggered.append({"id": p3["id"], "kind": "routing", "description": p3["description"]})
    teams: list[str] = []
    for cat in categories:
        for t in rules["teams"].get(cat, []):
            if t not in teams:
                teams.append(t)
    if severity in ("P0", "P1") and "Incident Lead" not in teams:
        teams.insert(0, "Incident Lead")

    sev_signals = dict(floor_signals, **{f"sev_{s}": s == severity for s in SEVERITY_ORDER},
                       floor_applied=floor_applied is not None)
    reasons = []
    for r in rules["mandatory_review"]:
        if matches(r, sev_signals):
            reasons.append({"id": r["id"], "source": "rules", "reason": r["description"]})
            triggered.append({"id": r["id"], "kind": "mandatory_review", "description": r["description"]})

    containment = []
    for cat in categories:
        for opt in rules.get("containment_options", {}).get(cat, []):
            if SEVERITY_ORDER[severity] <= SEVERITY_ORDER[opt.get("offer_at_or_above", "P3")]:
                containment.append({k: v for k, v in opt.items() if k != "offer_at_or_above"})

    return RuleResult(
        rule_version=version, signals=signals, matched_terms=matched, severity=severity,
        severity_rule_id=sev_rule, triggered_rules=triggered, potential_impact=impact,
        evidence_quality=quality, confidence=confidence, categories=categories,
        primary_route=route, teams=teams, mandatory_review=bool(reasons), review_reasons=reasons,
        unknown_fields=unknown, injection_findings=injection, containment_options=containment,
        floor_applied=floor_applied,
    )
