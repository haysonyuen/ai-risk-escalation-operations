"""Shared UI helpers. UI code only calls riskops services; it holds no business rules."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from riskops import workflow as wf  # noqa: E402
from riskops.db import connect, get_setting  # noqa: E402
from riskops.providers import FAULT_MODES, get_provider  # noqa: E402
from riskops import config  # noqa: E402

CSS = """
<style>
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:0.78rem;font-weight:600;margin-right:4px;border:1px solid transparent;white-space:nowrap}
.b-p0{background:#fde2e1;color:#8a1c1c;border-color:#f3b4b1}
.b-p1{background:#fdecd8;color:#8a4a0b;border-color:#f2c89a}
.b-p2{background:#fdf7d6;color:#6b5a07;border-color:#eadc8f}
.b-p3{background:#e8f1fb;color:#1f4f82;border-color:#b9d3ef}
.b-ai{background:#eef0ff;color:#3b3f99;border-color:#c9ccf5}
.b-fixture{background:#f3eefc;color:#5b2d91;border-color:#d7c6f2}
.b-sim{background:#f1f1f1;color:#444;border-color:#d6d6d6}
.b-live{background:#e3f6ec;color:#1b6b3f;border-color:#b3e1c7}
.b-fault{background:#ffe8e8;color:#9b1111;border-color:#f5b5b5}
.b-human{background:#e7f6f1;color:#10573f;border-color:#b0dfcd}
.b-rules{background:#fff4e0;color:#7a4b00;border-color:#f0d49c}
.b-sim-action{background:#fff;color:#9b1111;border:1px dashed #d98080}
.b-muted{background:#f6f6f6;color:#666;border-color:#e2e2e2}
.small{font-size:0.85rem;color:#555}
.kv td{padding:2px 10px 2px 0;vertical-align:top}
.unknown{color:#9b1111;font-weight:600}
</style>
"""

SOURCE_BADGE = {
    "offline_fixture": ("AI · offline fixture (hand-authored, not a model)", "b-fixture"),
    "offline_simulation": ("AI · offline simulation (deterministic, not a model)", "b-sim"),
    "live_model": ("AI · live model call", "b-live"),
    "fault_injection": ("FAULT INJECTION (test)", "b-fault"),
    "rules_only": ("Deterministic rules", "b-rules"),
    "none": ("No AI assessment", "b-muted"),
}


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{html.escape(str(text))}</span>'


def sev_badge(sev: str | None, prefix: str = "") -> str:
    if not sev:
        return badge(f"{prefix}—", "b-muted")
    return badge(f"{prefix}{sev}", f"b-{sev.lower()}")


def source_badge(kind: str | None) -> str:
    t, c = SOURCE_BADGE.get(kind or "none", (kind, "b-muted"))
    return badge(t, c)


def md(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def open_conn() -> None:
    """Open a fresh connection for this script run (closing the previous one). Avoids stale
    handles when the database file is replaced, e.g. re-seeded from the CLI."""
    old = st.session_state.pop("_conn", None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    st.session_state["_conn"] = connect()


def conn():
    if "_conn" not in st.session_state:
        open_conn()
    return st.session_state["_conn"]


def current_actor() -> wf.Actor:
    aid = st.session_state.get("actor_id", "alex.riskops")
    return {a.actor_id: a for a in wf.SIMULATED_ACTORS}[aid]


def provider_for_mode():
    mode = get_setting(conn(), "provider_mode")
    return get_provider(mode), mode


def flash(kind: str, text: str) -> None:
    st.session_state.setdefault("flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in st.session_state.pop("flash", []):
        getattr(st, kind)(text)


def run_action(fn, success: str | None = None) -> bool:
    """Call a service; show PermissionDenied/WorkflowError clearly. Returns True on success."""
    try:
        out = fn()
    except wf.PermissionDenied as e:
        flash("error", f"Blocked by service-layer permission check: {e}")
        return False
    except wf.WorkflowError as e:
        flash("error", f"Not allowed: {e}")
        return False
    except Exception as e:  # validation errors from pydantic etc.
        flash("error", f"{type(e).__name__}: {e}")
        return False
    if success:
        flash("success", success if not isinstance(out, str) else f"{success} ({out})")
    return True


def sidebar() -> str:
    md(CSS)
    with st.sidebar:
        st.markdown("### AI Risk & Escalation Ops")
        st.caption("Prototype · synthetic incidents · simulated actions")
        if "nav_to" in st.session_state:
            st.session_state["page"] = st.session_state.pop("nav_to")
        page = st.radio("View", ["Incident queue", "Incident workspace", "New intake", "Quality & evaluation",
                                 "Rules & playbooks", "Monitoring"], key="page")
        st.divider()
        actors = {a.actor_id: a for a in wf.SIMULATED_ACTORS}
        st.selectbox("Acting as (simulated identity)", list(actors), key="actor_id",
                     format_func=lambda k: actors[k].display)
        st.caption("Role selector is a demo convenience, not authentication. Permissions are still enforced in the service layer for the selected role.")
        st.divider()
        c = conn()
        mode = get_setting(c, "provider_mode")
        modes = ["offline", "live"] + [f"fault:{m}" for m in FAULT_MODES]
        labels = {"offline": "Offline (fixtures / deterministic simulation)",
                  "live": "Live model (Anthropic API)" + ("" if config.live_credentials_available() else " — no API key set")}
        labels.update({f"fault:{m}": f"FAULT INJECTION: {d}" for m, d in FAULT_MODES.items()})
        new = st.selectbox("Assessment provider", modes, index=modes.index(mode) if mode in modes else 0,
                           format_func=lambda m: labels[m])
        if new != mode:
            wf.set_provider_mode(c, new, current_actor())
            st.rerun()
        if new == "live" and not config.live_credentials_available():
            st.warning("Live mode selected but ANTHROPIC_API_KEY is not set. Assessments will fail visibly and route to manual review — there is no silent fallback.")
        if new.startswith("fault:"):
            st.error("Fault injection is active. Results are deliberate test failures, not model behavior.")
        st.caption(f"Active rules: `{get_setting(c, 'active_rule_version')}` · prompt: `{get_setting(c, 'active_prompt_version')}`")
        st.caption(f"DB: `{Path(config.db_path()).name}` (local SQLite)")
        with st.expander("Reset demo data"):
            st.caption("Deletes the local database and re-seeds synthetic incidents.")
            if st.checkbox("I understand this deletes local demo changes", key="confirm_reset"):
                if st.button("Reset and re-seed"):
                    from riskops.seed import seed
                    st.session_state.pop("_conn").close()
                    seed()
                    st.session_state.pop("confirm_reset", None)
                    flash("success", "Database reset and re-seeded.")
                    st.rerun()
    return page


def jdump(x) -> str:
    return json.dumps(x, indent=1, default=str)


def section(labels: list[str], key: str) -> str:
    """Stateful section selector (renders only the chosen section). Keyed widget state
    survives form submissions and st.rerun(), unlike st.tabs."""
    if st.session_state.get(key) not in labels:
        st.session_state[key] = labels[0]
    choice = st.segmented_control("Section", labels, key=key, required=True, label_visibility="collapsed")
    st.divider()
    return choice or labels[0]
