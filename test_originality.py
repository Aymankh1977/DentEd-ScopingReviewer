"""
Test the originality auditor on the manuscript we already generated.

Usage:
  python tests/test_originality.py <project_id> [folder|project|web]
"""
import sys, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.originality_auditor import audit_project_manuscript  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Usage: python tests/test_originality.py <project_id> [mode]")
        print("  mode: project (default) | folder | web")
        sys.exit(1)

    project_id = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "project"
    folder = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"\n── Auditing project {project_id} (mode={mode}) ──")
    result = audit_project_manuscript(
        project_id=project_id,
        corpus_mode=mode,
        folder_path=folder,
        granularity="both",
    )

    if result.error:
        print(f"❌ {result.error}")
        return

    print(f"\nOverall: {result.overall_score}/100 → {result.overall_verdict}")
    print(f"Corpus size: {result.reference_corpus_size}")
    print(f"\n{result.overall_summary}\n")

    print("Per-section novelty:")
    for s in result.section_reports:
        marker = {"novel": "★", "incremental": "✓", "derivative": "△",
                  "duplicative": "✗"}.get(s.verdict, "?")
        flags = len(s.overlap_matches)
        print(f"  {marker} {s.section_id:32} {s.novelty_score:>3}/100  "
              f"{s.verdict:12} ({flags} overlap flag{'s' if flags!=1 else ''})")

    # Detail any non-trivial overlap flags
    flagged = [s for s in result.section_reports if s.overlap_matches]
    if flagged:
        print("\nOverlap details:")
        for s in flagged:
            print(f"\n  ── {s.section_id} ──")
            for m in s.overlap_matches:
                sev = {"high": "‼", "medium": "!", "low": "·"}.get(m.severity, "?")
                print(f"    {sev} [{m.overlap_type}] vs {m.reference_label}")
                print(f"      {m.overlap_description}")

    # Save full result
    import json
    out = Path(f"data/exports/{project_id}_originality.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    print(f"\n✅ Full report: {out}")


if __name__ == "__main__":
    main()
