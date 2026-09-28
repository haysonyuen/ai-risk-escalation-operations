"""Workflow service layer: state machine, human decisions, containment, closure, linking.

All authorization checks live here, not in the UI. Roles are SIMULATED demo identities
selected from a dropdown; this is not authentication and provides no real access control.

Every state change writes an append-only event with actor, timestamp, previous value, new
value and reason.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import config
from .assessment import assess_incident, is_downgrade
from .db import get_setting, log_event, now_iso, row, rows, set_setting, utcnow
from .rules import available_versions
from .schemas import (REVERSIBLE_CONTAINMENT, SEVERITIES, SEVERITY_ORDER, ContainmentType, Evidence,
                      IncidentIntake)


class WorkflowError(Exception):
    """Invalid transition or missing required data."""


class PermissionDenied(WorkflowError):
    """Actor's simulated role may not perform this action."""


# ---------------------------------------------------------------------------------------
# Simulated identities and roles
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Actor:
    actor_id: str
    display: str
    role: str

    @property
    def is_human(self) -> bool:
        return self.role != "system"


ROLE_LABELS = {
    "risk_ops_analyst": "Risk Ops Analyst",
    "incident_lead": "Incident Lead",
    "safety_specialist": "Safety Specialist",
    "legal_privacy": "Legal/Privacy Reviewer",
    "support_agent": "Support Agent",
    "engineering": "Engineering On-call",
    "system": "AI assistant / automation (not a person)",
}
SIMULATED_ACTORS = [
    Actor("alex.riskops", "Alex — Risk Ops Analyst (simulated)", "risk_ops_analyst"),
    Actor("sam.lead", "Sam — Incident Lead (simulated)", "incident_lead"),
    Actor("priya.safety", "Priya — Safety Specialist (simulated)", "safety_specialist"),
    Actor("jordan.legal", "Jordan — Legal/Privacy (simulated)", "legal_privacy"),
    Actor("casey.support", "Casey — Support Agent (simulated)", "support_agent"),
    Actor("lee.eng", "Lee — Engineering On-call (simulated)", "engineering"),
]
SYSTEM_ACTOR = Actor("system.assistant", "AI assistant / automation", "system")
HUMAN_ROLES = {a.role for a in SIMULATED_ACTORS}
TRIAGE_ROLES = {"risk_ops_analyst", "incident_lead"}

PERMISSIONS: dict[str, set[str]] = {
    "create_incident": HUMAN_ROLES,
    "run_assessment": TRIAGE_ROLES | {"system"},
    "decide_severity": TRIAGE_ROLES,
    "assign_owner": TRIAGE_ROLES,
    "transition": TRIAGE_ROLES,
    "add_note": HUMAN_ROLES,
    "add_evidence": HUMAN_ROLES,
    "propose_containment": HUMAN_ROLES | {"system"},
    "approve_containment_p2p3": TRIAGE_ROLES,
    "approve_containment_p0p1": {"incident_lead"},
    "end_containment": TRIAGE_ROLES,
    "draft_communication": HUMAN_ROLES | {"system"},
    "edit_communication": HUMAN_ROLES,
    "approve_communication_general": TRIAGE_ROLES,
    "close_p2p3": TRIAGE_ROLES,
    "close_p0p1": {"incident_lead"},
    "reopen": TRIAGE_ROLES,
    "decide_link": TRIAGE_ROLES,
    "qa_review": TRIAGE_ROLES,
    "claim_review": TRIAGE_ROLES | {"safety_specialist", "legal_privacy"},
    "change_rule_version": {"incident_lead"},
}
SPECIALIST_REVIEW_ROLE = {"Legal/Privacy": "legal_privacy", "Safety": "safety_specialist"}


def require(actor: Actor, permission: str) -> None:
    if actor.role not in PERMISSIONS[permission]:
        raise PermissionDenied(f"{actor.display} ({ROLE_LABELS.get(actor.role, actor.role)}) may not {permission.replace('_', ' ')}")


# ---------------------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------------------

STATUSES = ["NEW", "ASSESSED", "ASSESSMENT_FAILED", "TRIAGED", "INVESTIGATING", "CONTAINMENT",
            "RESPONSE", "CLOSED", "REOPENED", "QA_REVIEWED"]
STAGE = {
    "NEW": "1 Intake", "ASSESSED": "2 AI enrichment", "ASSESSMENT_FAILED": "2 AI enrichment (failed → manual)",
    "TRIAGED": "3 Human severity triage", "INVESTIGATING": "4 Investigation", "CONTAINMENT": "5 Escalation & containment",
    "RESPONSE": "6 User/customer response", "CLOSED": "7 Resolution & closure", "REOPENED": "3 Re-triage (reopened)",
    "QA_REVIEWED": "8 Quality review & learning",
}
# (from, to): how the transition may happen
TRANSITIONS: dict[tuple[str, str], str] = {
    ("NEW", "ASSESSED"): "assessment", ("NEW", "ASSESSMENT_FAILED"): "assessment",
    ("ASSESSED", "ASSESSED"): "assessment", ("ASSESSED", "ASSESSMENT_FAILED"): "assessment",
    ("ASSESSMENT_FAILED", "ASSESSED"): "assessment", ("ASSESSMENT_FAILED", "ASSESSMENT_FAILED"): "assessment",
    ("NEW", "TRIAGED"): "severity_decision", ("ASSESSED", "TRIAGED"): "severity_decision",
    ("ASSESSMENT_FAILED", "TRIAGED"): "severity_decision", ("REOPENED", "TRIAGED"): "severity_decision",
    ("TRIAGED", "INVESTIGATING"): "manual", ("TRIAGED", "RESPONSE"): "manual",
    ("INVESTIGATING", "CONTAINMENT"): "manual", ("INVESTIGATING", "RESPONSE"): "manual",
    ("CONTAINMENT", "INVESTIGATING"): "manual", ("CONTAINMENT", "RESPONSE"): "manual",
    ("RESPONSE", "INVESTIGATING"): "manual",
    ("RESPONSE", "CLOSED"): "closure",
    ("CLOSED", "REOPENED"): "reopen", ("QA_REVIEWED", "REOPENED"): "reopen",
    ("CLOSED", "QA_REVIEWED"): "qa_review",
}


