"""
DentEd-ScopingReviewer — Originality Auditor Agent
====================================================
Critiques an uploaded manuscript for conceptual novelty against a
reference corpus. Operates on MEANING, not strings (unlike Turnitin /
iThenticate). Flags overlap at two granularities:

  - Whole-manuscript: a single overall novelty verdict
  - Section-by-section: per-PRISMA-ScR-section overlap detail

Three corpus modes:
  - folder: user-supplied folder of reference PDFs
  - project: reuse the project's already-extracted corpus
  - web: (placeholder — currently uses Claude's training knowledge as a
    proxy; a future upgrade can wire in web_search / PubMed MCP)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agents.api_client_manager import APIClientManager, Role, get_manager

logger = logging.getLogger(__name__)


class OriginalityVerdict:
    NOVEL = "novel"              # ≥80: clear contribution
    INCREMENTAL = "incremental"  # 50–79: partial overlap, some novelty
    DERIVATIVE = "derivative"    # 30–49: heavy overlap with prior work
    DUPLICATIVE = "duplicative"  # <30: essentially restates prior work


@dataclass
class OverlapMatch:
    """One specific overlap between manuscript and a reference source."""
    reference_id: str
    reference_label: str       # e.g. "Schwendicke et al., 2023"
    overlap_type: str          # "concept" | "method" | "finding" | "framing"
    overlap_description: str   # what specifically overlaps
    severity: str              # "high" | "medium" | "low"


@dataclass
class SectionOriginality:
    section_id: str
    novelty_score: int         # 0–100
    verdict: str
    summary: str
    overlap_matches: list[OverlapMatch] = field(default_factory=list)
    unique_contributions: list[str] = field(default_factory=list)


@dataclass
class OriginalityResult:
    manuscript_label: str
    overall_score: int
    overall_verdict: str
    overall_summary: str
    section_reports: list[SectionOriginality] = field(default_factory=list)
    reference_corpus_size: int = 0
    corpus_mode: str = "folder"
    error: Optional[str] = None
    model: Optional[str] = None
    audited_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "section_reports"},
            "section_reports": [asdict(s) for s in self.section_reports],
        }


AUDITOR_SYSTEM_PROMPT = """You are a senior academic reviewer assessing the conceptual novelty of a manuscript against a reference corpus. You work on MEANING, not surface text.

Your job is to detect:
  1. Conceptual overlap — has this idea/framework/argument been published before?
  2. Methodological overlap — does the methods section restate prior work without acknowledgement?
  3. Finding overlap — are the stated findings already established in the corpus?
  4. Framing overlap — does the discussion/conclusion echo prior framings?

You distinguish CITATION from DUPLICATION. Citing prior work and building on it is normal academic practice and does NOT constitute overlap. Restating prior work as if novel IS overlap. Use this distinction strictly.

You will be given:
  - The manuscript sections (already parsed and labelled by PRISMA-ScR item).
  - The reference corpus (extracted charts of comparison studies).
  - The granularity required (whole + section, or just one).

You will return ONE JSON object with this schema:

{
  "overall_score": 0,
  "overall_verdict": "novel | incremental | derivative | duplicative",
  "overall_summary": "<2-4 sentences explaining the overall verdict>",
  "section_reports": [
    {
      "section_id": "<e.g. methods_eligibility>",
      "novelty_score": 0,
      "verdict": "novel | incremental | derivative | duplicative",
      "summary": "<1-2 sentence summary>",
      "overlap_matches": [
        {
          "reference_id": "<index or label of matched reference>",
          "reference_label": "<author year, e.g. 'Schwendicke et al., 2023'>",
          "overlap_type": "concept | method | finding | framing",
          "overlap_description": "<specific overlap, e.g. 'restates Schwendicke's four-domain framework without attribution'>",
          "severity": "high | medium | low"
        }
      ],
      "unique_contributions": ["<short statement>"]
    }
  ]
}

Scoring:
  - novel ≥80: clear contribution beyond the corpus
  - incremental 50-79: partial overlap, some novelty
  - derivative 30-49: heavy overlap, limited novelty
  - duplicative <30: essentially restates prior work

