"""
DentEd-ScopingReviewer — Critic Agent
=====================================
Audits a drafted section against the PRISMA-ScR specification that
governed its creation. The critic is the discipline that separates this
platform from generic AI writing: every drafted section must pass
critique before it can be marked APPROVED.

What the critic actually does
-----------------------------
For one drafted section it returns:

  1. **A per-requirement compliance check.** Every entry in the
     section's `structural_requirements` list (from the prompt
     library) is rated `met`, `partially_met`, or `missing`, with
     a one-line justification.

  2. **An evidence-faithfulness audit.** Every author-year citation
     in the prose is matched against the charted corpus. Citations
     to studies not in the corpus are flagged as fabrications. Claims
     about studies are checked against the chart fields.

  3. **A scope-policing check.** Each prompt has guardrails like
     "do not pre-empt the discussion section" or "do not list
     specific included studies here". The critic flags violations.

  4. **A length check.** Word count vs the prompt's `word_target`.

  5. **An overall verdict.** APPROVE / REVISE / REJECT plus a
     prioritised list of concrete revision instructions.

Why this exists
---------------
The drafter writes once and is done. A real reviewer reads, scores,
and asks for revisions. The critic plays the reviewer role — and
because its rubric is anchored to the section's own prompt
specification (not a generic checklist), it can give the drafter
back specific, actionable feedback if revision is needed.

Design
------
The critic runs on the CRITIQUE role (Opus 4.7 by default) because
this is high-stakes judgement work where reasoning quality matters
most.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.api_client_manager import APIClientManager, Role, get_manager
from app.prompts import SectionPrompt, get_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Verdict types
# ---------------------------------------------------------------------------
class CritiqueVerdict:
    """High-level outcome of a critique pass."""

    APPROVE = "approve"   # ready to mark as APPROVED
    REVISE = "revise"     # has issues — send back to drafter with specific notes
    REJECT = "reject"     # fundamentally non-compliant — drafter should restart


# ---------------------------------------------------------------------------
# Critique result schema
# ---------------------------------------------------------------------------
@dataclass
class RequirementCheck:
    """One row in the per-requirement compliance check."""

    requirement: str
    status: str         # "met" | "partially_met" | "missing"
    evidence: str       # short justification quoting/pointing to the prose
    severity: str       # "critical" | "major" | "minor"


@dataclass
class CitationCheck:
    """One row in the evidence-faithfulness audit."""

    citation: str           # e.g. "Saghiri et al., 2022"
    in_corpus: bool         # True if matches a chart
    matched_source_id: Optional[str] = None
    issue: Optional[str] = None  # populated when in_corpus is False


@dataclass
class CritiqueResult:
    section_id: str
    verdict: str  # one of CritiqueVerdict
    overall_score: int          # 0-100
    compliance_score: int       # 0-100 — structural requirements
    faithfulness_score: int     # 0-100 — citation + evidence accuracy
    scope_score: int            # 0-100 — stayed within section's lane
    length_score: int           # 0-100 — within word target
    requirement_checks: list[RequirementCheck] = field(default_factory=list)
    citation_checks: list[CitationCheck] = field(default_factory=list)
    revision_notes: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    word_count: int = 0
    word_target: tuple[int, int] = (0, 0)
    model: Optional[str] = None
    error: Optional[str] = None
    critiqued_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        # word_target is a tuple, convert to list for JSON.
        d["word_target"] = list(self.word_target)
        return d


# ---------------------------------------------------------------------------
# Critic system prompt
# ---------------------------------------------------------------------------
CRITIC_SYSTEM_PROMPT = """You are a senior reviewer auditing one section of a PRISMA-ScR-compliant scoping review for a Health Professions Education (HPE) / dental education journal.

You play the role a journal's methods editor plays: you do NOT rewrite the section, you AUDIT it against the specification it was written to. You are rigorous, specific, and unsparing — but constructive.

You will be given:
  - The PRISMA-ScR item the section addresses (with the exact Tricco et al. 2018 wording).
  - The section's full specification: objective, required evidence, structural requirements, word target, scope guardrails.
  - The drafted prose.
  - The charted corpus of included studies (so you can verify citations).

You will return ONE JSON object with this exact schema:

