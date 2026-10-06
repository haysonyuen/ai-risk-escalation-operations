"""Policy library (synthetic, config/policies.json) and per-case policy suggestions.

A policy maps one-to-one onto a harm category of the taxonomy, so the rules, the evaluation and the
dataset are unchanged. The library order is the priority order: when several policies match, the
first one in the library is the primary policy (most severe first, same order as rule routing).
"""

from __future__ import annotations

import json
from functools import lru_cache

from .config import CONFIG_DIR


@lru_cache(maxsize=1)
def library() -> dict:
    return json.loads((CONFIG_DIR / "policies.json").read_text())


def all_policies() -> list[dict]:
    return library()["policies"]


def keys() -> list[str]:
    return [p["key"] for p in all_policies()]


def get(key: str | None) -> dict | None:
    return next((p for p in all_policies() if p["key"] == key), None)


def label(key: str | None, code: bool = True) -> str:
    p = get(key)
    if not p:
        return "—" if not key else key
    return f"{p['code']} · {p['name']}" if code else p["name"]


def code(key: str | None) -> str:
    p = get(key)
    return p["code"] if p else "—"


def ordered(categories: list[str]) -> list[str]:
    """Known policy keys in priority order; 'No policy issue' only when nothing else matched."""
    rank = {k: i for i, k in enumerate(keys())}
    out = sorted({c for c in categories if c in rank}, key=rank.get)
    return [c for c in out if c != "benign_noise"] or out


def suggested(assessment: dict | None) -> list[str]:
    """Policies suggested for a case: the AI's risk categories plus the rules' categories."""
    if not assessment:
        return []
    cats = list(assessment["rule_result"]["categories"])
    if assessment.get("output"):
        cats += list(assessment["output"]["risk_categories"])
    return ordered(cats)


def primary(categories: list[str]) -> str | None:
    o = ordered(categories)
    return o[0] if o else None


def why_matched(assessment: dict | None, key: str) -> list[str]:
    """Plain-language reasons a policy was suggested: the rules' signals that fired, and whether the AI tagged it."""
    if not assessment:
        return []
    from .rules import load_rules
    rr = assessment["rule_result"]
    out: list[str] = []
    try:
        cat_rules = [r for r in load_rules(rr["rule_version"])["category_rules"] if r["category"] == key]
    except Exception:  # archived rule version
        cat_rules = []
    sig, terms = rr.get("signals", {}), rr.get("matched_terms", {})
    for r in cat_rules:
        for cond in r.get("all", []) + r.get("any", []):
            name = cond.lstrip("!")
            if cond.startswith("!") or not sig.get(name):
                continue
            t = terms.get(name) or []
            line = f"Rules signal: {name.replace('_', ' ')}"
            if t:
                line += " (matched: " + ", ".join(dict.fromkeys(str(x) for x in t[:3])) + ")"
            if line not in out:
                out.append(line)
    if key in rr.get("categories", []) and not out:
        out.append("The rules tagged this policy area")
    if assessment.get("output") and key in assessment["output"].get("risk_categories", []):
        out.append("The AI assessment tagged this policy area")
    return out
