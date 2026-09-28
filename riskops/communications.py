"""Evidence-referenced communication drafts. Drafts are never sent.

Offline mode uses templates. Live mode (optional) asks the model to tighten the template
draft; if that call fails the template draft is kept and labeled as such.
"""

from __future__ import annotations

import json

from . import config
from .db import rows
from .workflow import (SIMULATED_ACTORS, effective_severity, get_assessment, get_incident, get_intake,
                       latest_communications)

STATUS_TEXT = {"NEW": "New", "ASSESSED": "Awaiting triage", "ASSESSMENT_FAILED": "Awaiting triage (AI assessment failed)",
               "TRIAGED": "Triaged", "INVESTIGATING": "Investigating", "CONTAINMENT": "Containment", "RESPONSE": "Response",
               "CLOSED": "Closed", "REOPENED": "Reopened", "QA_REVIEWED": "Closed (QA reviewed)"}


def _person(actor_id: str | None) -> str:
    for a in SIMULATED_ACTORS:
        if a.actor_id == actor_id:
            return a.display.replace(" (simulated)", "")
    return actor_id or "unassigned"

COMM_TYPES = {
    "executive_brief": "Executive incident brief",
    "handoff": "Cross-functional handoff",
    "user_ack": "User / customer acknowledgment",
    "closure_summary": "Closure summary",
}
HEADER = "DRAFT — NOT SENT. Simulated communication generated for review in a prototype.\n"


def _context(conn, incident_id: str) -> dict:
    inc = get_incident(conn, incident_id)
    intake = get_intake(conn, incident_id)
    a = get_assessment(conn, inc["current_assessment_id"])
    sev, basis = effective_severity(conn, inc)
    verified = {(r["assessment_id"], r["fact_index"]): r["verdict"] for r in
                rows(conn, "SELECT * FROM claim_reviews ORDER BY review_id")}
    facts = []
    if a and a["output"]:
        for i, f in enumerate(a["output"]["reported_facts"]):
            facts.append({"text": f["statement"], "refs": f["evidence_ids"], "verdict": verified.get((a["assessment_id"], i))})
    containment = rows(conn, "SELECT * FROM containment_actions WHERE incident_id=? ORDER BY proposed_at", (incident_id,))
    categories = (a["output"]["risk_categories"] if a and a["output"] else
                  (a["rule_result"]["categories"] if a else []))
    return {"inc": inc, "intake": intake, "a": a, "sev": sev, "basis": basis, "facts": facts,
            "containment": containment, "categories": categories}


def required_reviews(ctx: dict, comm_type: str) -> list[str]:
    i = ctx["intake"]
    req = []
    sensitive = i.sensitive_data in ("yes", "possible") or "sensitive_data" in ctx["categories"]
    external = comm_type in ("user_ack", "closure_summary", "executive_brief")
    if sensitive or (external and i.customer_type == "enterprise") or (external and ctx["sev"] in ("P0", "P1")):
        req.append("Legal/Privacy")
    if {"harmful_assistance", "synthetic_media"} & set(ctx["categories"]) and comm_type in ("user_ack", "executive_brief", "closure_summary"):
        req.append("Safety")
    return req


def _fact_lines(ctx: dict) -> list[str]:
    if not ctx["facts"]:
        return ["- No AI-extracted facts available; see evidence records directly."]
    out = []
    for f in ctx["facts"]:
        tag = {"supported": "reviewer-verified", "partially_supported": "partially verified",
               "unsupported": "REVIEWER MARKED UNSUPPORTED", "cannot_determine": "unverifiable"}.get(f["verdict"], "not yet verified")
        out.append(f"- {f['text']} [{', '.join(f['refs'])}] ({tag})")
    return out


def _uncertainty(ctx: dict) -> list[str]:
    a = ctx["a"]
    lines = []
    if a and a["output"]:
        o = a["output"]
        lines += [f"- Unknown: {m}" for m in o["missing_information"][:6]]
        lines += [f"- Contradiction: {c['description']} [{', '.join(c['evidence_ids'])}]" for c in o["contradictions"]]
        lines.append(f"- Confidence: {o['confidence']} — {o['confidence_justification']}")
    elif a:
        lines.append(f"- AI assessment failed ({a['error_kind']}); facts not machine-extracted.")
    return lines or ["- None recorded."]


def _actions(ctx: dict) -> list[str]:
    out = []
    for c in ctx["containment"]:
        out.append(f"- [SIMULATED] {c['action_type']} on {c['target']}: {c['status']}"
                   + (f", review by {c['review_by']}" if c["review_by"] and c["status"] == "active" else ""))
    return out or ["- No containment recorded."]


