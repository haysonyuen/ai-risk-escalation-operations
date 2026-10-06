"""Shared presentation helpers. No business rules live here — only calls into riskops."""

from __future__ import annotations

import html
import re
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from riskops import config  # noqa: E402
from riskops import policies  # noqa: E402
from riskops import workflow as wf  # noqa: E402
from riskops.db import connect, get_setting  # noqa: E402
from riskops.providers import get_provider  # noqa: E402
from riskops.schemas import TEAMS as SCHEMA_TEAMS  # noqa: E402

# --------------------------------------------------------------------------- labels

STATUS_LABEL = {
    "NEW": "Intake · not yet assessed", "ASSESSED": "AI assessed · awaiting triage",
    "ASSESSMENT_FAILED": "AI assessment failed · manual triage", "TRIAGED": "Triaged", "INVESTIGATING": "Investigating",
    "CONTAINMENT": "Containment", "RESPONSE": "Response", "CLOSED": "Closed · QA pending",
    "REOPENED": "Reopened · re-triage", "QA_REVIEWED": "Closed · QA reviewed",
}
STAGES = ["Intake", "AI assessment", "Triage", "Investigation", "Containment", "Response", "Closure", "QA review"]
STATUS_STAGE = {"NEW": 0, "ASSESSED": 1, "ASSESSMENT_FAILED": 1, "TRIAGED": 2, "REOPENED": 2, "INVESTIGATING": 3,
                "CONTAINMENT": 4, "RESPONSE": 5, "CLOSED": 6, "QA_REVIEWED": 7}
# Three high-level phases shown everywhere; the stage above is the detail underneath.
PHASES = ["Awaiting triage", "In progress", "Closed"]
STATUS_PHASE = {"NEW": 0, "ASSESSED": 0, "ASSESSMENT_FAILED": 0, "REOPENED": 0,
                "TRIAGED": 1, "INVESTIGATING": 1, "CONTAINMENT": 1, "RESPONSE": 1, "CLOSED": 2, "QA_REVIEWED": 2}
PHASE_HELP = {"Awaiting triage": "No human severity decision yet.",
              "In progress": "Triaged and owned; investigation, containment or response under way.",
              "Closed": "Signed off. QA review may still be pending."}
PHASE_BADGE = {"Awaiting triage": "b-warn", "In progress": "b-p3", "Closed": "b-human"}
STAGE_NEXT = {"NEW": "AI assessment", "ASSESSED": "Triage", "ASSESSMENT_FAILED": "Triage (manual)", "REOPENED": "Triage",
              "TRIAGED": "Investigation", "INVESTIGATING": "Containment or Response", "CONTAINMENT": "Response",
              "RESPONSE": "Closure", "CLOSED": "QA review", "QA_REVIEWED": None}


def phase(status: str) -> str:
    return PHASES[STATUS_PHASE[status]]


def stage(status: str) -> str:
    return STAGES[STATUS_STAGE[status]]


ROUTE_LABEL = {"safety": "Safety", "child_safety": "Child Safety", "threat_intel": "Threat Intel",
               "product_security": "Product Security", "legal_privacy": "Legal/Privacy", "model_behavior": "Model Behavior",
               "product_engineering": "Product/Engineering", "product_ux": "Product/UX", "risk_ops": "Risk Ops", "support": "Support"}
