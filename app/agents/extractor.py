"""Forwarding module — re-exports root extractor into app.agents namespace."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from extractor import *  # noqa: F401, F403, E402
from extractor import (  # noqa: E402  — private names excluded from * must be explicit
    ExtractorAgent,
    InvalidPDFError,
    _extract_pdf_text,
    _validate_pdf_file,
    _repair_and_parse_json,
)

__all__ = [
    "ExtractorAgent",
    "InvalidPDFError",
    "_extract_pdf_text",
    "_validate_pdf_file",
    "_repair_and_parse_json",
]
