"""Reset and seed the local demo database.

Seeded history uses a frozen clock so events carry historical timestamps. Every seeded
record has origin='seed' so monitoring can separate it from actions taken during a demo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, dedup, workflow as wf
from .config import DEMO_DIR, RESULTS_DIR, db_path
from .db import clock, connect, set_setting
from .providers import FaultInjectionProvider, OfflineProvider
from .schemas import IncidentIntake

# Bump when seeded data or the schema changes incompatibly; older local databases are rebuilt.
DEMO_DATA_VERSION = "demo-v3-policies"
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
    set_setting(conn, "active_rule_version", config.BASELINE_RULE_VERSION)
    set_setting(conn, "active_prompt_version", "prompt-v3")
    set_setting(conn, "provider_mode", "offline")
    set_setting(conn, "demo_data_version", DEMO_DATA_VERSION)
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

    def pending_ai_option(iid, action_type):
        acts = wf.get_assessment(conn, wf.get_incident(conn, iid)["current_assessment_id"])
        return next(o for o in acts["output"]["containment_options"] if o["action_type"] == action_type)

    # INC-1001: P0 CBRN. C7 paused the session automatically at assessment; Safety confirmed the
    # pause, the Incident Lead confirmed P0 and approved a classifier block; now investigating.
    hold = conn.execute("SELECT action_id FROM containment_actions WHERE incident_id='INC-1001' AND proposed_source='auto_hold'").fetchone()[0]
    with at("INC-1001", 12):
        wf.review_auto_hold(conn, hold, A["priya.safety"], True, "Specialist verdict E1 confirmed; keep the session paused.", origin=S)
    with at("INC-1001", 20):
        wf.decide_severity(conn, "INC-1001", A["sam.lead"], "P0", "safety", ["Incident Lead", "Safety", "Legal/Privacy", "Engineering"],
                           reason="Specialist verdict (E1) and classifier record (E2) agree; restricted content reviewed by Safety.",
                           evidence_reviewed=["E1", "E2", "E3"], origin=S)
        opt = pending_ai_option("INC-1001", "deploy_classifier_block")
        ca = wf.propose_containment(conn, "INC-1001", SYS, opt["action_type"], opt["target"], opt["rationale"], source="ai", origin=S)
    with at("INC-1001", 30):
        wf.decide_containment(conn, ca, A["sam.lead"], True, "Narrow block on the request pattern while the threshold is reviewed.", origin=S)
    with at("INC-1001", 35):
        wf.transition(conn, "INC-1001", "INVESTIGATING", A["sam.lead"], "Safety reviewing other sessions from the account", origin=S)
    with at("INC-1001", 70):
        wf.add_note(conn, "INC-1001", "Safety: no other sessions from this account in the last 30 days. Engineering reviewing the blocking threshold.",
                    A["priya.safety"], origin=S)

    # INC-1002: P0 child safety, 25 minutes old. C7 paused the session; nobody has confirmed or
    # lifted it yet, so it sits at the top of the queue (left open for the demo).

    # INC-1004: fixture under-calls an injection exfiltration as an agent mis-send (P2); C3 raised it
    # to P0 and C6 kept the rules' specialist route (Legal/Privacy). The analyst confirmed P0 and
    # re-routed to Product Security (override: routing) and the policy corrected to prompt injection; the lead approved key rotation.
    with at("INC-1004", 40):
        wf.decide_severity(conn, "INC-1004", A["alex.riskops"], "P0", "product_security",
                           ["Incident Lead", "Product Security", "Engineering", "Legal/Privacy"],
                           reason="E2 shows hidden instructions in the newsletter drove the send; injection-driven exfiltration is owned by Product Security, with Legal/Privacy involved.",
                           override_reason_code="routing_ownership", evidence_reviewed=["E1", "E2", "E3"], origin=S,
                           policy="prompt_injection", other_policies=["enterprise_data_leakage", "model_security"])
        wf.transition(conn, "INC-1004", "INVESTIGATING", A["alex.riskops"], "Product Security engaged", origin=S)
        rot = wf.propose_containment(conn, "INC-1004", A["alex.riskops"], "rotate_credentials", "the two exposed production API keys",
                                     "Keys were used from an unknown IP; they must be rotated.", origin=S)
        iso = wf.propose_containment(conn, "INC-1004", A["alex.riskops"], "isolate_untrusted_instructions",
                                     "email content ingestion for this workspace", "Treat newsletter text as data while Product Security investigates.", origin=S)
    with at("INC-1004", 55):
        wf.decide_containment(conn, rot, A["sam.lead"], True, "Keys confirmed used externally (E3); rotate both now, customer informed via their admin.", origin=S)
        wf.decide_containment(conn, iso, A["sam.lead"], True, "Narrow, reversible control; approve for 24h review.", origin=S)
    with at("INC-1004", 300):
        wf.add_note(conn, "INC-1004", "Engineering: newsletter sender blocked; checking other workspaces that received it.", A["lee.eng"], origin=S)

    # INC-1005: P1 cyber, investigating.
    with at("INC-1005", 120):
        wf.decide_severity(conn, "INC-1005", A["alex.riskops"], "P1", "safety", ["Incident Lead", "Safety", "Threat Intel", "Product Security"],
                           reason="Reviewer confirmed functional malware (E1); no evidence of deployment yet.", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1005", "INVESTIGATING", A["alex.riskops"], "Threat Intel checking for related accounts", origin=S)

    # INC-1006: P1 influence operation; rate limit approved; in response with a handoff draft.
    with at("INC-1006", 180):
        wf.decide_severity(conn, "INC-1006", A["alex.riskops"], "P1", "threat_intel", ["Incident Lead", "Threat Intel", "Safety", "Legal/Privacy"],
                           reason="Coordination confirmed by shared payment instrument and templates (E1, E2).", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1006", "INVESTIGATING", A["alex.riskops"], origin=S)
        opt = pending_ai_option("INC-1006", "rate_limit_accounts")
        rl = wf.propose_containment(conn, "INC-1006", SYS, opt["action_type"], opt["target"], opt["rationale"], source="ai", origin=S)
    with at("INC-1006", 200):
        wf.decide_containment(conn, rl, A["sam.lead"], True, "Rate-limit the cluster while Threat Intel prepares takedown.", origin=S)
    with at("INC-1006", 1500):
        wf.transition(conn, "INC-1006", "RESPONSE", A["alex.riskops"], "Takedown plan ready; handing off", origin=S)
        from .communications import generate
        generate(conn, "INC-1006", "handoff", SYS, origin=S)

    # INC-1007: P1 self-harm; in response; the user acknowledgment draft awaits Safety review.
    with at("INC-1007", 45):
        wf.decide_severity(conn, "INC-1007", A["alex.riskops"], "P1", "safety", ["Incident Lead", "Safety", "Support"],
                           reason="Specialist verdict E1: policy violation toward an at-risk user; welfare follow-up needed.",
                           evidence_reviewed=["E1", "E2", "E3"], origin=S)
        wf.transition(conn, "INC-1007", "RESPONSE", A["alex.riskops"], "Welfare follow-up and model fix tracked separately", origin=S)
        from .communications import generate
        generate(conn, "INC-1007", "user_ack", A["casey.support"], origin=S)

    # INC-1009: AI assessment timed out (fault test) -> manual review; awaiting a person.

    # INC-1011: P2 confirmed late (SLA breach on seeded history).
    with at("INC-1011", 2000):
        wf.decide_severity(conn, "INC-1011", A["alex.riskops"], "P2", "model_behavior", ["Model Behavior", "Engineering", "Support"],
                           reason="Audit E1 confirms a dosage unit-conversion regression affecting several users; rules missed the medical context.",
                           override_reason_code="under_escalation", evidence_reviewed=["E1", "E2"], origin=S,
                           policy="harmful_inaccuracy")
        wf.transition(conn, "INC-1011", "INVESTIGATING", A["alex.riskops"], origin=S)

    # INC-1012: P2 bias finding, closed and QA-reviewed.
    with at("INC-1012", 700):
        wf.decide_severity(conn, "INC-1012", A["alex.riskops"], "P2", "model_behavior", ["Model Behavior", "Legal/Privacy", "Enterprise/CS"],
                           reason="Paired-resume audit E2 confirms the pattern.", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1012", "INVESTIGATING", A["alex.riskops"], origin=S)
        wf.transition(conn, "INC-1012", "RESPONSE", A["alex.riskops"], origin=S)
    with at("INC-1012", 5000):
        wf.close_incident(conn, "INC-1012", {
            "closure_category": "model_behavior_issue", "final_severity": "P2",
            "root_cause": "Ranking prompt template let name-based signals influence scores.",
            "user_customer_impact": "Unfair candidate rankings for one enterprise customer over two weeks.",
            "evidence_reviewed": ["E1", "E2"], "teams_involved": ["Model Behavior", "Legal/Privacy", "Enterprise/CS"],
            "actions_taken": "Names removed from ranking inputs; customer advised to re-run affected screens.",
            "response_status": "Customer update approved (simulated; not sent).", "remaining_mitigation": "Fairness eval added to release checks.",
            "monitoring_required": True, "sign_off_statement": "Evidence reviewed; issue confirmed, mitigated and routed."}, A["alex.riskops"], origin=S)
    with at("INC-1012", 7000):
        wf.qa_review(conn, "INC-1012", A["sam.lead"], "agree_with_handling", "Sampled P2 closure; severity and routing appropriate.", origin=S)

    # INC-1013: P2 over-refusal appeal; in response.
    with at("INC-1013", 600):
        wf.decide_severity(conn, "INC-1013", A["alex.riskops"], "P2", "risk_ops", ["Risk Ops", "Model Behavior", "Enterprise/CS"],
                           reason="This is an appeal about refusals (E1), not a cyber-misuse case; Risk Ops owns policy exceptions.",
                           override_reason_code="routing_ownership", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1013", "RESPONSE", A["alex.riskops"], "Policy exception review requested", origin=S)

    # INC-1014: P3 classifier false positive, closed.
    with at("INC-1014", 300):
        wf.decide_severity(conn, "INC-1014", A["alex.riskops"], "P3", "safety", ["Safety"],
                           reason="Specialist found no violation (E1): homework at textbook level.", evidence_reviewed=["E1", "E2"], origin=S)
        wf.transition(conn, "INC-1014", "RESPONSE", A["alex.riskops"], origin=S)
    with at("INC-1014", 400):
        wf.close_incident(conn, "INC-1014", {
            "closure_category": "classifier_false_positive", "final_severity": "P3",
            "root_cause": "Classifier over-triggers on school chemistry vocabulary.", "user_customer_impact": "None.",
            "evidence_reviewed": ["E1", "E2"], "teams_involved": ["Safety"], "actions_taken": "Added to the classifier false-positive set.",
            "response_status": "No user contact needed.", "remaining_mitigation": "None.",
            "monitoring_required": False, "sign_off_statement": "Specialist verdict reviewed; no violation."}, A["alex.riskops"], origin=S)

    # INC-1015 looks like INC-1004 (same newsletter sender); the suggestion awaits review.
    with at("INC-1015", 5):
        target = wf.get_intake(conn, "INC-1015")
        others = [wf.get_intake(conn, r["incident_id"]) for r in conn.execute("SELECT incident_id FROM incidents").fetchall()]
        wf.record_link_suggestions(conn, "INC-1015", dedup.suggest(target, others))

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