CATEGORY_LABEL = {
    "cbrn": "CBRN weapons uplift", "cyber_misuse": "Cyber offense",
    "child_safety": "Child safety", "self_harm": "Self-harm & suicide", "violent_extremism": "Violent extremism & threats",
    "deepfake_ncii": "Deepfake / NCII", "influence_operations": "Influence operations", "fraud_scams": "Fraud & scams",
    "safeguard_bypass": "Jailbreak / safeguard bypass", "enterprise_data_leakage": "Enterprise data leakage",
    "privacy_pii": "Privacy / PII exposure", "prompt_injection": "Prompt injection & agent hijacking",
    "model_security": "Model / secret leakage", "agentic_overreach": "Agentic overreach",
    "harmful_inaccuracy": "Harmful inaccuracy", "bias_discrimination": "Bias & discrimination",
    "enforcement_appeal": "Over-refusal / enforcement appeal", "product_failure": "Product failure", "benign_noise": "Benign / no issue",
}
CONTAINMENT_LABEL = {
    "pause_interaction": "Pause the session", "restrict_tool_action": "Restrict a tool action",
    "require_confirmation_destructive": "Require confirmation for destructive actions",
    "warn_sensitive_file_access": "Warn on sensitive file access", "isolate_untrusted_instructions": "Isolate untrusted instructions",
    "pause_external_transactions": "Pause external transactions", "workspace_safe_mode": "Workspace safe mode",
    "disable_connector": "Disable a connector", "rotate_credentials": "Rotate exposed credentials (irreversible)",
    "deploy_classifier_block": "Deploy a classifier block rule", "rate_limit_accounts": "Rate-limit accounts",
    "account_lockout": "Suspend account (irreversible)", "file_mandatory_report": "Prepare mandatory external report (irreversible)",
}
SOURCE_LABEL = {
    "offline_fixture": ("Demo AI (pre-written, no live model)", "b-fixture"),
    "offline_simulation": ("Demo AI (simulated, no live model)", "b-sim"),
    "live_model": ("Live model", "b-live"),
    "fault_injection": ("Fault injection (AI deliberately broken)", "b-fault"),
    "none": ("Not assessed", "b-muted"),
}
BASIS_LABEL = {"human": "confirmed", "ai_after_controls": "AI-suggested · not confirmed",
               "rules_after_ai_failure": "needs manual triage", "unassessed_default": "default · not assessed"}
CONTROL_NAME = {
    "C1": "Unusable AI output", "C2": "Missing evidence", "C3": "Severity floor", "C4": "Embedded instructions",
    "C5": "Low-confidence review", "C6": "Specialist route", "C7": "Auto-pause",
}
CONTROL_TEXT = {
    "C1": "AI output unusable; no assessment was invented",
    "C2": "Cites evidence that does not exist",
    "C3": "Raised to the rules minimum",
    "C4": "Report text contains instructions aimed at the reviewer (ignored)",
    "C5": "High potential impact but low confidence",
    "C6": "Specialist route kept",
    "C7": "Session paused automatically (P0 CBRN / child safety); a person must confirm or lift",
}


def control_name(cid: str) -> str:
    """Name first, code second, e.g. 'Severity floor (C3)'."""
    return f"{CONTROL_NAME[cid]} ({cid})" if cid in CONTROL_NAME else cid


GLOSSARY = {
    "Escalation and response": [
        ("P0–P3", "Severity. P0 critical, P1 high, P2 medium, P3 low."),
        ("Policy", "Which policy the case may violate, with a short code (e.g. Child safety, CS-01). Suggested by the AI and rules, "
                   "confirmed by a person in the severity decision. See Rules & playbooks → Policies."),
        ("Triage", "A person sets severity and the owning team (route). Until then the case is *Awaiting triage*."),
        ("Containment", "Steps that limit ongoing harm, e.g. pausing a session or rotating credentials. All simulated here."),
        ("Response", "Communication with the affected user or customer. Drafts only; nothing is sent."),
        ("Closure", "Human sign-off that the case is resolved."),
        ("QA review", "A second person reviews a closed case and records lessons."),
        ("Route / owning team", "The team that owns the case, e.g. Safety, Child Safety, Product Security."),
        ("SLA", "Target time for the first human review (prototype assumptions)."),
        ("Mandatory review", "The case must be reviewed by a person before any decision; the AI cannot clear it."),
        ("Override", "A person's decision that differs from the AI recommendation, with a reason code."),
        ("Incident Lead", "Senior role that approves irreversible containment and reviews overdue pauses."),
    ],
    "Pipeline": [
        ("AI recommendation", "Severity and route suggested by the AI assessment, before any checks."),
        ("Safety controls", "Fixed checks applied after the AI: " + "; ".join(f"{control_name(k)}" for k in CONTROL_NAME)
         + ". They can raise severity or force review, never lower it."),
        ("Session auto-paused", "Shown as 'Auto-pause (control C7)' in technical views. P0 CBRN or child-safety cases pause the reported session automatically. "
                            "A Safety specialist or the Incident Lead must confirm or lift it; it never lifts itself."),
        ("Rules version", "The versioned rulebook that sets a minimum severity from warning signs in the report."),
        ("Demo AI", "Pre-written or simulated assessments; no live model is called in this demo."),
    ],
    "Evaluation": [
        ("Dev set / held-out set", "Dev cases (44) were used to tune the rules. Held-out cases (36) were frozen beforehand and never used for tuning."),
        ("Recall / precision", "Recall: share of real P0/P1 cases that were caught. Precision: share of P0/P1 calls that were right."),
        ("Fault injection", "A test that deliberately breaks the AI (timeouts, garbage, invented evidence) to check the safety controls still hold."),
        ("Regression gate", "Fails a change if a safety-critical metric drops at all, or another metric drops by more than 5 points."),
    ],
}


