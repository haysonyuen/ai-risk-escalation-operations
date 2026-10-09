"""Phase 1 (Jev shadow evaluation) dataset: external split and supplementary labels."""

from riskops import evaluation
from riskops.schemas import CHANNELS

CASE_TYPES = {"detection_alert", "harm_report", "complaint_appeal", "product_issue", "inquiry", "legal_request"}
OUTCOMES = {"occurred", "attempted_blocked", "repeated_attempts", "false_alarm", "unverified", "none_claimed"}
SUPPORT = {"supported", "partly", "contradicted", "claim_only", "no_claim"}


def test_external_split_is_separate_and_frozen_set_untouched():
    ext = evaluation.load_cases("external")
    assert len(ext) == 20
    assert all(c.incident_id.startswith("EXT-") for c in ext)
    assert not {c.incident_id for c in ext} & {c.incident_id for c in evaluation.load_cases("all")}
    assert evaluation.held_out_integrity()["matches_freeze"]
    assert len(evaluation.load_labels()) == 80  # default stays eval-v2 only


def test_external_cases_cover_the_new_sources():
    channels = {c.reporter_channel for c in evaluation.load_cases("external")}
    assert {"law_enforcement", "regulator", "ngo_partner", "researcher", "telemetry_alert"} <= channels
    assert channels <= set(CHANNELS)


def test_every_eval_case_has_valid_phase1_labels():
    p1 = evaluation.load_phase1_labels()
    ids = {c.incident_id for c in evaluation.load_cases("all") + evaluation.load_cases("external")}
    assert set(p1) == ids
    for iid, lab in p1.items():
        assert lab["case_type"] in CASE_TYPES, iid
        assert lab["harm_outcome"] in OUTCOMES, iid
        assert set(lab["harm_outcome_also_ok"]) <= OUTCOMES, iid
        assert lab["evidence_supports_claim"] in SUPPORT, iid


def test_external_labels_are_consistent():
    cases = {c.incident_id: c for c in evaluation.load_cases("external")}
    for iid, lab in evaluation.load_labels(include_external=True).items():
        if not iid.startswith("EXT-"):
            continue
        assert lab["expected_severity"] in lab["acceptable_severities"]
        assert lab["expected_route"] in lab["acceptable_routes"]
        assert set(lab["supporting_evidence_ids"]) <= {e.evidence_id for e in cases[iid].evidence}, iid


def test_severe_external_cases_use_restricted_format_only():
    severe = {"cbrn", "child_safety", "self_harm"}
    labels = evaluation.load_labels(include_external=True)
    for c in evaluation.load_cases("external"):
        if severe & set(labels[c.incident_id]["expected_categories"]) and labels[c.incident_id]["harm_outcome"] != "unverified":
            assert any(e.source_type == "restricted_evidence_ref" for e in c.evidence), c.incident_id
