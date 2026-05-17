"""
Smoke test for the drafter pipeline.
Run from project root:
    python tests/test_drafter_smoke.py path/to/sample.pdf
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
from app.prompts import SECTION_PROMPTS  # noqa: E402


def main(pdf_path: str) -> None:
    orch = Orchestrator()

    # 1. API client status
    print("\n── API client status ──────────────────────────────────────")
    for role, info in orch.manager.status_report().items():
        flag = "✓" if info["configured"] else "✗"
        print(f"  {flag} {role:12} → {info['model']:30} {info['description']}")

    # 2. Implemented section prompts
    print("\n── Implemented section prompts ────────────────────────────")
    for sid in sorted(SECTION_PROMPTS.keys()):
        print(f"  • {sid}")

    # 3. Start a project
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

    # 4. Register + extract
    print("\n── Registering source ─────────────────────────────────────")
    source = orch.register_source(project, path=pdf_path, role="corpus")
    print(f"  {source.filename}")

    print("\n── Running extraction ─────────────────────────────────────")
    orch.extract_all(project)

    chart = project.sources[source.source_id].extracted_chart
    if not chart or "_extraction_error" in chart:
        print("  ❌ Extraction failed — cannot continue.")
        return

    bib = chart.get("bibliographic", {})
    print(f"  Extracted: {bib.get('first_author')} ({bib.get('year')})")

    # 5. Draft methods_eligibility — needs only project metadata, no corpus
    print("\n── Drafting methods_eligibility ───────────────────────────")
    state = orch.draft_section(project, "methods_eligibility")
    _report_section(state)

    # 6. Draft methods_search (depends on methods_information_sources, which
    # we haven't implemented yet — should be NOT ready)
    print("\n── Ready sections after first draft ───────────────────────")
    ready = orch.ready_sections(project)
    for sid in ready:
        print(f"  • {sid}")

    # 7. Force-draft results_characteristics by satisfying its deps
    # (methods_data_charting → methods_eligibility already done).
    # Drive the dependency graph forward as far as it goes.
    print("\n── Drafting all ready (cascading)… ────────────────────────")
    drafted = orch.draft_all_ready(project, max_iterations=10)
    print(f"  Drafted in order: {drafted}")

    # 8. Final status overview
    print("\n── Section status overview ────────────────────────────────")
    for sid, st in project.sections.items():
        if sid not in SECTION_PROMPTS:
            continue
        marker = {
            SectionStatus.DRAFTED: "✓",
            SectionStatus.BLOCKED: "○",
            SectionStatus.FAILED: "✗",
            SectionStatus.PENDING: "·",
        }.get(st.status, "?")
        wc = f"{st.word_count}w" if st.word_count else ""
        print(f"  {marker} {sid:32} {st.status.value:10} {wc}")

    # 9. Print one drafted section's prose for inspection
    drafted_state = project.sections.get("methods_eligibility")
    if drafted_state and drafted_state.draft:
        print("\n── Drafted methods_eligibility ────────────────────────────\n")
        print(drafted_state.draft)
        print()

    saved = orch.save(project)
    print(f"\n✅ Project state saved to {saved}")


def _report_section(state) -> None:
    print(f"  status: {state.status.value}")
    if state.status == SectionStatus.DRAFTED:
        print(f"  words : {state.word_count}")
        first_lines = "\n".join(state.draft.splitlines()[:6])
        print("  preview:")
        for line in first_lines.splitlines():
            print(f"    {line}")
    elif state.status == SectionStatus.BLOCKED:
        print(f"  missing: {state.missing_evidence}")
    elif state.status == SectionStatus.FAILED:
        print(f"  error  : {state.error}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tests/test_drafter_smoke.py <path-to-pdf>")
        sys.exit(1)
    main(sys.argv[1])
