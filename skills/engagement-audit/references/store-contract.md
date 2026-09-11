# Observation store contract (engagement-audit)

This skill never fetches (`PROJECT_CONTEXT.md` D-6, D-2). It reads `HTTP_FETCH`/
`RENDER` observations, the `entity_profile` built by `entity-semantic-audit` (for
brand tokens), and `PROBE` observations. Mirrors the store-contract convention
established by `crawl-render-audit`/`entity-semantic-audit`/`trust-freshness-audit` —
each skill documents only the part of the shared contract it actually reads.

| Type | Cardinality | `value` shape (fields this skill reads) |
|---|---|---|
| `HTTP_FETCH` | one per crawled URL | `{status_code, final_url, headers, html}` — used as a fallback lens and for `E-CONTINUE-04`'s link-status check. |
| `RENDER` | zero or one per sampled URL | `{status, status_code, html}`. Prefer successful 2xx rendered HTML. Eligible text checks may fall back to successful 2xx raw HTML, but render-dependent checks may not. The current renderer supplies HTML, not viewport/first-paint geometry; DOM order is a structural proxy only. Shared [page selection](../../../lib/common/pages.py) rejects failed-page content. |
| `PAGE_CLASSIFICATION` | zero or one per URL | `{page_type}` — used to recognize utility/terminal pages (e.g. `contact`, `thank_you`) whose job is complete and need no next step (`E-CONTINUE-01`/`02`/`03`). |
| `PROBE` | zero or one per URL | `{questions: [{id, category, answered, answer, evidence_span}], source_text_hash}`. Reads engagement Q5/Q8 only, following the [canonical probe questions](../../entity-semantic-audit/references/probe-questions.md). The collector generates positive factual spans; Q5/Q8 engagement-model answers remain unavailable. E-ANSWER-04 can use relevant factual spans. |

`entity_profile` (not a store observation — an artifact passed in alongside the
store; the optional trust recorder can also consume it) supplies the canonical name
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
