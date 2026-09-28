"""Paths, environment settings and prototype configuration loading.

Every numeric target in ``config/sla.json`` is a PROTOTYPE ASSUMPTION chosen for the demo.
They are not policies of any company and are not specified by the original framework, which
only describes response postures ("same-hour", "same-day").
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PLAYBOOK_DIR = ROOT / "playbooks"
FIXTURE_DIR = ROOT / "fixtures" / "assessments"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
DATA_DIR = ROOT / "data"
EVAL_DIR = DATA_DIR / "eval"
DEMO_DIR = DATA_DIR / "demo"
RESULTS_DIR = ROOT / "evaluation" / "results"


def _load_dotenv() -> None:
    """Minimal .env loader (no extra dependency). Existing env vars win."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def db_path() -> Path:
    return Path(os.environ.get("RISKOPS_DB_PATH", str(DATA_DIR / "riskops.db")))


def live_model_name() -> str:
    return os.environ.get("RISKOPS_LIVE_MODEL", "claude-opus-5")


def live_timeout_seconds() -> float:
    return float(os.environ.get("RISKOPS_LIVE_TIMEOUT_SECONDS", "60"))


def live_credentials_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@lru_cache(maxsize=1)
def sla_config() -> dict:
    return json.loads((CONFIG_DIR / "sla.json").read_text())


def sla_minutes(severity: str, kind: str) -> int | None:
    """kind: 'first_human_review' or 'containment_or_escalation'."""
    targets = sla_config()["targets_minutes"].get(severity, {})
    return targets.get(kind)
