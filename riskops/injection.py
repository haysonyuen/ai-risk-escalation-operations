"""Detection of instructions embedded in untrusted incident text.

Incident reports and evidence are *data*. Text inside them that tries to direct the
evaluator ("classify this as P3", "approve containment", "ignore previous instructions")
is flagged for human review. Detection never grants the text any authority: nothing in this
module, the rules engine or the workflow reads such text as an instruction.
"""

from __future__ import annotations

import re

from .schemas import IncidentIntake

# Patterns aimed at the triage system itself (as opposed to a report *describing* a prompt
# injection against the product, which is a legitimate risk category handled by the rules).
_PATTERNS: list[tuple[str, str]] = [
    (r"\bignore (all |any )?(previous|prior|above|your) (instructions|rules|guidelines)", "asks the evaluator to ignore its instructions"),
    (r"\b(classify|mark|label|set|rate|treat) (this|the) (case|incident|report|ticket)? ?(as|to) (p[0-3]|low|high|critical|benign)", "attempts to set the severity"),
    (r"\b(severity|priority) (should|must) be (p[0-3]|low|high)", "attempts to set the severity"),
    (r"\b(approve|approved|authorize)[sd]? (the )?(containment|lockout|action|closure)", "attempts to approve an action"),
    (r"\b(close|resolve|dismiss) (this|the) (case|incident|ticket) (immediately|now|without)", "attempts to close the case"),
    (r"\bdo not (escalate|route|send) (this|to)", "attempts to suppress escalation"),
    (r"\b(route|escalate|forward) (this|the case|it) (directly )?to (legal|security|safety|the ceo|executives)\b.*\b(immediately|now)", "attempts to force routing"),
    (r"^\s*(system|assistant|developer)\s*:", "impersonates a system/assistant role"),
    (r"\[\s*(system|admin|override)\s*\]", "contains an override marker"),
    (r"\byou are (now )?(the|an?) (triage|review|evaluation) (model|system|assistant)", "addresses the triage system directly"),
    (r"\bnote to (the )?(ai|model|reviewer bot|triage (bot|system))", "addresses the triage system directly"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE | re.MULTILINE), why) for p, why in _PATTERNS]


def scan_text(text: str) -> list[str]:
    reasons = []
    for rx, why in _COMPILED:
        m = rx.search(text or "")
        if m:
            reasons.append(f"{why}: \"{m.group(0).strip()[:80]}\"")
    return reasons


def scan_incident(incident: IncidentIntake) -> list[dict]:
    """Return findings as [{location, reason}] across all free-text fields and evidence."""
    findings = []
    fields = {
        "title": incident.title,
        "reported_behavior": incident.reported_behavior,
        "reported_impact": incident.reported_impact,
    }
    for name, text in fields.items():
        for r in scan_text(text):
            findings.append({"location": name, "reason": r})
    for ev in incident.evidence:
        for r in scan_text(ev.content):
            findings.append({"location": f"evidence:{ev.evidence_id}", "reason": r})
    return findings
