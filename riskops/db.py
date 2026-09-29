"""SQLite persistence.

The ``events`` table is append-only at the application level and SQLite triggers reject
UPDATE/DELETE on it. This is a local integrity guard, NOT a tamper-proof audit log: anyone
with file access can modify or replace the database file.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    intake_json TEXT NOT NULL,
    title TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    origin TEXT NOT NULL,              -- seed | demo | import
    status TEXT NOT NULL,
    owner TEXT,
    current_assessment_id TEXT,
    human_severity TEXT,
    human_route TEXT,
    human_teams_json TEXT,
    severity_decided_by TEXT,
    severity_decided_at TEXT,
    first_human_review_at TEXT,
    closure_json TEXT,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    incident_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_description TEXT NOT NULL,
    content TEXT NOT NULL,
    collected_at TEXT,
    added_at TEXT NOT NULL,
    added_by TEXT NOT NULL,
    origin TEXT NOT NULL,
    PRIMARY KEY (incident_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    provider_kind TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_name TEXT,
    prompt_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,              -- valid | failed
    error_kind TEXT,
    error TEXT,
    output_json TEXT,
    rule_result_json TEXT NOT NULL,
    controls_json TEXT NOT NULL,
    model_severity TEXT,
    controlled_severity TEXT,
    controlled_route TEXT,
    mandatory_review INTEGER NOT NULL,
    latency_ms REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    origin TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    ts TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    event_type TEXT NOT NULL,
    field TEXT,
    previous_value TEXT,
    new_value TEXT,
    reason TEXT,
    origin TEXT NOT NULL,              -- seed | demo | system
    details_json TEXT
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TABLE IF NOT EXISTS containment_actions (
    action_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target TEXT NOT NULL,
    rationale TEXT NOT NULL,
    reversible INTEGER NOT NULL,
    proposed_by TEXT NOT NULL,
    proposed_source TEXT NOT NULL,     -- ai | human | auto_hold (C7, applied without prior approval)
    proposed_at TEXT NOT NULL,
    status TEXT NOT NULL,              -- proposed | rejected | active | reversed | expired
    decided_by TEXT,
    decided_at TEXT,
    decision_reason TEXT,
    review_by TEXT,
    expires_at TEXT,
    ended_at TEXT,
    ended_by TEXT,
    end_reason TEXT,
    simulated INTEGER NOT NULL DEFAULT 1,
    hold_review_outcome TEXT,          -- C7 auto-hold only: confirmed | lifted (NULL = awaiting a person)
    hold_reviewed_by TEXT,
    hold_reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS communications (
    comm_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    incident_id TEXT NOT NULL,
    comm_type TEXT NOT NULL,
    body TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    specialist_review_json TEXT NOT NULL,
    status TEXT NOT NULL,              -- draft | approved | rejected
    generator TEXT NOT NULL,           -- template | live_model | human_edit
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_note TEXT,
    PRIMARY KEY (comm_id, version)
);
CREATE TABLE IF NOT EXISTS links (
    link_id TEXT PRIMARY KEY,
    incident_a TEXT NOT NULL,
    incident_b TEXT NOT NULL,
    link_type TEXT NOT NULL,           -- duplicate | related
    status TEXT NOT NULL,              -- suggested | confirmed | rejected
    score REAL,
    explanation TEXT,
    suggested_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS claim_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id TEXT NOT NULL,
    fact_index INTEGER NOT NULL,
    verdict TEXT NOT NULL,             -- supported | partially_supported | unsupported | cannot_determine
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT NOT NULL,
    config_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    artifact_dir TEXT,
    origin TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "active_rule_version": "rules-v2.0",
    "active_prompt_version": "prompt-v3",
    "provider_mode": "offline",
    "quality_baseline_run_id": "",
}


_CLOCK: datetime | None = None


def utcnow() -> datetime:
    """Current time, or the frozen time set by ``clock()`` (used only when seeding history)."""
    return _CLOCK or datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


@contextmanager
def clock(dt: datetime):
    """Temporarily freeze time so seeded historical records carry historical timestamps."""
    global _CLOCK
    prev, _CLOCK = _CLOCK, dt
    try:
        yield
    finally:
        _CLOCK = prev


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    return conn


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def log_event(conn: sqlite3.Connection, *, incident_id: str | None, actor_id: str, actor_role: str,
              event_type: str, field: str | None = None, previous=None, new=None, reason: str | None = None,
              origin: str = "demo", details: dict | None = None, ts: str | None = None) -> None:
    def s(v):
        if v is None:
            return None
        return v if isinstance(v, str) else json.dumps(v, default=str)
    conn.execute(
        "INSERT INTO events(incident_id, ts, actor_id, actor_role, event_type, field, previous_value, new_value, reason, origin, details_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (incident_id, ts or now_iso(), actor_id, actor_role, event_type, field, s(previous), s(new), reason, origin,
         json.dumps(details, default=str) if details else None),
    )


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None
