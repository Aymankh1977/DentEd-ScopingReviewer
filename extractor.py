"""
DentEdTech-ScopingReviewer™ — Extractor Agent
=========================================
Performs PRISMA-ScR data charting (Items 10–11) from uploaded sources.

What "data charting" means in PRISMA-ScR
----------------------------------------
> "Describe the methods of charting data from the included sources of
>  evidence (e.g. calibrated forms or forms that have been tested by the
>  team before their use, and whether data charting was done independently
>  or in duplicate) and any processes for obtaining and confirming data
>  from investigators."
>                — Tricco et al. 2018, Item 10

In practice this means filling a structured form, per study, capturing
authorship, year, country, design, participants, intervention,
comparator, outcomes, key findings, themes, and notable limitations.

This agent is deliberately conservative:
  - Returns **NULL** when a field is genuinely absent (not a guess).
  - Quotes verbatim only when wording matters (e.g. eligibility
    criteria, primary outcome definitions); keeps quotes short and
    flagged so the drafter knows what came directly from the source.
  - Records page-level provenance so every extracted item can be traced.

It runs on the EXTRACTION role (cheap, fast model) since this is a
high-volume, low-judgement task.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.agents.api_client_manager import APIClientManager, Role, get_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception so the orchestrator can show a friendly message
# ---------------------------------------------------------------------------
class InvalidPDFError(Exception):
    """Raised when an uploaded file is not a usable PDF."""


# ---------------------------------------------------------------------------
# Schema for an extracted chart
# ---------------------------------------------------------------------------
EXTRACTION_SCHEMA = {
    "bibliographic": {
        "title": "string",
        "first_author": "string",
        "all_authors": "string",
        "year": "integer or null",
        "journal": "string",
        "country": "string",
        "doi": "string or null",
    },
    "study_design": {
        "design_type": "string (RCT / cohort / cross-sectional / qualitative / scoping review / etc.)",
        "setting": "string",
        "intervention_type": "string or null",
        "comparator": "string or null",
        "theoretical_framework": "string or null",
    },
    "participants": {
        "sample_size": "integer or null",
        "population": "string (e.g. 4th & 5th year dental students)",
        "country_of_participants": "string",
        "recruitment": "string",
    },
    "methods": {
        "data_collection": "string",
        "outcome_measures": "list of strings",
        "analysis_approach": "string",
        "quality_assessment": "string or null",
    },
    "findings": {
        "key_findings": "list of 3-7 concise bullet strings",
        "effect_direction": "string (positive / negative / mixed / no effect / n/a)",
        "themes": "list of short theme labels",
    },
    "limitations": {
        "reported_limitations": "list of strings",
        "risk_of_bias_notes": "string or null",
    },
    "relevance": {
        "relevance_to_question": "string (how it speaks to the review question)",
        "relevance_score": "integer 1-5",
        "inclusion_recommendation": "string (include / exclude / unclear)",
        "exclusion_reason": "string or null",
    },
    "provenance": {
        "pages_referenced": "list of integers",
        "verbatim_eligibility_quote": "string or null (≤25 words, used sparingly)",
    },
}


EXTRACTOR_SYSTEM_PROMPT = """You are a meticulous PRISMA-ScR data extractor working on a scoping review in Health Professions Education (HPE) and dental education.

Your job is to read a single research paper and fill a structured data-charting form. You follow these rules without exception:

1. **Faithfulness over fluency.** Only chart what the paper actually states. If a field is genuinely not reported, return the JSON value null — never guess, never paraphrase a missing fact into an existing one.

2. **Short verbatim quotes only where wording carries meaning.** Eligibility criteria, primary outcome definitions, and explicit theoretical positions may be quoted verbatim, but each quote must be 25 words or fewer and clearly flagged with quotation marks.

3. **Provenance.** Record the page numbers where each major fact was found. If the paper isn't paginated, record the section heading instead.

4. **Relevance.** Score the paper's relevance to the review's research question on a 1–5 integer scale and recommend include / exclude / unclear. If excluding, state the PRISMA-ScR-style reason concisely (e.g. "not dental education", "secondary review only", "no original findings").

