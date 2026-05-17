"""
Smoke test for orchestrator + extractor.
Run from project root:
    python tests/test_orchestrator_smoke.py path/to/sample.pdf
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

# Make `app` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import Orchestrator, ReviewMode  # noqa: E402


def main(pdf_path: str) -> None:
    orch = Orchestrator()

    # 1. Print API client status — should show which keys are loaded.
    print("\n── API client status ──────────────────────────────────────")
    for role, info in orch.manager.status_report().items():
        flag = "✓" if info["configured"] else "✗"
        print(f"  {flag} {role:12} → {info['model']:30} {info['description']}")

    # 2. Start a project.
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
    print(f"  workspace  = {project.workspace_dir}")

    # 3. Register the test source.
    print("\n── Registering source ─────────────────────────────────────")
    source = orch.register_source(project, path=pdf_path, role="corpus")
    print(f"  source_id  = {source.source_id}")
    print(f"  filename   = {source.filename}")

    # 4. Extract.
    print("\n── Running extraction ─────────────────────────────────────")
    orch.extract_all(project)

    chart = project.sources[source.source_id].extracted_chart
    if not chart:
        print("  ⚠️  No chart returned.")
        return

    if "_extraction_error" in chart:
        print(f"  ❌ Extraction error: {chart['_extraction_error']}")
        print(f"  Raw excerpt: {chart.get('_raw_excerpt', '')[:500]}")
        return

    # 5. Pretty-print the highlights.
    print("\n── Extracted chart ────────────────────────────────────────")
    bib = chart.get("bibliographic", {})
    print(f"  Title       : {bib.get('title')}")
    print(f"  Author      : {bib.get('first_author')} ({bib.get('year')})")
    print(f"  Journal     : {bib.get('journal')}")

    design = chart.get("study_design", {})
    print(f"  Design      : {design.get('design_type')}")

    parts = chart.get("participants", {})
    print(f"  N           : {parts.get('sample_size')}")
    print(f"  Population  : {parts.get('population')}")

    findings = chart.get("findings", {})
    print(f"  Themes      : {findings.get('themes')}")
    print(f"  Key findings:")
    for kf in findings.get("key_findings", []) or []:
        print(f"    • {kf}")

    relevance = chart.get("relevance", {})
    print(f"  Relevance   : {relevance.get('relevance_score')}/5 "
          f"→ {relevance.get('inclusion_recommendation')}")

    # 6. Check ready sections (none should be ready yet — extraction only
    #    unlocks the methods/results section that depend on charted data).
    print("\n── Sections ready to draft ────────────────────────────────")
    ready = orch.ready_sections(project)
    for sid in ready:
        print(f"  • {sid}")

    saved = orch.save(project)
    print(f"\n✅ Project state saved to {saved}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tests/test_orchestrator_smoke.py <path-to-pdf>")
        sys.exit(1)
    main(sys.argv[1])
