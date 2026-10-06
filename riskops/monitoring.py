"""Operational monitoring and quality alerts computed from the local database.

Honesty rules implemented here:
  * seeded (synthetic historical) timestamps are reported separately from actions performed
    during the demo;
  * repeat issues are reported as COUNTS - there is no exposure denominator, so no rates;
  * quality alerts come from evaluation runs on synthetic data and are labeled as such
    (never "production drift").
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import config
from .db import rows
from .workflow import effective_policy, effective_severity, get_assessment, latest_communications, next_actions

OPEN = {"NEW", "ASSESSED", "ASSESSMENT_FAILED", "TRIAGED", "INVESTIGATING", "CONTAINMENT", "RESPONSE", "REOPENED"}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def queue(conn, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for inc in rows(conn, "SELECT * FROM incidents ORDER BY reported_at DESC"):
        intake = json.loads(inc["intake_json"])
        a = get_assessment(conn, inc["current_assessment_id"])
        sev, basis = effective_severity(conn, inc)
        reported = _dt(inc["reported_at"])
        target = config.sla_minutes(sev, "first_human_review")
        deadline = reported + timedelta(minutes=target) if target else None
        reviewed = _dt(inc["first_human_review_at"])
        overdue = bool(deadline and not reviewed and now > deadline and inc["status"] in OPEN)
        breached = bool(deadline and reviewed and reviewed > deadline)
        pending = []
        holds = rows(conn, "SELECT review_by FROM containment_actions WHERE incident_id=? AND proposed_source='auto_hold'"
                           " AND status='active' AND hold_review_outcome IS NULL", (inc["incident_id"],))
        hold_overdue = any(_dt(h["review_by"]) <= now for h in holds)
        if holds:
            pending.append("auto-pause review")
        if not inc["human_severity"] and inc["status"] in OPEN:
            pending.append("severity decision")
        if rows(conn, "SELECT 1 FROM containment_actions WHERE incident_id=? AND status='proposed'", (inc["incident_id"],)):
            pending.append("containment approval")
        if any(c["status"] == "draft" and json.loads(c["specialist_review_json"])["required"]
               for c in latest_communications(conn, inc["incident_id"])):
            pending.append("specialist comms review")
        if rows(conn, "SELECT 1 FROM links WHERE (incident_a=? OR incident_b=?) AND status='suggested'", (inc["incident_id"], inc["incident_id"])):
            pending.append("link review")
        if inc["status"] == "RESPONSE":
            pending.append("closure sign-off")
        categories = list(a["rule_result"]["categories"]) if a else []
        if a and a["output"]:
            categories = list(a["output"]["risk_categories"]) + [c for c in categories if c not in a["output"]["risk_categories"]]
        categories = [c for c in categories if c != "benign_noise"] or categories
        pol, pol_basis, pol_other = effective_policy(conn, inc)
        out.append({
            "incident_id": inc["incident_id"], "title": inc["title"], "status": inc["status"], "owner": inc["owner"] or "",
            "product_surface": intake.get("product_surface"), "customer_type": intake.get("customer_type"),
            "categories": categories,
            "policy": pol, "policy_basis": pol_basis, "other_policies": pol_other,
            "ai_severity": a["controlled_severity"] if a else None,
            "ai_model_severity": a["model_severity"] if a else None,
            "ai_source": a["provider_kind"] if a else "none",
            "ai_status": a["status"] if a else "not_assessed",
            "rule_version": a["rule_version"] if a else None,
            "human_severity": inc["human_severity"],
            "effective_severity": sev, "severity_basis": basis,
            "mandatory_review": bool(a and a["mandatory_review"]) or not a,
            "reported_at": inc["reported_at"], "age_hours": round((now - reported).total_seconds() / 3600, 1),
            "review_deadline": deadline.isoformat(timespec="minutes") if deadline else None,
            "overdue": overdue, "first_review_breached": breached,
            "auto_paused": bool(holds), "auto_pause_overdue": hold_overdue,
            "pending": pending, "origin": inc["origin"],
            "next_actions": next_actions(conn, inc["incident_id"]),
            "minutes_to_deadline": round((deadline - now).total_seconds() / 60) if deadline and not reviewed else None,
            "urgency": (0 if holds else 1 if overdue else 2, {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[sev],
                        (deadline - now).total_seconds() if deadline and not reviewed else 1e12),
        })
    return out


def case_row(conn, incident_id: str, now: datetime | None = None) -> dict:
    return next(x for x in queue(conn, now) if x["incident_id"] == incident_id)


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    return (b - a).total_seconds() / 60 if a and b else None


def _stats(vals: list[float]) -> dict:
    return {"n": len(vals), "median_min": round(statistics.median(vals), 1) if vals else None,
            "max_min": round(max(vals), 1) if vals else None}


def ops_metrics(conn, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    incs = rows(conn, "SELECT * FROM incidents")
    q = queue(conn, now)
    open_q = [x for x in q if x["status"] in OPEN]

    first_review = {"seed": [], "demo": []}
    containment_time = {"seed": [], "demo": []}
    sla = {"first_review_breaches": 0, "first_review_evaluated": 0, "containment_breaches": 0, "containment_evaluated": 0}
    for inc in incs:
        rep = _dt(inc["reported_at"])
        # which origin produced the first human review event?
        ev = rows(conn, "SELECT * FROM events WHERE incident_id=? AND event_type IN ('human_severity_confirmed','human_override') ORDER BY ts, event_id LIMIT 1", (inc["incident_id"],))
        if ev:
            m = _minutes(rep, _dt(ev[0]["ts"]))
            first_review["seed" if ev[0]["origin"] == "seed" else "demo"].append(m)
            sev = inc["human_severity"]
            t = config.sla_minutes(sev, "first_human_review")
            if t:
                sla["first_review_evaluated"] += 1
                sla["first_review_breaches"] += int(m > t)
        ce = rows(conn, "SELECT * FROM events WHERE incident_id=? AND event_type='containment_approved' ORDER BY ts, event_id LIMIT 1", (inc["incident_id"],))
        if ce:
            m = _minutes(rep, _dt(ce[0]["ts"]))
            containment_time["seed" if ce[0]["origin"] == "seed" else "demo"].append(m)
            sev = inc["human_severity"] or effective_severity(conn, inc)[0]
            t = config.sla_minutes(sev, "containment_or_escalation")
            if t:
                sla["containment_evaluated"] += 1
                sla["containment_breaches"] += int(m > t)

    hold_rows = rows(conn, "SELECT * FROM containment_actions WHERE proposed_source='auto_hold'")
    reviewed = [h for h in hold_rows if h["hold_review_outcome"]]
    lifted = [h for h in reviewed if h["hold_review_outcome"] == "lifted"]
    hold_minutes = [_minutes(_dt(h["proposed_at"]), _dt(h["hold_reviewed_at"])) for h in reviewed]
    auto_hold = {
        "applied": len(hold_rows), "awaiting_review": len(hold_rows) - len(reviewed),
        "awaiting_review_overdue": sum(1 for h in hold_rows if not h["hold_review_outcome"] and _dt(h["review_by"]) <= now),
        "confirmed": len(reviewed) - len(lifted), "lifted": len(lifted),
        "lifted_share_of_reviewed": {"value": len(lifted) / len(reviewed) if reviewed else None,
                                     "numerator": len(lifted), "denominator": len(reviewed)},
        "time_to_human_review": _stats([m for m in hold_minutes if m is not None]),
        "note": "Lifted share is a false-alarm proxy: how often a person judged the automatic pause unnecessary.",
    }

    decisions = rows(conn, "SELECT * FROM events WHERE event_type IN ('human_severity_confirmed','human_override')")
    with_ai = [d for d in decisions if (json.loads(d["details_json"] or "{}").get("ai_recommendation") or {}).get("severity")]
    overrides = [d for d in with_ai if d["event_type"] == "human_override"]
    reasons = Counter(json.loads(d["details_json"])["override_reason_code"] for d in overrides)
    directions = Counter()
    for d in overrides:
        ai = json.loads(d["details_json"])["ai_recommendation"]["severity"]
        hu = json.loads(d["new_value"])["severity"]
        if hu != ai:
            directions["raised" if hu < ai else "lowered"] += 1
        else:
            nv, ai_rec = json.loads(d["new_value"]), json.loads(d["details_json"])["ai_recommendation"]
            directions["route_only" if nv.get("route") != ai_rec.get("route") else "policy_only"] += 1
    policy_changed = 0
    for d in with_ai:
        ai_pol = json.loads(d["details_json"])["ai_recommendation"].get("policy")
        if ai_pol and json.loads(d["new_value"]).get("policy", ai_pol) != ai_pol:
            policy_changed += 1

    cat_counts = Counter()
    for x in q:
        for c in x["categories"]:
            cat_counts[c] += 1
    linked = rows(conn, "SELECT link_type, COUNT(*) n FROM links WHERE status='confirmed' GROUP BY link_type")

    failures = rows(conn, "SELECT error_kind, provider_kind, COUNT(*) n FROM assessments WHERE status='failed' GROUP BY error_kind, provider_kind")
    by_version = rows(conn, """SELECT rule_version, prompt_version, provider_kind, COUNT(*) n,
                               SUM(status='failed') failed, SUM(mandatory_review) flagged FROM assessments
                               GROUP BY rule_version, prompt_version, provider_kind""")
    return {
        "queue_volume_open": len(open_q),
        "queue_by_status": dict(Counter(x["status"] for x in q)),
        "open_age_hours": _stats([x["age_hours"] * 60 for x in open_q]) | {"note": "values in minutes"},
        "overdue_open": sum(1 for x in open_q if x["overdue"]),
        "pending_human_decisions": sum(1 for x in open_q if x["pending"]),
        "time_to_first_human_review": {k: _stats(v) for k, v in first_review.items()},
        "time_to_recorded_simulated_containment": {k: _stats(v) for k, v in containment_time.items()},
        "sla": sla,
        "auto_hold": auto_hold,
        "overrides": {"decisions_with_ai_recommendation": len(with_ai), "overrides": len(overrides),
                      "override_rate": (len(overrides) / len(with_ai)) if with_ai else None,
                      "by_reason": dict(reasons), "by_direction": dict(directions),
                      "policy_changed": policy_changed},
        "category_counts": dict(cat_counts),
        "policy_counts": dict(Counter(x["policy"] for x in q if x["policy"])),
        "confirmed_links": {r["link_type"]: r["n"] for r in linked},
        "assessment_failures": failures,
        "assessments_by_version": by_version,
    }


# ---------------------------------------------------------------------------------------
# Regression gate / quality alerts
# ---------------------------------------------------------------------------------------

GATES = [
    ("P0/P1 recall (after controls)", lambda m: m["after_deterministic_controls"]["p0p1_recall"]["value"], 0.0),
    ("Mandatory review compliance", lambda m: m["mandatory_review"]["compliance_flagged_when_required"]["value"], 0.0),
    ("Severity within acceptable range", lambda m: m["after_deterministic_controls"]["within_acceptable_range"]["value"], 0.05),
    ("Primary route acceptable", lambda m: m["routing"]["primary_route_acceptable"]["value"], 0.05),
    ("Schema-valid rate", lambda m: m["schema_valid_rate"]["value"], 0.0),
    ("C7 auto-pause recall", lambda m: m.get("auto_hold_c7", {}).get("recall", {}).get("value"), 0.0),
]


def regression_check(baseline: dict, candidate: dict) -> dict:
    """Compare two eval summaries on the same split. Any drop in safety-critical metrics
    (P0/P1 recall, review compliance, schema validity) or >5pp drop elsewhere is flagged."""
    if baseline["split"] != candidate["split"]:
        raise ValueError("Compare runs on the same split")
    regressions, improvements = [], []
    for name, fn, tol in GATES:
        b, c = fn(baseline["metrics"]), fn(candidate["metrics"])
        if b is None or c is None:
            continue
        if c < b - tol - 1e-9:
            regressions.append({"metric": name, "baseline": b, "candidate": c})
        elif c > b + 1e-9:
            improvements.append({"metric": name, "baseline": b, "candidate": c})
    bf = {f["incident_id"]: f for f in baseline["failures"]}
    cf = {f["incident_id"]: f for f in candidate["failures"]}
    newly_failing = [cf[i] for i in cf if i not in bf or set(cf[i]["problems"]) - set(bf[i]["problems"])]
    fixed = [bf[i] for i in bf if i not in cf]
    return {"split": baseline["split"], "baseline_run": baseline["run_id"], "candidate_run": candidate["run_id"],
            "regressions": regressions, "improvements": improvements,
            "newly_failing_cases": newly_failing, "fixed_cases": fixed,
            "alert": bool(regressions),
            "label": "Evaluation on SYNTHETIC cases with provisional labels. Not production monitoring or drift."}
