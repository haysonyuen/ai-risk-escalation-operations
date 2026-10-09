"""Phase 1 Jev shadow mode: response parsing, derived views, evaluation plumbing and isolation.

Uses a fake transport that answers every question; these are plumbing tests, not Jev results.
"""

import inspect
import json

import pytest

from riskops import evaluation, jev_eval, shadow
from riskops import workflow as wf
from riskops.providers import jev
from riskops.providers.jev import JevClient, parse_response
from tests.conftest import make_intake


def fake_transport(pick=0):
    """Answers each question with option `pick` (or the last option if fewer) at probability 0.7."""
    def _t(payload):
        answers = {}
        for name, q in payload["questions"].items():
            options = list(q["criteria"]) if q["type"] == "choice" else [l.split(":")[0].split()[0] for l in q["levels"]]
            i = min(pick, len(options) - 1)
            rest = (1 - 0.7) / max(len(options) - 1, 1)
            probs = {o: (0.7 if j == i else rest) for j, o in enumerate(options)}
            answers[name] = ({"choice": options[i]} if q["type"] == "choice" else {"score": i}) | {"confidence": 0.7, "probabilities": probs}
        return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1000}}
    return _t


def test_parse_choice_and_score_answers():
    qs = {"c": {"type": "choice", "criteria": {"yes": "", "no": ""}},
          "s": {"type": "score", "levels": ["P3 Low: x", "P2 Medium: y", "P1 High: z", "P0 Critical: w"]}}
    body = {"answers": {"c": {"choice": "no", "confidence": 0.8, "probabilities": {"yes": 0.2, "no": 0.8}},
                        "s": {"score": 2, "probabilities": [0.1, 0.2, 0.6, 0.1]}}}
    a = parse_response(body, qs)
    assert a["c"].answer == "no" and a["c"].confidence == 0.8
    assert a["s"].answer == "P1" and a["s"].probabilities["P0"] == 0.1


def test_parse_rejects_unknown_options_and_missing_answers():
    qs = {"c": {"type": "choice", "criteria": {"yes": "", "no": ""}}}
    with pytest.raises(ValueError):
        parse_response({"answers": {"c": {"choice": "maybe"}}}, qs)
    with pytest.raises(ValueError):
        parse_response({"answers": {}}, qs)


def test_missing_key_is_a_config_error_not_a_guess():
    r = JevClient().ask({"x": 1}, {"c": {"type": "choice", "instructions": "?", "criteria": {"a": "", "b": ""}}})
    assert r.error_kind == "config" and not r.answers


def test_format_error_keeps_raw_response():
    r = JevClient(transport=lambda p: {"unexpected": True}).ask({}, {"c": {"type": "choice", "instructions": "?", "criteria": {"a": ""}}})
    assert r.error_kind == "format" and r.raw == {"unexpected": True}


@pytest.mark.parametrize("variant", ["A", "B"])
def test_run_case_derives_policy_and_both_severities(variant):
    case = evaluation.load_cases("dev")[0]
    out = shadow.run_case(case, variant, JevClient(transport=fake_transport()))
    assert not out["errors"]
    assert out["policy_ranking"] and all(0 <= v <= 1 for v in out["policy_probs"].values())
    if variant == "A":  # one choice question: a distribution. B's severe yes-scores are independent.
        assert abs(sum(out["policy_probs"].values()) - 1) < 0.05
    assert out["severity_a"] in {"P0", "P1", "P2", "P3"} and out["severity_b"] in {"P0", "P1", "P2", "P3"}
    assert set(out["factors"]) == {"scope", "reversibility", "sensitive_data", "external_action_attempted", "user_approved", "recurrence"}


def test_masked_state_hides_the_factor_fields():
    s = shadow.build_state(make_intake(), masked=True)
    assert not {"scope", "reversibility", "sensitive_data", "external_action_attempted", "user_approved", "recurrence"} & set(s)
    assert {"scope", "reversibility"} <= set(shadow.build_state(make_intake()))


def test_detection_alerts_take_case_type_from_the_channel():
    case = make_intake(reporter_channel="telemetry_alert")
    full, _ = shadow.questions_for(case, "A")
    assert "case_type" not in full and "evidence_support" not in full
    out = shadow.run_case(case, "A", JevClient(transport=fake_transport()))
    assert out["case_type"] == "detection_alert"


def test_evaluation_scores_and_applies_fixed_criteria():
    s = jev_eval.run("dev", "A", repeats=2, client=JevClient(transport=fake_transport()), write=False)
    assert [c["id"] for c in s["criteria"]] == ["severe_policy_miss", "p0_called_p2_or_lower", "severity_within_range", "policy_top2"]
    assert s["errors"] == 0 and s["stability"]["repeats"] == 2
    assert s["passed"] is False  # a constant fake answer must not pass
    assert "PASS" in jev_eval.render_report(s) or "NOT PASSED" in jev_eval.render_report(s)


def test_shadow_results_are_never_read_by_decision_code():
    """Rules, assessment, monitoring and workflow decisions must not read Jev shadow answers."""
    from riskops import assessment, monitoring, rules
    for mod in (rules, assessment, monitoring, evaluation):
        src = inspect.getsource(mod)
        assert "shadow_results" not in src and "import shadow" not in src and "shadow." not in src, mod.__name__
    src = inspect.getsource(wf)
    assert "results_for" not in src and "SELECT" not in inspect.getsource(wf._record_jev_shadow)


def test_assessment_records_shadow_when_configured_and_survives_failure(conn, actors, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(jev.JevClient, "_post", lambda self, payload: fake_transport()(payload))
    wf.create_incident(conn, make_intake(), actors["alex.riskops"])
    from riskops.providers import OfflineSimulationProvider
    rec = wf.run_assessment(conn, "T-1", OfflineSimulationProvider())
    rows = shadow.results_for(conn, "T-1")
    assert len(rows) == 1 and rows[0]["error_kind"] is None and rows[0]["result"]["policy_ranking"]

    def boom(self, payload):
        raise RuntimeError("Jev down")
    monkeypatch.setattr(jev.JevClient, "_post", boom)
    rec2 = wf.run_assessment(conn, "T-1", OfflineSimulationProvider())
    assert rec2["controlled_severity"] == rec["controlled_severity"]  # assessment unaffected
    assert json.loads(json.dumps(rec2["rule_result"]))  # still a complete record
