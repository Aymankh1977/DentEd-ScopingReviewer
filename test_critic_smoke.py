"""
Smoke test for the critic + revision loop.
Run from project root:
    python tests/test_critic_smoke.py path/to/sample.pdf
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import Orchestrator, ReviewMode, SectionStatus  # noqa: E402


def main(pdf_path: str) -> None:
    orch = Orchestrator(auto_critique=True)

    print("\n── Starting project ───────────────────────────────────────")
    project = orch.start_project(
        mode=ReviewMode.GENERATE,
        research_question=(
            "How is artificial intelligence being integrated into "
            "undergraduate dental education?"
        ),
        population="Undergraduate dental students and dental educators",
        concept="AI tools for teaching, assessment, and feedback",
        context="Undergraduate dental education globally, 2018–present",
    )
    print(f"  project_id = {project.project_id}")

    print("\n── Registering + extracting ───────────────────────────────")
    source = orch.register_source(project, path=pdf_path, role="corpus")
    print(f"  {source.filename}")
    orch.extract_all(project)
    chart = project.sources[source.source_id].extracted_chart
    if not chart or "_extraction_error" in chart:
        print("  ❌ Extraction failed.")
        return

    bib = chart.get("bibliographic", {}) or {}
    print(f"  Extracted: {bib.get('first_author')} ({bib.get('year')})")

    print("\n── Drafting + auto-critiquing methods_eligibility ─────────")
    state = orch.draft_section(project, "methods_eligibility")
    print(f"  draft status   : {state.status.value}")
    print(f"  word count     : {state.word_count}")

    crit = state.critique or {}
    print(f"  critique verdict      : {crit.get('verdict')}")
    print(f"  overall_score         : {crit.get('overall_score')}/100")
    print(f"  compliance_score      : {crit.get('compliance_score')}/100")
    print(f"  faithfulness_score    : {crit.get('faithfulness_score')}/100")
    print(f"  scope_score           : {crit.get('scope_score')}/100")
    print(f"  length_score          : {crit.get('length_score')}/100")

    print("\n  Per-requirement check:")
    for r in crit.get("requirement_checks", []):
        marker = {"met": "✓", "partially_met": "△", "missing": "✗"}.get(
            r.get("status"), "?"
        )
        sev = r.get("severity", "")
        req = (r.get("requirement", "") or "")[:78]
        print(f"    {marker} [{sev:>8}] {req}")

    if crit.get("citation_checks"):
        print("\n  Citation faithfulness:")
        for c in crit["citation_checks"]:
            marker = "✓" if c.get("in_corpus") else "✗"
            note = "" if c.get("in_corpus") else f" — {c.get('issue', 'no match')}"
            print(f"    {marker} {c.get('citation')}{note}")

    if crit.get("strengths"):
        print("\n  Strengths:")
        for s in crit["strengths"]:
            print(f"    • {s}")

    if crit.get("revision_notes"):
        print("\n  Revision notes:")
        for i, note in enumerate(crit["revision_notes"], 1):
            print(f"    {i}. {note}")

    # If the critic asked for revisions, run one revision cycle.
    if state.status == SectionStatus.REVISION_REQUESTED:
        print("\n── Running one revision pass ──────────────────────────────")
        revised = orch.revise_section(project, "methods_eligibility")
        print(f"  revised status        : {revised.status.value}")
        print(f"  iteration             : {revised.iteration}")
        new_crit = revised.critique or {}
        print(f"  new overall_score     : {new_crit.get('overall_score')}/100")
        print(f"  new verdict           : {new_crit.get('verdict')}")

    saved = orch.save(project)
    print(f"\n✅ Project state saved to {saved}")
    print()
    print("Inspect full critique JSON at:")
    print(f"   {Path(project.workspace_dir) / 'project.json'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tests/test_critic_smoke.py <path-to-pdf>")
        sys.exit(1)
    main(sys.argv[1])
