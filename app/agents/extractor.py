"""Forwarding module — re-exports root extractor into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from extractor import *  # noqa: F401, F403, E402
from extractor import ExtractorAgent  # noqa: E402

__all__ = ["ExtractorAgent"]
