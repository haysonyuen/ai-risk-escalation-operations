"""Shared presentation helpers. No business rules live here — only calls into riskops."""

from __future__ import annotations

import html
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
from riskops import workflow as wf  # noqa: E402
from riskops.db import connect, get_setting  # noqa: E402
from riskops.providers import get_provider  # noqa: E402
from riskops.schemas import TEAMS as SCHEMA_TEAMS  # noqa: E402

# --------------------------------------------------------------------------- labels

STATUS_LABEL = {
    "NEW": "New · not assessed", "ASSESSED": "Awaiting triage", "ASSESSMENT_FAILED": "Awaiting triage · AI failed",
    "TRIAGED": "Triaged", "INVESTIGATING": "Investigating", "CONTAINMENT": "Containment", "RESPONSE": "Response",
    "CLOSED": "Closed", "REOPENED": "Reopened · re-triage", "QA_REVIEWED": "Closed · QA reviewed",
}
STAGES = ["Intake", "AI enrichment", "Triage", "Investigation", "Containment", "Response", "Closure", "QA"]
STATUS_STAGE = {"NEW": 0, "ASSESSED": 1, "ASSESSMENT_FAILED": 1, "TRIAGED": 2, "REOPENED": 2, "INVESTIGATING": 3,
                "CONTAINMENT": 4, "RESPONSE": 5, "CLOSED": 6, "QA_REVIEWED": 7}
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
    "offline_fixture": ("Offline fixture · not a model", "b-fixture"),
    "offline_simulation": ("Offline simulation · not a model", "b-sim"),
    "live_model": ("Live model", "b-live"),
    "fault_injection": ("Fault injection test", "b-fault"),
    "none": ("Not assessed", "b-muted"),
}
BASIS_LABEL = {"human": "confirmed", "ai_after_controls": "AI · unconfirmed",
               "rules_after_ai_failure": "rules · AI failed", "unassessed_default": "default · unassessed"}
CONTROL_TEXT = {
    "C1": "AI output unusable; no assessment was invented",
    "C2": "Cites evidence that does not exist",
    "C3": "Raised to the rules minimum",
    "C4": "Report text contains instructions aimed at the reviewer (ignored)",
    "C5": "High potential impact but low confidence",
    "C6": "Specialist route kept",
    "C7": "Session paused automatically (P0 CBRN / child safety) — a person must confirm or lift",
}
FIELD_LABEL = {
    "product_surface": "Product surface", "customer_type": "Customer", "reporter_channel": "Channel",
    "model_version": "Model version", "file_action": "File action", "external_action_attempted": "External action",
    "user_approved": "User approved", "sensitive_data": "Sensitive data", "scope": "Scope", "recurrence": "Recurrence",
    "reversibility": "Reversibility",
}
TEAMS = SCHEMA_TEAMS
EVIDENCE_TYPES = ["reporter_statement", "conversation_excerpt", "tool_action_log", "file_diff", "approval_event",
                  "telemetry", "classifier_output", "account_settings", "screenshot_description", "reviewer_note"]
ACTORS = {a.actor_id: a for a in wf.SIMULATED_ACTORS}


def pretty(v) -> str:
    return str(v).replace("_", " ")


def action_label(t: str) -> str:
    return CONTAINMENT_LABEL.get(t, pretty(t))


def humanize(text: str) -> str:
    """Replace internal route keys in explanatory text with their display names."""
    for k, v in ROUTE_LABEL.items():
        text = text.replace(k, v)
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
.block-container{padding-top:2.2rem;max-width:1500px}
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
.evt{font-size:0.86rem;padding:5px 0;border-bottom:1px solid #f0f0f2}.evt .t{color:#888;font-size:0.78rem}
</style>
"""


def md(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s))


def badge(text: str, cls: str = "b-muted") -> str:
    return f'<span class="badge {cls}">{esc(text)}</span>'


def sev_badge(sev: str | None, suffix: str = "") -> str:
    if not sev:
        return badge("—")
    return badge(f"{sev}{(' · ' + suffix) if suffix else ''}", f"b-{sev.lower()}")


def source_badge(kind: str | None) -> str:
    t, c = SOURCE_LABEL.get(kind or "none", (kind, "b-muted"))
    return badge(t, c)


def stepper(status: str) -> str:
    cur = STATUS_STAGE[status]
    cells = "".join(f'<div class="{"cur" if i == cur else "done" if i < cur else ""}">{i + 1}. {s}</div>' for i, s in enumerate(STAGES))
    return f'<div class="stepper">{cells}</div>'


def relative(minutes: float | None) -> str:
    if minutes is None:
        return ""
    m = abs(int(minutes))
    txt = f"{m // 1440}d {m % 1440 // 60}h" if m >= 1440 else f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"
    return f"overdue {txt}" if minutes < 0 else f"due in {txt}"


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
    Enable with RISKOPS_PUBLIC_DEMO=1 (env var or Streamlit secret)."""
    if os.environ.get("RISKOPS_PUBLIC_DEMO") == "1":
        return True
    try:
        return str(st.secrets.get("RISKOPS_PUBLIC_DEMO", "")) == "1"
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
        st.session_state.setdefault("_errors", {})[area] = f"{type(e).__name__}: {e}"
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
        return f"{who} moved the case to <b>{STATUS_LABEL.get(new, new)}</b>{reason}"
    if t == "owner_assigned":
        return f"{who} assigned owner <b>{esc(actor_name(new))}</b>{reason}"
    if t == "investigation_note":
        return f"{who} added a note: {esc(new)}"
    if t == "evidence_added":
        return f"{who} added evidence <b>{esc(new)}</b> ({pretty(details.get('source_type'))})"
    if t == "containment_proposed":
        return f"{who} proposed containment <b>{action_label(nv['action_type'])}</b> on {esc(nv['target'])} [simulated]"
    if t == "auto_hold_applied":
        return (f"<b>⏸ C7 automatic pause</b> applied to {esc(pretty(details.get('action_type', '')))} — {esc(e['reason'] or '')}"
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
        st.error(f"{type(e).__name__}: {e}")
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