```json
{
  "verdict": "approve | revise | reject",
  "overall_score": 0,
  "compliance_score": 0,
  "faithfulness_score": 0,
  "scope_score": 0,
  "length_score": 0,
  "requirement_checks": [
    {
      "requirement": "<exact text from the spec's structural_requirements>",
      "status": "met | partially_met | missing",
      "evidence": "<short justification, ideally pointing to the prose>",
      "severity": "critical | major | minor"
    }
  ],
  "citation_checks": [
    {
      "citation": "<the author-year string as it appears in the prose>",
      "in_corpus": true,
      "matched_source_id": "<id if matched, otherwise null>",
      "issue": "<null if fine; otherwise describe the problem>"
    }
  ],
  "revision_notes": [
    "<numbered, concrete, actionable instruction for the drafter>"
  ],
  "strengths": [
    "<short statement of what the section does well>"
  ]
}
```

Scoring guidance
----------------
- `compliance_score`: weight by severity. A missing CRITICAL structural requirement zeroes this category; missing MAJOR halves it; missing MINOR docks 10 points each.
- `faithfulness_score`: any citation not present in the charted corpus is a fabrication and brings this to ≤40. Any factual claim about a study that contradicts its chart is also a fabrication.
- `scope_score`: deduct for content that belongs in a different PRISMA-ScR section (e.g. discussing limitations in a Methods section).
- `length_score`: 100 within ±10% of target, declining by 10 points per 10% outside.
- `overall_score`: not a simple average — weight compliance and faithfulness at 35% each, scope at 20%, length at 10%.

Verdict thresholds
------------------
- `approve`: overall_score ≥ 80 AND no CRITICAL requirements missing AND faithfulness_score ≥ 80.
- `reject`: overall_score < 50 OR any fabricated citation OR critical structural failure (e.g. wrong section content).
- `revise`: everything else.

