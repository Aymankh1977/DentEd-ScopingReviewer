# DentEdTech-ScopingReviewer™

**AI-powered scoping review generator and manuscript critique platform**
for Health Professions Education (HPE) and dental education research,
following the **PRISMA-ScR** reporting standard.

## What it does

1. **Generate scoping reviews from scratch** — ingest a corpus of PDFs,
   extract themes, build a coherent manuscript section by section.
2. **Critique existing manuscripts** — uniqueness audit, originality check,
   section-level rigour, coherence across the full document.
3. **Section-by-section workflow** — each PRISMA-ScR section is built and
   audited independently, then assembled and checked for comprehension.

## PRISMA-ScR coverage

22-item checklist baked in — see `docs/prisma_scr/checklist.md`.

## Stack

- Streamlit (UI)
- Anthropic Claude API (multi-key, role-specialised)
- pypdf / pdfplumber (document parsing)
- pandas (charting study attributes)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your keys
streamlit run app.py
```

## Multi-key strategy

| Key                              | Role                                      |
|----------------------------------|-------------------------------------------|
| `ANTHROPIC_API_KEY_PRIMARY`      | Orchestration, planning, assembly         |
| `ANTHROPIC_API_KEY_EXTRACTION`   | PDF parsing, attribute charting           |
| `ANTHROPIC_API_KEY_CRITIQUE`     | Originality + coherence audits            |
| `ANTHROPIC_API_KEY_DRAFTING`     | Section prose generation (highest spend)  |
| `ANTHROPIC_API_KEY_FALLBACK`     | Hot spare for rate-limit overflow         |

## Status

🚧 Scaffolding in place. Section modules to follow.
