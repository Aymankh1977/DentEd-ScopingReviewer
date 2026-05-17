"""Forwarding module — re-exports root orchestrator into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from orchestrator import *  # noqa: F401, F403, E402
from orchestrator import (  # noqa: E402
    Orchestrator,
    ReviewMode,
    SectionStatus,
    SectionState,
    ReviewProject,
    UploadedSource,
    PRISMA_SCR_SECTIONS,
    COMPLETED_STATUSES,
)

__all__ = [
    "Orchestrator",
    "ReviewMode",
    "SectionStatus",
    "SectionState",
    "ReviewProject",
    "UploadedSource",
    "PRISMA_SCR_SECTIONS",
    "COMPLETED_STATUSES",
]
