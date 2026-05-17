"""Forwarding module — re-exports root drafter into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from drafter import *  # noqa: F401, F403, E402
from drafter import DrafterAgent, DraftStatus, DraftResult  # noqa: E402

__all__ = ["DrafterAgent", "DraftStatus", "DraftResult"]
