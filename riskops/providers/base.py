"""Provider interface.

A provider turns an incident into a *candidate* assessment (a JSON-like dict). The pipeline
in ``riskops.assessment`` validates it, checks evidence references and applies deterministic
controls. Providers never write to the database and never take workflow actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..rules import RuleResult
from ..schemas import IncidentIntake


@dataclass
class ProviderResult:
    provider_kind: str                 # live_model | offline_fixture | offline_simulation | fault_injection
    provider_name: str
    model_name: str | None = None
    raw_text: str | None = None
    candidate: dict | None = None      # parsed JSON (not yet schema-validated)
    error_kind: str | None = None      # timeout | unavailable | malformed | refusal | config
    error: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    notes: list[str] = field(default_factory=list)


class AssessmentProvider(Protocol):
    kind: str
    name: str

    def assess(self, incident: IncidentIntake, prompt_version: str, rule_result: RuleResult) -> ProviderResult:
        ...
