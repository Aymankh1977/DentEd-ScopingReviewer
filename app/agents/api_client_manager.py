"""Forwarding module — re-exports root api_client_manager into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api_client_manager import *  # noqa: F401, F403, E402
from api_client_manager import (  # noqa: E402
    APIClientManager,
    Role,
    get_manager,
)

__all__ = ["APIClientManager", "Role", "get_manager"]