def ver(v: str | None) -> str:
    """'rules-v2.1' → 'v2.1'; 'rules-v2.1-fault-demo' → 'v2.1 fault demo'."""
    v = str(v or "")
    return v.split("-", 1)[1].replace("-", " ") if "-" in v else v


SEVERITY_BASIS_WORD = {"human": "Confirmed", "ai_after_controls": "AI-suggested", "rules_after_ai_failure": "Needs manual triage",
                       "unassessed_default": "Not assessed"}
POLICY_STATUS_WORD = {"human": "Confirmed", "ai_after_controls": "AI-suggested", "rules_after_ai_failure": "Not confirmed",
                      "unassessed_default": "—"}


def alerts(x: dict) -> list[str]:
    """Plain-word alerts for a queue row (replaces the ⏸️ ⚠️ ⚑ 🧪 symbols)."""
    is_open = x["status"] not in ("CLOSED", "QA_REVIEWED")
    out = []
    if x["auto_paused"]:
        out.append("Session auto-paused")
    if x["overdue"] and is_open:
        out.append("SLA overdue")
    if x["mandatory_review"] and is_open and not x["human_severity"]:
        out.append("Review required")
    if x["ai_status"] == "failed" and is_open and not x["human_severity"]:
        out.append("AI failed")
    if x["ai_source"] == "fault_injection":
        out.append("Test data")
    return out


def policy_with_more(x: dict) -> str:
    n = len(x["other_policies"])
    return policies.label(x["policy"], code=False) + (f" (+{n} more)" if n else "") if x["policy"] else "Not assessed"


POLICY_BASIS = {"human": "✓ confirmed", "ai_after_controls": "AI-suggested", "rules_after_ai_failure": "not confirmed · AI failed",
                "unassessed_default": "not assessed"}


def policy_label(key: str | None, code: bool = True) -> str:
    return policies.label(key, code) if key else "Not assessed"


def policy_badge(key: str | None, basis: str, prefix: str = "Policy: ") -> str:
    p = policies.get(key)
    cls = "b-human" if basis == "human" else "b-fixture"
    tip = (f"{p['code']} · {p['name']}: {p['definition']} "
           + ("A person confirmed this policy." if basis == "human" else "Suggested by the AI and rules; a person confirms it in the decision.")) if p else None
    return badge(prefix + policy_label(key) + (" · " + POLICY_BASIS.get(basis, basis) if key else ""), cls, tip)


def phase_badge(status: str) -> str:
    p = phase(status)
    return badge(p, PHASE_BADGE[p], PHASE_HELP[p])


FIELD_LABEL = {
    "product_surface": "Product surface", "customer_type": "Customer", "reporter_channel": "Channel",
    "model_version": "Model version", "file_action": "File action", "external_action_attempted": "External action",
    "user_approved": "User approved", "sensitive_data": "Sensitive data", "scope": "Scope", "recurrence": "Recurrence",
    "reversibility": "Reversibility",
}
SPLIT_NAME = {"dev": "Dev set", "held_out": "Held-out set", "all": "All cases"}
SPLIT_HELP = {"dev": "used for tuning", "held_out": "frozen, never used for tuning", "all": "dev + held-out"}
GATE_LABEL = {"P0/P1 recall (after controls)": "P0/P1 recall", "Mandatory review compliance": "Mandatory review flagged when needed",
              "Severity within acceptable range": "Severity within range", "Primary route acceptable": "Route acceptable",
              "Schema-valid rate": "Valid AI output", "C7 auto-pause recall": "Auto-pause recall"}
