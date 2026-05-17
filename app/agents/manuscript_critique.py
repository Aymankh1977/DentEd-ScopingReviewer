"""Forwarding module — re-exports root manuscript_critique into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from manuscript_critique import *  # noqa: F401, F403, E402
from manuscript_critique import ManuscriptCritiqueAgent  # noqa: E402

__all__ = ["ManuscriptCritiqueAgent"]
