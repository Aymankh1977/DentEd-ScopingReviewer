"""
DentEd-ScopingReviewer — Manuscript Critique Mode
====================================================
Takes any manuscript PDF (yours or someone else's), parses it into
PRISMA-ScR-mapped sections, and runs:

  1. The critic agent on each section it can identify
  2. The originality auditor against a chosen reference corpus

This is the second pillar of the platform: the "audit an existing
manuscript" mode (vs. the "generate a new one" mode in the orchestrator).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agents.api_client_manager import APIClientManager, Role, get_manager
from app.agents.extractor import _extract_pdf_text, InvalidPDFError
from app.agents.critic import CriticAgent
from app.agents.originality_auditor import OriginalityAuditor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section parsing — heuristic mapping from manuscript headings to PRISMA-ScR
# ---------------------------------------------------------------------------
SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("title",                        ["^title", "^# "]),
    ("abstract",                     ["^abstract"]),
    ("introduction_rationale",       ["^introduction", "^background", "^rationale"]),
    ("introduction_objectives",      ["^objectives", "^aim", "^research questions?"]),
    ("methods_protocol",             ["protocol", "^registration"]),
    ("methods_eligibility",          ["eligibility", "inclusion.*exclusion"]),
    ("methods_information_sources",  ["information sources", "data sources"]),
    ("methods_search",               ["search strategy", "search method"]),
    ("methods_selection",            ["selection of studies", "study selection"]),
    ("methods_data_charting",        ["data charting", "data extraction"]),
    ("methods_data_items",           ["data items", "variables"]),
    ("methods_synthesis",            ["synthesis", "analysis approach"]),
    ("results_selection",            ["selection of sources", "screening results"]),
    ("results_characteristics",      ["characteristics of", "study characteristics"]),
    ("results_critical_appraisal",   ["critical appraisal", "quality assessment"]),
    ("results_individual_sources",   ["individual sources", "results of individual"]),
    ("results_synthesis",            ["synthesis of results", "thematic"]),
    ("discussion_summary",           ["^discussion", "summary of evidence"]),
    ("discussion_limitations",       ["limitation"]),
    ("discussion_conclusions",       ["^conclusion"]),
    ("funding",                      ["funding", "conflicts? of interest"]),
]


@dataclass
class ManuscriptCritique:
    manuscript_filename: str
    sections_parsed: dict[str, str]
    critic_reports: dict[str, dict] = field(default_factory=dict)
    originality_report: Optional[dict] = None
    parse_errors: list[str] = field(default_factory=list)
    audited_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


def parse_manuscript(pdf_path: str | Path) -> dict[str, str]:
    """
    Extract manuscript text and split into PRISMA-ScR-mapped sections.

    Uses heuristic heading matching. Returns dict {section_id: prose}.
    """
    text, _ = _extract_pdf_text(pdf_path)

    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        if re.match(r"^\[Page \d+\]$", line.strip()):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)

    # Find candidate heading positions
    matches: list[tuple[int, str, str]] = []  # (position, heading_text, section_id)
    for section_id, patterns in SECTION_PATTERNS:
        for pat in patterns:
            for m in re.finditer(rf"(?im)^\s*\d*\.?\s*({pat})[^\n]{{0,80}}$",
                                 text, flags=re.MULTILINE):
                matches.append((m.start(), m.group(0).strip(), section_id))

    # Sort by position, dedupe by section_id (first occurrence wins)
    matches.sort()
    seen: set[str] = set()
    ordered: list[tuple[int, str, str]] = []
    for pos, head, sid in matches:
        if sid not in seen:
            seen.add(sid)
            ordered.append((pos, head, sid))

    if not ordered:
        return {"full_manuscript": text[:50_000]}

    # Slice text between consecutive headings
    sections: dict[str, str] = {}
    for i, (pos, head, sid) in enumerate(ordered):
        end = ordered[i + 1][0] if i + 1 < len(ordered) else len(text)
        section_text = text[pos:end].strip()
        # Drop the heading line itself
        section_text = re.sub(rf"^.{{0,200}}{re.escape(head[:50])}.{{0,80}}\n",
                              "", section_text, count=1)
        if len(section_text) > 50:
            sections[sid] = section_text[:10_000]  # cap per section

    return sections


class ManuscriptCritiqueAgent:
    """
    Critiques an uploaded manuscript end-to-end:
    parse → per-section critic → originality audit.
    """

    def __init__(self, manager: Optional[APIClientManager] = None):
        self.manager = manager or get_manager()
        self.critic = CriticAgent(self.manager)
        self.auditor = OriginalityAuditor(self.manager)

    def critique_pdf(
        self,
        pdf_path: str | Path,
        reference_corpus: list[dict],
        project_context: dict[str, Any],
        run_critic: bool = True,
        run_originality: bool = True,
        granularity: str = "both",
    ) -> ManuscriptCritique:
        path = Path(pdf_path)

        try:
            sections = parse_manuscript(path)
        except InvalidPDFError as e:
            return ManuscriptCritique(
                manuscript_filename=path.name,
                sections_parsed={},
                parse_errors=[str(e)],
            )

        result = ManuscriptCritique(
            manuscript_filename=path.name,
            sections_parsed=sections,
        )

        if not sections or "full_manuscript" in sections:
            result.parse_errors.append(
                "Could not identify PRISMA-ScR section headings; "
                "critic skipped per-section. Originality audit "
                "(if requested) will use the full manuscript text."
            )

        if run_critic:
            from app.prompts import SECTION_PROMPTS
            for sid, prose in sections.items():
                if sid not in SECTION_PROMPTS:
                    continue
                logger.info(f"Critiquing {sid}...")
                r = self.critic.critique(
                    section_id=sid,
                    drafted_prose=prose,
                    project_context=project_context,
                    corpus_charts=reference_corpus,
                )
                result.critic_reports[sid] = r.to_dict()

        if run_originality:
            logger.info("Running originality audit...")
            audit_input = sections if sections and "full_manuscript" not in sections \
                else {"full_manuscript": sections.get("full_manuscript", "")}
            r = self.auditor.audit(
                manuscript_sections=audit_input,
                reference_corpus=reference_corpus,
                manuscript_label=path.name,
                corpus_mode="folder",
                granularity=granularity,
            )
            result.originality_report = r.to_dict()

        return result
