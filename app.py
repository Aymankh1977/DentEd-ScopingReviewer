"""
DentEdTech-ScopingReviewer™ — Streamlit UI (v2)
=============================================
Major upgrades over v1:
  • Project names (no more hex-only IDs in sidebar)
  • Manuscript Critique tab actually works — upload PDF, get full audit
  • Bulk corpus upload (no 5-paper limit)
  • Better sidebar listing showing name + ID + status
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import streamlit as st

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.orchestrator import (
    Orchestrator, ReviewMode, SectionStatus, PRISMA_SCR_SECTIONS,
)
from app.agents.api_client_manager import get_manager
from app.agents.originality_auditor import (
    OriginalityAuditor, audit_project_manuscript,
)
from app.agents.manuscript_critique import ManuscriptCritiqueAgent
from app.prompts import SECTION_PROMPTS

logging.basicConfig(level=logging.INFO)

APP_VERSION = "0.2.0"
WORKSPACE_ROOT = Path("data/processed")
EXPORT_ROOT = Path("data/exports")
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
EXPORT_ROOT.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="DentEdTech-ScopingReviewer™", page_icon="🦷",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.stApp { background-color: #fbf8f3; }
h1, h2, h3 { font-family: 'Playfair Display', Georgia, serif; color: #2c4a5a; }
[data-testid="stSidebar"] { background-color: #2c4a5a; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] label { color: #f2ede4 !important; }
.metric-pill {
    display: inline-block; padding: 4px 12px; border-radius: 12px;
    font-size: 0.85em; margin: 2px; font-weight: 600;
}
.pill-approve { background-color: #d4edda; color: #155724; }
.pill-revise  { background-color: #fff3cd; color: #856404; }
.pill-reject  { background-color: #f8d7da; color: #721c24; }
.pill-pending { background-color: #e9ecef; color: #495057; }
.pill-novel       { background-color: #d4edda; color: #155724; }
.pill-incremental { background-color: #fff3cd; color: #856404; }
.pill-derivative  { background-color: #f8d7da; color: #721c24; }
.pill-duplicative { background-color: #f5c6cb; color: #721c24; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "active_project_id" not in st.session_state:
    st.session_state.active_project_id = None
if "orch" not in st.session_state:
    st.session_state.orch = Orchestrator(auto_critique=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _save_uploaded(file, prefix: str = "upload") -> str:
    suffix = Path(file.name).suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix,
                                       prefix=f"{prefix}_")
    tmp.write(file.getbuffer())
    tmp.close()
    return tmp.name


def _list_projects() -> list[dict]:
    """Return projects sorted by updated_at desc with name+id+stats."""
    rows: list[dict] = []
    for d in sorted(WORKSPACE_ROOT.iterdir(),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True):
        if not d.is_dir():
            continue
        pf = d / "project.json"
        if not pf.exists():
            continue
        try:
            data = json.loads(pf.read_text())
        except Exception:
            continue
        sections = data.get("sections", {})
        drafted = sum(1 for s in sections.values() if s.get("draft"))
        rows.append({
            "id": data.get("project_id", d.name),
            "name": data.get("name", f"project-{d.name[:6]}"),
            "rq": (data.get("research_question") or "")[:60],
            "drafted": drafted,
            "sources": len(data.get("sources", {})),
        })
    return rows


def _pill(value: str, score: int | None = None) -> str:
    label = value.upper() if value else "—"
    if score is not None:
        label = f"{score}/100 · {label}"
    css = {
        "approve": "pill-approve", "revise": "pill-revise", "reject": "pill-reject",
        "novel": "pill-novel", "incremental": "pill-incremental",
        "derivative": "pill-derivative", "duplicative": "pill-duplicative",
    }.get(value, "pill-pending")
    return f'<span class="metric-pill {css}">{label}</span>'


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🦷 DentEdTech-ScopingReviewer™")
    st.caption(f"v{APP_VERSION} · PRISMA-ScR-compliant")
    st.divider()

    st.subheader("API roles")
    try:
        for role, info in get_manager().status_report().items():
            flag = "✓" if info["configured"] else "✗"
            st.caption(f"{flag} **{role}** · {info['model']}")
    except Exception as e:
        st.error(f"API: {e}")

    st.divider()
    st.subheader("Projects")
    projects = _list_projects()
    if projects:
        labels = {p["id"]: f"{p['name']} · {p['drafted']}/21 sections "
                          f"· {p['sources']} sources"
                  for p in projects}
        ids = list(labels.keys())
        current = (ids.index(st.session_state.active_project_id)
                   if st.session_state.active_project_id in ids else 0)
        selected = st.selectbox(
            "Active project",
            options=ids, format_func=lambda x: labels[x], index=current,
        )
        st.session_state.active_project_id = selected
        chosen = next(p for p in projects if p["id"] == selected)
        st.caption(f"**RQ:** {chosen['rq']}…")
        st.caption(f"**ID:** `{selected}`")
    else:
        st.caption("No projects yet.")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "📝 New Review", "🔍 Critique a Manuscript",
    "📚 Project Workspace", "✨ Originality Audit",
])


# ============================================================================
# TAB 1: New Review
# ============================================================================
with tab1:
    st.header("Generate a new scoping review")
    st.caption("Upload corpus → PRISMA-ScR cascade through all 21 sections.")

    with st.form("new_project"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Project name",
                                  placeholder="e.g. ai-dental-curriculum-2025")
            rq = st.text_area("Research question",
                              placeholder="What empirical evidence...",
                              height=80)
            population = st.text_input("Population (P)")
            concept = st.text_input("Concept (C)")
            context = st.text_input("Context (C)")
        with col2:
            uploads = st.file_uploader(
                "Upload corpus PDFs (no limit)",
                accept_multiple_files=True, type=["pdf"])
            auto_critique = st.checkbox("Auto-critique each section", value=True)
            full_cascade = st.checkbox("Cascade through all 21 sections", value=True)

        with st.expander("📋 Review administration details (strongly recommended)"):
            st.caption("These are used directly in Methods, Funding, and Abstract sections — "
                       "providing them now avoids placeholder text in the manuscript.")
            mc1, mc2 = st.columns(2)
            with mc1:
                reg_platform = st.selectbox("Protocol registration platform",
                    ["None / not registered", "Open Science Framework (OSF)",
                     "PROSPERO", "JBI", "Other"])
                reg_number  = st.text_input("Registration number", placeholder="e.g. OSF: 10.17605/...")
                reg_url     = st.text_input("Registration URL (optional)")
                last_search = st.text_input("Date of last database search", placeholder="e.g. March 2024")
                date_range  = st.text_input("Eligibility date range", placeholder="e.g. 2015–2024")
                lang_rest   = st.text_input("Language restriction", placeholder="e.g. English only")
            with mc2:
                screening_tool  = st.text_input("Screening tool", placeholder="e.g. Rayyan, Covidence, Excel")
                n_reviewers     = st.text_input("Number of independent reviewers", placeholder="e.g. 2")
                conflict_res    = st.text_input("Conflict resolution method",
                                                placeholder="e.g. consensus / third reviewer")
                funding_src     = st.text_input("Funding source",
                                                placeholder="e.g. Unfunded / Grant agency name")
                grant_num       = st.text_input("Grant number (if funded)", placeholder="e.g. WT123456")
                coi             = st.text_input("Conflicts of interest",
                                                placeholder="e.g. The authors declare no conflicts of interest.")
                authors         = st.text_area("Authors & affiliations (optional)",
                                               placeholder="e.g. Smith J¹, Jones A²...", height=60)

        submit = st.form_submit_button("🚀 Start review", type="primary")

    if submit:
        if not (name and rq and population and concept and context and uploads):
            st.error("Fill all fields and upload at least one PDF.")
        else:
            meta = {
                "registration_platform": reg_platform if reg_platform != "None / not registered" else "",
                "registration_number": reg_number,
                "registration_url": reg_url,
                "last_search_date": last_search,
                "eligibility_date_range": date_range,
                "language_restriction": lang_rest,
                "screening_tool": screening_tool,
                "n_reviewers": n_reviewers,
                "conflict_resolution": conflict_res,
                "funding_source": funding_src,
                "grant_number": grant_num,
                "conflicts_of_interest": coi,
                "authors": authors,
            }
            orch = Orchestrator(auto_critique=auto_critique)
            with st.spinner("Starting project..."):
                project = orch.start_project(
                    mode=ReviewMode.GENERATE, name=name,
                    research_question=rq, population=population,
                    concept=concept, context=context,
                    metadata={k: v for k, v in meta.items() if v},
                )
                st.session_state.active_project_id = project.project_id

            st.success(f"Created project **{project.name}** (`{project.project_id}`)")

            progress = st.progress(0.0, text="Registering PDFs…")
            for i, f in enumerate(uploads):
                path = _save_uploaded(f, "corpus")
                orch.register_source(project, path, role="corpus", filename=f.name)
                progress.progress((i + 1) / len(uploads),
                                  text=f"Registered {f.name}")

            extract_bar = st.progress(0.0, text="Extracting PDF 1…")
            sources_list = list(project.sources.values())
            from app.agents.extractor import ExtractorAgent
            extractor = ExtractorAgent(orch.manager)
            ctx = orch._project_context(project)
            for i, source in enumerate(sources_list):
                extract_bar.progress((i + 0.5) / len(sources_list),
                                     text=f"Extracting {source.filename}…")
                if source.extracted_chart is None:
                    source.extracted_chart = extractor.extract_chart(
                        source_path=source.path, project_context=ctx)
                extract_bar.progress((i + 1) / len(sources_list),
                                     text=f"✓ {source.filename}")
            orch.save(project)

            included = sum(
                1 for s in project.sources.values()
                if (s.extracted_chart or {}).get("relevance", {}).get(
                    "inclusion_recommendation") == "include")
            st.info(f"Extracted {len(uploads)} papers · {included} marked for inclusion.")

            if full_cascade:
                section_status_area = st.empty()
                drafted_log: list[str] = []

                def _cascade_with_progress(proj, orch_inst):
                    from app.agents.orchestrator import (
                        COMPLETED_STATUSES, SectionStatus, PRISMA_SCR_SECTIONS,
                    )
                    revision_counts: dict[str, int] = {}
                    for _iter in range(40):
                        ready = orch_inst.ready_sections(proj)
                        for sid in ready:
                            section_status_area.info(
                                f"✍️ Drafting **{sid}** "
                                f"({len(drafted_log)+1}/21)…")
                            orch_inst.draft_section(proj, sid,
                                                    auto_critique=auto_critique)
                            if proj.sections[sid].status in COMPLETED_STATUSES:
                                drafted_log.append(sid)
                        revise_cands = [
                            sid for sid, st_ in proj.sections.items()
                            if st_.status == SectionStatus.REVISION_REQUESTED
                            and revision_counts.get(sid, 0) < 2
                        ]
                        for sid in revise_cands:
                            revision_counts[sid] = revision_counts.get(sid, 0) + 1
                            section_status_area.info(
                                f"🔁 Revising **{sid}** "
                                f"(attempt {revision_counts[sid]}/2)…")
                            orch_inst.revise_section(proj, sid)
                        if not ready and not revise_cands:
                            break

                _cascade_with_progress(project, orch)
                section_status_area.empty()
                st.success(f"Drafted {len(drafted_log)}/21 sections: "
                           f"{', '.join(drafted_log)}")
            st.rerun()


# ============================================================================
# TAB 2: Critique a Manuscript  (NEW — fully working)
# ============================================================================
with tab2:
    st.header("Critique an existing manuscript")
    st.caption("Upload any PDF manuscript. The platform parses it into "
               "PRISMA-ScR sections, audits each, and runs originality "
               "checks against a reference corpus you supply.")

    with st.form("ms_critique"):
        col1, col2 = st.columns(2)
        with col1:
            ms_file = st.file_uploader("Manuscript PDF", type=["pdf"])
            ref_mode = st.radio("Reference corpus source",
                                ["Upload comparison PDFs",
                                 "Use existing project's corpus",
                                 "No corpus (originality vs training only)"])
            run_critic = st.checkbox("Run per-section critic", value=True)
            run_orig = st.checkbox("Run originality audit", value=True)

        with col2:
            ref_files = st.file_uploader(
                "Comparison PDFs (for option 1)",
                accept_multiple_files=True, type=["pdf"], key="refs")
            ref_project = st.selectbox(
                "Or pick project (for option 2)",
                options=["— none —"] +
                        [p["id"] for p in _list_projects()],
                format_func=lambda x: next(
                    (p["name"] for p in _list_projects() if p["id"] == x),
                    x))
            granularity = st.radio("Originality granularity",
                                    ["both", "section", "whole"],
                                    horizontal=True)

            rq_field = st.text_input(
                "Manuscript's research question (helps the critic)",
                placeholder="(optional)")

        go = st.form_submit_button("🔍 Critique", type="primary")

    if go:
        if not ms_file:
            st.error("Upload a manuscript PDF.")
        elif not (run_critic or run_orig):
            st.error("Enable at least one check.")
        else:
            ms_path = _save_uploaded(ms_file, "manuscript")

            # Build reference corpus
            ref_corpus: list[dict] = []
            with st.spinner("Preparing reference corpus..."):
                if ref_mode == "Upload comparison PDFs" and ref_files:
                    from app.agents.extractor import ExtractorAgent
                    extractor = ExtractorAgent()
                    ctx = {"research_question": rq_field or "general",
                           "population": "", "concept": "", "context": "",
                           "mode": "critique"}
                    for f in ref_files:
                        p = _save_uploaded(f, "ref")
                        chart = extractor.extract_chart(p, ctx)
                        if "_extraction_error" not in chart:
                            ref_corpus.append(chart)
                elif ref_mode == "Use existing project's corpus" and ref_project != "— none —":
                    orch = Orchestrator()
                    proj = orch.load(ref_project)
                    ref_corpus = [s.extracted_chart
                                  for s in proj.sources.values()
                                  if s.extracted_chart and
                                  "_extraction_error" not in s.extracted_chart]

            st.info(f"Reference corpus: {len(ref_corpus)} sources")

            project_ctx = {
                "research_question": rq_field or
                "(not specified by user — critique on PRISMA-ScR rubric only)",
                "population": "", "concept": "", "context": "",
                "mode": "critique",
            }

            with st.spinner("Parsing manuscript and running checks..."):
                agent = ManuscriptCritiqueAgent()
                result = agent.critique_pdf(
                    pdf_path=ms_path,
                    reference_corpus=ref_corpus,
                    project_context=project_ctx,
                    run_critic=run_critic,
                    run_originality=run_orig,
                    granularity=granularity,
                )

            st.success(f"Critique complete for **{result.manuscript_filename}**")

            # Show parse results
            with st.expander(f"Parsed {len(result.sections_parsed)} sections "
                             f"from the manuscript"):
                for sid, prose in result.sections_parsed.items():
                    st.caption(f"**{sid}** · {len(prose.split())} words")

            if result.parse_errors:
                for e in result.parse_errors:
                    st.warning(e)

            # Critic reports
            if result.critic_reports:
                st.subheader("Per-section critique")
                for sid, crit in result.critic_reports.items():
                    score = crit.get("overall_score", 0)
                    verdict = crit.get("verdict", "")
                    cols = st.columns([3, 2])
                    cols[0].write(f"**{sid}**")
                    cols[1].markdown(_pill(verdict, score),
                                      unsafe_allow_html=True)
                    if crit.get("revision_notes"):
                        with st.expander(f"💬 {sid} feedback "
                                         f"({len(crit['revision_notes'])} notes)"):
                            if crit.get("strengths"):
                                st.markdown("**Strengths**")
                                for s in crit["strengths"]:
                                    st.markdown(f"- {s}")
                            st.markdown("**Revision notes**")
                            for i, n in enumerate(crit["revision_notes"], 1):
                                st.markdown(f"{i}. {n}")

            # Originality
            if result.originality_report:
                rep = result.originality_report
                st.subheader("Originality audit")
                c1, c2 = st.columns([1, 3])
                with c1:
                    st.metric("Overall", f"{rep.get('overall_score', 0)}/100")
                    st.markdown(_pill(rep.get("overall_verdict", "")),
                                 unsafe_allow_html=True)
                with c2:
                    st.markdown(f"**Summary:** {rep.get('overall_summary', '')}")

                for sr in rep.get("section_reports", []) or []:
                    if sr.get("overlap_matches"):
                        with st.expander(
                            f"⚠ {sr['section_id']} · "
                            f"{sr['novelty_score']}/100 · "
                            f"{len(sr['overlap_matches'])} flags"
                        ):
                            for m in sr["overlap_matches"]:
                                sev_icon = {"high": "‼", "medium": "!",
                                            "low": "·"}.get(m.get("severity"),
                                                            "?")
                                st.markdown(
                                    f"{sev_icon} **[{m.get('overlap_type')}] "
                                    f"vs {m.get('reference_label')}** "
                                    f"({m.get('severity')}): "
                                    f"{m.get('overlap_description')}")

            # Save
            out = EXPORT_ROOT / f"manuscript_critique_{Path(ms_file.name).stem}.json"
            out.write_text(json.dumps(result.to_dict(), indent=2,
                                       ensure_ascii=False))
            st.caption(f"Full report saved to `{out}`")


# ============================================================================
# TAB 3: Project Workspace
# ============================================================================
with tab3:
    st.header("Project workspace")
    pid = st.session_state.active_project_id
    if not pid:
        st.info("Pick a project from the sidebar.")
    else:
        orch = st.session_state.orch
        try:
            project = orch.load(pid)
        except Exception as e:
            st.error(f"Could not load: {e}")
            st.stop()

        st.subheader(f"**{project.name}** ")
        st.caption(f"ID `{pid}` · **RQ:** {project.research_question}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sources", len(project.sources))
        drafted = sum(1 for s in project.sections.values() if s.draft)
        c2.metric("Drafted", f"{drafted}/21")
        critiqued = sum(1 for s in project.sections.values()
                        if s.status in {SectionStatus.CRITIQUED,
                                         SectionStatus.APPROVED})
        c3.metric("Approved", critiqued)
        scores = [(s.critique or {}).get("overall_score")
                  for s in project.sections.values()
                  if s.critique and (s.critique or {}).get("overall_score")]
        if scores:
            c4.metric("Mean", f"{sum(scores) / len(scores):.0f}/100")

        st.divider()
        st.subheader("Sections")
        for entry in PRISMA_SCR_SECTIONS:
            sid = entry["id"]
            state = project.sections.get(sid)
            if not state:
                continue
            crit = state.critique or {}
            score = crit.get("overall_score")
            verdict = crit.get("verdict", "")

            label = (f"**{sid}** · {state.status.value} · {state.word_count}w"
                     + (f" · {score}/100" if score else ""))
            with st.expander(label):
                if score is not None:
                    st.markdown(_pill(verdict, score),
                                 unsafe_allow_html=True)
                if state.draft:
                    st.markdown(state.draft)
                if crit:
                    if crit.get("strengths"):
                        st.markdown("**Strengths**")
                        for s in crit["strengths"]:
                            st.markdown(f"- {s}")
                    if crit.get("revision_notes"):
                        st.markdown("**Revision notes**")
                        for i, n in enumerate(crit["revision_notes"], 1):
                            st.markdown(f"{i}. {n}")
                if state.status == SectionStatus.REVISION_REQUESTED:
                    if st.button(f"🔁 Revise {sid}", key=f"rev_{sid}"):
                        with st.spinner("Revising..."):
                            orch.revise_section(project, sid)
                        st.rerun()

        # -- Update review details for existing projects ------------------
        with st.expander("📋 Update / add review administration details"):
            st.caption("Fill in any field below and click Save. "
                       "Tick the box to reset affected sections so they "
                       "are re-drafted using the new information.")
            existing = getattr(project, "metadata", {})
            um1, um2 = st.columns(2)
            with um1:
                u_reg_platform = st.text_input("Registration platform",
                    value=existing.get("registration_platform", ""),
                    key="u_reg_plat")
                u_reg_number = st.text_input("Registration number",
                    value=existing.get("registration_number", ""),
                    key="u_reg_num")
                u_reg_url = st.text_input("Registration URL",
                    value=existing.get("registration_url", ""),
                    key="u_reg_url")
                u_last_search = st.text_input("Date of last search",
                    value=existing.get("last_search_date", ""),
                    key="u_search_date")
                u_date_range = st.text_input("Eligibility date range",
                    value=existing.get("eligibility_date_range", ""),
                    key="u_date_range")
                u_lang = st.text_input("Language restriction",
                    value=existing.get("language_restriction", ""),
                    key="u_lang")
            with um2:
                u_tool = st.text_input("Screening tool",
                    value=existing.get("screening_tool", ""), key="u_tool")
                u_rev = st.text_input("No. of reviewers",
                    value=existing.get("n_reviewers", ""), key="u_rev")
                u_conflict_res = st.text_input("Conflict resolution",
                    value=existing.get("conflict_resolution", ""),
                    key="u_conflict_res")
                u_funding = st.text_input("Funding source",
                    value=existing.get("funding_source", ""), key="u_funding")
                u_grant = st.text_input("Grant number",
                    value=existing.get("grant_number", ""), key="u_grant")
                u_coi = st.text_input("Conflicts of interest",
                    value=existing.get("conflicts_of_interest", ""),
                    key="u_coi")
                u_authors = st.text_area("Authors & affiliations",
                    value=existing.get("authors", ""),
                    height=60, key="u_authors")
            reset_secs = st.checkbox(
                "Reset affected sections to PENDING so they are re-drafted "
                "with the updated information",
                value=False, key="reset_secs")
            if st.button("💾 Save details", key="save_meta"):
                new_meta = {
                    "registration_platform": u_reg_platform,
                    "registration_number": u_reg_number,
                    "registration_url": u_reg_url,
                    "last_search_date": u_last_search,
                    "eligibility_date_range": u_date_range,
                    "language_restriction": u_lang,
                    "screening_tool": u_tool,
                    "n_reviewers": u_rev,
                    "conflict_resolution": u_conflict_res,
                    "funding_source": u_funding,
                    "grant_number": u_grant,
                    "conflicts_of_interest": u_coi,
                    "authors": u_authors,
                }
                orch.update_metadata(project, new_meta,
                                     reset_affected_sections=reset_secs)
                st.success("Details saved.")
                st.rerun()

        st.divider()
        cols = st.columns(3)
        with cols[0]:
            if st.button("▶ Draft remaining sections", type="primary"):
                sec_area = st.empty()
                drafted_log2: list[str] = []
                revision_counts2: dict[str, int] = {}
                from app.agents.orchestrator import COMPLETED_STATUSES as CS
                for _i in range(40):
                    ready2 = orch.ready_sections(project)
                    for sid in ready2:
                        sec_area.info(f"✍️ Drafting **{sid}**…")
                        orch.draft_section(project, sid)
                        if project.sections[sid].status in CS:
                            drafted_log2.append(sid)
                    rev2 = [
                        s for s, st_ in project.sections.items()
                        if st_.status == SectionStatus.REVISION_REQUESTED
                        and revision_counts2.get(s, 0) < 2
                    ]
                    for sid in rev2:
                        revision_counts2[sid] = revision_counts2.get(sid, 0) + 1
                        sec_area.info(f"🔁 Revising **{sid}**…")
                        orch.revise_section(project, sid)
                    if not ready2 and not rev2:
                        break
                sec_area.empty()
                st.success(f"Drafted {len(drafted_log2)} new section(s).")
                st.rerun()
        with cols[1]:
            if st.button("🔁 Revise all flagged"):
                with st.spinner("Revising…"):
                    for sid_, st_ in project.sections.items():
                        if st_.status == SectionStatus.REVISION_REQUESTED:
                            orch.revise_section(project, sid_)
                st.rerun()
        with cols[2]:
            if st.button("📄 Export manuscript"):
                from export_review import export  # root-level module
                out = export(pid)
                with open(out) as f:
                    st.download_button("⬇ Download .md", data=f.read(),
                                        file_name=f"{project.name}.md",
                                        mime="text/markdown")


# ============================================================================
# TAB 4: Originality Audit
# ============================================================================
with tab4:
    st.header("Originality audit")
    pid = st.session_state.active_project_id
    if not pid:
        st.info("Pick a project from the sidebar (or use Tab 2 to audit any "
                "PDF directly).")
    else:
        mode = st.radio("Reference corpus mode",
                        ["project (reuse, free)",
                         "folder (upload PDFs)",
                         "web (training knowledge)"])
        granularity = st.radio("Granularity",
                                ["both", "section", "whole"], horizontal=True)
        folder_files = None
        if "folder" in mode:
            folder_files = st.file_uploader("Comparison PDFs",
                                              accept_multiple_files=True,
                                              type=["pdf"])

        if st.button("✨ Run audit", type="primary"):
            corpus_mode = mode.split(" ")[0]
            tmp_folder = None
            if corpus_mode == "folder":
                if not folder_files:
                    st.error("Upload at least one PDF.")
                    st.stop()
                tmp_folder = Path(tempfile.mkdtemp(prefix="audit_"))
                for f in folder_files:
                    (tmp_folder / f.name).write_bytes(f.getbuffer())

            with st.spinner("Auditing..."):
                result = audit_project_manuscript(
                    project_id=pid, corpus_mode=corpus_mode,
                    folder_path=str(tmp_folder) if tmp_folder else None,
                    granularity=granularity)

            if result.error:
                st.error(result.error)
            else:
                c1, c2 = st.columns([1, 2])
                c1.metric("Overall", f"{result.overall_score}/100")
                c1.markdown(_pill(result.overall_verdict),
                            unsafe_allow_html=True)
                c1.caption(f"Corpus: {result.reference_corpus_size}")
                c2.markdown(f"**Summary:** {result.overall_summary}")

                if result.section_reports:
                    st.subheader("Per-section novelty")
                    for sr in result.section_reports:
                        cols = st.columns([3, 1, 2])
                        cols[0].write(sr.section_id)
                        cols[1].write(f"{sr.novelty_score}/100")
                        cols[2].markdown(_pill(sr.verdict),
                                          unsafe_allow_html=True)
                        if sr.overlap_matches:
                            with st.expander(
                                f"{len(sr.overlap_matches)} flag(s)"):
                                for m in sr.overlap_matches:
                                    st.markdown(
                                        f"- **[{m.overlap_type}] "
                                        f"vs {m.reference_label}** "
                                        f"({m.severity}): "
                                        f"{m.overlap_description}")