OVERRIDE_DIRECTION = {"raised": "Raised severity", "lowered": "Lowered severity", "route_only": "Route only (owning team changed)",
                      "policy_only": "Policy only (policy changed)"}
TEAMS = SCHEMA_TEAMS
EVIDENCE_TYPES = ["reporter_statement", "conversation_excerpt", "tool_action_log", "file_diff", "approval_event",
                  "telemetry", "classifier_output", "account_settings", "screenshot_description", "reviewer_note",
                  "restricted_evidence_ref"]
ACTORS = {a.actor_id: a for a in wf.SIMULATED_ACTORS}


def pretty(v) -> str:
    return str(v).replace("_", " ")


def action_label(t: str) -> str:
    return CONTAINMENT_LABEL.get(t, pretty(t))


_KV = re.compile(r"^\s*([a-z][a-z0-9_]*)=(.+?)\s*$")


def readable_fields(text: str) -> str:
    """HTML for display. Structured 'key=value; key=value' records (restricted-evidence and classifier
    fields) become 'Key: value · Key: value'; any other text is escaped unchanged."""
    text = str(text)
    head, sep, rest = text.partition(": ") if re.match(r"^[^=;]*: [a-z_]+=", text) else ("", "", text)
    parts = [x for x in rest.split(";") if x.strip()]
    kv = [_KV.match(x) for x in parts]
    if sum(1 for m in kv if m) < 2:
        return html.escape(text)
    out = []
    for x, m in zip(parts, kv):
        if m:
            out.append(f"<b>{html.escape(m.group(1).replace('_', ' ').capitalize())}:</b> {html.escape(m.group(2).replace('_', ' '))}")
        else:
            out.append(html.escape(x.strip()))
    return (html.escape(head) + sep if sep else "") + " · ".join(out)


def humanize(text: str) -> str:
    """Replace internal route keys in explanatory text with their display names."""
    # Only underscore keys (e.g. legal_privacy, child_safety): plain words such as "safety" or
    # "support" are ordinary English in sentences and must not be capitalised.
    for k, v in ROUTE_LABEL.items():
        if "_" in k:
            text = re.sub(rf"(?<![\w]){re.escape(k)}(?![\w])", v, text)
    return text


def actor_name(actor_id: str | None) -> str:
    if not actor_id:
        return "—"
    if actor_id == wf.SYSTEM_ACTOR.actor_id:
        return "AI / automation"
    a = ACTORS.get(actor_id)
    return a.display.split(" (")[0] if a else actor_id


# --------------------------------------------------------------------------- styling

