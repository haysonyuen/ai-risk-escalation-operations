"""TypeSafe Jev client (Phase 1: shadow mode only).

Jev is a decision model: it reads a *state* and answers typed *questions* with a probability per
option. Nothing here feeds the rules, the workflow or the AI assessment (see riskops/shadow.py).

The request/response shape was confirmed against the live API (jev-1.13.0, 2026-10-09): score
questions take their ordered levels as a ``criteria`` list, and answer with an expected ``score``
(a float, e.g. 2.42) plus ``probabilities`` keyed by level index. All format handling is in
``build_request`` and ``parse_response``. An answer that cannot be parsed is recorded as an error
with the raw response, never guessed.

The API key is read from TYPESAFE_API_KEY and is never logged or stored.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# Reported list price (USD per million input tokens; output is free). Used only for a cost
# estimate next to results - verify against the TypeSafe console.
PRICE_PER_MTOK_INPUT = 0.042


def base_url() -> str:
    return os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")


def model_name() -> str:
    # Pinned to the version the live API reported on 2026-10-09 ("jev-latest" moves with each
    # release). The model actually used is recorded with every result.
    return os.environ.get("JEV_MODEL", "jev-1.13.0")


def credentials_available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


@dataclass
class JevAnswer:
    answer: str | None
    confidence: float | None
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class JevResult:
    answers: dict[str, JevAnswer] = field(default_factory=dict)
    model: str | None = None
    input_tokens: int | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    error_kind: str | None = None   # config | unavailable | timeout | format
    error: str | None = None
    raw: dict | None = None


def build_request(state, questions: dict[str, dict], model: str) -> dict:
    """One request per case: every question shares the same state."""
    qs = {}
    for name, q in questions.items():
        item = {"type": q["type"], "instructions": q["instructions"]}
        if q["type"] == "choice":
            item["criteria"] = q["criteria"]
        else:  # score: ordered levels, lowest first, sent as a criteria list
            item["criteria"] = q["levels"]
        qs[name] = item
    return {"model": model, "state": state, "questions": qs}


def _probabilities(raw, options: list[str]) -> dict[str, float]:
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            key = options[int(k)] if isinstance(k, str) and k.isdigit() and int(k) < len(options) else k
            out[str(key)] = float(v)
        return out
    if isinstance(raw, list) and len(raw) == len(options):
        return {o: float(p) for o, p in zip(options, raw)}
    return {}


def parse_response(body: dict, questions: dict[str, dict]) -> dict[str, JevAnswer]:
    """Normalise answers to {question: JevAnswer(answer, confidence, probabilities)}.
    Score answers are reported by level label (the level text up to the first ':')."""
    container = body.get("answers") or body.get("results") or body.get("decisions") or body
    out: dict[str, JevAnswer] = {}
    for name, q in questions.items():
        a = container.get(name) if isinstance(container, dict) else None
        if not isinstance(a, dict):
            raise ValueError(f"no answer for question '{name}'")
        if q["type"] == "choice":
            options = list(q["criteria"])
            answer = a.get("choice", a.get("answer"))
        else:
            options = [lvl.split(":")[0].split()[0] for lvl in q["levels"]]
            s = a.get("score", a.get("answer"))
            answer = options[round(s)] if isinstance(s, (int, float)) and 0 <= round(s) < len(options) else s
        probs = _probabilities(a.get("probabilities"), options)
        if q["type"] == "score" and probs and isinstance(a.get("score", a.get("answer")), (int, float)):
            # The score is an expected value over levels; report the most likely level, not a
            # truncation of the mean (which would bias towards lower severity).
            answer = max(probs, key=probs.get)
        if probs and set(probs) - set(options):
            raise ValueError(f"question '{name}': unexpected options {sorted(set(probs) - set(options))}")
        if answer is None and probs:
            answer = max(probs, key=probs.get)
        if answer not in options:
            raise ValueError(f"question '{name}': answer {answer!r} is not one of the options")
        conf = a.get("confidence")
        out[name] = JevAnswer(str(answer), float(conf) if conf is not None else probs.get(str(answer)), probs)
    return out


class JevClient:
    kind = "jev"

    def __init__(self, model: str | None = None, timeout: float = 30.0, transport=None) -> None:
        self.model = model or model_name()
        self.timeout = timeout
        self._transport = transport  # tests inject a callable(request_dict) -> response_dict

    def _post(self, payload: dict) -> dict:
        if self._transport is not None:
            return self._transport(payload)
        req = urllib.request.Request(
            base_url() + "/v1/systemone", data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def ask(self, state, questions: dict[str, dict]) -> JevResult:
        res = JevResult(model=self.model)
        if self._transport is None and not credentials_available():
            res.error_kind, res.error = "config", "TYPESAFE_API_KEY is not set; Jev shadow mode unavailable."
            return res
        t0 = time.perf_counter()
        try:
            body = self._post(build_request(state, questions, self.model))
        except urllib.error.HTTPError as e:
            res.error_kind, res.error = "unavailable", f"Jev returned HTTP {e.code}"
            try:  # validation details only; the request carries no secrets in its body
                res.raw = {"status": e.code, "body": e.read().decode()[:2000]}
            except Exception:
                pass
        except TimeoutError:
            res.error_kind, res.error = "timeout", f"Jev timed out after {self.timeout}s"
        except (urllib.error.URLError, OSError) as e:
            res.error_kind, res.error = "unavailable", f"Connection error: {type(e).__name__}"
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if res.error_kind:
            return res
        res.raw = body
        res.model = body.get("model", self.model)
        usage = body.get("usage") or {}
        res.input_tokens = usage.get("input_tokens")
        if res.input_tokens is not None:
            res.cost_usd = res.input_tokens * PRICE_PER_MTOK_INPUT / 1e6
        try:
            res.answers = parse_response(body, questions)
        except (ValueError, TypeError, KeyError) as e:
            res.error_kind, res.error = "format", f"Could not read Jev response: {e}"
        return res