5. **JSON only.** Return ONE JSON object that conforms exactly to the schema you will be given. No prose preamble, no markdown fences, no trailing commentary.

6. **Conservative themes.** Theme labels must be short noun phrases (2–5 words) drawn from the paper's own framing, not invented categories. If a theme is implicit but obvious, you may infer it but mark it with the prefix "[inferred]".

You will be given:
  - The paper's full extracted text (which may be imperfect OCR).
  - The review's research question, population, concept, and context (PCC).
  - The required JSON schema.

You will respond with ONE JSON object only."""


# ---------------------------------------------------------------------------
# Pre-flight PDF validation
# ---------------------------------------------------------------------------
_MIN_PDF_BYTES = 10_240  # 10 KB — anything smaller is almost certainly not a real paper

def _validate_pdf_file(path: Path) -> None:
    """
    Inspect the file BEFORE handing it to pypdf/pdfplumber. We can give
    much more actionable errors at this stage than the libraries can.

    Catches:
      - missing files
      - empty / tiny files (paywall pages, error stubs)
      - HTML content that pretends to be a PDF
      - files whose magic bytes are not %PDF-
    """
    if not path.exists():
        raise InvalidPDFError(
            f"File does not exist: {path}\n"
            f"   Tip: check spelling, escape spaces, and use an absolute path."
        )

    if not path.is_file():
        raise InvalidPDFError(f"Not a file: {path}")

    size = path.stat().st_size
    if size == 0:
        raise InvalidPDFError(f"File is empty (0 bytes): {path.name}")

    if size < _MIN_PDF_BYTES:
        raise InvalidPDFError(
            f"File is suspiciously small ({size:,} bytes): {path.name}\n"
            f"   A real journal PDF is usually 200 KB – 2 MB.\n"
            f"   Likely cause: a paywall HTML page was downloaded instead "
            f"of the PDF. Try downloading the paper manually from your "
            f"institution's library, or from PubMed Central / a "
            f"preprint server."
        )

    with path.open("rb") as fh:
        head = fh.read(1024)

    # PDF magic bytes are "%PDF-" — anything else is not a PDF.
    if not head.startswith(b"%PDF-"):
        # Try to detect what it actually is for a better error message.
        head_str = head[:200].decode("latin-1", errors="replace").lower()
        if any(marker in head_str for marker in ("<!doctype", "<html", "<head", "<body")):
            raise InvalidPDFError(
                f"File looks like HTML, not a PDF: {path.name}\n"
                f"   This usually happens when curl/wget hits a paywall "
                f"or login page instead of the actual PDF. Open the URL "
                f"in a browser, log in if needed, then save the real PDF "
                f"via 'Save as'."
            )
        raise InvalidPDFError(
            f"File does not start with %PDF- magic bytes: {path.name}\n"
            f"   First 80 bytes: {head[:80]!r}\n"
            f"   This file is not a valid PDF. It may be corrupted or "
            f"saved in another format."
        )


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------
def _extract_pdf_text(path: str | Path, max_chars: int = 120_000) -> tuple[str, int]:
    """
    Pull text from a PDF using pypdf, with pdfplumber as a fallback for
    pages where pypdf returns nothing useful.

    Returns (text, page_count).
    """
    path = Path(path)

    # Pre-flight check — fail fast with a helpful message.
    _validate_pdf_file(path)

    text_parts: list[str] = []
    page_count = 0

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        for i, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(f"\n[Page {i}]\n{page_text}")
    except Exception as e:
        logger.warning("pypdf failed for %s: %s — falling back to pdfplumber.",
                       path.name, e)

    if not text_parts or sum(len(t) for t in text_parts) < 500:
        try:
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                page_count = len(pdf.pages)
                text_parts = []
                for i, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"\n[Page {i}]\n{page_text}")
        except Exception as e:
            logger.error("pdfplumber also failed for %s: %s", path.name, e)
            raise InvalidPDFError(
                f"Could not extract text from {path.name}: {e}\n"
                f"   This PDF may be scanned (image-only) and require OCR, "
                f"or it may be corrupted."
            )

    full = "\n".join(text_parts)
    if len(full) > max_chars:
        head = full[: max_chars // 2]
        tail = full[-max_chars // 2 :]
        full = head + "\n\n[... text truncated for context window ...]\n\n" + tail

    return full, page_count


# ---------------------------------------------------------------------------
# JSON repair (lightweight) — same pattern used in your DentEdTech audit
# ---------------------------------------------------------------------------
def _repair_and_parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    start = raw.find("{")
    if start == -1:
        raise ValueError("No JSON object found in extractor output.")

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
        raise ValueError("Unbalanced braces in extractor output.")

    return json.loads(raw[start:end])


@dataclass
class ExtractionResult:
    chart: dict
    page_count: int
    char_count: int
    raw_model_output: str
    truncated: bool


class ExtractorAgent:
    """
    Performs PRISMA-ScR data charting for a single source.
    """

    def __init__(self, manager: Optional[APIClientManager] = None):
        self.manager = manager or get_manager()

    def extract_chart(
        self,
        source_path: str | Path,
        project_context: dict[str, Any],
    ) -> dict:
        """Extract one source. Returns the raw chart dict (not the wrapper)."""
        try:
            result = self.extract_chart_detailed(source_path, project_context)
            return result.chart
        except InvalidPDFError as e:
            # Surface a structured error so downstream agents can skip
            # this source instead of crashing the whole project.
            logger.error("Invalid PDF for %s: %s", Path(source_path).name, e)
            return {
                "_extraction_error": str(e),
                "_error_type": "invalid_pdf",
            }

    def extract_chart_detailed(
        self,
        source_path: str | Path,
        project_context: dict[str, Any],
    ) -> ExtractionResult:
        text, pages = _extract_pdf_text(source_path)
        truncated = "[... text truncated for context window ...]" in text

        user_msg = self._build_user_message(text, project_context)
        response = self.manager.complete(
            role=Role.EXTRACTION,
            system=EXTRACTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw = response.content[0].text if response.content else ""
        try:
            chart = _repair_and_parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("Extractor JSON parse failed for %s: %s",
                         Path(source_path).name, e)
            chart = {
                "_extraction_error": str(e),
                "_raw_excerpt": raw[:2000],
            }

        return ExtractionResult(
            chart=chart,
            page_count=pages,
            char_count=len(text),
            raw_model_output=raw,
            truncated=truncated,
        )

    def _build_user_message(
        self,
        paper_text: str,
        project_context: dict[str, Any],
    ) -> str:
        return (
            "## Review context (PCC framework)\n"
            f"- **Research question:** {project_context.get('research_question', 'n/a')}\n"
            f"- **Population:** {project_context.get('population', 'n/a')}\n"
            f"- **Concept:** {project_context.get('concept', 'n/a')}\n"
            f"- **Context:** {project_context.get('context', 'n/a')}\n"
            f"- **Mode:** {project_context.get('mode', 'generate')}\n\n"
            "## Required JSON schema\n"
            "Return ONE JSON object with the following structure. "
            "Use null for absent fields, integers where indicated, "
            "and lists of short strings where indicated.\n\n"
            f"```json\n{json.dumps(EXTRACTION_SCHEMA, indent=2)}\n```\n\n"
            "## Paper text\n"
            "Below is the extracted text of the paper, with page markers "
            "in `[Page N]` form. OCR may be imperfect — use surrounding "
            "context where individual characters look wrong.\n\n"
            "---\n"
            f"{paper_text}\n"
            "---\n\n"
            "Now return ONE JSON object that fills the schema for this paper. "
            "JSON only, no prose."
        )

    def extract_batch(
        self,
        source_paths: list[str | Path],
        project_context: dict[str, Any],
    ) -> dict[str, ExtractionResult]:
        results: dict[str, ExtractionResult] = {}
        for path in source_paths:
            name = Path(path).name
            logger.info("Extracting %s…", name)
            try:
                results[name] = self.extract_chart_detailed(path, project_context)
            except Exception as e:
                logger.error("Extraction failed for %s: %s", name, e)
                results[name] = ExtractionResult(
                    chart={"_extraction_error": str(e)},
                    page_count=0,
                    char_count=0,
                    raw_model_output="",
                    truncated=False,
                )
        return results
