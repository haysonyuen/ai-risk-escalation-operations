"""Race-safe creation of the demo database for the Streamlit app.

Kept in its own module (not riskops.seed) so a hosted app that hot-reloads code can never
pair a new app/common.py with an older, already-imported copy of riskops.seed.
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from .seed import seed


_SEED_LOCK = threading.Lock()


def seed_atomic(path: str | Path) -> Path:
    """Build the demo database in a private temporary file, then move it into place in one
    step. Readers never see a half-built database, and concurrent builders cannot collide."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        seed(str(tmp))
        os.replace(tmp, target)
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            leftover = Path(str(tmp) + suffix)
            if leftover.exists():
                leftover.unlink()
    return target


def ensure_seeded(path: str | Path) -> Path:
    """Seed ``path`` once, even if several sessions ask at the same moment (e.g. a hosted
    app's first page load racing its health check)."""
    target = Path(path)
    if target.exists():
        return target
    with _SEED_LOCK:
        if not target.exists():  # re-check: another thread may have finished meanwhile
            seed_atomic(target)
    return target