def render(conn, incident_id: str, comm_type: str) -> tuple[str, list[str], list[str]]:
    ctx = _context(conn, incident_id)
    inc, i = ctx["inc"], ctx["intake"]
    refs = sorted({r for f in ctx["facts"] for r in f["refs"]}) or [e.evidence_id for e in i.evidence]
    teams = json.loads(inc["human_teams_json"] or "null") or ((ctx["a"] or {}).get("rule_result") or {}).get("teams", [])
    sev_line = f"{ctx['sev']} ({'human-confirmed' if ctx['basis'] == 'human' else 'NOT YET CONFIRMED by a human: ' + ctx['basis']})"
    if comm_type == "executive_brief":
        body = [HEADER, f"EXECUTIVE BRIEF — {i.incident_id}: {i.title}", "",
                f"Severity: {sev_line}", f"Status: {STATUS_TEXT.get(inc['status'], inc['status'])}  |  Owner: {_person(inc['owner'])}",
                f"Teams: {', '.join(teams) or 'not set'}", "",
                "Impact (as reported / assessed):", f"- {i.reported_impact if i.reported_impact != 'unknown' else 'Impact not yet established.'}",
                f"- Scope: {i.scope.replace('_', ' ')}; customer type: {i.customer_type}; sensitive data: {i.sensitive_data}", "",
                "Facts from evidence:", *_fact_lines(ctx), "", "Uncertainty:", *_uncertainty(ctx), "",
                "Actions:", *_actions(ctx), "",
                "Next decision / update needed:",
                f"- {'Human severity confirmation' if ctx['basis'] != 'human' else 'Confirm containment review and root-cause investigation plan'}; next update at the SLA checkpoint."]
    elif comm_type == "handoff":
        o = (ctx["a"] or {}).get("output") or {}
        body = [HEADER, f"HANDOFF — {i.incident_id}: {i.title}", f"To: {', '.join(teams) or 'owning team'}",
                f"Severity: {sev_line}", "", "What we know (with evidence IDs):", *_fact_lines(ctx), "",
                "Hypotheses (unverified):", *([f"- {h['statement']} — basis: {h['basis']}" for h in o.get("hypotheses", [])] or ["- None recorded."]),
                "", "Open questions:", *_uncertainty(ctx), "", "Requested from receiving team:",
                *([f"- {s}" for s in o.get("next_steps", [])] or ["- Review evidence and confirm ownership."]),
                "", "Containment state:", *_actions(ctx)]
    elif comm_type == "user_ack":
        safety = "harmful_assistance" in ctx["categories"]
        body = [HEADER, "Subject: We received your report" + (f" ({i.incident_id})" if i.incident_id else ""), "",
                "Hello,", "",
                "Thank you for reporting this. We have received it and a member of our team is reviewing it.",
                "We are looking at what the assistant did, what was shown to you, and whether anything else was affected.",
                "Approving an action in the product does not mean you did anything wrong; we are reviewing how the action was presented.",
                *(["For your safety we will not repeat the content of the response here. The report has been escalated for specialist review."] if safety else []),
                *(["If files were changed, you can review and restore earlier versions from version history while we investigate."] if i.file_action in ("edited", "deleted") else []),
                "We will not speculate about the cause until we have reviewed the records. We will follow up with an update.",
                "", "— Support team (draft)", "", f"[Internal: evidence referenced {', '.join(refs)}; no commitments about exposure, retention, deletion or legal impact are made in this draft.]"]
    elif comm_type == "closure_summary":
        cl = json.loads(inc["closure_json"]) if inc["closure_json"] else None
        body = [HEADER, f"CLOSURE SUMMARY — {i.incident_id}: {i.title}"]
        if cl:
            body += [f"Final severity: {cl['final_severity']} | Category: {cl['closure_category']}",
                     f"Root cause: {cl['root_cause']}", f"Impact: {cl['user_customer_impact']}",
                     f"Evidence reviewed: {', '.join(cl['evidence_reviewed'])}", f"Teams: {', '.join(cl['teams_involved'])}",
                     f"Actions: {cl['actions_taken']}", f"Response: {cl['response_status']}",
                     f"Remaining mitigation: {cl['remaining_mitigation']}", f"Monitoring required: {cl['monitoring_required']}"]
        else:
            body += ["Case not yet closed. Proposed summary based on current record:", f"Severity: {sev_line}",
                     "Facts:", *_fact_lines(ctx), "Actions:", *_actions(ctx)]
    else:
        raise ValueError(comm_type)
    return "\n".join(body), refs, required_reviews(ctx, comm_type)


def live_polish(text: str, comm_type: str) -> tuple[str, str]:
    """Optional model-assisted drafting. Returns (text, generator label)."""
    if not config.live_credentials_available():
        return text, "template"
    try:
        import anthropic
        client = anthropic.Anthropic(timeout=config.live_timeout_seconds(), max_retries=1)
        msg = client.messages.create(
            model=config.live_model_name(), max_tokens=4000,
            system=("Tighten this incident communication draft. Keep every evidence ID in brackets, keep the DRAFT header, "
                    "do not add facts, do not remove uncertainty, do not blame the user, and do not include harmful details."),
            messages=[{"role": "user", "content": f"<draft type='{comm_type}'>\n{text}\n</draft>"}])
        out = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text").strip()
        if msg.stop_reason != "end_turn" or "DRAFT" not in out:
            return text + "\n[Live drafting output rejected; template kept]", "template"
        return out, "live_model"
    except Exception as e:  # noqa: BLE001 - any provider failure keeps the template, visibly
        return text + f"\n[Live drafting unavailable ({type(e).__name__}); template kept]", "template"


def generate(conn, incident_id: str, comm_type: str, actor, use_live: bool = False, origin: str = "demo") -> str:
    from .workflow import save_communication
    body, refs, req = render(conn, incident_id, comm_type)
    generator = "template"
    if use_live:
        body, generator = live_polish(body, comm_type)
    existing = [c for c in latest_communications(conn, incident_id) if c["comm_type"] == comm_type]
    return save_communication(conn, incident_id, comm_type, body, refs, req, actor, generator,
                              comm_id=existing[0]["comm_id"] if existing else None, origin=origin)
