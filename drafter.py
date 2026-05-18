"""
DentEdTech-ScopingReviewer™ — Drafter Agent (v2 — revision support)
================================================================
Produces section prose for one PRISMA-ScR item at a time, and revises
existing drafts in response to critic feedback.

Workflow
--------
First draft:
    drafter.draft(section_id, project_context, corpus_charts, previous_sections)

Revision after critique:
    drafter.revise(section_id, prior_draft, revision_notes,
                   project_context, corpus_charts, previous_sections)

The revise() path uses the same drafter system prompt but adds an extra
user-message block containing the prior draft and the critic's revision
notes. The drafter is told to address each note specifically while
preserving anything the critic praised.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.api_client_manager import APIClientManager, Role, get_manager
from app.prompts import SECTION_PROMPTS, SectionPrompt, get_prompt

logger = logging.getLogger(__name__)


DRAFTER_SYSTEM_PROMPT = """You are a senior academic writer producing one section of a PRISMA-ScR-compliant scoping review for a Health Professions Education (HPE) / dental education journal.

You will be given:
  - The project's research question and PCC (Population, Concept, Context).
  - The charted corpus of included studies (as structured JSON).
  - Any previously-drafted sections this section depends on.
  - A detailed specification for THIS section, including the exact PRISMA-ScR item it addresses, the evidence you must use, the structural requirements, the word target, and section-specific guidance.
  - (For revision passes only) the prior draft plus the critic's revision notes.

You follow these rules without exception:

1. **PRISMA-ScR compliance is non-negotiable.** Every structural requirement listed in the section spec must appear in your output. If you cannot meet a requirement because evidence is missing, write `[TO BE FILLED — evidence missing: <description>]` exactly, never invent the missing fact.

2. **Faithfulness to the corpus.** Every factual claim about included studies must trace to a chart in the corpus. Use in-text citations as (FirstAuthor et al., Year). Do not cite studies that are not in the corpus. Do not invent author names, years, or findings.

3. **Stay in your lane.** Do not preview or pre-empt content that belongs in a later section. If guidance says "do not discuss limitations here", do not discuss limitations here.

4. **Word target.** Stay within the word target ±10%. Brevity is a virtue in PRISMA-ScR sections — academic editors penalise padding.

5. **UK English, academic register.** Neutral, evidence-led. Avoid hedge stacking ("it may possibly be the case that..."), avoid hype ("revolutionary", "groundbreaking"), avoid the first person plural unless the project context indicates a single review team.

6. **Output format.** Follow the section's output_format exactly. If a markdown table is required, render it correctly with pipes and dashes. If a fenced code block is required at the end (e.g. JSON for the flow diagram), include it verbatim.

7. **No preamble, no postamble.** Do not write "Here is the section..." or "Let me know if you need changes." Start with the section content; end with the section content (or the required trailing code block).

8. **For revision passes:** address every revision note specifically. Preserve sections the critic identified as strengths. Do not rewrite the entire section if only specific changes were requested. If a revision note is impossible to address (e.g. asks for evidence not in the corpus), insert `[TO BE FILLED — <reason>]` and continue rather than fabricating.