CSS = """
<style>
.block-container{padding-top:4.2rem;max-width:1500px}
@media (min-width: 900px){
  [data-testid="stColumn"]:has(.st-key-case_actions){position:sticky;top:4rem;align-self:flex-start;
    max-height:calc(100vh - 5rem);overflow-y:auto;overflow-x:hidden;padding:2px 8px 12px 2px;
    scrollbar-width:thin;overscroll-behavior:contain}
}
h1{font-size:1.7rem!important} h2{font-size:1.35rem!important} h3{font-size:1.15rem!important} h4{font-size:1.02rem!important;margin-top:.4rem!important}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:0.76rem;font-weight:600;margin:0 4px 2px 0;border:1px solid transparent;white-space:nowrap;vertical-align:middle}
.b-p0{background:#fde2e1;color:#8a1c1c;border-color:#f3b4b1}.b-p1{background:#fdecd8;color:#8a4a0b;border-color:#f2c89a}
.b-p2{background:#fdf7d6;color:#6b5a07;border-color:#eadc8f}.b-p3{background:#e8f1fb;color:#1f4f82;border-color:#b9d3ef}
.b-fixture{background:#f3eefc;color:#5b2d91;border-color:#d7c6f2}.b-sim{background:#f1f1f1;color:#444;border-color:#d6d6d6}
.b-live{background:#e3f6ec;color:#1b6b3f;border-color:#b3e1c7}.b-fault{background:#ffe8e8;color:#9b1111;border-color:#f5b5b5}
.b-human{background:#e7f6f1;color:#10573f;border-color:#b0dfcd}.b-muted{background:#f4f4f5;color:#555;border-color:#e2e2e2}
.b-warn{background:#fff4e0;color:#7a4b00;border-color:#f0d49c}.b-sim-action{background:#fff;color:#9b1111;border:1px dashed #d98080}
.small{font-size:0.83rem;color:#666}.muted{color:#777}.unknown{color:#a11;font-weight:600}
.kv{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px 18px;font-size:0.88rem}
.kv div span{color:#777;display:inline-block;min-width:118px}
.quote{border-left:3px solid #d0d4dc;padding:6px 12px;background:#fafbfc;border-radius:4px;margin:4px 0 8px 0}
.cite{border-left:2px solid #e3e5ea;padding:2px 10px;margin:2px 0 10px 18px;font-size:0.82rem;color:#555}
.stepper{display:flex;gap:0;margin:6px 0 10px 0;font-size:0.76rem}
.stepper div{flex:1;text-align:center;padding:5px 2px;border-bottom:3px solid #e6e7eb;color:#999}
.stepper div.done{border-color:#9bc2a8;color:#557}.stepper div.cur{border-color:#e05a47;color:#222;font-weight:700}
.next{border-left:4px solid #e05a47;background:#fff8f6;padding:8px 14px;border-radius:4px;margin:4px 0 12px 0}
.next.ok{border-left-color:#3d8b5f;background:#f5fbf7}
.lbl{display:inline-block;font-size:0.72rem;font-weight:700;letter-spacing:.02em;padding:1px 8px;border-radius:4px;margin:0 0 6px 0}
.lbl-src{background:#eef0f3;color:#4a5160}.lbl-ai{background:#efe8fb;color:#5b2d91}
.card{border:1px solid #e3e5ea;border-radius:8px;padding:10px 14px 12px 14px;margin:6px 0 14px 0}
.card.src{border-left:5px solid #9aa3b2}.card.ai{border-left:5px solid #8e6bd6;background:#fdfbff}
.card-h{font-weight:700;font-size:1.02rem;margin:0 0 6px 0}
.st-key-src_panel{border-left:5px solid #9aa3b2;padding-left:14px}
.st-key-ai_panel{border-left:5px solid #8e6bd6;padding-left:14px}
.raw{font-size:0.9rem;white-space:pre-wrap}
.trail{border-collapse:collapse;font-size:0.88rem;margin:0 0 8px 0;width:100%}
.trail td{border:none!important;padding:4px 10px 4px 0;vertical-align:top}
.trail td:first-child{white-space:nowrap;color:#555;font-weight:600;width:150px}
.tip{position:relative;cursor:help}.tip-i{opacity:.55;font-weight:400}
.tip:hover::after{content:attr(data-tip);position:absolute;top:calc(100% + 6px);left:0;z-index:1000;width:300px;white-space:normal;
  background:#1f2430;color:#fff;padding:9px 11px;border-radius:7px;font-weight:400;font-size:.8rem;line-height:1.4;
  box-shadow:0 6px 18px rgba(0,0,0,.18);text-align:left}
.evt{font-size:0.86rem;padding:5px 0;border-bottom:1px solid #f0f0f2}.evt .t{color:#888;font-size:0.78rem}
</style>
"""


def md(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s))


def badge(text: str, cls: str = "b-muted", title: str | None = None) -> str:
    if not title:
        return f'<span class="badge {cls}">{esc(text)}</span>'
    return f'<span class="badge tip {cls}" data-tip="{esc(title)}">{esc(text)} <span class="tip-i">ⓘ</span></span>'


def sev_badge(sev: str | None, suffix: str = "") -> str:
    if not sev:
        return badge("—")
    return badge(f"{sev}{(' · ' + suffix) if suffix else ''}", f"b-{sev.lower()}")


SOURCE_HELP = {
    "offline_fixture": "The AI assessment is pre-written for the demo; no live model was called.",
    "offline_simulation": "The AI assessment is simulated for the demo; no live model was called.",
    "live_model": "The assessment came from a live model call.",
    "fault_injection": "Test data: the AI was deliberately broken (fault injection) to check that the safety controls still hold.",
}


