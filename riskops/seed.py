"""Reset and seed the local demo database.

Seeded history uses a frozen clock so events carry historical timestamps. Every seeded
record has origin='seed' so monitoring can separate it from actions taken during a demo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import dedup, workflow as wf
from .config import DEMO_DIR, RESULTS_DIR, db_path
from .db import clock, connect, set_setting
from .providers import FaultInjectionProvider, OfflineProvider
from .schemas import IncidentIntake

A = {a.actor_id: a for a in wf.SIMULATED_ACTORS}
SYS = wf.SYSTEM_ACTOR
S = "seed"


def _intake_actor(channel: str) -> wf.Actor:
    return {"safety_reviewer": A["priya.safety"], "enterprise_report": A["casey.support"],
            "internal_observation": A["alex.riskops"], "telemetry_alert": A["alex.riskops"]}.get(channel, A["casey.support"])


def seed(path: str | None = None, now: datetime | None = None) -> Path:
    p = Path(path) if path else db_path()
    for suffix in ("", "-wal", "-shm", "-journal"):
        f = Path(str(p) + suffix)
        if f.exists():
            os.remove(f)
    conn = connect(p)
    now = now or datetime.now(timezone.utc)
    set_setting(conn, "active_rule_version", "rules-v1.0")
    set_setting(conn, "active_prompt_version", "prompt-v1")
    set_setting(conn, "provider_mode", "offline")
    conn.commit()

    spec = json.loads((DEMO_DIR / "seed_incidents.json").read_text())["incidents"]
    t0: dict[str, datetime] = {}
    offline = OfflineProvider()
    for item in spec:
        start = now - timedelta(minutes=item["minutes_ago"])
        data = dict(item["intake"], reported_at=start.isoformat(timespec="seconds"))
        intake = IncidentIntake.model_validate(data)
        iid = intake.incident_id
        t0[iid] = start
        with clock(start + timedelta(minutes=1)):
            wf.create_incident(conn, intake, _intake_actor(intake.reporter_channel), origin=S, owner=item["owner"])
        if iid == "INC-1010":
            continue  # left in NEW to show an unassessed case
        with clock(start + timedelta(minutes=3)):
            provider = FaultInjectionProvider("timeout") if iid == "INC-1009" else offline
            wf.run_assessment(conn, iid, provider, SYS, origin=S)

    def at(iid, minutes):
        return clock(t0[iid] + timedelta(minutes=minutes))

    # INC-1001: P0 confirmed, containment approved by the Incident Lead, investigating.
    with at("INC-1001", 4):
        a = wf.get_assessment(conn, wf.get_incident(conn, "INC-1001")["current_assessment_id"])
        opt = a["output"]["containment_options"][0]
        ca = wf.propose_containment(conn, "INC-1001", SYS, opt["action_type"], opt["target"], opt["rationale"], source="ai", origin=S)
    with at("INC-1001", 25):
        wf.decide_severity(conn, "INC-1001", A["sam.lead"], "P0", "safety", ["Incident Lead", "Safety", "Legal/Privacy", "Engineering"],
                           reason="Read E1-E3 in full; facilitation offer is explicit in E2.", evidence_reviewed=["E1", "E2", "E3"], origin=S)
    with at("INC-1001", 30):
        wf.decide_containment(conn, ca, A["sam.lead"], True, "Pause transaction tools for this account while Safety and Legal review.", origin=S)
    with at("INC-1001", 35):
        wf.transition(conn, "INC-1001", "INVESTIGATING", A["sam.lead"], "Safety actionability review started", origin=S)
    with at("INC-1001", 70):
        wf.add_note(conn, "INC-1001", "Safety: no order placed per E1; reviewing whether E2 wording was actionable. Legal consulted on obligations.", A["priya.safety"], origin=S)

    # INC-1003: fixture under-calls; analyst overrides with reason; containment approved.
    with at("INC-1003", 180):
        wf.decide_severity(conn, "INC-1003", A["alex.riskops"], "P1", "product_security",
                           ["Incident Lead", "Product Security", "Engineering", "Safety", "Product/UX"],
                           reason="E2 shows hidden page instructions directing the post; this is untrusted-instruction following, not UX confusion.",
                           override_reason_code="evidence_contradicts_ai", evidence_reviewed=["E1", "E2", "E3"], origin=S)
        wf.transition(conn, "INC-1003", "INVESTIGATING", A["alex.riskops"], "Product Security engaged", origin=S)
        ca3 = wf.propose_containment(conn, "INC-1003", A["alex.riskops"], "isolate_untrusted_instructions",
                                     "web content ingestion in the browser extension for this workspace",
                                     "Treat page text as data while Product Security investigates.", origin=S)
    with at("INC-1003", 215):
        wf.decide_containment(conn, ca3, A["sam.lead"], True, "Narrow, reversible control; approve for 24h review.", origin=S)
    with at("INC-1003", 400):
        wf.add_note(conn, "INC-1003", "Engineering: channel post deleted; checking other sessions that visited promo.example.test.", A["lee.eng"], origin=S)

    # INC-1004: P2 approval-fatigue pattern, in response stage with a handoff draft.
    with at("INC-1004", 600):
        wf.decide_severity(conn, "INC-1004", A["alex.riskops"], "P2", "product_ux", ["Product/UX", "Support", "Risk Ops"],
                           reason="Approval-fatigue pattern (E1, E2) belongs with Product/UX, not Engineering.",
                           override_reason_code="routing_ownership", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1004", "INVESTIGATING", A["alex.riskops"], origin=S)
    with at("INC-1004", 2000):
        wf.transition(conn, "INC-1004", "RESPONSE", A["alex.riskops"], "Pattern documented; handing off to Product/UX", origin=S)
        from .communications import generate
        generate(conn, "INC-1004", "handoff", SYS, origin=S)

    # INC-1005: P3 closed with a closure record.
    with at("INC-1005", 300):
        wf.decide_severity(conn, "INC-1005", A["alex.riskops"], "P3", "support", ["Support"], reason="Undo question; no harm. v1.0 rules over-rate any file edit as P2.", override_reason_code="false_positive",
                           evidence_reviewed=["E1"], origin=S)
        wf.transition(conn, "INC-1005", "RESPONSE", A["alex.riskops"], origin=S)
        from .communications import generate
        cid = generate(conn, "INC-1005", "user_ack", A["casey.support"], origin=S)
        wf.review_communication(conn, cid, A["alex.riskops"], True, "Fine to use.", origin=S)
    with at("INC-1005", 400):
        wf.close_incident(conn, "INC-1005", {
            "closure_category": "user_misunderstanding_no_defect", "final_severity": "P3",
            "root_cause": "User did not know about version history.", "user_customer_impact": "None beyond inconvenience.",
            "evidence_reviewed": ["E1"], "teams_involved": ["Support"], "actions_taken": "Undo guidance drafted and approved.",
            "response_status": "Acknowledgment approved (simulated; not sent).", "remaining_mitigation": "None.",
            "monitoring_required": False, "sign_off_statement": "Reviewed ticket; no defect or risk found."}, A["alex.riskops"], origin=S)

    # INC-1006/1007: related reports with different apparent severity; suggestion awaits review.
    for iid in ("INC-1006", "INC-1007"):
        with at(iid, 5):
            target = wf.get_intake(conn, iid)
            others = [wf.get_intake(conn, r["incident_id"]) for r in conn.execute("SELECT incident_id FROM incidents").fetchall()]
            wf.record_link_suggestions(conn, iid, dedup.suggest(target, others))

    # INC-1011: P2 confirmed late (SLA breach on seeded history).
    with at("INC-1011", 2000):
        wf.decide_severity(conn, "INC-1011", A["alex.riskops"], "P2", "product_engineering", ["Engineering", "Support"],
                           reason="Telemetry E1 confirms regression.", evidence_reviewed=["E1"], origin=S)
        wf.transition(conn, "INC-1011", "INVESTIGATING", A["alex.riskops"], origin=S)

    # INC-1012: P2 closed and QA-reviewed.
    with at("INC-1012", 700):
        wf.decide_severity(conn, "INC-1012", A["alex.riskops"], "P2", "product_engineering", ["Engineering", "Product/UX", "Support"],
                           reason="Recurring pattern confirmed by E1/E2.", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1012", "INVESTIGATING", A["alex.riskops"], origin=S)
        wf.transition(conn, "INC-1012", "RESPONSE", A["alex.riskops"], origin=S)
    with at("INC-1012", 3000):
        wf.close_incident(conn, "INC-1012", {
            "closure_category": "product_defect", "final_severity": "P2",
            "root_cause": "Formatter applied to whole file on single-function edits.", "user_customer_impact": "Noisy diffs; reverts needed.",
            "evidence_reviewed": ["E1", "E2"], "teams_involved": ["Engineering", "Product/UX", "Support"],
            "actions_taken": "Bug filed; support macro updated.", "response_status": "Macro approved (simulated).",
            "remaining_mitigation": "Fix scheduled in next release.", "monitoring_required": True,
            "sign_off_statement": "Evidence reviewed; defect confirmed and routed."}, A["alex.riskops"], origin=S)
    with at("INC-1012", 5000):
        wf.qa_review(conn, "INC-1012", A["sam.lead"], "agree_with_handling", "Sampled P2 closure; severity and routing appropriate.", origin=S)

    # Import evaluation runs already on disk so the Quality page shows actual artifacts.
    for d in sorted(RESULTS_DIR.glob("*/summary.json")):
        s = json.loads(d.read_text())
        s["artifact_dir"] = str(d.parent)
        wf.record_eval_run(conn, s, origin="cli")
    conn.commit()
    conn.close()
    return p


if __name__ == "__main__":
    print(seed())