You write one section. You write it well. You write it once (or revise it precisely)."""


class DraftStatus:
    OK = "ok"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class DraftResult:
    section_id: str
    status: str
    prose: Optional[str] = None
    structured_blocks: dict[str, Any] = field(default_factory=dict)
    missing_evidence: list[str] = field(default_factory=list)
    error: Optional[str] = None
    word_count: int = 0
    model: Optional[str] = None
    raw_output: Optional[str] = None
    iteration_type: str = "initial"  # "initial" or "revision"
    drafted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "status": self.status,
            "prose": self.prose,
            "structured_blocks": self.structured_blocks,
            "missing_evidence": self.missing_evidence,
            "error": self.error,
            "word_count": self.word_count,
            "model": self.model,
            "iteration_type": self.iteration_type,
            "drafted_at": self.drafted_at,
        }


class DrafterAgent:
    """
    Drafts one PRISMA-ScR section at a time, with optional revision
    support driven by critic feedback.
    """

    def __init__(self, manager: Optional[APIClientManager] = None):
        self.manager = manager or get_manager()

    # -- public API: initial draft ----------------------------------------
    def draft(
        self,
        section_id: str,
        project_context: dict[str, Any],
        corpus_charts: Optional[list[dict]] = None,
        previous_sections: Optional[dict[str, str]] = None,
    ) -> DraftResult:
        try:
            spec = get_prompt(section_id)
        except NotImplementedError as e:
            return DraftResult(
                section_id=section_id,
                status=DraftStatus.FAILED,
                error=str(e),
            )

        corpus_charts = corpus_charts or []
        previous_sections = previous_sections or {}

        missing = self._check_required_evidence(
            spec, project_context, corpus_charts, previous_sections
        )
        if missing:
            logger.info(
                "Section %s blocked — missing evidence: %s",
                section_id, missing,
            )
            return DraftResult(
                section_id=section_id,
                status=DraftStatus.BLOCKED,
                missing_evidence=missing,
            )

        user_message = self._build_user_message(
            spec, project_context, corpus_charts, previous_sections
        )

        return self._call_model(spec, user_message, iteration_type="initial")

    # -- public API: revision pass ----------------------------------------
    def revise(
        self,
        section_id: str,
        prior_draft: str,
        revision_notes: list[str],
        project_context: dict[str, Any],
        corpus_charts: Optional[list[dict]] = None,
        previous_sections: Optional[dict[str, str]] = None,
    ) -> DraftResult:
        try:
            spec = get_prompt(section_id)
        except NotImplementedError as e:
            return DraftResult(
                section_id=section_id,
                status=DraftStatus.FAILED,
                error=str(e),
                iteration_type="revision",
            )

        corpus_charts = corpus_charts or []
        previous_sections = previous_sections or {}

        user_message = self._build_revision_message(
            spec=spec,
            prior_draft=prior_draft,
            revision_notes=revision_notes,
            project_context=project_context,
            corpus_charts=corpus_charts,
            previous_sections=previous_sections,
        )

        return self._call_model(spec, user_message, iteration_type="revision")

    # -- core model call ---------------------------------------------------
    def _call_model(
        self,
        spec: SectionPrompt,
        user_message: str,
        iteration_type: str,
    ) -> DraftResult:
        try:
            response = self.manager.complete(
                role=Role.DRAFTING,
                system=DRAFTER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:
            logger.exception("Drafter API call failed for %s", spec.section_id)
            return DraftResult(
                section_id=spec.section_id,
                status=DraftStatus.FAILED,
                error=str(e),
                iteration_type=iteration_type,
            )

        raw = response.content[0].text if response.content else ""
        prose, structured = self._split_prose_and_structured_blocks(raw)
        word_count = len(prose.split())

        return DraftResult(
            section_id=spec.section_id,
            status=DraftStatus.OK,
            prose=prose,
            structured_blocks=structured,
            word_count=word_count,
            model=response.model,
            raw_output=raw,
            iteration_type=iteration_type,
        )

    # -- evidence gate -----------------------------------------------------
    def _check_required_evidence(
        self,
        spec: SectionPrompt,
        project_context: dict[str, Any],
        corpus_charts: list[dict],
        previous_sections: dict[str, str],
    ) -> list[str]:
        missing: list[str] = []
        for key in ("research_question", "population", "concept", "context"):
            if not project_context.get(key):
                missing.append(f"project_context.{key}")

        joined = " ".join(spec.required_evidence).lower()
        needs_corpus = any(
            kw in joined
            for kw in ("chart", "corpus", "themes", "included stud", "extract")
        )
        if needs_corpus and not corpus_charts:
            missing.append("corpus_charts (no included studies provided)")
        return missing

    # -- prompt assembly: initial -----------------------------------------
    def _build_user_message(
        self,
        spec: SectionPrompt,
        project_context: dict[str, Any],
        corpus_charts: list[dict],
        previous_sections: dict[str, str],
    ) -> str:
        parts: list[str] = []

        parts.append("## Project metadata")
        parts.append(f"- **Research question:** {project_context.get('research_question')}")
        parts.append(f"- **Population (P):** {project_context.get('population')}")
        parts.append(f"- **Concept (C):** {project_context.get('concept')}")
        parts.append(f"- **Context (C):** {project_context.get('context')}")
        parts.append(f"- **Mode:** {project_context.get('mode', 'generate')}")
        parts.append("")

        if corpus_charts:
            included = [
                c for c in corpus_charts
                if (c.get("relevance", {}) or {})
                    .get("inclusion_recommendation", "include").lower() == "include"
                and "_extraction_error" not in c
            ]
            parts.append(f"## Charted corpus ({len(included)} included studies)")
            parts.append(
                "Each entry below is one included study's extracted chart. "
                "Use these as the evidence base. Author and year are in "
                "`bibliographic.first_author` and `bibliographic.year`."
            )
            parts.append("```json")
            parts.append(json.dumps(included, indent=2, ensure_ascii=False))
            parts.append("```")
            parts.append("")
        else:
            parts.append("## Charted corpus")
            parts.append(
                "_No charted studies provided. If this section requires "
                "corpus evidence, mark the relevant claims as `[TO BE "
                "FILLED — evidence missing]`._"
            )
            parts.append("")

        if previous_sections:
            parts.append("## Previously drafted sections")
            for sid, prose in previous_sections.items():
                parts.append(f"### {sid}")
                parts.append(prose.strip())
                parts.append("")

        parts.append("## Specification for THIS section")
        parts.append(spec.render_requirements_block())
        parts.append("")
        parts.append(
            "Now draft this section, following every structural "
            "requirement and the output_format. Begin immediately with "
            "the section content — no preamble."
        )

        return "\n".join(parts)

    # -- prompt assembly: revision -----------------------------------------
    def _build_revision_message(
        self,
        spec: SectionPrompt,
        prior_draft: str,
        revision_notes: list[str],
        project_context: dict[str, Any],
        corpus_charts: list[dict],
        previous_sections: dict[str, str],
    ) -> str:
        parts: list[str] = []

        parts.append("# REVISION PASS")
        parts.append(
            "A prior draft of this section was reviewed by the critic agent "
            "and revisions were requested. Your task is to produce a "
            "revised version that addresses every revision note below "
            "without rewriting parts that were already acceptable."
        )
        parts.append("")

        # Inline the project metadata + corpus so the drafter has full context.
        parts.append("## Project metadata")
        parts.append(f"- Research question: {project_context.get('research_question')}")
        parts.append(f"- Population (P): {project_context.get('population')}")
        parts.append(f"- Concept (C): {project_context.get('concept')}")
        parts.append(f"- Context (C): {project_context.get('context')}")
        parts.append("")

        if corpus_charts:
            included = [
                c for c in corpus_charts
                if (c.get("relevance", {}) or {})
                    .get("inclusion_recommendation", "include").lower() == "include"
                and "_extraction_error" not in c
            ]
            parts.append(f"## Charted corpus ({len(included)} included studies)")
            parts.append("```json")
            parts.append(json.dumps(included, indent=2, ensure_ascii=False))
            parts.append("```")
            parts.append("")

        if previous_sections:
            parts.append("## Previously drafted sections (for context only)")
            for sid, prose in previous_sections.items():
                parts.append(f"### {sid}")
                parts.append(prose.strip())
                parts.append("")

        parts.append("## Section specification (the rubric this must meet)")
        parts.append(spec.render_requirements_block())
        parts.append("")

        parts.append("## Prior draft")
        parts.append("---")
        parts.append(prior_draft)
        parts.append("---")
        parts.append("")

        parts.append("## Revision notes from the critic")
        parts.append(
            "Address each note specifically. Number them in your "
            "internal thinking so nothing is missed."
        )
        for i, note in enumerate(revision_notes, start=1):
            parts.append(f"{i}. {note}")
        parts.append("")

        parts.append(
            "Now produce the REVISED full section. Output the complete "
            "revised text — not a diff, not a list of changes. "
            "Begin immediately with the section content — no preamble."
        )

        return "\n".join(parts)

    # -- response parsing --------------------------------------------------
    _FENCED_JSON_RE = re.compile(
        r"```(?:json)?\s*\n(\{.*?\})\s*\n```",
        re.DOTALL,
    )

    def _split_prose_and_structured_blocks(
        self, raw: str
    ) -> tuple[str, dict[str, Any]]:
        structured: dict[str, Any] = {}
        prose = raw.strip()

        matches = list(self._FENCED_JSON_RE.finditer(prose))
        if matches:
            for i, m in enumerate(matches):
                try:
                    structured[f"json_block_{i}"] = json.loads(m.group(1))
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Could not parse fenced JSON block %d: %s", i, e
                    )
                    structured[f"json_block_{i}_raw"] = m.group(1)
            prose = self._FENCED_JSON_RE.sub("", prose).strip()

        return prose, structured

    def available_sections(self) -> list[str]:
        return sorted(SECTION_PROMPTS.keys())