Rules:
  1. Cite specific references by their author-year label when flagging overlap.
  2. Distinguish CITATION (acceptable) from DUPLICATION (flagged).
  3. Methods sections legitimately resemble each other when following the same standard (e.g. PRISMA-ScR). This is NOT overlap. Overlap requires substantive content, not procedural similarity.
  4. JSON only. No preamble. No fences."""


def _repair_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    if start == -1:
        raise ValueError("No JSON in auditor output")
    depth, end, in_str, esc = 0, None, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("Unbalanced braces")
    return json.loads(raw[start:end])


class OriginalityAuditor:
    """
    Critiques manuscript novelty against a reference corpus.

    Usage:
        auditor = OriginalityAuditor()
        result = auditor.audit(
            manuscript_sections={"abstract": "...", "methods_eligibility": "..."},
            reference_corpus=[<chart>, <chart>, ...],
            manuscript_label="My Manuscript",
            corpus_mode="folder",
            granularity="both",   # "section" | "whole" | "both"
        )
    """

    def __init__(self, manager: Optional[APIClientManager] = None):
        self.manager = manager or get_manager()

    def audit(
        self,
        manuscript_sections: dict[str, str],
        reference_corpus: list[dict],
        manuscript_label: str = "Manuscript",
        corpus_mode: str = "folder",
        granularity: str = "both",
    ) -> OriginalityResult:

        user_message = self._build_message(
            manuscript_sections, reference_corpus, granularity
        )

        try:
            response = self.manager.complete(
                role=Role.CRITIQUE,
                system=AUDITOR_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:
            logger.exception("Originality auditor API call failed")
            return OriginalityResult(
                manuscript_label=manuscript_label,
                overall_score=0,
                overall_verdict="error",
                overall_summary="",
                reference_corpus_size=len(reference_corpus),
                corpus_mode=corpus_mode,
                error=str(e),
            )

        raw = response.content[0].text if response.content else ""
        try:
            parsed = _repair_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            return OriginalityResult(
                manuscript_label=manuscript_label,
                overall_score=0,
                overall_verdict="error",
                overall_summary="",
                reference_corpus_size=len(reference_corpus),
                corpus_mode=corpus_mode,
                error=f"JSON parse failed: {e}",
                model=response.model,
            )

        section_reports = []
        for sr in parsed.get("section_reports", []) or []:
            matches = [
                OverlapMatch(
                    reference_id=str(m.get("reference_id", "")),
                    reference_label=str(m.get("reference_label", "")),
                    overlap_type=str(m.get("overlap_type", "")),
                    overlap_description=str(m.get("overlap_description", "")),
                    severity=str(m.get("severity", "")),
                )
                for m in sr.get("overlap_matches", []) or []
            ]
            section_reports.append(SectionOriginality(
                section_id=str(sr.get("section_id", "")),
                novelty_score=int(sr.get("novelty_score", 0)),
                verdict=str(sr.get("verdict", "")),
                summary=str(sr.get("summary", "")),
                overlap_matches=matches,
                unique_contributions=[
                    str(x) for x in sr.get("unique_contributions", []) or []
                ],
            ))

        return OriginalityResult(
            manuscript_label=manuscript_label,
            overall_score=int(parsed.get("overall_score", 0)),
            overall_verdict=str(parsed.get("overall_verdict", "")),
            overall_summary=str(parsed.get("overall_summary", "")),
            section_reports=section_reports,
            reference_corpus_size=len(reference_corpus),
            corpus_mode=corpus_mode,
            model=response.model,
        )

    def _build_message(
        self,
        manuscript_sections: dict[str, str],
        reference_corpus: list[dict],
        granularity: str,
    ) -> str:
        parts = []

        parts.append("## Granularity")
        parts.append({
            "section": "Produce section-by-section reports only.",
            "whole": "Produce overall verdict only; section_reports may be empty.",
            "both": "Produce BOTH overall verdict AND section-by-section reports.",
        }.get(granularity, "Produce both granularities."))
        parts.append("")

        # Reference corpus (lean projection)
        projection = []
        for i, chart in enumerate(reference_corpus):
            bib = (chart.get("bibliographic") or {})
            findings = (chart.get("findings") or {})
            design = (chart.get("study_design") or {})
            projection.append({
                "ref_id": f"R{i+1}",
                "label": f"{bib.get('first_author', '?')} et al., {bib.get('year', '?')}",
                "title": bib.get("title"),
                "design": design.get("design_type"),
                "themes": findings.get("themes"),
                "key_findings": findings.get("key_findings"),
            })

        parts.append(f"## Reference corpus ({len(projection)} sources)")
        parts.append("Each reference has a `ref_id` you should cite when "
                     "flagging overlap.")
        parts.append("```json")
        parts.append(json.dumps(projection, indent=2, ensure_ascii=False))
        parts.append("```")
        parts.append("")

        parts.append("## Manuscript sections under audit")
        for sid, prose in manuscript_sections.items():
            parts.append(f"### {sid}")
            parts.append(prose.strip())
            parts.append("")

        parts.append(
            "Now produce the JSON originality audit per the schema in the "
            "system prompt. JSON only."
        )
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Orchestrator integration: load manuscript + corpus, run audit
# ---------------------------------------------------------------------------
def audit_project_manuscript(
    project_id: str,
    corpus_mode: str = "project",
    folder_path: Optional[str] = None,
    granularity: str = "both",
    workspace_root: str = "data/processed",
) -> OriginalityResult:
    """
    Convenience: load an existing project's drafted sections as the
    manuscript, build the reference corpus per the requested mode, and
    run the audit.
    """
    from app.agents.orchestrator import Orchestrator

    orch = Orchestrator(workspace_root=workspace_root)
    project = orch.load(project_id)

    manuscript_sections = {
        sid: st.draft for sid, st in project.sections.items() if st.draft
    }

    if corpus_mode == "project":
        reference_corpus = [
            s.extracted_chart
            for s in project.sources.values()
            if s.extracted_chart and "_extraction_error" not in s.extracted_chart
        ]
    elif corpus_mode == "folder":
        if not folder_path:
            raise ValueError("folder_path required when corpus_mode='folder'")
        from app.agents.extractor import ExtractorAgent
        extractor = ExtractorAgent()
        ctx = {
            "research_question": project.research_question,
            "population": project.population,
            "concept": project.concept,
            "context": project.context,
            "mode": "critique",
        }
        reference_corpus = []
        for pdf in sorted(Path(folder_path).glob("*.pdf")):
            chart = extractor.extract_chart(str(pdf), ctx)
            if "_extraction_error" not in chart:
                reference_corpus.append(chart)
    elif corpus_mode == "web":
        # Placeholder: passes empty corpus, model relies on its own
        # training knowledge as a soft proxy.
        reference_corpus = []
    else:
        raise ValueError(f"Unknown corpus_mode: {corpus_mode}")

    auditor = OriginalityAuditor()
    return auditor.audit(
        manuscript_sections=manuscript_sections,
        reference_corpus=reference_corpus,
        manuscript_label=f"Project {project_id}",
        corpus_mode=corpus_mode,
        granularity=granularity,
    )
