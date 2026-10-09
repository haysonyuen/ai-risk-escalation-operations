"""Optional live LLM provider (Anthropic Messages API).

Enabled only when ANTHROPIC_API_KEY is set. There is no silent fallback: if the key is
missing or the call fails, the result carries an error and the pipeline routes the case to
manual review. The API key is never logged or stored.
"""

from __future__ import annotations

import json
import re
import time

from .. import config
from ..rules import RuleResult
from ..schemas import AssessmentOutput, IncidentIntake
from .base import ProviderResult

# USD per million tokens (input, output). List prices at the time of writing; used only for
# a cost *estimate* shown next to live results. Verify against current pricing before relying on it.
PRICE_PER_MTOK = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}


def load_prompt(prompt_version: str) -> str:
    text = (config.PROMPT_DIR / f"{prompt_version}.md").read_text()
    schema = json.dumps(AssessmentOutput.model_json_schema(), indent=1)
    return text.replace("{schema}", schema)


def incident_payload(incident: IncidentIntake) -> str:
    data = incident.model_dump(mode="json")
    return "<incident_data>\n" + json.dumps(data, indent=1) + "\n</incident_data>"


# JSON-schema keywords the structured-outputs API does not accept. They are dropped from the schema
# sent to the API; the full Pydantic model still validates the answer afterwards (control C1).
_UNSUPPORTED = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum", "multipleOf",
                "exclusiveMinimum", "exclusiveMaximum", "pattern", "default", "title", "uniqueItems"}


def _api_schema(node):
    if isinstance(node, dict):
        out = {k: _api_schema(v) for k, v in node.items() if k not in _UNSUPPORTED}
        if out.get("type") == "object":
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out
    if isinstance(node, list):
        return [_api_schema(v) for v in node]
    return node


def api_json_schema() -> dict:
    """AssessmentOutput as a structured-outputs schema, so the model can only return valid JSON
    of the right shape (prompt-v3 in free-text mode produced malformed JSON on Claude Opus 5)."""
    return _api_schema(AssessmentOutput.model_json_schema())


def extract_json(text: str) -> dict:
    """Parse a JSON object from model text; tolerate a surrounding code fence only."""
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if fence:
        t = fence.group(1)
    obj = json.loads(t)
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON value is not an object")
    return obj


class AnthropicProvider:
    kind = "live_model"
    name = "anthropic"

    def __init__(self, model: str | None = None, timeout: float | None = None, client=None) -> None:
        self.model = model or config.live_model_name()
        self.timeout = timeout or config.live_timeout_seconds()
        self._client = client

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(timeout=self.timeout, max_retries=1)
        return self._client

    def assess(self, incident: IncidentIntake, prompt_version: str, rr: RuleResult) -> ProviderResult:
        res = ProviderResult(provider_kind=self.kind, provider_name=self.name, model_name=self.model)
        if self._client is None and not config.live_credentials_available():
            res.error_kind, res.error = "config", "ANTHROPIC_API_KEY is not set; live mode unavailable (no fallback applied)."
            return res
        import anthropic
        t0 = time.perf_counter()
        try:
            msg = self._get_client().messages.create(
                model=self.model,
                max_tokens=16000,
                system=load_prompt(prompt_version),
                output_config={"format": {"type": "json_schema", "schema": api_json_schema()}},
                messages=[{"role": "user", "content": "Assess this incident.\n\n" + incident_payload(incident)}],
            )
        except anthropic.APITimeoutError:
            res.error_kind, res.error = "timeout", f"Provider timed out after {self.timeout}s"
        except anthropic.AuthenticationError:
            res.error_kind, res.error = "unavailable", "Authentication failed (check ANTHROPIC_API_KEY)"
        except anthropic.RateLimitError:
            res.error_kind, res.error = "unavailable", "Rate limited by provider"
        except anthropic.APIConnectionError as e:
            res.error_kind, res.error = "unavailable", f"Connection error: {type(e).__name__}"
        except anthropic.APIStatusError as e:
            res.error_kind, res.error = "unavailable", f"Provider returned HTTP {e.status_code}"
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if res.error_kind:
            return res

        usage = getattr(msg, "usage", None)
        if usage is not None:
            res.input_tokens, res.output_tokens = usage.input_tokens, usage.output_tokens
            price = PRICE_PER_MTOK.get(self.model)
            if price:
                res.cost_usd = (usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1e6
        if msg.stop_reason == "refusal":
            res.error_kind, res.error = "refusal", "Model declined to produce an assessment (stop_reason=refusal)"
            return res
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        res.raw_text = text
        if msg.stop_reason == "max_tokens":
            res.error_kind, res.error = "malformed", "Output truncated at max_tokens"
            return res
        try:
            res.candidate = extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            res.error_kind, res.error = "malformed", f"Could not parse JSON: {e}"
        return res