Rules
-----
1. **Be specific.** Every revision note must reference what exactly to add, remove, or change. "Improve the section" is never acceptable.
2. **No prose outside the JSON.** No preamble. No markdown fences around the JSON. Just the JSON object.
3. **Match citations strictly.** "Saghiri et al., 2022" and "Saghiri, 2022" both count as referring to the same study if the corpus contains that first author and year. Spelling variants are acceptable.
4. **Distinguish severity honestly.** Critical = breaks PRISMA-ScR compliance. Major = breaks academic rigour but not compliance. Minor = stylistic or completeness."""


# ---------------------------------------------------------------------------
# JSON repair (shared pattern with extractor)
# ---------------------------------------------------------------------------
def _repair_and_parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    start = raw.find("{")
    if start == -1:
        raise ValueError("No JSON object found in critic output.")

    depth = 0
    end = None
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        raise ValueError("Unbalanced braces in critic output.")

    return json.loads(raw[start:end])


# ---------------------------------------------------------------------------
# Critic agent
# ---------------------------------------------------------------------------
class CriticAgent:
    """
    Audits one drafted section against its PRISMA-ScR specification.

    Usage (called from the Orchestrator)
    -------------------------------------
        critic = CriticAgent()
        result = critic.critique(
            section_id="methods_eligibility",
            drafted_prose="<the prose>",
            project_context={...},
            corpus_charts=[...],
        )
        if result.verdict == CritiqueVerdict.APPROVE:
            mark_section_approved()
    """

    def __init__(self, manager: Optional[APIClientManager] = None):
        self.manager = manager or get_manager()

    # -- public API --------------------------------------------------------
    def critique(
        self,
        section_id: str,
        drafted_prose: str,
        project_context: dict[str, Any],
        corpus_charts: Optional[list[dict]] = None,
    ) -> CritiqueResult:
        try:
            spec = get_prompt(section_id)
        except NotImplementedError as e:
            return CritiqueResult(
                section_id=section_id,
                verdict=CritiqueVerdict.REJECT,
                overall_score=0,
                compliance_score=0,
                faithfulness_score=0,
                scope_score=0,
                length_score=0,
                error=str(e),
            )

        corpus_charts = corpus_charts or []
        included_charts = [
            c for c in corpus_charts
            if (c.get("relevance", {}) or {})
                .get("inclusion_recommendation", "include").lower() == "include"
            and "_extraction_error" not in c
        ]

        user_message = self._build_user_message(
            spec=spec,
            drafted_prose=drafted_prose,
            project_context=project_context,
            corpus_charts=included_charts,
        )

        try:
            response = self.manager.complete(
                role=Role.CRITIQUE,
                system=CRITIC_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:
            logger.exception("Critic API call failed for %s", section_id)
            return CritiqueResult(
                section_id=section_id,
                verdict=CritiqueVerdict.REJECT,
                overall_score=0,
                compliance_score=0,
                faithfulness_score=0,
                scope_score=0,
                length_score=0,
                error=str(e),
            )

        raw = response.content[0].text if response.content else ""
        try:
            parsed = _repair_and_parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("Critic JSON parse failed for %s: %s", section_id, e)
            return CritiqueResult(
                section_id=section_id,
                verdict=CritiqueVerdict.REJECT,
                overall_score=0,
                compliance_score=0,
                faithfulness_score=0,
                scope_score=0,
                length_score=0,
                error=f"JSON parse failed: {e}",
                model=response.model,
            )

        return self._build_result(
            spec=spec,
            parsed=parsed,
            drafted_prose=drafted_prose,
            model=response.model,
        )

    # -- result assembly ---------------------------------------------------
    def _build_result(
        self,
        spec: SectionPrompt,
        parsed: dict,
        drafted_prose: str,
        model: str,
    ) -> CritiqueResult:
        word_count = len(drafted_prose.split())

        requirement_checks = [
            RequirementCheck(
                requirement=str(item.get("requirement", "")),
                status=str(item.get("status", "missing")),
                evidence=str(item.get("evidence", "")),
                severity=str(item.get("severity", "major")),
            )
            for item in parsed.get("requirement_checks", []) or []
        ]
        citation_checks = [
            CitationCheck(
                citation=str(item.get("citation", "")),
                in_corpus=bool(item.get("in_corpus", False)),
                matched_source_id=item.get("matched_source_id"),
                issue=item.get("issue"),
            )
            for item in parsed.get("citation_checks", []) or []
        ]

        return CritiqueResult(
            section_id=spec.section_id,
            verdict=str(parsed.get("verdict", "revise")),
            overall_score=int(parsed.get("overall_score", 0)),
            compliance_score=int(parsed.get("compliance_score", 0)),
            faithfulness_score=int(parsed.get("faithfulness_score", 0)),
            scope_score=int(parsed.get("scope_score", 0)),
            length_score=int(parsed.get("length_score", 0)),
            requirement_checks=requirement_checks,
            citation_checks=citation_checks,
            revision_notes=[str(x) for x in parsed.get("revision_notes", []) or []],
            strengths=[str(x) for x in parsed.get("strengths", []) or []],
            word_count=word_count,
            word_target=spec.word_target,
            model=model,
        )

    # -- prompt assembly ---------------------------------------------------
    def _build_user_message(
        self,
        spec: SectionPrompt,
        drafted_prose: str,
        project_context: dict[str, Any],
        corpus_charts: list[dict],
    ) -> str:
        parts: list[str] = []

        parts.append("## Section under critique")
        parts.append(f"**section_id:** `{spec.section_id}`")
        parts.append(f"**word_count:** {len(drafted_prose.split())} "
                     f"(target: {spec.word_target[0]}–{spec.word_target[1]})")
        parts.append("")

        parts.append("## Project metadata")
        parts.append(f"- Research question: {project_context.get('research_question')}")
        parts.append(f"- Population (P): {project_context.get('population')}")
        parts.append(f"- Concept (C): {project_context.get('concept')}")
        parts.append(f"- Context (C): {project_context.get('context')}")
        parts.append("")

        parts.append("## Section specification (this is what the section was written to)")
        parts.append(spec.render_requirements_block())
        parts.append("")

        # Lean projection of the corpus — just author/year/themes — to keep
        # the context tight for the citation check.
        if corpus_charts:
            projection = []
            for chart in corpus_charts:
                bib = chart.get("bibliographic", {}) or {}
                findings = chart.get("findings", {}) or {}
                projection.append({
                    "first_author": bib.get("first_author"),
                    "year": bib.get("year"),
                    "title": bib.get("title"),
                    "journal": bib.get("journal"),
                    "country": bib.get("country"),
                    "themes": findings.get("themes"),
                    "effect_direction": findings.get("effect_direction"),
                })
            parts.append("## Charted corpus (for citation matching)")
            parts.append(
                "Any author-year cited in the prose must be matchable to "
                "one of these. Spelling variants are acceptable. If a "
                "citation does not match any entry below, flag it as a "
                "fabrication."
            )
            parts.append("```json")
            parts.append(json.dumps(projection, indent=2, ensure_ascii=False))
            parts.append("```")
        else:
            parts.append("## Charted corpus")
            parts.append(
                "_No charted studies. The section under critique should "
                "not contain any author-year citations. If it does, flag "
                "every one as a fabrication._"
            )
        parts.append("")

        parts.append("## Drafted prose to audit")
        parts.append("---")
        parts.append(drafted_prose)
        parts.append("---")
        parts.append("")
        parts.append(
            "Now produce the JSON critique. JSON only, no preamble."
        )

        return "\n".join(parts)