def source_badge(kind: str | None) -> str:
    t, c = SOURCE_LABEL.get(kind or "none", (kind, "b-muted"))
    return badge(t, c, SOURCE_HELP.get(kind or ""))


def stepper(status: str) -> str:
    """Three-phase bar with the current stage underneath (the detail)."""
    cur = STATUS_PHASE[status]
    cells = "".join(f'<div class="{"cur" if i == cur else "done" if i < cur else ""}" title="{esc(PHASE_HELP[p])}">{p}</div>'
                    for i, p in enumerate(PHASES))
    nxt = STAGE_NEXT[status]
    line = f"Stage {STATUS_STAGE[status] + 1} of 8: <b>{esc(STATUS_LABEL[status])}</b>" + (f" · next: {esc(nxt)}" if nxt else "")
    return f'<div class="stepper">{cells}</div><div class="small" style="margin:-4px 0 10px 0">{line}</div>'


def relative(minutes: float | None) -> str:
    if minutes is None:
        return ""
    m = abs(int(minutes))
    txt = f"{m // 1440}d {m % 1440 // 60}h" if m >= 1440 else f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"
    return f"overdue by {txt}" if minutes < 0 else f"due in {txt}"


def ago(ts: str | None) -> str:
    if not ts:
        return ""
    d = datetime.fromisoformat(ts)
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    mins = (datetime.now(timezone.utc) - d).total_seconds() / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    if mins < 1440:
        return f"{int(mins // 60)}h ago"
    return f"{int(mins // 1440)}d ago"


# --------------------------------------------------------------------------- session

def public_demo() -> bool:
    """Public demo mode: each browser session gets its own private, freshly seeded database.
    Enable with RISKOPS_PUBLIC_DEMO=1 (or true/yes; env var or Streamlit secret)."""
    on = {"1", "true", "yes", "on"}
    if os.environ.get("RISKOPS_PUBLIC_DEMO", "").strip().lower() in on:
        return True
    try:
        return str(st.secrets.get("RISKOPS_PUBLIC_DEMO", "")).strip().strip('"').lower() in on
    except Exception:  # no secrets file
        return False


SESSION_DB_DIR = Path(tempfile.gettempdir()) / "riskops_sessions"