def allowed_manual_transitions(status: str) -> list[str]:
    return [to for (frm, to), how in TRANSITIONS.items() if frm == status and how == "manual"]


def _check_transition(frm: str, to: str, how: str) -> None:
    if TRANSITIONS.get((frm, to)) != how:
        raise WorkflowError(f"Transition {frm} → {to} is not allowed via {how}")


def _set_status(conn, incident_id: str, frm: str, to: str, actor: Actor, reason: str | None, origin: str) -> None:
    conn.execute("UPDATE incidents SET status=? WHERE incident_id=?", (to, incident_id))
    if frm != to:
        log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role,
                  event_type="status_change", field="status", previous=frm, new=to, reason=reason, origin=origin)


# ---------------------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------------------


def get_incident(conn, incident_id: str) -> dict:
    inc = row(conn, "SELECT * FROM incidents WHERE incident_id=?", (incident_id,))
    if not inc:
        raise WorkflowError(f"Unknown incident {incident_id}")
    return inc


def get_intake(conn, incident_id: str) -> IncidentIntake:
    inc = get_incident(conn, incident_id)
    data = json.loads(inc["intake_json"])
    data["evidence"] = [
        {k: e[k] for k in ("evidence_id", "source_type", "source_description", "content", "collected_at")}
        for e in rows(conn, "SELECT * FROM evidence WHERE incident_id=? ORDER BY rowid", (incident_id,))
    ]
    return IncidentIntake.model_validate(data)


def get_assessment(conn, assessment_id: str | None) -> dict | None:
    if not assessment_id:
        return None
    a = row(conn, "SELECT * FROM assessments WHERE assessment_id=?", (assessment_id,))
    if a:
        a["output"] = json.loads(a["output_json"]) if a["output_json"] else None
        a["rule_result"] = json.loads(a["rule_result_json"])
        a["controls"] = json.loads(a["controls_json"])
    return a


def list_assessments(conn, incident_id: str) -> list[dict]:
    return [get_assessment(conn, r["assessment_id"]) for r in
            rows(conn, "SELECT assessment_id FROM assessments WHERE incident_id=? ORDER BY created_at, rowid", (incident_id,))]


def effective_severity(conn, inc: dict) -> tuple[str, str]:
    """(severity, basis). Human decision wins; otherwise control-adjusted AI recommendation;
    otherwise P1 as a conservative placeholder so unassessed cases are not left without urgency."""
    if inc["human_severity"]:
        return inc["human_severity"], "human"
    a = get_assessment(conn, inc["current_assessment_id"])
    if a and a["controlled_severity"]:
        return a["controlled_severity"], "ai_after_controls" if a["status"] == "valid" else "rules_after_ai_failure"
    return "P1", "unassessed_default"


def timeline(conn, incident_id: str) -> list[dict]:
    return rows(conn, "SELECT * FROM events WHERE incident_id=? ORDER BY ts, event_id", (incident_id,))


# ---------------------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------------------


def create_incident(conn, intake: IncidentIntake, actor: Actor, origin: str = "demo",
                    owner: str | None = None, created_at: str | None = None) -> str:
    require(actor, "create_incident")
    if row(conn, "SELECT 1 FROM incidents WHERE incident_id=?", (intake.incident_id,)):
        raise WorkflowError(f"Incident {intake.incident_id} already exists")
    ts = created_at or now_iso()
    if intake.reported_at > utcnow() + timedelta(minutes=5):
        raise WorkflowError("reported_at is in the future; check the timestamp and timezone")
    data = intake.model_dump(mode="json")
    evidence = data.pop("evidence")
    conn.execute(
        "INSERT INTO incidents(incident_id, intake_json, title, reported_at, created_at, origin, status, owner)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (intake.incident_id, json.dumps(data), intake.title, data["reported_at"], ts, origin, "NEW", owner))
    for e in evidence:
        conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?)",
                     (intake.incident_id, e["evidence_id"], e["source_type"], e["source_description"], e["content"],
                      e["collected_at"], ts, actor.actor_id, origin))
    log_event(conn, incident_id=intake.incident_id, actor_id=actor.actor_id, actor_role=actor.role,
              event_type="intake_created", new=intake.title, origin=origin, ts=ts,
              details={"evidence_ids": [e["evidence_id"] for e in evidence], "unknown_fields":
                       [k for k, v in data.items() if v == "unknown"]})
    if owner:
        log_event(conn, incident_id=intake.incident_id, actor_id=actor.actor_id, actor_role=actor.role,
                  event_type="owner_assigned", field="owner", previous=None, new=owner, origin=origin, ts=ts)
    conn.commit()
    return intake.incident_id


