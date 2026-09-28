"""Repeatable evaluation harness.

Separation of inputs and labels: ``load_cases`` reads only ``cases.jsonl``. Labels are read by
``load_labels`` inside the scorer, after predictions have been produced. The assessment
pipeline has no access to labels.

Systems:
  rules          - rules-only baseline (deterministic; the offline simulation restates rules output)
  live           - AI-assisted pipeline with the live Anthropic provider (requires ANTHROPIC_API_KEY;
                   refuses to run otherwise - never falls back to offline results)
  fault:<mode>   - deliberately injected faults to test safeguards (not model findings)

Every metric carries its numerator and denominator. Undefined metrics are reported as
``null`` with a reason instead of 0 or 1.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .assessment import CONTROLS_VERSION, assess_incident
from .providers import AnthropicProvider, FaultInjectionProvider, OfflineSimulationProvider
from .rules import load_rules
from .schemas import SEVERITIES, IncidentIntake

HIGH = {"P0", "P1"}


class LiveEvaluationUnavailable(RuntimeError):
    pass


def load_splits() -> dict:
    return json.loads((config.EVAL_DIR / "splits.json").read_text())


def load_cases(split: str = "dev") -> list[IncidentIntake]:
    splits = load_splits()
    ids = set(splits["dev"] + splits["held_out"]) if split == "all" else set(splits[split])
    out = []
    for line in (config.EVAL_DIR / "cases.jsonl").read_text().splitlines():
        if line.strip():
            c = IncidentIntake.model_validate_json(line)
            if c.incident_id in ids:
                out.append(c)
    return out


def load_labels() -> dict[str, dict]:
    labels = {}
    for line in (config.EVAL_DIR / "labels.jsonl").read_text().splitlines():
        if line.strip():
            lab = json.loads(line)
            labels[lab["incident_id"]] = lab
    return labels


def held_out_integrity() -> dict:
    freeze = json.loads((config.EVAL_DIR / "FREEZE.json").read_text())
    ho = set(freeze["held_out_case_ids"])
    cases = [l for l in (config.EVAL_DIR / "cases.jsonl").read_text().splitlines(keepends=True) if json.loads(l)["incident_id"] in ho]
    labs = [l for l in (config.EVAL_DIR / "labels.jsonl").read_text().splitlines(keepends=True) if json.loads(l)["incident_id"] in ho]
    h = hashlib.sha256(("".join(cases) + "".join(labs)).encode()).hexdigest()
    return {"matches_freeze": h == freeze["sha256_cases_and_labels"], "status": freeze["status"],
            "frozen_at": freeze["frozen_at"], "disclosures": freeze.get("disclosures", [])}


def _provider(system: str):
    if system == "rules":
        return OfflineSimulationProvider()
    if system == "live":
        if not config.live_credentials_available():
            raise LiveEvaluationUnavailable(
                "Live evaluation requires ANTHROPIC_API_KEY. Nothing was run and no offline results were substituted.\n"
                "Run later with:\n  export ANTHROPIC_API_KEY=...\n"
                "  python -m riskops.cli eval --system live --rules rules-v1.1 --prompt prompt-v2 --split dev")
        return AnthropicProvider()
    if system.startswith("fault:"):
        return FaultInjectionProvider(system.split(":", 1)[1])
    raise ValueError(system)


def ratio(num: int, den: int, why_undefined: str = "") -> dict:
    return {"value": (num / den) if den else None, "numerator": num, "denominator": den,
            **({} if den else {"undefined_reason": why_undefined or "denominator is 0"})}


def _severity_metrics(preds: list[dict], key: str) -> dict:
    if not preds:
        why = "no schema-valid provider assessments in this run"
        return {k: ratio(0, 0, why) for k in ("exact_match", "within_acceptable_range", "p0p1_precision", "p0p1_recall")} | {
            "p0p1_missed_where_all_acceptable_tiers_are_p0p1": None, "under_severity_outside_range": None,
            "over_severity_outside_range": None, "confusion_matrix_expected_rows_predicted_cols":
            {e: {p: 0 for p in SEVERITIES + ["none"]} for e in SEVERITIES}}
    labels = [p["label"] for p in preds]
    pred = [p[key] for p in preds]
    n = len(preds)
    exact = sum(1 for p, l in zip(pred, labels) if p == l["expected_severity"])
    acceptable = sum(1 for p, l in zip(pred, labels) if p in l["acceptable_severities"])
    tp = sum(1 for p, l in zip(pred, labels) if p in HIGH and l["expected_severity"] in HIGH)
    fp = sum(1 for p, l in zip(pred, labels) if p in HIGH and l["expected_severity"] not in HIGH)
    fn = sum(1 for p, l in zip(pred, labels) if p not in HIGH and l["expected_severity"] in HIGH)
    # acceptable-aware: a miss only if no acceptable tier is P2/P3-compatible with the prediction
    fn_strict_accept = sum(1 for p, l in zip(pred, labels) if p not in HIGH and all(s in HIGH for s in l["acceptable_severities"]))
    under = sum(1 for p, l in zip(pred, labels) if p is not None and p not in l["acceptable_severities"] and
                min(l["acceptable_severities"]) < p)  # 'P0' < 'P3' lexically == more severe
    over = sum(1 for p, l in zip(pred, labels) if p is not None and p not in l["acceptable_severities"] and
               max(l["acceptable_severities"]) > p)
    matrix = {e: {p: 0 for p in SEVERITIES + ["none"]} for e in SEVERITIES}
    for p, l in zip(pred, labels):
        matrix[l["expected_severity"]][p or "none"] += 1
    return {
        "exact_match": ratio(exact, n),
        "within_acceptable_range": ratio(acceptable, n),
        "p0p1_precision": ratio(tp, tp + fp, "no case predicted P0/P1"),
        "p0p1_recall": ratio(tp, tp + fn, "no case labeled P0/P1"),
        "p0p1_missed_where_all_acceptable_tiers_are_p0p1": fn_strict_accept,
        "under_severity_outside_range": under,
        "over_severity_outside_range": over,
        "confusion_matrix_expected_rows_predicted_cols": matrix,
    }


def score(preds: list[dict]) -> dict:
    n = len(preds)
    valid = [p for p in preds if p["status"] == "valid"]
    failed = [p for p in preds if p["status"] == "failed"]
    total_facts = sum(len(p["fact_ref_status"]) for p in valid)
    bad_facts = sum(1 for p in valid for f in p["fact_ref_status"] if f["invalid_refs"])
    mand = [p for p in preds if p["label"]["requires_mandatory_review"]]
    not_mand = [p for p in preds if not p["label"]["requires_mandatory_review"]]
    lat = [p["latency_ms"] for p in preds if p["latency_ms"] is not None]
    costs = [p["cost_usd"] for p in preds if p["cost_usd"] is not None]

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in preds:
        by_cat[p["label"]["scenario_family"].split("-")[1]].append(p)
    categories = {}
    for cat, ps in sorted(by_cat.items()):
        categories[cat] = {
            "n": len(ps),
            "severity_within_range_after_controls": ratio(sum(1 for p in ps if p["controlled_severity"] in p["label"]["acceptable_severities"]), len(ps)),
            "route_acceptable_after_controls": ratio(sum(1 for p in ps if p["controlled_route"] in p["label"]["acceptable_routes"]), len(ps)),
            "mandatory_review_flagged_when_required": ratio(
                sum(1 for p in ps if p["label"]["requires_mandatory_review"] and p["mandatory_review"]),
                sum(1 for p in ps if p["label"]["requires_mandatory_review"]), "no case in category requires mandatory review"),
        }

    return {
        "n_cases": n,
        "recommendation_before_controls": _severity_metrics(valid, "model_severity") | {
            "note": "Provider recommendation on schema-valid assessments only (denominator = valid assessments)."},
        "after_deterministic_controls": _severity_metrics(preds, "controlled_severity") | {
            "note": "Recommendation after controls, all cases (failed assessments use the rules recommendation, labeled)."},
        "routing": {
            "primary_route_exact": ratio(sum(1 for p in preds if p["controlled_route"] == p["label"]["expected_route"]), n),
            "primary_route_acceptable": ratio(sum(1 for p in preds if p["controlled_route"] in p["label"]["acceptable_routes"]), n),
        },
        "mandatory_review": {
            "compliance_flagged_when_required": ratio(sum(1 for p in mand if p["mandatory_review"]), len(mand), "no case requires mandatory review"),
            "flagged_when_not_required": ratio(sum(1 for p in not_mand if p["mandatory_review"]), len(not_mand), "every case requires review"),
        },
        "schema_valid_rate": ratio(len(valid), n),
        "assessment_failures_routed_to_manual_review": ratio(sum(1 for p in failed if p["mandatory_review"]), len(failed), "no failures"),
        "invalid_evidence_reference_rate_by_fact": ratio(bad_facts, total_facts, "no facts produced"),
        "assessments_with_any_invalid_reference": ratio(sum(1 for p in valid if p["invalid_evidence_refs"]), len(valid), "no valid assessments"),
        "claim_support_accuracy": {"value": None, "undefined_reason": "No human claim-support reviews recorded for this run (see claim_review_worksheet.csv).", "reviewed": 0},
        "latency_ms": {"mean": statistics.mean(lat) if lat else None, "p95": (sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else None), "n": len(lat)},
        "cost_usd_estimate": {"total": sum(costs) if costs else None, "n_with_cost": len(costs)},
        "by_category": categories,
    }


def run_eval(system: str = "rules", rule_version: str = "rules-v1.0", prompt_version: str = "prompt-v1",
             split: str = "dev", label: str | None = None, write: bool = True, out_dir: Path | None = None) -> dict:
    provider = _provider(system)
    cases = load_cases(split)
    preds = []
    for case in cases:
        rec = assess_incident(case, provider, rule_version, prompt_version)
        preds.append({k: rec[k] for k in (
            "incident_id", "status", "error_kind", "provider_kind", "provider_name", "model_name", "model_severity",
            "rules_severity", "controlled_severity", "controlled_route", "mandatory_review", "review_reasons",
            "invalid_evidence_refs", "fact_ref_status", "latency_ms", "cost_usd", "impact", "evidence_quality",
            "confidence")} | {"triggered_rules": [t["id"] for t in rec["rule_result"]["triggered_rules"]],
                              "facts": (rec["output"] or {}).get("reported_facts", [])})
    # Labels are joined only now, after all predictions exist.
    labels = load_labels()
    for p in preds:
        p["label"] = labels[p["incident_id"]]
    metrics = score(preds)

    kind = {"rules": "rules_only_baseline", "live": "live_model"}.get(system, "fault_injection")
    if "FAULT" in load_rules(rule_version).get("status", ""):
        kind = "fault_injection"  # a deliberately broken rule set is a fault-injection test, not a baseline
    tag = system.replace(":", "-")
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{kind}-{tag}-{rule_version}-{split}-{uuid.uuid4().hex[:4]}"
    failures = [
        {"incident_id": p["incident_id"], "family": p["label"]["scenario_family"],
         "expected": p["label"]["expected_severity"], "acceptable": p["label"]["acceptable_severities"],
         "model_or_rules": p["model_severity"], "after_controls": p["controlled_severity"],
         "route": p["controlled_route"], "acceptable_routes": p["label"]["acceptable_routes"],
         "review_required": p["label"]["requires_mandatory_review"], "review_flagged": p["mandatory_review"],
         "triggered_rules": p["triggered_rules"], "status": p["status"], "error_kind": p["error_kind"],
         "problems": [x for x, bad in [
             ("severity_outside_range", p["controlled_severity"] not in p["label"]["acceptable_severities"]),
             ("route_not_acceptable", p["controlled_route"] not in p["label"]["acceptable_routes"]),
             ("missed_mandatory_review", p["label"]["requires_mandatory_review"] and not p["mandatory_review"]),
             ("assessment_failed", p["status"] == "failed")] if bad]}
        for p in preds]
    failures = [f for f in failures if f["problems"]]
    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label or f"{kind} {rule_version} {prompt_version if system == 'live' else ''} on {split}".replace("  ", " "),
        "evaluation_kind": kind,
        "system": system,
        "rule_version": rule_version,
        "prompt_version": prompt_version if system == "live" else None,
        "controls_version": CONTROLS_VERSION,
        "model_name": config.live_model_name() if system == "live" else None,
        "split": split,
        "held_out_integrity": held_out_integrity(),
        "labels_disclaimer": "Labels are provisional author-generated judgments on synthetic cases, not independently validated ground truth.",
        "interpretation": {
            "rules_only_baseline": "Deterministic rules; says nothing about model quality.",
            "fault_injection": "Deliberately injected faults to test safeguards; not observations about any model.",
            "live_model": "Live model outputs, scored against provisional labels.",
        }[kind],
        "metrics": metrics,
        "failures": failures,
    }
    if write:
        d = (out_dir or config.RESULTS_DIR) / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        with open(d / "predictions.jsonl", "w") as f:
            for p in preds:
                f.write(json.dumps({k: v for k, v in p.items() if k != "label"}, default=str) + "\n")
        (d / "report.md").write_text(render_report(summary))
        write_claim_worksheet(preds, d / "claim_review_worksheet.csv")
        summary["artifact_dir"] = str(d)
    return summary


def write_claim_worksheet(preds: list[dict], path: Path) -> None:
    """Blank worksheet for human claim-support review. Verdict column intentionally empty."""
    cases = {c.incident_id: c for c in load_cases("all")}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["incident_id", "fact_index", "statement", "cited_evidence_ids", "cited_evidence_text",
                    "verdict(supported|partially_supported|unsupported|cannot_determine)", "reviewer", "note"])
        for p in preds:
            ev = {e.evidence_id: e.content for e in cases[p["incident_id"]].evidence}
            for i, fact in enumerate(p["facts"]):
                w.writerow([p["incident_id"], i, fact["statement"], " ".join(fact["evidence_ids"]),
                            " | ".join(ev.get(r, "<MISSING>") for r in fact["evidence_ids"]), "", "", ""])


def summarize_claim_worksheet(path: Path) -> dict:
    """Report claim-support accuracy from a filled worksheet; only rows with a verdict count."""
    verdicts = Counter()
    with open(path) as f:
        for r in csv.DictReader(f):
            v = (r.get("verdict(supported|partially_supported|unsupported|cannot_determine)") or "").strip()
            if v:
                verdicts[v] += 1
    reviewed = sum(verdicts.values())
    return {"reviewed": reviewed, "verdicts": dict(verdicts),
            "supported_rate": ratio(verdicts["supported"], reviewed, "no reviewed rows")}


def _fmt(m: dict) -> str:
    if m.get("value") is None:
        return f"undefined ({m.get('undefined_reason', '')}; {m['numerator']}/{m['denominator']})"
    return f"{m['value']:.1%} ({m['numerator']}/{m['denominator']})"


def render_report(s: dict) -> str:
    m = s["metrics"]
    a, b = m["after_deterministic_controls"], m["recommendation_before_controls"]
    lines = [
        f"# Evaluation run {s['run_id']}", "",
        f"* Kind: **{s['evaluation_kind']}** — {s['interpretation']}",
        f"* Rule version: `{s['rule_version']}`; controls: `{s.get('controls_version')}`; prompt: `{s['prompt_version']}`; model: `{s['model_name']}`",
        f"* Split: `{s['split']}`; cases: {m['n_cases']}",
        f"* Held-out integrity: matches freeze = {s['held_out_integrity']['matches_freeze']}, status = {s['held_out_integrity']['status']}",
        f"* {s['labels_disclaimer']}", "",
        "## Severity", "",
        "| Metric | Before controls (valid assessments) | After deterministic controls (all cases) |",
        "| --- | --- | --- |",
    ]
    for k in ("exact_match", "within_acceptable_range", "p0p1_precision", "p0p1_recall"):
        lines.append(f"| {k} | {_fmt(b[k])} | {_fmt(a[k])} |")
    lines += [f"| under-severity outside range (count) | {b['under_severity_outside_range']} | {a['under_severity_outside_range']} |",
              f"| over-severity outside range (count) | {b['over_severity_outside_range']} | {a['over_severity_outside_range']} |",
              "", "### Confusion matrix after controls (rows = expected, cols = predicted)", "",
              "| expected \\ predicted | P0 | P1 | P2 | P3 | none |", "| --- | --- | --- | --- | --- | --- |"]
    for e, row in a["confusion_matrix_expected_rows_predicted_cols"].items():
        lines.append(f"| {e} | " + " | ".join(str(row[c]) for c in ["P0", "P1", "P2", "P3", "none"]) + " |")
    lines += ["", "## Routing, review and schema", "",
              f"* Primary route exact: {_fmt(m['routing']['primary_route_exact'])}",
              f"* Primary route within acceptable routes: {_fmt(m['routing']['primary_route_acceptable'])}",
              f"* Mandatory review flagged when required: {_fmt(m['mandatory_review']['compliance_flagged_when_required'])}",
              f"* Review flagged when not required (over-flagging): {_fmt(m['mandatory_review']['flagged_when_not_required'])}",
              f"* Schema-valid assessments: {_fmt(m['schema_valid_rate'])}",
              f"* Failed assessments routed to manual review: {_fmt(m['assessment_failures_routed_to_manual_review'])}",
              f"* Facts with invalid evidence references: {_fmt(m['invalid_evidence_reference_rate_by_fact'])}",
              f"* Claim-support accuracy: not reported — {m['claim_support_accuracy']['undefined_reason']}",
              f"* Latency ms (mean / p95, n): {m['latency_ms']['mean']} / {m['latency_ms']['p95']} (n={m['latency_ms']['n']})",
              f"* Estimated cost USD: {m['cost_usd_estimate']['total']}", "",
              "## By scenario category (after controls)", "",
              "| category | n | severity in range | route acceptable | review flagged when required |",
              "| --- | --- | --- | --- | --- |"]
    for cat, c in m["by_category"].items():
        lines.append(f"| {cat} | {c['n']} | {_fmt(c['severity_within_range_after_controls'])} | {_fmt(c['route_acceptable_after_controls'])} | {_fmt(c['mandatory_review_flagged_when_required'])} |")
    lines += ["", f"## Failures ({len(s['failures'])})", "",
              "| case | family | expected (acceptable) | rec. | after controls | route | problems | rules |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for f in s["failures"]:
        lines.append(f"| {f['incident_id']} | {f['family']} | {f['expected']} ({'/'.join(f['acceptable'])}) | {f['model_or_rules']} | "
                     f"{f['after_controls']} | {f['route']} | {', '.join(f['problems'])} | {' '.join(f['triggered_rules'])} |")
    return "\n".join(lines) + "\n"


def compare(summaries: list[dict]) -> str:
    keys = [
        ("Severity within acceptable range (after controls)", lambda m: m["after_deterministic_controls"]["within_acceptable_range"]),
        ("Severity exact (after controls)", lambda m: m["after_deterministic_controls"]["exact_match"]),
        ("P0/P1 precision (after controls)", lambda m: m["after_deterministic_controls"]["p0p1_precision"]),
        ("P0/P1 recall (after controls)", lambda m: m["after_deterministic_controls"]["p0p1_recall"]),
        ("Route acceptable", lambda m: m["routing"]["primary_route_acceptable"]),
        ("Mandatory review compliance", lambda m: m["mandatory_review"]["compliance_flagged_when_required"]),
        ("Review over-flagging", lambda m: m["mandatory_review"]["flagged_when_not_required"]),
        ("Schema-valid rate", lambda m: m["schema_valid_rate"]),
    ]
    head = "| Metric | " + " | ".join(f"{s['evaluation_kind']} `{s['rule_version']}` {s['split']}" for s in summaries) + " |"
    lines = [head, "| --- |" + " --- |" * len(summaries)]
    for name, fn in keys:
        lines.append(f"| {name} | " + " | ".join(_fmt(fn(s["metrics"])) for s in summaries) + " |")
    return "\n".join(lines) + "\n"