def db_file() -> Path:
    if not public_demo():
        return Path(config.db_path())
    if "_db_file" not in st.session_state:
        SESSION_DB_DIR.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 12 * 3600  # remove sessions idle for 12h
        for old in SESSION_DB_DIR.glob("*.db"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass
        st.session_state["_db_file"] = SESSION_DB_DIR / f"{uuid.uuid4().hex}.db"
    return st.session_state["_db_file"]


def open_conn() -> None:
    """Fresh connection per script run (avoids stale handles if the DB file is replaced).
    Seeds the database on first use."""
    old = st.session_state.pop("_conn", None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    from riskops.demo_db import ensure_seeded
    path = ensure_seeded(db_file())
    st.session_state["_conn"] = connect(path)


def conn():
    if "_conn" not in st.session_state:
        open_conn()
    return st.session_state["_conn"]


def current_actor() -> wf.Actor:
    return ACTORS[st.session_state.get("actor_id", "alex.riskops")]


def provider_for_mode():
    mode = get_setting(conn(), "provider_mode")
    return get_provider(mode), mode


def go_case(incident_id: str) -> None:
    st.session_state["case_id"] = incident_id
    st.switch_page(st.session_state["_pages"]["case"])


def go(page: str) -> None:
    st.switch_page(st.session_state["_pages"][page])


# --------------------------------------------------------------------------- feedback

FORM_FIELD_LABEL = {
    "title": "Short title", "reported_behavior": "What was reported", "incident_id": "Incident ID",
    "reported_at": "Reported time", "evidence": "Evidence", "evidence_id": "Evidence ID", "content": "Evidence content",
    "source_description": "Evidence source", "source_type": "Evidence type", "root_cause": "Root cause",
    "user_customer_impact": "User / customer impact", "actions_taken": "Actions taken", "sign_off_statement": "Sign-off statement",
    "remaining_mitigation": "Remaining mitigation", "response_status": "Response status", "evidence_reviewed": "Evidence reviewed",
    "teams_involved": "Teams involved",
}


def friendly_error(e: Exception) -> str:
    """Plain-language message for validation errors instead of a raw technical dump."""
    from pydantic import ValidationError
    if not isinstance(e, ValidationError):
        return f"Something went wrong: {e}"
    lines = []
    for err in e.errors():
        loc = [x for x in err["loc"] if not isinstance(x, int)]
        rows = [x for x in err["loc"] if isinstance(x, int)]
        field = " → ".join(FORM_FIELD_LABEL.get(str(x), pretty(x)) for x in loc) or "Input"
        if rows:
            field += f" (row {rows[0] + 1})"
        kind = err.get("type", "")
        if kind in ("string_too_short", "missing", "too_short"):
            msg = "is required"
        elif kind == "string_pattern_mismatch":
            msg = "may only use letters, numbers and . _ : -"
        elif kind == "literal_error":
            msg = "has a value that isn't one of the allowed options"
        else:
            msg = err.get("msg", "is invalid").removeprefix("Value error, ")
        lines.append(f"- **{field}** {msg}")
    return "Please fix the following:\n" + "\n".join(dict.fromkeys(lines))


def run_action(fn, success: str | None = None, area: str = "global") -> bool:
    """Call a service. Success → toast after rerun. Failure → message shown inline at ``area``."""
    try:
        out = fn()
    except wf.PermissionDenied as e:
        st.session_state.setdefault("_errors", {})[area] = f"Not permitted: {e}"
        return False
    except wf.WorkflowError as e:
        st.session_state.setdefault("_errors", {})[area] = str(e)
        return False
    except Exception as e:  # pydantic validation etc.
        st.session_state.setdefault("_errors", {})[area] = friendly_error(e)
        return False
    st.session_state.get("_errors", {}).pop(area, None)
    if success:
        st.session_state.setdefault("_toasts", []).append(success if not isinstance(out, str) else f"{success} ({out})")
    return True


def feedback(area: str) -> None:
    err = st.session_state.get("_errors", {}).get(area)
    if err:
        st.error(err)


def show_toasts() -> None:
    for t in st.session_state.pop("_toasts", []):
        st.toast(t, icon="✅")


def drop_stale(key: str, options: list) -> None:
    """Forget a remembered widget value that is no longer a valid option (e.g. after labels were renamed)."""
    v = st.session_state.get(key)
    if v is None:
        return
    if isinstance(v, list):
        keep = [x for x in v if x in options]
        if keep != v:
            st.session_state[key] = keep
    elif v not in options:
        del st.session_state[key]


def section(labels: list[str], key: str) -> str:
    """Stateful section switcher (keyed widget state survives form submissions and reruns)."""
    if st.session_state.get(key) not in labels:
        st.session_state[key] = labels[0]
    choice = st.segmented_control("Section", labels, key=key, required=True, label_visibility="collapsed")
    return choice or labels[0]


def permission_hint(permission: str) -> str | None:
    """None if the current actor may do this, otherwise a short explanation."""
    if wf.can(current_actor(), permission):
        return None
    return f"Requires {wf.roles_for(permission)}"


# --------------------------------------------------------------------------- activity feed

def describe_event(e: dict) -> str:
    t, new = e["event_type"], e["new_value"]
    try:
        nv = json.loads(new) if new and new[:1] in "{[" else new
    except json.JSONDecodeError:
        nv = new
    details = json.loads(e["details_json"]) if e["details_json"] else {}
    who = f"<b>{esc(actor_name(e['actor_id']))}</b>"
    reason = f' — <i>{esc(e["reason"])}</i>' if e["reason"] else ""
    if t == "intake_created":
        return f"{who} created the report"
    if t in ("ai_assessment", "ai_reassessment"):
        what = "re-ran" if t == "ai_reassessment" else "ran"
        res = details.get("status")
        return (f"{who} {what} the AI assessment ({pretty(details.get('provider_kind'))}, rules {details.get('rule_version')}): "
                + (f"recommends {details.get('controlled_severity')} after controls" if res == "valid" else f"<b>failed</b> ({details.get('error_kind')})"))
    if t == "human_severity_confirmed":
        return f"{who} confirmed severity <b>{nv['severity']}</b> → {ROUTE_LABEL.get(nv['route'], nv['route'])}{reason}"
    if t == "human_override":
        ai = details.get("ai_recommendation", {})
        return (f"{who} <b>overrode</b> the AI ({ai.get('severity')} → {ROUTE_LABEL.get(ai.get('route'), ai.get('route'))}) with "
                f"<b>{nv['severity']}</b> → {ROUTE_LABEL.get(nv['route'], nv['route'])} · {pretty(details.get('override_reason_code'))}{reason}")
    if t == "status_change":
        # history: say "Closed", not the current-state hint "Closed · QA pending"
        return f"{who} moved the case to <b>{'Closed' if new == 'CLOSED' else STATUS_LABEL.get(new, new)}</b>{reason}"
    if t == "owner_assigned":
        return f"{who} assigned owner <b>{esc(actor_name(new))}</b>{reason}"
    if t == "investigation_note":
        return f"{who} added a note: {esc(new)}"
    if t == "evidence_added":
        return f"{who} added evidence <b>{esc(new)}</b> ({pretty(details.get('source_type'))})"
    if t == "containment_proposed":
        return f"{who} proposed containment <b>{action_label(nv['action_type'])}</b> on {esc(nv['target'])} [simulated]"
    if t == "auto_hold_applied":
        return (f"<b>⏸️ Session auto-paused</b>: automatic pause applied to {esc(pretty(details.get('action_type', '')))} — {esc(e['reason'] or '')}"
                f" [simulated · awaiting human review]")
    if t in ("auto_hold_confirmed", "auto_hold_lifted"):
        return f"{who} <b>{'confirmed' if t.endswith('confirmed') else 'lifted'}</b> the automatic pause [simulated]{reason}"
    if t in ("containment_approved", "containment_rejected", "containment_reversed", "containment_expired"):
        verb = t.split("_")[1]
        return f"{who} {verb} containment {esc(e['field'].split(':')[1])} [simulated]{reason}"
    if t in ("communication_drafted", "communication_edited"):
        return f"{who} {'drafted' if t.endswith('drafted') else 'edited'} {pretty(details.get('comm_type'))} (v{new}) — not sent"
    if t == "communication_reviewed":
        return f"{who} reviewed a draft → <b>{esc(new)}</b> (as {', '.join(details.get('reviewed_as', []))}){reason}"
    if t.startswith("link_"):
        return f"{who} {t.split('_')[1]} link to <b>{esc(new)}</b> as {details.get('link_type')}{reason}"
    if t == "linked_higher_severity_warning":
        return f"⚠ {esc(e['reason'])}"
    if t == "ai_human_disagreement":
        return f"AI now recommends {esc(nv)}; human decision {esc(e['previous_value'])} kept"
    if t == "closure_signed_off":
        return f"{who} <b>signed off closure</b> ({pretty(nv['closure_category'])}, {nv['final_severity']}){reason}"
    if t == "qa_review":
        return f"{who} recorded QA review: <b>{pretty(new)}</b>{reason}"
    if t == "claim_support_review":
        return f"{who} marked {esc(e['field'].split(':')[1])} as <b>{pretty(new)}</b>"
    return f"{who} {pretty(t)}{reason}"


def run_inline(fn, success: str | None = None) -> bool:
    """For dialogs: show errors immediately where the user is; toast on success."""
    try:
        fn()
    except wf.WorkflowError as e:
        st.error(("Not permitted: " if isinstance(e, wf.PermissionDenied) else "") + str(e))
        return False
    except Exception as e:
        st.error(friendly_error(e))
        return False
    if success:
        st.session_state.setdefault("_toasts", []).append(success)
    return True


def flash(kind: str, text: str) -> None:
    """Compatibility helper: successes/info become toasts; errors show at the top of the page."""
    if kind == "error":
        st.session_state.setdefault("_errors", {})["global"] = text
    else:
        st.session_state.setdefault("_toasts", []).append(text)
