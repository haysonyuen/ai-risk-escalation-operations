"""Keep the running app on one consistent version of the code.

Streamlit re-executes the entry script on every interaction but keeps imported modules in
``sys.modules``. When a hosted app pulls new code without restarting the process, the entry
script and page modules can be new while ``riskops`` modules are still the old ones (seen as
ImportError / schema ValidationError after deploys). This drops every project module when the
code on disk changes, so the next imports load the new code together.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_STATE = "_riskops_reload_state"


def _fingerprint() -> tuple:
    files = sorted(list((ROOT / "riskops").rglob("*.py")) + list((ROOT / "app").glob("*.py")))
    return tuple((str(f.relative_to(ROOT)), f.stat().st_mtime_ns, f.stat().st_size) for f in files)


def _project_module(name: str, mod) -> bool:
    if name == "riskops" or name.startswith("riskops."):
        return True
    path = getattr(mod, "__file__", None) or ""
    return bool(path) and Path(path).resolve().parent == ROOT / "app" and name not in ("__main__", __name__)


def refresh_if_code_changed() -> bool:
    state = sys.modules.get(_STATE)
    if state is None:
        state = types.ModuleType(_STATE)
        state.fingerprint = None
        sys.modules[_STATE] = state
    fp = _fingerprint()
    # First run of this guard in this process: anything already imported was loaded before the
    # guard existed (e.g. by an older deploy), so it cannot be trusted either.
    if state.fingerprint is not None and fp == state.fingerprint:
        return False
    dropped = 0
    for name, mod in list(sys.modules.items()):
        if mod is not None and _project_module(name, mod):
            del sys.modules[name]
            dropped += 1
    state.fingerprint = fp
    return dropped > 0
