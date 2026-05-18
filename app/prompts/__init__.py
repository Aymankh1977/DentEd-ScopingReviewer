"""
DentEd-ScopingReviewer — Section Prompt Library
================================================
Defines `SectionPrompt`, the complete `SECTION_PROMPTS` registry for all
21 PRISMA-ScR sections, and the `get_prompt()` accessor used by the
Drafter and Critic agents.

Each SectionPrompt encodes:
  - The PRISMA-ScR item it addresses (verbatim from Tricco et al. 2018,
    *Annals of Internal Medicine*, 169(7):467-473).
  - Minimum evidence required from the charted corpus or project metadata.
  - Mandatory structural elements the drafter must include.
  - Word target range (min, max).
  - Scope guardrails — what must NOT appear in this section.
  - Output format instructions.

Why per-section prompts?
------------------------
Generic "write the methods" prompts produce generic methods. PRISMA-ScR
Item 8 demands the full electronic search string for at least one database.
Item 14 demands PRISMA flow numbers with per-stage exclusion reasons.
Item 18 demands synthesis aligned with the review objectives. These are
distinct tasks requiring distinct evidence. Treating them as one task is
why AI-written reviews fail journal scrutiny.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SectionPrompt:
    """
    Complete specification for drafting one PRISMA-ScR section.

    Attributes
    ----------
    section_id
        Matches the ID used in the orchestrator's PRISMA_SCR_SECTIONS list.
    prisma_scr_item
        Item number + verbatim Tricco et al. 2018 requirement text.
    objective
        Plain-English statement of what this section must achieve.
    required_evidence
        List of evidence keys the drafter must find in context before
        drafting. If any are absent the drafter returns BLOCKED.
    structural_requirements
        Mandatory elements the prose must contain. The critic checks each.
    word_target
        (min, max) word count. Drafter and critic both enforce ±10%.
    scope_guardrails
        Explicit list of content that must NOT appear here — prevents
        section bleed-over.
    output_format
        Format instructions for the drafter's response.
    extra_guidance
        Any additional model-facing notes not covered above.
    """

    section_id: str
    prisma_scr_item: str
    objective: str
    required_evidence: list[str]
    structural_requirements: list[str]
    word_target: tuple[int, int]
    scope_guardrails: list[str] = field(default_factory=list)
    output_format: str = "Markdown prose, academic register, UK English"
    extra_guidance: list[str] = field(default_factory=list)

    def render_requirements_block(self) -> str:
        """Produce the spec block injected into drafter and critic prompts."""
        lines: list[str] = [
            "### PRISMA-ScR item",
            self.prisma_scr_item,
            "",
            "### Objective for this section",
            self.objective,
            "",
            "### Evidence you must use from the project context",
        ]
        lines += [f"- {e}" for e in self.required_evidence]
        lines += ["", "### Structural requirements (critic checks each one)"]
        lines += [f"- {r}" for r in self.structural_requirements]
        lines += [
            "",
            "### Word target",
            f"{self.word_target[0]}–{self.word_target[1]} words (±10% tolerance).",
            "",
        ]
        if self.scope_guardrails:
            lines += ["### Scope guardrails — do NOT include this content here"]
            lines += [f"- {g}" for g in self.scope_guardrails]
            lines += [""]
        lines += ["### Output format", self.output_format]
        if self.extra_guidance:
            lines += ["", "### Section-specific guidance"]
            lines += [f"- {g}" for g in self.extra_guidance]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
SECTION_PROMPTS: dict[str, SectionPrompt] = {}


def _reg(prompt: SectionPrompt) -> SectionPrompt:
    SECTION_PROMPTS[prompt.section_id] = prompt
    return prompt


# ===========================================================================
# TITLE  (PRISMA-ScR item 1)
# ===========================================================================
_reg(SectionPrompt(
    section_id="title",
    prisma_scr_item=(
        "Item 1 — Title: Identify the report as a scoping review."
    ),
    objective=(
        "Produce a precise, informative title that identifies the work as a "
        "scoping review and captures the Population, Concept, and Context "
        "(PCC) of the review."
    ),
    required_evidence=[
        "project_context.research_question",
        "project_context.population",
        "project_context.concept",
        "project_context.context",
    ],
    structural_requirements=[
        "Include the exact phrase 'scoping review' in the title",
        "Reflect the Population element of the PCC framework",
        "Reflect the Concept element of the PCC framework",
        "Reflect the Context element (setting or domain) of the PCC framework",
        "Be concise: 10–25 words maximum",
    ],
    word_target=(10, 25),
    scope_guardrails=[
        "Do not include a subtitle unless essential for clarity",
        "Do not state conclusions, findings, or interpretive language",
        "Do not use rhetorical questions",
    ],
    output_format=(
        "A single title string — no markdown headers, no bold formatting, "
        "no punctuation at the end. Output only the title text."
    ),
    extra_guidance=[
        "Pattern: '<Noun phrase capturing concept> in <context/setting>: "
        "a scoping review' — e.g. 'Artificial intelligence integration in "
        "undergraduate dental education: a scoping review'",
        "If the PCC cannot all fit without exceeding 25 words, prioritise "
        "Concept and Context; Population can be implied.",
    ],
))


# ===========================================================================
# ABSTRACT  (PRISMA-ScR item 2)
# ===========================================================================
_reg(SectionPrompt(
    section_id="abstract",
    prisma_scr_item=(
        "Item 2 — Structured summary: Provide a structured summary "
        "including, as applicable: background, objectives, eligibility "
        "criteria, sources of evidence, charting methods, results, and "
        "conclusions. (Tricco et al. 2018)"
    ),
    objective=(
        "Deliver a structured abstract that lets readers assess the review's "
        "scope, methods, and principal conclusions without reading the full "
        "text. All mandatory PRISMA-ScR abstract subsections must appear."
    ),
    required_evidence=[
        "project_context.research_question",
        "project_context.population",
        "project_context.concept",
        "project_context.context",
        "corpus_charts (for results numbers and key themes)",
        "previous_sections: introduction_rationale, methods_eligibility, "
        "methods_information_sources, results_selection, results_synthesis, "
        "discussion_conclusions",
    ],
    structural_requirements=[
        "**Background** subsection (2–3 sentences): why the topic matters and "
        "why a scoping review is warranted",
        "**Objectives** subsection: explicit research question with PCC elements",
        "**Eligibility criteria** subsection: main inclusion and exclusion criteria",
        "**Sources of evidence** subsection: databases searched and date range",
        "**Charting methods** subsection: brief description of data extraction approach",
        "**Results** subsection: number of included studies, key thematic findings "
        "(2–3 main themes), and geographic/design distribution",
        "**Conclusions** subsection: key implication for practice, policy, or research",
    ],
    word_target=(250, 350),
    scope_guardrails=[
        "Do not introduce new information not present in the main manuscript",
        "Do not include references or in-text citations",
        "Do not exceed 350 words",
    ],
    output_format=(
        "Structured markdown with bold subsection headers in this exact order: "
        "**Background**, **Objectives**, **Eligibility criteria**, "
        "**Sources of evidence**, **Charting methods**, **Results**, "
        "**Conclusions**. Each subsection is 2–4 sentences of continuous prose."
    ),
    extra_guidance=[
        "Derive the number of included studies from the charted corpus "
        "(count inclusion_recommendation == 'include')",
        "Mirror the language of the research question exactly in the "
        "Objectives subsection",
    ],
))


# ===========================================================================
# INTRODUCTION — RATIONALE  (PRISMA-ScR item 3)
# ===========================================================================
_reg(SectionPrompt(
    section_id="introduction_rationale",
    prisma_scr_item=(
        "Item 3 — Rationale: Describe the rationale for the review in the "
        "context of what is already known. (Tricco et al. 2018)"
    ),
    objective=(
        "Justify why this scoping review is needed by situating the "
        "research question within existing knowledge and explicitly "
        "identifying the gap or uncertainty the review addresses."
    ),
    required_evidence=[
        "project_context.research_question",
        "project_context.population",
        "project_context.concept",
        "project_context.context",
        "previous_sections: results_synthesis (to ground the gap statement "
        "in what the review actually found)",
    ],
    structural_requirements=[
        "Opening paragraph: establish the importance and scope of the "
        "broader field (HPE / dental education / the relevant domain)",
        "Second paragraph: summarise what is already known — reference "
        "existing systematic reviews, scoping reviews, or landmark studies "
        "on related topics using general knowledge",
        "Third paragraph: identify the specific gap, inconsistency, or "
        "uncertainty this review addresses — this must be explicit, not "
        "implied",
        "Fourth paragraph: justify the choice of a scoping review design "
        "rather than a systematic review (e.g. heterogeneous evidence base, "
        "mapping rather than synthesis of effect sizes, emerging field)",
        "Closing sentence: signpost to the objectives section that follows",
    ],
    word_target=(400, 600),
    scope_guardrails=[
        "Do not state the research question or objectives here "
        "(that belongs in introduction_objectives)",
        "Do not describe methods (that belongs in the Methods sections)",
        "Do not present results or findings (that belongs in Results)",
        "Do not use author-year citations from the charted corpus — "
        "rationale draws on general disciplinary knowledge, not the "
        "included studies",
    ],
    output_format="Markdown prose, four paragraphs, academic register, UK English",
    extra_guidance=[
        "If the field is health professions education or dental education, "
        "anchor the opening to accreditation pressures, technological change, "
        "or curriculum reform as appropriate to the research question",
        "The gap statement must be specific: do not write 'more research is "
        "needed' — write 'no scoping review has mapped X in Y context'",
    ],
))


# ===========================================================================
# INTRODUCTION — OBJECTIVES  (PRISMA-ScR item 4)
# ===========================================================================
_reg(SectionPrompt(
    section_id="introduction_objectives",
    prisma_scr_item=(
        "Item 4 — Objectives: Provide an explicit statement of the questions "
        "and objectives being addressed with reference to their key elements "
        "(e.g., population, concept, and context). (Tricco et al. 2018)"
    ),
    objective=(
        "State the review's research question and objectives with explicit "
        "reference to the PCC framework so readers and reviewers can "
        "evaluate alignment between the question and the methods."
    ),
    required_evidence=[
        "project_context.research_question",
        "project_context.population",
        "project_context.concept",
        "project_context.context",
        "previous_sections: introduction_rationale",
    ],
    structural_requirements=[
        "One overarching research question stated in full, verbatim or "
        "closely paraphrased from the project metadata",
        "Explicit labelling or parenthetical identification of Population (P), "
        "Concept (C), and Context (C) elements within or immediately after "
        "the research question",
        "Any secondary sub-questions or objectives listed separately, "
        "if applicable",
        "Brief one-sentence statement of what the review will and will not "
        "address (scope boundary) to pre-empt misreading",
    ],
    word_target=(150, 250),
    scope_guardrails=[
        "Do not restate the rationale (that belongs in introduction_rationale)",
        "Do not describe methods here",
        "Do not state findings or conclusions",
    ],
    output_format=(
        "Markdown prose; PCC elements may be highlighted in parentheses "
        "or bold — e.g. '...among **undergraduate dental students** (P) "
        "regarding the use of **AI-assisted learning tools** (C) in "
        "**university-based dental programmes globally** (C)...'"
    ),
    extra_guidance=[
        "The research question should begin with 'What', 'How', 'To what "
        "extent', or 'Which' — not 'Does' (which implies a hypothesis-testing "
        "design inappropriate for scoping reviews)",
    ],
))


# ===========================================================================
# METHODS — PROTOCOL  (PRISMA-ScR item 5)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_protocol",
    prisma_scr_item=(
        "Item 5 — Protocol and registration: Indicate whether a review "
        "protocol exists; if so, provide a registration number and where it "
        "can be accessed. (Tricco et al. 2018)"
    ),
    objective=(
        "Disclose whether a protocol was prospectively registered, and if "
        "so, provide the registration details. If no protocol exists, "
        "acknowledge this transparently."
    ),
    required_evidence=[
        "project_context.research_question",
    ],
    structural_requirements=[
        "Explicit statement of whether a protocol was registered prior to "
        "the review (yes/no)",
        "If registered: name of the registration platform (e.g. Open Science "
        "Framework, PROSPERO, Joanna Briggs Institute), registration number, "
        "and URL or DOI",
        "If not registered: one-sentence acknowledgement that the absence "
        "of prospective registration is a limitation",
        "If a protocol document exists but was not formally registered: "
        "describe where it is accessible",
    ],
    word_target=(50, 150),
    scope_guardrails=[
        "Do not describe the review methods here (that belongs in "
        "subsequent Methods sections)",
        "Do not discuss search strategies or eligibility criteria here",
    ],
    output_format="Markdown prose, 1–2 short paragraphs",
    extra_guidance=[
        "If registration details are unknown, insert "
        "[TO BE FILLED — registration platform and number] rather than "
        "inventing details",
        "PROSPERO does not accept scoping review protocols; if relevant, "
        "note that OSF or JBI is the appropriate platform",
    ],
))


# ===========================================================================
# METHODS — ELIGIBILITY CRITERIA  (PRISMA-ScR item 6)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_eligibility",
    prisma_scr_item=(
        "Item 6 — Eligibility criteria: Specify characteristics of the "
        "sources of evidence used as criteria for including sources of "
        "evidence in the review. (Tricco et al. 2018)"
    ),
    objective=(
        "Describe all inclusion and exclusion criteria applied to determine "
        "whether a source qualified for inclusion, anchored to the PCC frame."
    ),
    required_evidence=[
        "project_context.population",
        "project_context.concept",
        "project_context.context",
        "project_context.research_question",
    ],
    structural_requirements=[
        "Inclusion criteria — study design: types of study designs accepted "
        "(e.g. RCTs, observational studies, qualitative studies, mixed-methods, "
        "reviews, conference papers — state which were included and why)",
        "Inclusion criteria — population: participant characteristics aligned "
        "with the P element of the PCC framework",
        "Inclusion criteria — concept: scope of the intervention, phenomenon, "
        "or topic aligned with the C element of PCC",
        "Inclusion criteria — context: setting or context aligned with the "
        "second C element of PCC",
        "Inclusion criteria — date range: publication years eligible for inclusion",
        "Inclusion criteria — language: languages accepted (and rationale if "
        "restricted to English)",
        "Exclusion criteria: explicitly listed, not merely implied by the "
        "inclusion criteria",
        "Brief rationale for at least one key criterion choice that readers "
        "might question (e.g. why grey literature was/was not included)",
    ],
    word_target=(300, 500),
    scope_guardrails=[
        "Do not list specific included studies (that belongs in "
        "results_characteristics)",
        "Do not describe the search strategy or databases (that belongs in "
        "methods_information_sources and methods_search)",
        "Do not describe the selection process (that belongs in "
        "methods_selection)",
        "Do not discuss data extraction (that belongs in "
        "methods_data_charting)",
    ],
    output_format=(
        "Markdown prose, 2–3 paragraphs. Do not use a bullet list — "
        "integrate criteria into flowing academic prose with clear signposting "
        "(e.g. 'Studies were included if they...', 'Studies were excluded if...')"
    ),
    extra_guidance=[
        "The criteria must be operationally specific — not 'relevant studies' "
        "but 'peer-reviewed studies reporting on AI-based tools used in "
        "undergraduate dental curricula'",
        "If the review includes grey literature, state the types accepted "
        "(institutional reports, theses, conference proceedings)",
    ],
))


# ===========================================================================
# METHODS — INFORMATION SOURCES  (PRISMA-ScR item 7)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_information_sources",
    prisma_scr_item=(
        "Item 7 — Information sources: Describe all information sources "
        "in the search (e.g., databases with date ranges accessed) and date "
        "when last searched. (Tricco et al. 2018)"
    ),
    objective=(
        "Report every database and supplementary source searched, with the "
        "date range covered and the date on which each was last searched."
    ),
    required_evidence=[
        "project_context.concept",
        "project_context.context",
    ],
    structural_requirements=[
        "Named list of all electronic databases searched "
        "(e.g. MEDLINE via PubMed, EMBASE, CINAHL, ERIC, Web of Science, "
        "Scopus, Cochrane Library, PsycINFO — list those applicable)",
        "Date range of coverage for each database",
        "Date on which each database was last searched",
        "Supplementary search strategies: hand searching of key journals, "
        "reference list scanning, grey literature sources, expert consultation "
        "(state 'not conducted' for any that were not attempted)",
        "Rationale for the selection of databases (why these databases are "
        "appropriate for the topic and population)",
    ],
    word_target=(200, 350),
    scope_guardrails=[
        "Do not include search strings or MeSH terms here (that belongs in "
        "methods_search)",
        "Do not describe the selection process (that belongs in "
        "methods_selection)",
    ],
    output_format=(
        "Markdown prose, 2 paragraphs: first paragraph covers electronic "
        "databases; second covers supplementary and grey literature sources"
    ),
    extra_guidance=[
        "If specific search dates are unknown, use "
        "[TO BE FILLED — date last searched] rather than approximating",
        "For health professions education, MEDLINE, CINAHL, and ERIC are "
        "the minimum recommended databases; EMBASE and Web of Science "
        "add breadth",
    ],
))


# ===========================================================================
# METHODS — SEARCH  (PRISMA-ScR item 8)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_search",
    prisma_scr_item=(
        "Item 8 — Search: Present the full electronic search strategy for "
        "at least one database, including any filters that were used, as "
        "it would be replicable. (Tricco et al. 2018)"
    ),
    objective=(
        "Provide a fully replicable search strategy — including MeSH terms, "
        "free-text synonyms, Boolean operators, truncation, and any filters — "
        "for at least one database, with a narrative account of how the "
        "strategy was constructed and adapted across databases."
    ),
    required_evidence=[
        "project_context.population",
        "project_context.concept",
        "project_context.context",
        "project_context.research_question",
        "previous_sections: methods_information_sources",
    ],
    structural_requirements=[
        "Narrative description of search strategy construction: how PCC "
        "elements were translated into MeSH/controlled vocabulary terms and "
        "free-text synonyms",
        "Explanation of how Boolean logic (AND, OR, NOT) was applied",
        "Description of any truncation or wildcard symbols used",
        "Statement of any limits/filters applied: date range, language, "
        "document type, age group",
        "Full verbatim search string for at least one primary database "
        "(e.g. MEDLINE/PubMed) presented in a fenced code block",
        "Brief description of how the strategy was adapted for other databases",
        "Date of the final search run",
    ],
    word_target=(350, 550),
    scope_guardrails=[
        "Do not list the databases here (that belongs in "
        "methods_information_sources)",
        "Do not describe the screening/selection process (that belongs in "
        "methods_selection)",
        "Do not report results (that belongs in results_selection)",
    ],
    output_format=(
        "Markdown prose (narrative description) followed by at least one "
        "fenced code block containing the full, verbatim search string for "
        "the primary database. Format the code block with language tag 'text'."
    ),
    extra_guidance=[
        "The search string must be plausible for the concept. "
        "For AI in dental education, MeSH terms include 'Artificial "
        "Intelligence', 'Education, Dental', 'Machine Learning'; free-text "
        "synonyms include 'deep learning', 'neural network', 'chatbot', "
        "'digital simulation', 'virtual patient'",
        "If the actual search string is unknown, construct a "
        "representative, replicable string from the PCC and note that the "
        "exact string should be verified against the team's records; do NOT "
        "use [TO BE FILLED] for the search string itself — always provide one",
    ],
))


# ===========================================================================
# METHODS — SELECTION OF SOURCES  (PRISMA-ScR item 9)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_selection",
    prisma_scr_item=(
        "Item 9 — Selection of sources of evidence: Describe the process "
        "for selecting sources of evidence. (Tricco et al. 2018)"
    ),
    objective=(
        "Describe the study selection workflow, including the number of "
        "independent reviewers at each stage, the tools used, and the "
        "process for resolving disagreements."
    ),
    required_evidence=[
        "project_context.research_question",
        "previous_sections: methods_eligibility",
    ],
    structural_requirements=[
        "Stage 1: title and abstract screening — number of independent "
        "reviewers, tool used (e.g. Rayyan, Covidence, Excel), decision rule",
        "Stage 2: full-text review — number of independent reviewers, "
        "eligibility criteria applied, decision rule",
        "Conflict resolution process: how disagreements between reviewers "
        "were resolved (e.g. discussion, third reviewer arbitration)",
        "Pilot testing: whether a calibration exercise was conducted before "
        "full screening, and the inter-rater reliability result if measured "
        "(e.g. Cohen's kappa)",
        "Statement of whether authors of included studies were contacted for "
        "additional information",
    ],
    word_target=(250, 400),
    scope_guardrails=[
        "Do not report the number of studies screened or included here "
        "(that belongs in results_selection)",
        "Do not describe data extraction (that belongs in "
        "methods_data_charting)",
    ],
    output_format="Markdown prose, 2–3 paragraphs",
    extra_guidance=[
        "If screening was conducted by a single reviewer (common in "
        "AI-assisted reviews), acknowledge this as a limitation and note "
        "any verification step taken",
    ],
))


# ===========================================================================
# METHODS — DATA CHARTING PROCESS  (PRISMA-ScR item 10)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_data_charting",
    prisma_scr_item=(
        "Item 10 — Data charting process: Describe the methods of charting "
        "data from the included sources of evidence (e.g., calibrated "
        "extraction or extraction by one reviewer) and any processes for "
        "obtaining and confirming data from investigators. (Tricco et al. 2018)"
    ),
    objective=(
        "Describe how data were extracted from each included study, "
        "including the charting form, the number of reviewers, and any "
        "quality-assurance steps."
    ),
    required_evidence=[
        "project_context.concept",
        "previous_sections: methods_eligibility",
    ],
    structural_requirements=[
        "Description of the charting form: whether it was piloted and "
        "calibrated before full use, and in what format (spreadsheet, "
        "online tool, structured template)",
        "Number of reviewers who independently completed data charting "
        "for each study",
        "Forward reference to methods_data_items for the list of variables "
        "charted",
        "Process for handling missing or ambiguous data: were study authors "
        "contacted? If so, by what method and with what response rate?",
        "Process for handling studies that report relevant data across "
        "multiple publications (companion papers)",
    ],
    word_target=(200, 350),
    scope_guardrails=[
        "Do not list the specific variables charted here (that belongs in "
        "methods_data_items)",
        "Do not describe the selection process (that belongs in "
        "methods_selection)",
        "Do not report results of charting (that belongs in Results sections)",
    ],
    output_format="Markdown prose, 1–2 paragraphs",
    extra_guidance=[
        "In scoping reviews charting is often done by a single reviewer; "
        "if so, state whether a second reviewer checked a random sample "
        "for accuracy",
    ],
))


# ===========================================================================
# METHODS — DATA ITEMS  (PRISMA-ScR item 11)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_data_items",
    prisma_scr_item=(
        "Item 11 — Data items: List and define all variables for which data "
        "were sought and any assumptions and simplifications made. "
        "(Tricco et al. 2018)"
    ),
    objective=(
        "Enumerate every variable extracted during data charting, provide a "
        "brief operational definition for each, and note any assumptions "
        "made when data were incomplete or inconsistently reported."
    ),
    required_evidence=[
        "project_context.concept",
        "project_context.population",
        "corpus_charts",
    ],
    structural_requirements=[
        "Brief introductory sentence stating the number of data items and "
        "grouping principle",
        "Group 1 — Bibliographic variables: author(s), year, journal/source, "
        "country, DOI",
        "Group 2 — Study design variables: design type, setting, sample size, "
        "population characteristics",
        "Group 3 — Concept/intervention variables: type of intervention or "
        "technology, delivery mode, duration, integration into curriculum",
        "Group 4 — Outcome variables: outcome measures used, effect direction, "
        "key findings as reported",
        "Group 5 — Limitations: limitations reported by study authors",
        "Markdown table (Table 1) with columns: Variable | Group | Definition / "
        "Notes — one row per extracted variable",
        "Statement of any assumptions or simplifications made when data "
        "were missing or ambiguous",
    ],
    word_target=(300, 500),
    scope_guardrails=[
        "Do not report the actual extracted data here (that belongs in "
        "results_characteristics and results_individual_sources)",
        "Do not describe the charting process (that belongs in "
        "methods_data_charting)",
    ],
    output_format=(
        "Markdown prose introduction (1 paragraph) followed by a markdown "
        "table titled 'Table 1. Data items extracted from included studies'"
    ),
    extra_guidance=[
        "Derive the variable list from the fields present in the "
        "corpus_charts JSON (bibliographic, study_design, participants, "
        "methods, findings, limitations, relevance)",
        "Use plain language in the Definition column — avoid jargon that "
        "would require further explanation",
    ],
))


# ===========================================================================
# METHODS — SYNTHESIS  (PRISMA-ScR item 13)
# ===========================================================================
_reg(SectionPrompt(
    section_id="methods_synthesis",
    prisma_scr_item=(
        "Item 13 — Synthesis of results: Describe the methods of handling "
        "and summarising the data that were charted. (Tricco et al. 2018)"
    ),
    objective=(
        "Explain how extracted data were organised, synthesised, and "
        "narratively summarised, and why the chosen approach is appropriate "
        "for the evidence base."
    ),
    required_evidence=[
        "project_context.research_question",
        "project_context.concept",
    ],
    structural_requirements=[
        "Statement of synthesis approach: narrative synthesis (the standard "
        "for scoping reviews) — state this explicitly and cite the Arksey & "
        "O'Malley or Levac et al. framework if the review follows one",
        "Description of how studies were grouped for synthesis: by theme, "
        "outcome type, study design, population, or time period",
        "Explanation of why quantitative meta-analysis was or was not "
        "attempted (typically not appropriate for scoping reviews due to "
        "heterogeneity)",
        "Description of thematic analysis process: how themes were derived "
        "(inductively from the data, deductively from the PCC framework, "
        "or a combination)",
        "Description of how convergence (agreement across studies) and "
        "divergence (contradiction) were handled in the synthesis",
    ],
    word_target=(200, 350),
    scope_guardrails=[
        "Do not report results of the synthesis here (that belongs in "
        "results_synthesis)",
        "Do not describe data extraction (that belongs in "
        "methods_data_charting)",
    ],
    output_format="Markdown prose, 1–2 paragraphs",
    extra_guidance=[
        "The Arksey & O'Malley (2005) framework and its update by Levac "
        "et al. (2010) are the dominant methodological frameworks for "
        "scoping reviews — reference whichever the team followed",
        "If thematic analysis was used, cite the Braun & Clarke (2006) "
        "approach or equivalent",
    ],
))


# ===========================================================================
# RESULTS — SELECTION OF SOURCES  (PRISMA-ScR item 14)
# ===========================================================================
_reg(SectionPrompt(
    section_id="results_selection",
    prisma_scr_item=(
        "Item 14 — Selection of sources of evidence: Give numbers of "
        "sources of evidence screened, assessed for eligibility, and "
        "included in the review, with reasons for exclusions at each "
        "stage, ideally using a flow diagram. (Tricco et al. 2018)"
    ),
    objective=(
        "Report the complete study selection flow with PRISMA-compatible "
        "numbers at each stage, reasons for exclusion at full-text stage, "
        "and a machine-readable PRISMA flow diagram data block."
    ),
    required_evidence=[
        "corpus_charts (derive n_included by counting inclusion_recommendation "
        "== 'include')",
        "previous_sections: methods_selection",
    ],
    structural_requirements=[
        "Total records identified through database searching (state if "
        "unknown as [TO BE FILLED — total records identified])",
        "Records after duplicate removal",
        "Records screened at title/abstract stage",
        "Records excluded at title/abstract stage (with primary reason if known)",
        "Full-text articles retrieved for eligibility assessment",
        "Full-text articles excluded with primary reason categories "
        "(e.g. wrong population n=X, wrong concept n=Y, wrong study design n=Z)",
        "Final number of studies included in the scoping review",
        "PRISMA flow diagram data embedded as a fenced JSON block with keys: "
        "records_identified, records_after_deduplication, records_screened, "
        "records_excluded_abstract, fulltext_assessed, fulltext_excluded "
        "(with reasons list), studies_included",
    ],
    word_target=(200, 400),
    scope_guardrails=[
        "Do not describe the selection process or methods here (that belongs "
        "in methods_selection)",
        "Do not describe study characteristics (that belongs in "
        "results_characteristics)",
    ],
    output_format=(
        "Markdown prose narrative (1–2 paragraphs) followed by a fenced "
        "JSON code block labelled 'prisma_flow' representing the flow "
        "diagram data"
    ),
    extra_guidance=[
        "Derive n_included from corpus_charts: count studies where "
        "relevance.inclusion_recommendation == 'include' and no "
        "_extraction_error key is present",
        "For any stage where the exact number is unknown, use the "
        "[TO BE FILLED] placeholder — do not invent numbers",
        "The prose should describe the flow in past tense: "
        "'Database searches identified X records. After duplicate removal, "
        "Y records were screened...'",
    ],
))


# ===========================================================================
# RESULTS — CHARACTERISTICS OF SOURCES  (PRISMA-ScR item 15)
# ===========================================================================
_reg(SectionPrompt(
    section_id="results_characteristics",
    prisma_scr_item=(
        "Item 15 — Characteristics of sources of evidence: For each source "
        "of evidence, present characteristics for which data were charted "
        "and provide the citations. (Tricco et al. 2018)"
    ),
    objective=(
        "Summarise the bibliographic and methodological characteristics of "
        "all included studies, both narratively and in a structured table "
        "that enables rapid cross-study comparison."
    ),
    required_evidence=[
        "corpus_charts (all included studies with bibliographic and "
        "study_design fields populated)",
    ],
    structural_requirements=[
        "Narrative overview paragraph: total number of included studies, "
        "publication year range, geographic distribution (countries/regions), "
        "predominant study designs",
        "Narrative description of sample size range and participant "
        "characteristics across the corpus",
        "Narrative description of the range of concepts/interventions covered "
        "and how they relate to the review's PCC",
        "Table of included studies with columns: First Author, Year, Country, "
        "Study Design, Sample Size (n), Setting/Population, "
        "Concept/Intervention, Main Outcome Measured — one row per study, "
        "studies ordered chronologically",
        "Note on any variability in reporting completeness across studies "
        "(e.g. 'Five studies did not report sample size')",
    ],
    word_target=(400, 700),
    scope_guardrails=[
        "Do not synthesise or interpret findings across studies here "
        "(that belongs in results_synthesis)",
        "Do not report individual study findings in detail here "
        "(that belongs in results_individual_sources)",
        "Do not discuss critical appraisal quality scores here "
        "(that belongs in results_critical_appraisal)",
    ],
    output_format=(
        "Markdown prose (2–3 paragraphs) followed by a markdown table. "
        "The table header must use this exact format: "
        "| First Author | Year | Country | Design | n | Setting | "
        "Concept/Intervention | Main Outcome |"
    ),
    extra_guidance=[
        "Every row in the table must correspond to an included study "
        "in the corpus_charts (inclusion_recommendation == 'include')",
        "Use (FirstAuthor et al., Year) format in the narrative prose "
        "when referring to specific studies",
        "If country is not reported in the chart, use 'NR' in the table",
    ],
))


# ===========================================================================
# RESULTS — CRITICAL APPRAISAL  (PRISMA-ScR item 16)
# ===========================================================================
_reg(SectionPrompt(
    section_id="results_critical_appraisal",
    prisma_scr_item=(
        "Item 16 — Critical appraisal within sources of evidence: If done, "
        "present data on critical appraisal of included sources of evidence. "
        "(Tricco et al. 2018)"
    ),
    objective=(
        "Report the results of any formal critical appraisal conducted, "
        "or — if not conducted — justify the omission with reference to "
        "scoping review methodology and summarise author-reported limitations."
    ),
    required_evidence=[
        "corpus_charts (limitations field for each included study)",
        "previous_sections: results_characteristics",
    ],
    structural_requirements=[
        "Statement of whether formal critical appraisal was conducted: "
        "explicitly 'yes' with tool named (e.g. JBI critical appraisal "
        "checklists, MMAT, GRADE), or 'no' with methodological justification",
        "If formal appraisal conducted: summary of quality rating distribution "
        "across studies (e.g. 'Of 18 studies, 6 were rated high quality, "
        "10 moderate, and 2 low quality')",
        "If not conducted: cite methodological precedent (Arksey & O'Malley "
        "2005 or Peters et al. 2020 JBI scoping review manual) supporting "
        "the omission",
        "Summary of study-author-reported limitations synthesised across "
        "the corpus — group by limitation type (e.g. small sample, "
        "single-site, self-report bias, short follow-up)",
    ],
    word_target=(150, 300),
    scope_guardrails=[
        "Do not conduct a de-novo quality appraisal here if none was done",
        "Do not discuss implications of quality for conclusions "
        "(that belongs in discussion_limitations)",
        "Do not repeat individual study limitations already reported in "
        "results_individual_sources",
    ],
    output_format="Markdown prose, 1–2 paragraphs",
    extra_guidance=[
        "In scoping reviews, critical appraisal is explicitly described as "
        "optional by Tricco et al. 2018 and the JBI manual; a well-reasoned "
        "statement of non-appraisal is fully compliant with PRISMA-ScR",
        "The author-reported limitations section is mandatory regardless "
        "of whether formal appraisal was conducted",
    ],
))


# ===========================================================================
# RESULTS — INDIVIDUAL SOURCES  (PRISMA-ScR item 17)
# ===========================================================================
_reg(SectionPrompt(
    section_id="results_individual_sources",
    prisma_scr_item=(
        "Item 17 — Results of individual sources of evidence: For each "
        "included source of evidence, report the relevant data that were "
        "charted and provide citations. (Tricco et al. 2018)"
    ),
    objective=(
        "Report the relevant extracted findings from every included study, "
        "citing each study by first author and year, and grouping studies "
        "thematically when the corpus exceeds eight studies."
    ),
    required_evidence=[
        "corpus_charts (all included studies — findings, study_design, "
        "participants, limitations fields)",
        "previous_sections: results_characteristics",
    ],
    structural_requirements=[
        "For small corpora (≤8 studies): one paragraph per study with "
        "author-year citation, design, participants, main findings, and "
        "any key limitation reported by authors",
        "For larger corpora (>8 studies): organise under thematic "
        "subheadings derived from the data; each study must still be "
        "cited at least once within the relevant theme",
        "Every included study in the corpus must be cited at least once "
        "using the (FirstAuthor et al., Year) format",
        "Studies with incomplete extraction data must be noted as such "
        "rather than silently omitted",
        "Do not paraphrase findings beyond what the corpus chart supports; "
        "if a finding field is empty, use [TO BE FILLED — findings not "
        "extracted] rather than inferring",
    ],
    word_target=(600, 1200),
    scope_guardrails=[
        "Do not synthesise or interpret across studies here "
        "(that belongs in results_synthesis)",
        "Do not draw implications or recommendations here "
        "(that belongs in Discussion sections)",
        "Do not fabricate findings not present in the corpus charts",
    ],
    output_format=(
        "Markdown prose with level-3 subheadings (###) for thematic groups "
        "if corpus > 8 studies. Each study reference in (FirstAuthor et al., "
        "Year) format. No bullet lists — prose paragraphs only."
    ),
    extra_guidance=[
        "Extract: first_author and year from bibliographic; design_type "
        "from study_design; sample_size from participants; key_findings "
        "and themes from findings; reported_limitations from limitations",
        "Limit each study summary to 3–5 sentences to manage section length",
        "When two studies report conflicting findings, present both and "
        "note the conflict explicitly",
    ],
))


# ===========================================================================
# RESULTS — SYNTHESIS  (PRISMA-ScR item 18)
# ===========================================================================
_reg(SectionPrompt(
    section_id="results_synthesis",
    prisma_scr_item=(
        "Item 18 — Synthesis of results: Summarise and/or present the "
        "charting results as they relate to the review objectives. "
        "(Tricco et al. 2018)"
    ),
    objective=(
        "Synthesise findings across all included studies, organised by "
        "theme, in relation to the review's research question and PCC. "
        "Identify convergence, divergence, and gaps in the evidence."
    ),
    required_evidence=[
        "corpus_charts (findings.themes and findings.key_findings for all "
        "included studies)",
        "previous_sections: results_individual_sources",
        "project_context.research_question",
    ],
    structural_requirements=[
        "Opening: brief restatement of the review objective, then overall "
        "summary of the evidence base (number of studies, spread of designs "
        "and countries)",
        "Theme 1 (primary): narrative synthesis of the dominant theme, "
        "with citations to all studies contributing to it, noting "
        "convergent and divergent findings",
        "Theme 2: narrative synthesis of the second major theme with "
        "citations",
        "Additional themes: continue for all themes identified, each with "
        "its own subheading if corpus > 12 studies",
        "Convergence paragraph: explicit statement of where the evidence "
        "converges (what is consistently found across studies)",
        "Divergence paragraph: explicit statement of where studies "
        "contradict each other or yield mixed findings, with possible "
        "explanations (e.g. methodological differences, context differences)",
        "Evidence gap paragraph: gaps identified by the synthesis — topics "
        "within the review's scope that remain under-studied",
    ],
    word_target=(700, 1100),
    scope_guardrails=[
        "Do not interpret or recommend here (that belongs in Discussion)",
        "Do not repeat the individual study summaries already given in "
        "results_individual_sources — synthesise across them",
        "Do not introduce new studies not in the corpus_charts",
    ],
    output_format=(
        "Markdown prose with level-3 subheadings (###) for each major "
        "theme. All claims must trace to corpus citations in "
        "(FirstAuthor et al., Year) format."
    ),
    extra_guidance=[
        "Derive themes from the findings.themes field in each chart; "
        "group similar themes under a common label",
        "The convergence/divergence and gap paragraphs are critical for "
        "PRISMA-ScR compliance — do not omit them",
        "Quantify where possible: e.g. 'Twelve of eighteen studies reported "
        "improved student engagement...'",
    ],
))


# ===========================================================================
# DISCUSSION — SUMMARY OF EVIDENCE  (PRISMA-ScR item 19)
# ===========================================================================
_reg(SectionPrompt(
    section_id="discussion_summary",
    prisma_scr_item=(
        "Item 19 — Summary of evidence: Summarise the main results "
        "(including an overview of concepts, themes, and types of evidence "
        "available), link to the review objectives, and consider the "
        "relevance to key stakeholders. (Tricco et al. 2018)"
    ),
    objective=(
        "Interpret the synthesised findings in relation to the review's "
        "objectives, contextualise them against the existing literature, "
        "and articulate implications for key stakeholders."
    ),
    required_evidence=[
        "project_context.research_question",
        "project_context.population",
        "project_context.concept",
        "project_context.context",
        "previous_sections: results_synthesis",
    ],
    structural_requirements=[
        "Opening: concise statement of the principal findings, linked "
        "explicitly to the review's research question",
        "Contextualisation paragraph: how these findings compare to, "
        "extend, or diverge from prior systematic or scoping reviews on "
        "related topics (use general disciplinary knowledge — do not "
        "cite included studies as comparators here)",
        "Implications for practice paragraph: specific, actionable "
        "implications for educators, clinicians, or curriculum designers "
        "in the relevant field",
        "Implications for policy paragraph: implications for accreditation "
        "bodies, professional associations, or health workforce planners",
        "Implications for further research paragraph: what future studies "
        "are most needed, based on the gaps identified in results_synthesis",
        "Relevance to key stakeholders paragraph: who will benefit from "
        "this review and how (e.g. dental school faculty, postgraduate "
        "training leads, accrediting bodies, students)",
    ],
    word_target=(500, 800),
    scope_guardrails=[
        "Do not introduce new data from the corpus not already presented "
        "in Results sections",
        "Do not describe methods here",
        "Do not list limitations here (that belongs in discussion_limitations)",
        "Do not use author-year citations from the corpus as primary support "
        "for interpretive claims — the summary should synthesise, not repeat",
    ],
    output_format=(
        "Markdown prose, 5–6 paragraphs corresponding to structural "
        "requirements. No subheadings within this section — run as "
        "continuous prose."
    ),
    extra_guidance=[
        "Begin with: 'This scoping review identified [n] studies...' or "
        "similar — anchor immediately to the evidence base",
        "The implications paragraphs should be specific, not generic; "
        "avoid 'more training is needed' without specifying what kind",
    ],
))


# ===========================================================================
# DISCUSSION — LIMITATIONS  (PRISMA-ScR item 20)
# ===========================================================================
_reg(SectionPrompt(
    section_id="discussion_limitations",
    prisma_scr_item=(
        "Item 20 — Limitations: Discuss any limitations of the scoping "
        "review process. (Tricco et al. 2018)"
    ),
    objective=(
        "Transparently acknowledge the methodological limitations of this "
        "scoping review — focused on the REVIEW PROCESS, not on the "
        "limitations of individual included studies."
    ),
    required_evidence=[
        "project_context.research_question",
        "previous_sections: results_characteristics, methods_search, "
        "methods_eligibility",
    ],
    structural_requirements=[
        "Limitation 1 — Search comprehensiveness: databases covered, "
        "languages restricted, grey literature coverage; note whether "
        "hand-searching was conducted and its scope",
        "Limitation 2 — Language bias: if restricted to English, "
        "acknowledge potential exclusion of relevant non-English studies",
        "Limitation 3 — Synthesis method: narrative synthesis cannot "
        "quantify effect sizes; heterogeneity precluded meta-analysis",
        "Limitation 4 — Heterogeneity: variability in study designs, "
        "populations, outcome measures, and settings limits direct "
        "comparison across studies",
        "Limitation 5 — Critical appraisal: if not conducted, acknowledge "
        "that quality assessment was outside scope and results should be "
        "interpreted in light of included studies' own limitations",
        "Limitation 6 — Screening: if single-reviewer screening was used, "
        "acknowledge the risk of selection error",
        "For each limitation: one sentence on what step was taken to "
        "mitigate it, or an honest acknowledgement that mitigation was "
        "not possible",
    ],
    word_target=(250, 450),
    scope_guardrails=[
        "Focus exclusively on limitations of the REVIEW PROCESS — not "
        "on limitations of individual included studies (those belong in "
        "results_critical_appraisal)",
        "Do not discuss implications or recommendations here "
        "(that belongs in discussion_conclusions)",
        "Do not repeat findings",
    ],
    output_format=(
        "Markdown prose, structured as a series of named limitation "
        "statements integrated into flowing paragraphs — not a bullet list"
    ),
    extra_guidance=[
        "The limitation section is not an apology — frame each limitation "
        "factually and pair it with the mitigating step taken",
        "Protocol non-registration (if applicable) should be acknowledged "
        "here if not already noted in methods_protocol",
    ],
))


# ===========================================================================
# DISCUSSION — CONCLUSIONS  (PRISMA-ScR item 21)
# ===========================================================================
_reg(SectionPrompt(
    section_id="discussion_conclusions",
    prisma_scr_item=(
        "Item 21 — Conclusions: Provide a general interpretation of the "
        "results with respect to the review objectives, and describe the "
        "implications for future research, practice, or policy. "
        "(Tricco et al. 2018)"
    ),
    objective=(
        "Deliver a synthesis-level conclusion that closes the review by "
        "answering the research question, summarising key themes, and "
        "setting a concrete research agenda."
    ),
    required_evidence=[
        "project_context.research_question",
        "previous_sections: discussion_summary, discussion_limitations",
    ],
    structural_requirements=[
        "Opening statement: direct, one-sentence answer to the review's "
        "research question based on the evidence mapped",
        "Key theme summary: 3–4 key findings stated concisely in prose "
        "(not a bullet list), each anchored to the review's evidence base",
        "Implications for practice: 1–2 specific, actionable recommendations "
        "for educators, practitioners, or curriculum leads",
        "Implications for policy: 1–2 specific implications for "
        "accreditation bodies, professional organisations, or health "
        "workforce policy",
        "Research agenda: 3–5 specific and prioritised future research "
        "directions that address gaps identified in the review — each "
        "framed as a researchable question or study design need",
        "Closing sentence: statement on the value of this scoping review "
        "for the field",
    ],
    word_target=(300, 500),
    scope_guardrails=[
        "Do not introduce new data or citations from the corpus",
        "Do not repeat limitations (those belong in discussion_limitations)",
        "Do not use hedging language that undermines the conclusion "
        "('it may possibly be suggested that...')",
        "Research agenda items must be specific: not 'more research is "
        "needed' but 'randomised trials comparing X versus Y in Z setting "
        "are warranted'",
    ],
    output_format="Markdown prose, 5–6 focused paragraphs",
    extra_guidance=[
        "The opening sentence must directly echo the research question "
        "from the objectives section",
        "The research agenda should be ordered by priority or logical "
        "sequence (foundational before applied)",
    ],
))


# ===========================================================================
# FUNDING  (PRISMA-ScR item 22)
# ===========================================================================
_reg(SectionPrompt(
    section_id="funding",
    prisma_scr_item=(
        "Item 22 — Funding: Describe sources of funding for the included "
        "sources of evidence, as well as sources of funding for the scoping "
        "review. Describe the role of the funders in the scoping review. "
        "(Tricco et al. 2018)"
    ),
    objective=(
        "Disclose all funding sources for this review and any potential "
        "conflicts of interest, and summarise funding patterns among the "
        "included studies if charted."
    ),
    required_evidence=[
        "project_context.research_question",
    ],
    structural_requirements=[
        "Statement of funding for this scoping review: named funder(s) "
        "with grant reference numbers, or explicit statement that the "
        "review received no external funding",
        "Role of funder(s) in the review: did funder(s) influence study "
        "design, data collection, analysis, interpretation, or the "
        "decision to publish?",
        "Conflicts of interest declaration for all review authors",
        "Summary of funding sources of included studies (if funding data "
        "were charted): e.g. proportion industry-funded vs. publicly "
        "funded vs. unfunded",
    ],
    word_target=(50, 200),
    scope_guardrails=[
        "Do not discuss study quality or results here",
        "Do not discuss methods",
    ],
    output_format="Markdown prose, 2–3 short paragraphs",
    extra_guidance=[
        "If funding details for this review are unknown, use "
        "[TO BE FILLED — funding source and grant reference] — do not "
        "invent funding details",
        "The conflicts of interest statement is mandatory even if there "
        "are none: 'The authors declare no conflicts of interest.'",
        "Funding data for included studies may not be available in the "
        "charted corpus; if so, state: 'Funding sources of included "
        "studies were not systematically charted in this review.'",
    ],
))


# ===========================================================================
# Public API
# ===========================================================================

def get_prompt(section_id: str) -> SectionPrompt:
    """Return the SectionPrompt for section_id, raising NotImplementedError if absent."""
    if section_id not in SECTION_PROMPTS:
        raise NotImplementedError(
            f"No prompt defined for section '{section_id}'. "
            f"Implemented sections: {sorted(SECTION_PROMPTS.keys())}"
        )
    return SECTION_PROMPTS[section_id]


def available_sections() -> list[str]:
    """Return sorted list of all implemented section IDs."""
    return sorted(SECTION_PROMPTS.keys())