def import_json(conn, text: str, actor: Actor, origin: str = "import") -> tuple[list[str], list[str]]:
    """Import one incident object or a list. Returns (created_ids, errors). Invalid records are
    reported and skipped, never partially imported."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"Invalid JSON: {e}"]
    items = data if isinstance(data, list) else [data]
    created, errors = [], []
    for i, item in enumerate(items):
        try:
            intake = IncidentIntake.model_validate(item)
            created.append(create_incident(conn, intake, actor, origin=origin))
        except ValidationError as e:
            errors.append(f"record {i}: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5]))
        except WorkflowError as e:
            errors.append(f"record {i}: {e}")
    return created, errors


def add_evidence(conn, incident_id: str, evidence: Evidence, actor: Actor, origin: str = "demo") -> None:
    """Adding evidence to a closed case reopens it (closure record kept in history)."""
    require(actor, "add_evidence")
    inc = get_incident(conn, incident_id)
    if row(conn, "SELECT 1 FROM evidence WHERE incident_id=? AND evidence_id=?", (incident_id, evidence.evidence_id)):
        raise WorkflowError(f"Evidence {evidence.evidence_id} already exists on {incident_id}; evidence IDs are stable and cannot be reused")
    conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?)",
                 (incident_id, evidence.evidence_id, evidence.source_type, evidence.source_description, evidence.content,
                  evidence.collected_at.isoformat() if evidence.collected_at else None, now_iso(), actor.actor_id, origin))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role, event_type="evidence_added",
              new=evidence.evidence_id, origin=origin, details={"source_type": evidence.source_type, "source": evidence.source_description})
    if inc["status"] in ("CLOSED", "QA_REVIEWED"):
        _check_transition(inc["status"], "REOPENED", "reopen")
        _set_status(conn, incident_id, inc["status"], "REOPENED", actor,
                    f"New evidence {evidence.evidence_id} arrived after closure; human re-triage required", origin)
        conn.execute("UPDATE incidents SET closed_at=NULL WHERE incident_id=?", (incident_id,))
    conn.commit()


def add_note(conn, incident_id: str, text: str, actor: Actor, origin: str = "demo") -> None:
    require(actor, "add_note")
    get_incident(conn, incident_id)
    if not text.strip():
        raise WorkflowError("Note text is required")
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role, event_type="investigation_note",
              new=text.strip(), origin=origin)
    conn.commit()


def assign_owner(conn, incident_id: str, owner: str, actor: Actor, reason: str = "", origin: str = "demo") -> None:
    require(actor, "assign_owner")
    inc = get_incident(conn, incident_id)
    conn.execute("UPDATE incidents SET owner=? WHERE incident_id=?", (owner, incident_id))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role, event_type="owner_assigned",
              field="owner", previous=inc["owner"], new=owner, reason=reason or None, origin=origin)
    conn.commit()


# ---------------------------------------------------------------------------------------
# AI assessment
# ---------------------------------------------------------------------------------------


def run_assessment(conn, incident_id: str, provider, actor: Actor = SYSTEM_ACTOR, rule_version: str | None = None,
                   prompt_version: str | None = None, origin: str = "demo", ts: str | None = None) -> dict:
    """Run and store an assessment. Earlier assessments are preserved. Human decisions are
    never modified; disagreement with a human decision is logged, not applied."""
    require(actor, "run_assessment")
    inc = get_incident(conn, incident_id)
    if inc["status"] in ("CLOSED", "QA_REVIEWED"):
        raise WorkflowError("Closed incidents are not reassessed; reopen first")
    rule_version = rule_version or get_setting(conn, "active_rule_version")
    prompt_version = prompt_version or get_setting(conn, "active_prompt_version")
    intake = get_intake(conn, incident_id)
    rec = assess_incident(intake, provider, rule_version, prompt_version)
    ts = ts or now_iso()
    conn.execute(
        "INSERT INTO assessments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec["assessment_id"], incident_id, ts, rec["provider_kind"], rec["provider_name"], rec["model_name"],
         rec["prompt_version"], rec["rule_version"], rec["status"], rec["error_kind"], rec["error"],
         json.dumps(rec["output"]) if rec["output"] else None, json.dumps(rec["rule_result"]),
         json.dumps({k: rec[k] for k in ("controls", "review_reasons", "invalid_evidence_refs", "fact_ref_status",
                                          "impact", "evidence_quality", "confidence", "rules_severity", "provider_notes", "raw_text", "controls_version")}),
         rec["model_severity"], rec["controlled_severity"], rec["controlled_route"], int(rec["mandatory_review"]),
         rec["latency_ms"], rec["input_tokens"], rec["output_tokens"], rec["cost_usd"], origin))
    previous = inc["current_assessment_id"]
    conn.execute("UPDATE incidents SET current_assessment_id=? WHERE incident_id=?", (rec["assessment_id"], incident_id))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role,
              event_type="ai_assessment" if not previous else "ai_reassessment", field="current_assessment_id",
              previous=previous, new=rec["assessment_id"], origin=origin, ts=ts,
              details={"provider_kind": rec["provider_kind"], "status": rec["status"], "error_kind": rec["error_kind"],
                       "model_severity": rec["model_severity"], "controlled_severity": rec["controlled_severity"],
                       "rule_version": rule_version, "prompt_version": prompt_version})
    new_status = "ASSESSED" if rec["status"] == "valid" else "ASSESSMENT_FAILED"
    if inc["status"] in ("NEW", "ASSESSED", "ASSESSMENT_FAILED"):
        _check_transition(inc["status"], new_status, "assessment")
        _set_status(conn, incident_id, inc["status"], new_status, actor,
                    None if rec["status"] == "valid" else f"AI assessment failed ({rec['error_kind']}); manual review", origin)
    if inc["human_severity"] and rec["controlled_severity"] and rec["controlled_severity"] != inc["human_severity"]:
        log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role,
                  event_type="ai_human_disagreement", field="severity", previous=inc["human_severity"],
                  new=rec["controlled_severity"], reason="New AI recommendation differs; human decision unchanged",
                  origin=origin, ts=ts)
    conn.commit()
    return rec


# ---------------------------------------------------------------------------------------
# Human severity decision
# ---------------------------------------------------------------------------------------

OVERRIDE_REASONS = {
    "evidence_contradicts_ai": "Source evidence contradicts the AI summary",
    "missing_context": "AI lacked context the reviewer has (customer, history, telemetry)",
    "policy_interpretation": "Policy interpretation differs",
    "scope_or_impact_different": "Scope / blast radius or impact assessed differently",
    "false_positive": "False positive (benign or misread keywords)",
    "under_escalation": "AI under-estimated severity",
    "routing_ownership": "Different owning team is appropriate",
    "other": "Other (explain)",
}


def decide_severity(conn, incident_id: str, actor: Actor, severity: str, route: str, teams: list[str],
                    reason: str = "", override_reason_code: str | None = None,
                    evidence_reviewed: list[str] | None = None, origin: str = "demo", ts: str | None = None) -> dict:
    require(actor, "decide_severity")
    if severity not in SEVERITIES:
        raise WorkflowError("Invalid severity")
    inc = get_incident(conn, incident_id)
    if inc["status"] in ("CLOSED", "QA_REVIEWED"):
        raise WorkflowError("Reopen the incident before changing severity")
    a = get_assessment(conn, inc["current_assessment_id"])
    ai_sev = a["controlled_severity"] if a else None
    ai_route = a["controlled_route"] if a else None
    is_override = bool(a) and (severity != ai_sev or route != ai_route)
    evidence_reviewed = evidence_reviewed or []
    valid_ids = {e["evidence_id"] for e in rows(conn, "SELECT evidence_id FROM evidence WHERE incident_id=?", (incident_id,))}
    bad = [e for e in evidence_reviewed if e not in valid_ids]
    if bad:
        raise WorkflowError(f"Unknown evidence IDs: {bad}")
    high = severity in ("P0", "P1") or (ai_sev in ("P0", "P1"))
    if high and not evidence_reviewed:
        raise WorkflowError("P0/P1 decisions (and any decision on a case the AI rated P0/P1) require listing the source evidence reviewed")
    if is_override:
        if override_reason_code not in OVERRIDE_REASONS:
            raise WorkflowError("An override of the AI recommendation requires a reason code")
        if len(reason.strip()) < 10:
            raise WorkflowError("An override requires a written rationale (at least 10 characters)")
    if ai_sev and is_downgrade(ai_sev, severity) and ai_sev in ("P0", "P1") and len(reason.strip()) < 20:
        raise WorkflowError("Downgrading from an AI P0/P1 recommendation requires a rationale of at least 20 characters")
    if inc["human_severity"] and inc["human_severity"] != severity and len(reason.strip()) < 10:
        raise WorkflowError("Changing an existing human severity decision requires a rationale")

    ts = ts or now_iso()
    prev = {"severity": inc["human_severity"], "route": inc["human_route"], "teams": json.loads(inc["human_teams_json"] or "null")}
    conn.execute("UPDATE incidents SET human_severity=?, human_route=?, human_teams_json=?, severity_decided_by=?,"
                 " severity_decided_at=?, first_human_review_at=COALESCE(first_human_review_at, ?) WHERE incident_id=?",
                 (severity, route, json.dumps(teams), actor.actor_id, ts, ts, incident_id))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role,
              event_type="human_override" if is_override else "human_severity_confirmed", field="severity/route",
              previous=prev, new={"severity": severity, "route": route, "teams": teams},
              reason=reason.strip() or None, origin=origin, ts=ts,
              details={"ai_recommendation": {"severity": ai_sev, "route": ai_route, "assessment_id": a["assessment_id"] if a else None},
                       "override_reason_code": override_reason_code if is_override else None,
                       "evidence_reviewed": evidence_reviewed})
    if inc["status"] in ("NEW", "ASSESSED", "ASSESSMENT_FAILED", "REOPENED"):
        _check_transition(inc["status"], "TRIAGED", "severity_decision")
        _set_status(conn, incident_id, inc["status"], "TRIAGED", actor, "Human severity decision recorded", origin)
    conn.commit()
    return {"override": is_override}


def transition(conn, incident_id: str, to: str, actor: Actor, reason: str = "", origin: str = "demo") -> None:
    require(actor, "transition")
    inc = get_incident(conn, incident_id)
    _check_transition(inc["status"], to, "manual")
    if not inc["human_severity"]:
        raise WorkflowError("A human severity decision is required before investigation/response stages")
    _set_status(conn, incident_id, inc["status"], to, actor, reason or None, origin)
    conn.commit()


# ---------------------------------------------------------------------------------------
# Containment (SIMULATED - nothing is executed against any system)
# ---------------------------------------------------------------------------------------


def propose_containment(conn, incident_id: str, actor: Actor, action_type: ContainmentType, target: str,
                        rationale: str, source: str = "human", origin: str = "demo") -> str:
    require(actor, "propose_containment")
    get_incident(conn, incident_id)
    if action_type not in REVERSIBLE_CONTAINMENT and action_type != "account_lockout":
        raise WorkflowError(f"Unknown containment type {action_type}")
    if not target.strip() or not rationale.strip():
        raise WorkflowError("Containment proposals need a target and rationale")
    aid = f"CA-{uuid.uuid4().hex[:8]}"
    conn.execute("INSERT INTO containment_actions(action_id, incident_id, action_type, target, rationale, reversible,"
                 " proposed_by, proposed_source, proposed_at, status, simulated) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                 (aid, incident_id, action_type, target, rationale, int(action_type in REVERSIBLE_CONTAINMENT),
                  actor.actor_id, source, now_iso(), "proposed"))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role, event_type="containment_proposed",
              new={"action_id": aid, "action_type": action_type, "target": target}, reason=rationale, origin=origin,
              details={"source": source, "simulated": True})
    conn.commit()
    return aid


def decide_containment(conn, action_id: str, actor: Actor, approve: bool, reason: str,
                       review_by: datetime | None = None, expires_at: datetime | None = None, origin: str = "demo") -> None:
    """Approve (-> active, simulated) or reject a proposal. Enforced here, regardless of UI."""
    act = row(conn, "SELECT * FROM containment_actions WHERE action_id=?", (action_id,))
    if not act:
        raise WorkflowError("Unknown containment action")
    if act["status"] != "proposed":
        raise WorkflowError(f"Containment action is {act['status']}, not proposed")
    if not actor.is_human:
        raise PermissionDenied("Containment decisions require a human; AI/automation may only propose")
    inc = get_incident(conn, act["incident_id"])
    sev, basis = effective_severity(conn, inc)
    perm = "approve_containment_p0p1" if sev in ("P0", "P1") else "approve_containment_p2p3"
    require(actor, perm)
    if len(reason.strip()) < 5:
        raise WorkflowError("A decision reason is required")
    if approve and act["action_type"] == "account_lockout":
        if not (inc["human_severity"] == "P0"):
            raise WorkflowError("Account lockout is reserved for human-confirmed P0 (high-confidence active abuse)")
        if len(reason.strip()) < 30:
            raise WorkflowError("Account lockout requires a detailed rationale (30+ characters)")
    now = utcnow()
    cfg = config.sla_config()
    review_by = review_by or now + timedelta(hours=cfg["containment_default_review_hours"])
    expires_at = expires_at or now + timedelta(hours=cfg["containment_default_expiry_hours"])
    if approve and expires_at <= now:
        raise WorkflowError("Expiry must be in the future")
    new_status = "active" if approve else "rejected"
    conn.execute("UPDATE containment_actions SET status=?, decided_by=?, decided_at=?, decision_reason=?, review_by=?, expires_at=?"
                 " WHERE action_id=?", (new_status, actor.actor_id, now_iso(), reason.strip(),
                                        review_by.isoformat(timespec="seconds") if approve else None,
                                        expires_at.isoformat(timespec="seconds") if approve else None, action_id))
    log_event(conn, incident_id=act["incident_id"], actor_id=actor.actor_id, actor_role=actor.role,
              event_type="containment_approved" if approve else "containment_rejected", field=f"containment:{action_id}",
              previous="proposed", new=new_status, reason=reason.strip(), origin=origin,
              details={"action_type": act["action_type"], "severity_basis": f"{sev} ({basis})", "simulated": True,
                       "review_by": review_by.isoformat() if approve else None, "expires_at": expires_at.isoformat() if approve else None})
    conn.commit()


def end_containment(conn, action_id: str, actor: Actor, reason: str, origin: str = "demo") -> None:
    require(actor, "end_containment")
    act = row(conn, "SELECT * FROM containment_actions WHERE action_id=?", (action_id,))
    if not act or act["status"] != "active":
        raise WorkflowError("Only active containment can be reversed")
    if len(reason.strip()) < 5:
        raise WorkflowError("A reason is required to reverse containment")
    conn.execute("UPDATE containment_actions SET status='reversed', ended_at=?, ended_by=?, end_reason=? WHERE action_id=?",
                 (now_iso(), actor.actor_id, reason.strip(), action_id))
    log_event(conn, incident_id=act["incident_id"], actor_id=actor.actor_id, actor_role=actor.role, event_type="containment_reversed",
              field=f"containment:{action_id}", previous="active", new="reversed", reason=reason.strip(), origin=origin,
              details={"simulated": True})
    conn.commit()


def expire_due_containment(conn, now: datetime | None = None) -> int:
    now = now or utcnow()
    due = rows(conn, "SELECT * FROM containment_actions WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= ?",
               (now.isoformat(timespec="seconds"),))
    for act in due:
        conn.execute("UPDATE containment_actions SET status='expired', ended_at=?, ended_by=?, end_reason=? WHERE action_id=?",
                     (now_iso(), SYSTEM_ACTOR.actor_id, "Reached expiry", act["action_id"]))
        log_event(conn, incident_id=act["incident_id"], actor_id=SYSTEM_ACTOR.actor_id, actor_role="system",
                  event_type="containment_expired", field=f"containment:{act['action_id']}", previous="active", new="expired",
                  reason="Temporary containment reached its expiry time", origin="system", details={"simulated": True})
    conn.commit()
    return len(due)


# ---------------------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------------------

CLOSURE_CATEGORIES = [
    "confirmed_safety_incident", "privacy_sensitive_data_incident", "product_defect", "ux_approval_issue",
    "prompt_injection", "user_misunderstanding_no_defect", "insufficient_evidence", "duplicate_known_issue",
]


class ClosureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    closure_category: Literal[
        "confirmed_safety_incident", "privacy_sensitive_data_incident", "product_defect", "ux_approval_issue",
        "prompt_injection", "user_misunderstanding_no_defect", "insufficient_evidence", "duplicate_known_issue"]
    final_severity: Literal["P0", "P1", "P2", "P3"]
    root_cause: str = Field(min_length=5)
    user_customer_impact: str = Field(min_length=5)
    evidence_reviewed: list[str] = Field(min_length=1)
    teams_involved: list[str] = Field(min_length=1)
    actions_taken: str = Field(min_length=5)
    response_status: str = Field(min_length=3)
    remaining_mitigation: str = Field(min_length=2)
    monitoring_required: bool
    acknowledge_active_containment: bool = False
    sign_off_statement: str = Field(min_length=10)


def close_incident(conn, incident_id: str, closure: ClosureRecord | dict, actor: Actor, origin: str = "demo") -> None:
    if isinstance(closure, dict):
        closure = ClosureRecord.model_validate(closure)
    inc = get_incident(conn, incident_id)
    if not actor.is_human:
        raise PermissionDenied("Closure requires human sign-off")
    if not inc["human_severity"]:
        raise WorkflowError("Closure requires a human-confirmed severity")
    require(actor, "close_p0p1" if inc["human_severity"] in ("P0", "P1") else "close_p2p3")
    _check_transition(inc["status"], "CLOSED", "closure")
    if closure.final_severity != inc["human_severity"]:
        raise WorkflowError(f"Final severity {closure.final_severity} differs from the recorded human decision "
                            f"{inc['human_severity']}; record a severity decision first")
    valid_ids = {e["evidence_id"] for e in rows(conn, "SELECT evidence_id FROM evidence WHERE incident_id=?", (incident_id,))}
    bad = [e for e in closure.evidence_reviewed if e not in valid_ids]
    if bad:
        raise WorkflowError(f"Unknown evidence IDs in closure: {bad}")
    pending = rows(conn, "SELECT action_id FROM containment_actions WHERE incident_id=? AND status='proposed'", (incident_id,))
    if pending:
        raise WorkflowError(f"Decide pending containment proposals before closure: {[p['action_id'] for p in pending]}")
    active = rows(conn, "SELECT action_id FROM containment_actions WHERE incident_id=? AND status='active'", (incident_id,))
    if active and not closure.acknowledge_active_containment:
        raise WorkflowError("Active (simulated) containment remains; reverse it or acknowledge it with a review date in remaining mitigation")
    for c in latest_communications(conn, incident_id):
        spec = json.loads(c["specialist_review_json"])
        if spec["required"] and c["status"] == "draft":
            raise WorkflowError(f"Communication {c['comm_id']} ({c['comm_type']}) awaits required specialist review")
    ts = now_iso()
    conn.execute("UPDATE incidents SET closure_json=?, closed_at=? WHERE incident_id=?",
                 (closure.model_dump_json(), ts, incident_id))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role, event_type="closure_signed_off",
              new=closure.model_dump(mode="json"), reason=closure.sign_off_statement, origin=origin, ts=ts)
    _set_status(conn, incident_id, inc["status"], "CLOSED", actor, "Human-approved closure", origin)
    conn.commit()


def reopen(conn, incident_id: str, actor: Actor, reason: str, origin: str = "demo") -> None:
    require(actor, "reopen")
    inc = get_incident(conn, incident_id)
    _check_transition(inc["status"], "REOPENED", "reopen")
    if len(reason.strip()) < 10:
        raise WorkflowError("Reopening requires a reason")
    _set_status(conn, incident_id, inc["status"], "REOPENED", actor, reason.strip(), origin)
    conn.execute("UPDATE incidents SET closed_at=NULL WHERE incident_id=?", (incident_id,))
    conn.commit()


QA_OUTCOMES = ["agree_with_handling", "missed_escalation", "over_escalation", "evidence_gap", "ai_summary_inaccurate", "other"]


def qa_review(conn, incident_id: str, actor: Actor, outcome: str, notes: str, origin: str = "demo") -> None:
    require(actor, "qa_review")
    if outcome not in QA_OUTCOMES:
        raise WorkflowError("Unknown QA outcome")
    inc = get_incident(conn, incident_id)
    _check_transition(inc["status"], "QA_REVIEWED", "qa_review")
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role, event_type="qa_review",
              new=outcome, reason=notes, origin=origin)
    _set_status(conn, incident_id, inc["status"], "QA_REVIEWED", actor, f"QA: {outcome}", origin)
    conn.commit()


# ---------------------------------------------------------------------------------------
# Communications (drafts only - never sent)
# ---------------------------------------------------------------------------------------


def latest_communications(conn, incident_id: str) -> list[dict]:
    return rows(conn, """SELECT c.* FROM communications c JOIN (SELECT comm_id, MAX(version) v FROM communications
                         WHERE incident_id=? GROUP BY comm_id) m ON c.comm_id=m.comm_id AND c.version=m.v ORDER BY c.created_at""",
                (incident_id,))


def save_communication(conn, incident_id: str, comm_type: str, body: str, evidence_refs: list[str], required_reviews: list[str],
                       actor: Actor, generator: str, comm_id: str | None = None, origin: str = "demo") -> str:
    perm = "edit_communication" if comm_id else "draft_communication"
    require(actor, perm)
    get_incident(conn, incident_id)
    if comm_id:
        prev = row(conn, "SELECT * FROM communications WHERE comm_id=? ORDER BY version DESC LIMIT 1", (comm_id,))
        if not prev:
            raise WorkflowError("Unknown communication")
        version = prev["version"] + 1
        spec = json.loads(prev["specialist_review_json"])
        spec["approvals"] = {}  # an edit invalidates earlier approvals
        comm_type = prev["comm_type"]
    else:
        comm_id = f"CM-{uuid.uuid4().hex[:8]}"
        version = 1
        spec = {"required": required_reviews, "approvals": {}}
    conn.execute("INSERT INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (comm_id, version, incident_id, comm_type, body, json.dumps(evidence_refs), json.dumps(spec), "draft",
                  generator, actor.actor_id, now_iso(), None, None, None))
    log_event(conn, incident_id=incident_id, actor_id=actor.actor_id, actor_role=actor.role,
              event_type="communication_drafted" if version == 1 else "communication_edited",
              field=f"communication:{comm_id}", previous=version - 1 if version > 1 else None, new=version, origin=origin,
              details={"comm_type": comm_type, "generator": generator, "specialist_review_required": spec["required"],
                       "sent": False})
    conn.commit()
    return comm_id


def review_communication(conn, comm_id: str, actor: Actor, approve: bool, note: str = "", origin: str = "demo") -> str:
    """Record a review. Specialist-flagged drafts need approval from each flagged specialist role;
    others need Risk Ops / Incident Lead approval. Approval never sends anything."""
    c = row(conn, "SELECT * FROM communications WHERE comm_id=? ORDER BY version DESC LIMIT 1", (comm_id,))
    if not c:
        raise WorkflowError("Unknown communication")
    if not actor.is_human:
        raise PermissionDenied("Communication review requires a human")
    spec = json.loads(c["specialist_review_json"])
    if spec["required"]:
        mine = [s for s in spec["required"] if SPECIALIST_REVIEW_ROLE.get(s) == actor.role]
        if not mine:
            raise PermissionDenied(f"This draft requires review by: {', '.join(spec['required'])}")
    else:
        require(actor, "approve_communication_general")
        mine = ["General"]
    if not approve:
        status = "rejected"
    else:
        for s in mine:
            spec["approvals"][s] = {"by": actor.actor_id, "at": now_iso()}
        status = "approved" if (not spec["required"] or all(s in spec["approvals"] for s in spec["required"])) else "draft"
    conn.execute("UPDATE communications SET status=?, specialist_review_json=?, reviewed_by=?, reviewed_at=?, review_note=?"
                 " WHERE comm_id=? AND version=?", (status, json.dumps(spec), actor.actor_id, now_iso(), note or None,
                                                     comm_id, c["version"]))
    log_event(conn, incident_id=c["incident_id"], actor_id=actor.actor_id, actor_role=actor.role,
              event_type="communication_reviewed", field=f"communication:{comm_id}", previous=c["status"], new=status,
              reason=note or None, origin=origin, details={"version": c["version"], "reviewed_as": mine, "sent": False})
    conn.commit()
    return status


# ---------------------------------------------------------------------------------------
# Related / duplicate reports
# ---------------------------------------------------------------------------------------


def record_link_suggestions(conn, incident_id: str, suggestions: list[dict]) -> int:
    n = 0
    for s in suggestions:
        a, b = sorted([incident_id, s["incident_id"]])
        if row(conn, "SELECT 1 FROM links WHERE incident_a=? AND incident_b=?", (a, b)):
            continue
        conn.execute("INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"LK-{uuid.uuid4().hex[:8]}", a, b, "related", "suggested", s["score"], s["explanation"], now_iso(),
                      None, None, None))
        n += 1
    conn.commit()
    return n


def decide_link(conn, link_id: str, actor: Actor, confirm: bool, link_type: str, reason: str, origin: str = "demo") -> None:
    """Confirm or reject a suggested relationship. Never merges, deletes or re-statuses either
    incident; evidence on both incidents is preserved."""
    require(actor, "decide_link")
    if link_type not in ("duplicate", "related"):
        raise WorkflowError("link_type must be duplicate or related")
    lk = row(conn, "SELECT * FROM links WHERE link_id=?", (link_id,))
    if not lk:
        raise WorkflowError("Unknown link")
    if not reason.strip():
        raise WorkflowError("A reason is required")
    status = "confirmed" if confirm else "rejected"
    conn.execute("UPDATE links SET status=?, link_type=?, decided_by=?, decided_at=?, reason=? WHERE link_id=?",
                 (status, link_type, actor.actor_id, now_iso(), reason.strip(), link_id))
    sev_a = effective_severity(conn, get_incident(conn, lk["incident_a"]))[0]
    sev_b = effective_severity(conn, get_incident(conn, lk["incident_b"]))[0]
    for this, other, s_this, s_other in ((lk["incident_a"], lk["incident_b"], sev_a, sev_b), (lk["incident_b"], lk["incident_a"], sev_b, sev_a)):
        log_event(conn, incident_id=this, actor_id=actor.actor_id, actor_role=actor.role,
                  event_type=f"link_{status}", field="linked_incident", new=other, reason=reason.strip(), origin=origin,
                  details={"link_type": link_type, "link_id": link_id, "other_severity": s_other})
        if confirm and SEVERITY_ORDER[s_other] < SEVERITY_ORDER[s_this]:
            log_event(conn, incident_id=this, actor_id=SYSTEM_ACTOR.actor_id, actor_role="system",
                      event_type="linked_higher_severity_warning", new=other, origin=origin,
                      reason=f"Linked report {other} is {s_other} (this case {s_this}); review whether this case should be re-triaged. Nothing was changed automatically.")
    conn.commit()


def links_for(conn, incident_id: str) -> list[dict]:
    return rows(conn, "SELECT * FROM links WHERE incident_a=? OR incident_b=? ORDER BY suggested_at", (incident_id, incident_id))


# ---------------------------------------------------------------------------------------
# Claim-support review, rule versions, evaluation runs
# ---------------------------------------------------------------------------------------

CLAIM_VERDICTS = ["supported", "partially_supported", "unsupported", "cannot_determine"]


def record_claim_review(conn, assessment_id: str, fact_index: int, verdict: str, actor: Actor, note: str = "") -> None:
    require(actor, "claim_review")
    if verdict not in CLAIM_VERDICTS:
        raise WorkflowError("Unknown verdict")
    a = get_assessment(conn, assessment_id)
    if not a or not a["output"] or fact_index >= len(a["output"]["reported_facts"]):
        raise WorkflowError("Unknown assessment fact")
    conn.execute("INSERT INTO claim_reviews(assessment_id, fact_index, verdict, reviewer, reviewed_at, note) VALUES (?,?,?,?,?,?)",
                 (assessment_id, fact_index, verdict, actor.actor_id, now_iso(), note or None))
    log_event(conn, incident_id=a["incident_id"], actor_id=actor.actor_id, actor_role=actor.role, event_type="claim_support_review",
              field=f"{assessment_id}:fact{fact_index}", new=verdict, reason=note or None)
    conn.commit()


def change_rule_version(conn, version: str, actor: Actor, reason: str, origin: str = "demo") -> None:
    """Switch the active rule version. Does not modify any incident, assessment or human
    decision; existing assessments keep the version they were produced with."""
    require(actor, "change_rule_version")
    if version not in available_versions():
        raise WorkflowError(f"Unknown rule version {version}")
    if len(reason.strip()) < 10:
        raise WorkflowError("Rule changes require a rationale")
    prev = get_setting(conn, "active_rule_version")
    set_setting(conn, "active_rule_version", version)
    log_event(conn, incident_id=None, actor_id=actor.actor_id, actor_role=actor.role, event_type="rule_version_changed",
              field="active_rule_version", previous=prev, new=version, reason=reason.strip(), origin=origin)
    conn.commit()


def set_provider_mode(conn, mode: str, actor: Actor, origin: str = "demo") -> None:
    prev = get_setting(conn, "provider_mode")
    set_setting(conn, "provider_mode", mode)
    log_event(conn, incident_id=None, actor_id=actor.actor_id, actor_role=actor.role, event_type="provider_mode_changed",
              field="provider_mode", previous=prev, new=mode, origin=origin)
    conn.commit()


def record_eval_run(conn, summary: dict, origin: str = "demo") -> None:
    conn.execute("INSERT OR REPLACE INTO eval_runs VALUES (?,?,?,?,?,?,?)",
                 (summary["run_id"], summary["created_at"], summary["label"],
                  json.dumps({k: summary[k] for k in ("evaluation_kind", "system", "rule_version", "prompt_version", "split", "model_name")}),
                  json.dumps(summary), summary.get("artifact_dir"), origin))
    conn.commit()


# ---------------------------------------------------------------------------------------
# Guidance for the UI: who may do what, and what a case needs next.
# These read-only helpers mirror the checks above so the interface can disable controls
# with a reason; the mutating functions still enforce every rule themselves.
# ---------------------------------------------------------------------------------------


def can(actor: Actor, permission: str) -> bool:
    return actor.role in PERMISSIONS[permission]


def roles_for(permission: str) -> str:
    return " or ".join(ROLE_LABELS[r] for r in sorted(PERMISSIONS[permission]) if r != "system")


def containment_permission(conn, inc: dict) -> str:
    sev, _ = effective_severity(conn, inc)
    return "approve_containment_p0p1" if sev in ("P0", "P1") else "approve_containment_p2p3"


def closure_permission(inc: dict) -> str:
    return "close_p0p1" if inc["human_severity"] in ("P0", "P1") else "close_p2p3"


def closure_blockers(conn, incident_id: str) -> list[str]:
    """Reasons closure would be refused right now (same checks as close_incident)."""
    inc = get_incident(conn, incident_id)
    out = []
    if not inc["human_severity"]:
        out.append("No human severity decision recorded")
    if inc["status"] != "RESPONSE":
        out.append(f"Case must be in the Response stage (currently {inc['status']})")
    n = len(rows(conn, "SELECT 1 FROM containment_actions WHERE incident_id=? AND status='proposed'", (incident_id,)))
    if n:
        out.append(f"{n} containment proposal(s) awaiting a decision")
    for c in latest_communications(conn, incident_id):
        spec = json.loads(c["specialist_review_json"])
        if spec["required"] and c["status"] == "draft":
            missing = [s for s in spec["required"] if s not in spec["approvals"]]
            out.append(f"Draft '{c['comm_type']}' awaits {', '.join(missing)} review")
    return out


def next_actions(conn, incident_id: str) -> list[dict]:
    """Ordered list of what this case needs next: {title, detail, permission, urgent}.
    ``permission`` is a key of PERMISSIONS (or a specialist role marker)."""
    inc = get_incident(conn, incident_id)
    a = get_assessment(conn, inc["current_assessment_id"])
    st = inc["status"]
    out: list[dict] = []

    def add(title, detail, permission, urgent=False, role=None):
        out.append({"title": title, "detail": detail, "permission": permission, "role": role, "urgent": urgent})

    if st == "NEW":
        add("Run the AI assessment", "Or record a severity decision manually.", "run_assessment")
    if st in ("NEW", "ASSESSED", "ASSESSMENT_FAILED", "REOPENED"):
        detail = "Review the source evidence, then confirm or correct the AI recommendation."
        if a and a["status"] == "failed":
            detail = "The AI assessment failed. Triage manually from the evidence."
        elif st == "REOPENED":
            detail = "New evidence reopened this case. Re-triage it."
        add("Decide severity and routing", detail, "decide_severity", urgent=True)
    for p in rows(conn, "SELECT * FROM containment_actions WHERE incident_id=? AND status='proposed'", (incident_id,)):
        add("Decide on proposed containment", f"{p['action_type'].replace('_', ' ')} on {p['target']}",
            containment_permission(conn, inc), urgent=True)
    now = utcnow().isoformat(timespec="seconds")
    for p in rows(conn, "SELECT * FROM containment_actions WHERE incident_id=? AND status='active' AND review_by<=?", (incident_id, now)):
        add("Review temporary containment", f"{p['action_type'].replace('_', ' ')} passed its review time", "end_containment", urgent=True)
    for c in latest_communications(conn, incident_id):
        spec = json.loads(c["specialist_review_json"])
        if c["status"] == "draft":
            missing = [s for s in spec["required"] if s not in spec["approvals"]]
            for s in missing:
                add(f"{s} review of a draft", c["comm_type"].replace("_", " "), None, role=SPECIALIST_REVIEW_ROLE[s])
    if rows(conn, "SELECT 1 FROM links WHERE (incident_a=? OR incident_b=?) AND status='suggested'", (incident_id, incident_id)):
        add("Confirm or reject related reports", "Suggested matches are waiting for a reviewer.", "decide_link")
    if st == "TRIAGED":
        add("Start investigation", "Or move straight to response for low-risk cases.", "transition")
    elif st == "INVESTIGATING":
        add("Contain or move to response", "Propose containment if there is credible ongoing risk.", "transition")
    elif st == "CONTAINMENT":
        add("Move to response", "Once containment is in place.", "transition")
    elif st == "RESPONSE":
        blockers = closure_blockers(conn, incident_id)
        add("Close the case with sign-off", "Blocked: " + "; ".join(blockers) if blockers else "Ready to close.",
            closure_permission(inc))
    elif st == "CLOSED":
        add("Quality review (sampling)", "Optional: check the handling for missed escalation.", "qa_review")
    return out


def actor_can_do(conn, actor: Actor, action: dict) -> bool:
    if action["role"]:
        return actor.role == action["role"]
    return can(actor, action["permission"])


def who_can_do(action: dict) -> str:
    if action["role"]:
        return ROLE_LABELS[action["role"]]
    return roles_for(action["permission"])
