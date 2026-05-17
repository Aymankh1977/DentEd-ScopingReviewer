"""Forwarding module — re-exports root originality_auditor into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from originality_auditor import *  # noqa: F401, F403, E402
from originality_auditor import (  # noqa: E402
    OriginalityAuditor,
    audit_project_manuscript,
)

__all__ = ["OriginalityAuditor", "audit_project_manuscript"]
