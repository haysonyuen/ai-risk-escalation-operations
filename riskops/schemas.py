"""Pydantic schemas shared by intake, assessment, workflow and evaluation.

Unknown values are explicit (``"unknown"``) rather than silently defaulted, so that missing
information stays visible to reviewers and to the rules engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["P0", "P1", "P2", "P3"]
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
SEVERITIES = ["P0", "P1", "P2", "P3"]

TriState = Literal["yes", "no", "unknown"]
SensitiveData = Literal["yes", "possible", "no", "unknown"]
FileAction = Literal["none", "read", "summarized", "edited", "deleted", "unknown"]
Scope = Literal["single_user", "multiple_users", "workspace", "multiple_customers", "unknown"]
Recurrence = Literal["first_report", "repeated", "unknown"]
Reversibility = Literal["reversible", "irreversible", "partially_reversible", "unknown"]
CustomerType = Literal["consumer", "enterprise", "internal", "unknown"]
Channel = Literal["support_ticket", "enterprise_report", "safety_reviewer", "internal_observation", "telemetry_alert"]
EvidenceType = Literal[
    "reporter_statement", "conversation_excerpt", "tool_action_log", "file_diff", "approval_event",
    "telemetry", "classifier_output", "account_settings", "screenshot_description", "reviewer_note",
]

# Taxonomy v2 (2026-09-29): harm areas modelled on the incident types frontier AI labs
# commonly describe (catastrophic misuse, severe content harms, platform abuse, data and
# security, agent and model quality). Taxonomy v1 (generic categories) is archived with the
# v1 rule sets and evaluation dataset; see docs/versioning.md.
TAXONOMY_VERSION = "taxonomy-v2"
RiskCategory = Literal[
    # catastrophic misuse
    "cbrn", "cyber_misuse",
    # severe content harms
    "child_safety", "self_harm", "violent_extremism", "deepfake_ncii",
    # platform abuse
    "influence_operations", "fraud_scams", "safeguard_bypass",
    # data & security
    "enterprise_data_leakage", "privacy_pii", "prompt_injection", "model_security",
    # agent & model quality
    "agentic_overreach", "harmful_inaccuracy", "bias_discrimination",
    # operations
    "enforcement_appeal", "product_failure", "benign_noise",
]
RISK_CATEGORIES = list(RiskCategory.__args__)
# Categories where a P0 recommendation triggers the C7 automatic session pause.
AUTO_HOLD_CATEGORIES = {"cbrn", "child_safety"}
Route = Literal["safety", "child_safety", "threat_intel", "product_security", "legal_privacy", "model_behavior",
                "product_engineering", "product_ux", "risk_ops", "support"]
ROUTES = list(Route.__args__)
Team = Literal[
    "Risk Ops", "Incident Lead", "Safety", "Child Safety", "Threat Intel", "Support", "Engineering",
    "Product Security", "Product/UX", "Legal/Privacy", "Enterprise/CS", "Model Behavior", "Data/Analytics",
]
TEAMS = list(Team.__args__)
Level = Literal["critical", "high", "moderate", "low", "unknown"]
EvidenceQuality = Literal["strong", "partial", "weak", "none"]
Confidence = Literal["high", "medium", "low"]
ContainmentType = Literal[
    "pause_interaction", "restrict_tool_action", "require_confirmation_destructive",
    "warn_sensitive_file_access", "isolate_untrusted_instructions", "pause_external_transactions",
    "workspace_safe_mode", "disable_connector", "rotate_credentials", "deploy_classifier_block",
    "rate_limit_accounts", "account_lockout", "file_mandatory_report",
]
REVERSIBLE_CONTAINMENT = {
    "pause_interaction", "restrict_tool_action", "require_confirmation_destructive",
    "warn_sensitive_file_access", "isolate_untrusted_instructions", "pause_external_transactions",
    "workspace_safe_mode", "disable_connector", "deploy_classifier_block", "rate_limit_accounts",
}
# Not reversible: need a human-confirmed P0/P1 and the Incident Lead (see workflow.decide_containment).
# rotate_credentials cannot be undone but is low-risk to the user; file_mandatory_report records that a
# (simulated) legally required external report, e.g. to a child-protection hotline, was prepared.
IRREVERSIBLE_CONTAINMENT = {"account_lockout", "rotate_credentials", "file_mandatory_report"}
CONTAINMENT_TYPES = sorted(REVERSIBLE_CONTAINMENT | IRREVERSIBLE_CONTAINMENT)

ProviderKind = Literal["live_model", "offline_fixture", "offline_simulation", "rules_only", "fault_injection"]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=64)
    source_type: EvidenceType
    source_description: str = Field(min_length=1)
    content: str = Field(min_length=1)
    collected_at: Optional[datetime] = None


class IncidentIntake(BaseModel):
    """Everything known at intake. Labels for evaluation are never part of this model."""

    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=64)
    reported_at: datetime
    title: str = Field(min_length=1, max_length=200)
    product_surface: str = "unknown"
    customer_type: CustomerType = "unknown"
    reporter_channel: Channel = "support_ticket"
    reported_behavior: str = Field(min_length=1)
    reported_impact: str = "unknown"
    model_version: str = "unknown"
    file_action: FileAction = "unknown"
    external_action_attempted: TriState = "unknown"
    user_approved: TriState = "unknown"
    sensitive_data: SensitiveData = "unknown"
    scope: Scope = "unknown"
    recurrence: Recurrence = "unknown"
    reversibility: Reversibility = "unknown"
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def unique_evidence_ids(cls, v: list[Evidence]) -> list[Evidence]:
        ids = [e.evidence_id for e in v]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique within an incident")
        return v


# ---------------------------------------------------------------------------
# Assessment output contract. Providers (live model, fixtures, simulation) must return
# exactly this shape. extra="forbid": an output that adds fields such as "approved" or
# "close_case" fails validation instead of being partially trusted.
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1)
    basis: str = Field(min_length=1)


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ContainmentOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: ContainmentType
    target: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    reversible: bool


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1200)
    reported_facts: list[Fact]
    hypotheses: list[Hypothesis]
    missing_information: list[str]
    contradictions: list[Contradiction]
    risk_categories: list[RiskCategory] = Field(min_length=1)
    recommended_severity: Severity
    severity_rationale: str = Field(min_length=1)
    potential_impact: Level
    evidence_quality: EvidenceQuality
    confidence: Confidence
    confidence_justification: str = Field(min_length=1)
    suggested_primary_route: Route
    suggested_teams: list[Team]
    next_steps: list[str]
    human_review_reasons: list[str]
    containment_options: list[ContainmentOption]
    incident_brief: str = Field(min_length=1)


def severity_max(a: str, b: str) -> str:
    """Return the more severe of two tiers (P0 is most severe)."""
    return a if SEVERITY_ORDER[a] <= SEVERITY_ORDER[b] else b
