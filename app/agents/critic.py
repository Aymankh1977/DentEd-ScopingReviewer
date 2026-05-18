"""Forwarding module — re-exports root critic into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from critic import *  # noqa: F401, F403, E402
from critic import CriticAgent, CritiqueVerdict, CritiqueResult  # noqa: E402

__all__ = ["CriticAgent", "CritiqueVerdict", "CritiqueResult"]
