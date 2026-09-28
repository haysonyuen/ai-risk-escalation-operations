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

RiskCategory = Literal[
    "harmful_assistance", "sensitive_data", "prompt_injection", "unintended_action",
    "file_modification", "approval_ux", "synthetic_media", "inaccurate_output",
    "product_failure", "containment_appeal", "benign_noise",
]
Route = Literal["safety", "legal_privacy", "product_security", "product_engineering", "product_ux", "support", "risk_ops"]
ROUTES = ["safety", "legal_privacy", "product_security", "product_engineering", "product_ux", "support", "risk_ops"]
Team = Literal[
    "Risk Ops", "Incident Lead", "Safety", "Support", "Engineering", "Product Security",
    "Product/UX", "Legal/Privacy", "Enterprise/CS", "Data/Analytics",
]
Level = Literal["critical", "high", "moderate", "low", "unknown"]
EvidenceQuality = Literal["strong", "partial", "weak", "none"]
Confidence = Literal["high", "medium", "low"]
ContainmentType = Literal[
    "pause_interaction", "restrict_tool_action", "require_confirmation_destructive",
    "warn_sensitive_file_access", "isolate_untrusted_instructions", "pause_external_transactions",
    "workspace_safe_mode", "account_lockout",
]
REVERSIBLE_CONTAINMENT = {
    "pause_interaction", "restrict_tool_action", "require_confirmation_destructive",
    "warn_sensitive_file_access", "isolate_untrusted_instructions", "pause_external_transactions",
    "workspace_safe_mode",
}

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
