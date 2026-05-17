"""
DentEd-ScopingReviewer — Folder-Based Batch Processor (v2)
============================================================
Point at a folder, get a complete PRISMA-ScR scoping review.

Usage:
    python tests/batch_corpus.py <folder> "<research_question>" "<name>" [options]

Examples:
    # Run on the full Scoping AI folder
    python tests/batch_corpus.py ~/Desktop/Scoping\\ AI \\
      "How is AI being integrated into dental education?" \\
      "ai-dental-ed-full"

    # Limit to 10 papers, no auto-critique (faster, cheaper)
    python tests/batch_corpus.py ~/Desktop/Scoping\\ AI \\
      "..." "test-run" --max 10 --no-critique

    # Filter papers by filename pattern
    python tests/batch_corpus.py ~/Desktop/Scoping\\ AI \\
      "..." "competency-only" --pattern "competen|readiness"
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s | %(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import (  # noqa: E402
    Orchestrator, ReviewMode, SectionStatus, PRISMA_SCR_SECTIONS,
)


DEFAULT_PCC = {
    "population": "Undergraduate and postgraduate dental students and educators",
    "concept": "AI tools, frameworks, and curriculum integration",
    "context": "Dental education programmes globally",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="Folder containing PDFs")
    ap.add_argument("research_question", help="The review's research question")
    ap.add_argument("name", help="Human-readable project name")
    ap.add_argument("--population", default=DEFAULT_PCC["population"])
    ap.add_argument("--concept", default=DEFAULT_PCC["concept"])
    ap.add_argument("--context", default=DEFAULT_PCC["context"])
    ap.add_argument("--max", type=int, default=None,
                    help="Max papers to process (default: all)")
    ap.add_argument("--pattern", default=None,
                    help="Regex on filename to include")
    ap.add_argument("--no-critique", action="store_true",
                    help="Skip auto-critique (faster, ~50%% cheaper)")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"❌ Not a directory: {folder}")
        sys.exit(1)

    # Find PDFs (size > 50KB to skip stubs/paywall HTML)
    candidates = sorted(p for p in folder.glob("*.pdf")
                        if p.stat().st_size > 50_000)
    if args.pattern:
        rx = re.compile(args.pattern, re.IGNORECASE)
        candidates = [p for p in candidates if rx.search(p.name)]
    if args.max:
        candidates = candidates[:args.max]

    if not candidates:
        print(f"❌ No qualifying PDFs in {folder}")
        sys.exit(1)

    # Confirm before running
    print(f"\n{'=' * 70}")
    print(f"Batch corpus run")
    print(f"{'=' * 70}")
    print(f"  Folder    : {folder}")
    print(f"  Papers    : {len(candidates)}")
    print(f"  Question  : {args.research_question[:60]}")
    print(f"  Name      : {args.name}")
    print(f"  Critique  : {'OFF' if args.no_critique else 'ON'}")

    est_cost = len(candidates) * 0.05  # extraction
    est_cost += 21 * 0.20  # drafting
    if not args.no_critique:
        est_cost += 21 * 0.40  # critique
    est_minutes = max(3, len(candidates) * 0.3 + (15 if args.no_critique else 25))
    print(f"  Est. cost : ~${est_cost:.0f}")
    print(f"  Est. time : ~{est_minutes:.0f} min")
    print(f"{'=' * 70}\n")

    print("Papers to process:")
    for i, p in enumerate(candidates, 1):
        print(f"  {i:2}. {p.name[:65]:65} ({p.stat().st_size // 1024:>5} KB)")
    print()

    resp = input("Continue? [y/N] ").strip().lower()
    if resp != "y":
        print("Aborted.")
        sys.exit(0)

    # -- Run --
    orch = Orchestrator(auto_critique=not args.no_critique)
    project = orch.start_project(
        mode=ReviewMode.GENERATE,
        name=args.name,
        research_question=args.research_question,
        population=args.population,
        concept=args.concept,
        context=args.context,
    )
    print(f"\n✓ Started project: {project.name} ({project.project_id})")

    print(f"\n── Registering {len(candidates)} sources ──")
    for p in candidates:
        orch.register_source(project, str(p), role="corpus")

    print(f"\n── Extracting ──")
    t0 = time.time()
    orch.extract_all(project)
    print(f"Extraction done in {time.time() - t0:.0f}s")

    included = sum(1 for s in project.sources.values()
                   if (s.extracted_chart or {}).get("relevance", {}).get(
                       "inclusion_recommendation") == "include")
    print(f"Included: {included}/{len(candidates)}")

    print(f"\n── Cascading through 21 sections ──")
    t0 = time.time()
    drafted = orch.draft_all_ready(project, max_iterations=30)
    print(f"Cascade done in {time.time() - t0:.0f}s — {len(drafted)} sections drafted")

    # Summary
    print(f"\n── Final status ──")
    for entry in PRISMA_SCR_SECTIONS:
        sid = entry["id"]
        s = project.sections[sid]
        crit = s.critique or {}
        score = crit.get("overall_score", "")
        verdict = crit.get("verdict", "")
        marker = {
            SectionStatus.CRITIQUED: "✓",
            SectionStatus.APPROVED: "★",
            SectionStatus.REVISION_REQUESTED: "◯",
            SectionStatus.DRAFTED: "✎",
            SectionStatus.PENDING: "·",
            SectionStatus.BLOCKED: "⚠",
            SectionStatus.FAILED: "✗",
        }.get(s.status, "?")
        print(f"  {marker} {sid:32} {s.status.value:12} "
              f"{s.word_count:>4}w  {str(score):>3}/100 {verdict}")

    # Quality metrics
    critiqued = [s for s in project.sections.values()
                 if s.critique and (s.critique or {}).get("overall_score")]
    if critiqued:
        scores = [s.critique["overall_score"] for s in critiqued]
        print(f"\nMean score: {sum(scores) / len(scores):.1f}/100")
        verdicts = [s.critique.get("verdict") for s in critiqued]
        print(f"Verdicts: approve={verdicts.count('approve')}, "
              f"revise={verdicts.count('revise')}, "
              f"reject={verdicts.count('reject')}")

    # Export
    try:
        from tests.export_review import export
        out = export(project.project_id)
        print(f"\n✅ Exported: {out}")
    except Exception as e:
        print(f"⚠ Export failed: {e}")

    print(f"\nProject: {project.name} ({project.project_id})")


if __name__ == "__main__":
    main()
