"""Jev shadow mode (Phase 1).

Runs the versioned Jev questions (config/jev_questions.json) on a case and records the answers.
Shadow results never influence anything: the rules, the workflow and the AI assessment do not
import this module or read the ``shadow_results`` table (tests/test_jev_shadow.py enforces it).
Only the admin-only shadow views and the evaluation command read them.

Derived views of the raw answers:
  * policy ranking   - variant A: the 19-option choice (a probability distribution); variant B:
                       independent yes-probabilities of the five severe areas, then the 14-option
                       choice scaled by (1 - largest severe yes). B's scores are a ranking, not a
                       distribution, and need not sum to 1.
  * severity A       - Jev's direct P3..P0 score
  * severity B       - the existing rules engine run on the case with the six severity factors
                       replaced by Jev's answers (factor questions see a state without those fields)
"""

from __future__ import annotations

import json
import uuid
from functools import lru_cache

from . import policies, rules
from .config import CONFIG_DIR
from .db import now_iso
from .providers.jev import JevClient, JevResult
from .schemas import IncidentIntake

SEVERITY_LEVELS = ["P3", "P2", "P1", "P0"]


@lru_cache(maxsize=1)
def question_config() -> dict:
    return json.loads((CONFIG_DIR / "jev_questions.json").read_text())


def code_to_key() -> dict[str, str]:
    return {p["code"]: p["key"] for p in policies.all_policies()}


def build_state(intake: IncidentIntake, masked: bool = False) -> dict:
    """What Jev reads. ``masked`` drops the structured severity-factor fields so the factor
    questions have to recover them from the text (hide-and-recover)."""
    data = intake.model_dump(mode="json")
    keep = ["title", "reported_behavior", "reported_impact", "product_surface", "customer_type", "reporter_channel",
            "model_version"]
    if not masked:
        keep += list(question_config()["factor_fields"].values()) + ["file_action"]
    state = {k: data[k] for k in keep}
    state["evidence"] = [{"type": e["source_type"], "source": e["source_description"], "content": e["content"]}
                         for e in data["evidence"]]
    return state


def questions_for(intake: IncidentIntake, variant: str) -> tuple[dict, dict]:
    """(questions on the full state, questions on the masked state) for this case."""
    cfg = question_config()
    full, masked = {}, {}
    for name in cfg["variants"][variant]:
        q = cfg["questions"][name]
        if q["runs_on"] == "free_text_channels" and intake.reporter_channel in cfg["deterministic_case_type"]:
            continue
        if q["runs_on"] == "claims" and intake.reporter_channel == "telemetry_alert":
            continue
        (masked if q.get("state") == "masked" else full)[name] = q
    return full, masked


def run_case(intake: IncidentIntake, variant: str, client: JevClient | None = None,
             rule_version: str = "rules-v2.1") -> dict:
    """Ask Jev every question for this case (two requests: full state, masked state)."""
    client = client or JevClient()
    full_q, masked_q = questions_for(intake, variant)
    parts: list[JevResult] = [client.ask(build_state(intake), full_q)]
    if masked_q:
        parts.append(client.ask(build_state(intake, masked=True), masked_q))
    answers, errors = {}, []
    for p in parts:
        answers.update({k: vars(v) for k, v in p.answers.items()})
        if p.error_kind:
            errors.append({"kind": p.error_kind, "error": p.error, "raw": p.raw})
    out = {
        "incident_id": intake.incident_id, "variant": variant,
        "question_version": question_config()["version"], "model": parts[0].model,
        "answers": answers, "errors": errors,
        "latency_ms": sum(p.latency_ms or 0 for p in parts),
        "input_tokens": sum(p.input_tokens or 0 for p in parts) if any(p.input_tokens for p in parts) else None,
        "cost_usd": sum(p.cost_usd or 0 for p in parts) if any(p.cost_usd for p in parts) else None,
    }
    if not errors:
        out.update(derive(intake, answers, variant, rule_version))
    return out


def derive(intake: IncidentIntake, answers: dict, variant: str, rule_version: str = "rules-v2.1") -> dict:
    cfg = question_config()
    c2k = code_to_key()
    if variant == "A":
        probs = dict(answers["policy_a"]["probabilities"]) or {answers["policy_a"]["answer"]: 1.0}
    else:
        sev = {c: answers[f"severe_{c}"]["probabilities"].get("yes", 1.0 if answers[f"severe_{c}"]["answer"] == "yes" else 0.0)
               for c in cfg["severe_codes"]}
        rest = dict(answers["policy_b_other"]["probabilities"]) or {answers["policy_b_other"]["answer"]: 1.0}
        scale = 1 - max(sev.values())
        probs = sev | {c: p * scale for c, p in rest.items()}
    ranking = sorted(probs.items(), key=lambda kv: -kv[1])
    out = {"policy_probs": {c2k.get(c, c): round(p, 4) for c, p in ranking},
           "policy_ranking": [c2k.get(c, c) for c, _ in ranking]}

    sd = answers.get("severity_direct")
    if sd:
        out["severity_a"] = sd["answer"]
        out["severity_a_probs"] = sd["probabilities"]

    fields = cfg["factor_fields"]
    if all(q in answers for q in fields):
        recovered = {f: answers[q]["answer"] for q, f in fields.items()}
        shadow_intake = intake.model_copy(update=recovered)
        out["factors"] = recovered
        out["severity_b"] = rules.evaluate(shadow_intake, rule_version).severity
    for k in ("case_type", "harm_outcome", "evidence_support"):
        if k in answers:
            out[k] = answers[k]["answer"]
    if intake.reporter_channel in cfg["deterministic_case_type"]:
        out["case_type"] = cfg["deterministic_case_type"][intake.reporter_channel]
    return out


def record(conn, result: dict) -> str:
    sid = f"SH-{uuid.uuid4().hex[:10]}"
    err = result["errors"][0] if result["errors"] else {}
    conn.execute(
        "INSERT INTO shadow_results(shadow_id, incident_id, created_at, provider, model, question_version, variant,"
        " result_json, latency_ms, input_tokens, cost_usd, error_kind, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, result["incident_id"], now_iso(), "jev", result.get("model"), result["question_version"], result["variant"],
         json.dumps(result), result.get("latency_ms"), result.get("input_tokens"), result.get("cost_usd"),
         err.get("kind"), err.get("error")))
    conn.commit()
    return sid


def results_for(conn, incident_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM shadow_results WHERE incident_id=? ORDER BY created_at DESC", (incident_id,)).fetchall()
    return [dict(r) | {"result": json.loads(r["result_json"]) if r["result_json"] else None} for r in rows]
