# Observation store contract (engagement-audit)

This skill never fetches (`PROJECT_CONTEXT.md` D-6, D-2). It reads `HTTP_FETCH`/
`RENDER` observations, the `entity_profile` built by `entity-semantic-audit` (for
brand tokens), and `PROBE` observations. Mirrors the store-contract convention
established by `crawl-render-audit`/`entity-semantic-audit`/`trust-freshness-audit` —
each skill documents only the part of the shared contract it actually reads.

| Type | Cardinality | `value` shape (fields this skill reads) |
|---|---|---|
| `HTTP_FETCH` | one per crawled URL | `{status_code, final_url, headers, html}` — used as a fallback lens and for `E-CONTINUE-04`'s link-status check. |
| `RENDER` | zero or one per sampled URL | `{status, html}`. This is the **primary** lens for this skill — a human visitor experiences the rendered page, not raw HTML. Text-based checks (`E-ORIENT-01`, `E-ANSWER-01`, `E-CONTINUE-*`) fall back to raw `HTTP_FETCH` HTML when no render exists (`effective_pages()`, same pattern as the other two detector skills). DOM-geometry checks that reason about what appears at first paint (`E-ANSWER-02`, `E-ANSWER-04`) do **not** fall back — without a render, they are inapplicable and stay silent, never approximated from raw HTML, because "what a rendered page shows at first paint" is not a question raw HTML can answer. |
| `PAGE_CLASSIFICATION` | zero or one per URL | `{page_type}` — used to recognize utility/terminal pages (e.g. `contact`, `thank_you`) whose job is complete and need no next step (`E-CONTINUE-01`/`02`/`03`). |
| `PROBE` | zero or one per URL | `{questions: [{id, category, answered, answer, evidence_span}], source_text_hash}`. This skill reads `category == "engagement"` questions **Q5** (what question does this page answer) and **Q8** (how would a visitor take the next step) from `references/probe-questions.md`'s canonical numbering (defined in `entity-semantic-audit`'s references, consumed here per that file's own "Consumed by" column) — never `factual` or `identity` questions, which belong to `crawl-render-audit` and `entity-semantic-audit` respectively. |

`entity_profile` (not a store observation — an artifact passed in alongside the
store, exactly as `trust-freshness-audit` consumes it) supplies the canonical name
and aliases used as the brand-token set for `E-ORIENT-01`.

Archetype gating reads the store's top-level `archetype` field.

## Deterministic-first, and the two LLM-adjacent judgment points

Per this skill's design brief: prefer deterministic, positional/structural
measurement everywhere. Two checks reason about a *judgment* rather than a
structural fact — title/body promise matching (`E-ANSWER-01`) and whether an
outgoing link is a *relevant* next step (part of `E-CONTINUE-01`) — and both are
built deterministic-first (word-containment overlap, link-text/target
classification) with the `PROBE` engagement questions as a fallback only, exactly
the pattern `entity-semantic-audit` and `trust-freshness-audit` already use. No
finding from either check is asserted at more than medium confidence or medium
severity (`SKILL.md` Evidence rules), and both are structurally incapable of
resting on aesthetics — every trigger is a text or DOM-structural measurement.
