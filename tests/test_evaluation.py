"""Dataset integrity, label isolation, metric handling and regression detection."""

import json

import pytest

from riskops import config, evaluation, monitoring
from riskops.evaluation import LiveEvaluationUnavailable, ratio


def test_dataset_size_splits_and_family_isolation():
    splits = evaluation.load_splits()
    labels = evaluation.load_labels()
    assert 75 <= len(labels) <= 90
    assert not set(splits["dev"]) & set(splits["held_out"])
    fam_split = {}
    for iid, lab in labels.items():
        split = "dev" if iid in splits["dev"] else "held_out"
        assert fam_split.setdefault(lab["scenario_family"], split) == split, "family leaks across splits"
    for lab in labels.values():
        assert lab["expected_severity"] in lab["acceptable_severities"]
        assert lab["label_rationale"] and lab["supporting_evidence_ids"] is not None
        assert lab["label_status"] == "provisional-author-label"


def test_cases_contain_no_label_fields():
    for line in (config.EVAL_DIR / "cases.jsonl").read_text().splitlines():
        c = json.loads(line)
        assert not {"expected_severity", "acceptable_severities", "expected_route", "scenario_family", "label_rationale"} & set(c)


def test_supporting_evidence_ids_exist():
    cases = {c.incident_id: c for c in evaluation.load_cases("all")}
    for iid, lab in evaluation.load_labels().items():
        ids = {e.evidence_id for e in cases[iid].evidence}
        assert set(lab["supporting_evidence_ids"]) <= ids, iid


def test_held_out_matches_freeze():
    assert evaluation.held_out_integrity()["matches_freeze"]


def test_ratio_undefined_handling():
    r = ratio(0, 0, "no positives")
    assert r["value"] is None and r["undefined_reason"] == "no positives"


def test_rules_eval_runs_and_reports_denominators():
    s = evaluation.run_eval("rules", "rules-v1.1", split="dev", write=False)
    m = s["metrics"]
    assert m["n_cases"] == len(evaluation.load_splits()["dev"])
    assert m["after_deterministic_controls"]["p0p1_recall"]["denominator"] > 0
    assert m["claim_support_accuracy"]["value"] is None  # never invented
    assert s["evaluation_kind"] == "rules_only_baseline"


def test_live_eval_refuses_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LiveEvaluationUnavailable, match="no offline results were substituted"):
        evaluation.run_eval("live", "rules-v1.1", split="dev", write=False)


def test_fault_injection_run_is_labeled_and_controls_hold():
    s = evaluation.run_eval("fault:under_severity", "rules-v1.1", split="all", write=False)
    assert s["evaluation_kind"] == "fault_injection"
    before = s["metrics"]["recommendation_before_controls"]["p0p1_recall"]["value"]
    after = s["metrics"]["after_deterministic_controls"]["p0p1_recall"]["value"]
    assert before == 0 and after > 0.8


def test_regression_gate_flags_injected_rule_regression():
    base = evaluation.run_eval("rules", "rules-v1.1", split="all", write=False)
    bad = evaluation.run_eval("rules", "rules-v1.1-fault-demo", split="all", write=False)
    chk = monitoring.regression_check(base, bad)
    assert chk["alert"]
    assert any(r["metric"].startswith("Mandatory review") or r["metric"].startswith("P0/P1") for r in chk["regressions"])
    assert "SYNTHETIC" in chk["label"]


def test_claim_worksheet_summary_counts_only_reviewed_rows(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text("incident_id,fact_index,statement,cited_evidence_ids,cited_evidence_text,"
                 "verdict(supported|partially_supported|unsupported|cannot_determine),reviewer,note\n"
                 "A,0,s,E1,t,supported,me,\nA,1,s,E1,t,,,\nB,0,s,E2,t,unsupported,me,\n")
    out = evaluation.summarize_claim_worksheet(p)
    assert out["reviewed"] == 2 and out["supported_rate"]["value"] == 0.5
