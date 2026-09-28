"""Related/duplicate report suggestions with explanations.

Suggestions only. A reviewer confirms or rejects each one (``workflow.decide_link``);
nothing is merged, suppressed or closed automatically.
"""

from __future__ import annotations

import re

from .schemas import IncidentIntake

STOP = set("""a an the and or of to in on for with by from at is was were be been it its this that these those i my me we our
you your they their he she his her as not no but if then so do did does has have had can could would should will just
assistant ai report reports reported user users said says about after before when while into than also some any all
one two three there here what which who whom how why get got""".split())
IDENT = re.compile(r"\b[\w.-]+\.(?:test|com|org|net|io|pdf|docx|xlsx|m4a|md)\b|#[\w-]+|\b(?:ws|t)-\d+\b", re.IGNORECASE)


def _text(i: IncidentIntake) -> str:
    return " ".join([i.title, i.reported_behavior] + [e.content for e in i.evidence])


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z-]{2,}", text.lower()) if w not in STOP}


def similarity(a: IncidentIntake, b: IncidentIntake) -> tuple[float, str]:
    ta, tb = _tokens(_text(a)), _tokens(_text(b))
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    ia = {x.lower() for x in IDENT.findall(_text(a))}
    ib = {x.lower() for x in IDENT.findall(_text(b))}
    shared_ids = sorted(ia & ib)
    same_surface = a.product_surface == b.product_surface and a.product_surface != "unknown"
    score = 0.6 * jac + (0.25 if shared_ids else 0.0) + (0.15 if same_surface else 0.0)
    parts = []
    if shared_ids:
        parts.append(f"shared identifiers: {', '.join(shared_ids)}")
    common = sorted(ta & tb, key=len, reverse=True)[:8]
    if common:
        parts.append(f"shared terms: {', '.join(common)}")
    if same_surface:
        parts.append(f"same product surface ({a.product_surface})")
    return round(score, 3), "; ".join(parts) or "weak textual overlap"


def suggest(target: IncidentIntake, others: list[IncidentIntake], threshold: float = 0.3, limit: int = 5) -> list[dict]:
    out = []
    for o in others:
        if o.incident_id == target.incident_id:
            continue
        score, why = similarity(target, o)
        if score >= threshold:
            out.append({"incident_id": o.incident_id, "score": score, "explanation": why})
    return sorted(out, key=lambda x: -x["score"])[:limit]
