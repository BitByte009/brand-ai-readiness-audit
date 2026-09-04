# Aggregation and deduplication

## Aggregation
The unit of a finding is `(check_id, template_cluster)` — never `(check_id, url)`.
Twelve product pages missing the same thing is ONE finding carrying
`affected: {count, total_in_scope, sample_urls[<=5]}`. That count then feeds the
scope modifier in the severity matrix.

## Cross-skill deduplication
Findings are partitioned by question, not by artifact, so overlap should be rare.
Where two skills legitimately fire on the same page from different lenses (for example
D-ENTITY-02 machine-facing and E-ORIENT-01 human-facing), that co-occurrence is a real
signal and is KEPT, with a `related_findings` cross-reference.

Merge only when: **same `check_id`** (the narrowest, safest reading of "same
check family, same mechanism" — two different check IDs are, by the marketplace's
own partition-the-question-space design, never the same mechanism, so merging
across check IDs is never attempted here regardless of how similar two titles
look) **and** a substantially overlapping URL set (`source_urls ∪
affected.sample_urls`, Jaccard similarity `>= 0.5`). Each skill already
aggregates internally to one finding per `(check_id, template_cluster)`
(`PROJECT_CONTEXT.md` D-7), so a same-check_id collision in the pooled set
should be rare; this pass exists as a defensive second aggregation over the
*pooled* set, not the primary one.

The surviving finding inherits, from the whole merged group: the union of
`observation_ids` and `source_urls`, `affected.sample_urls` as the first 5 of
that union, `affected.count` as the **size of that union** (never a sum —
the merge criterion itself requires substantial URL overlap, so summing each
source's count would double-count every URL the sources already agree is
affected, inflating scope for the exact case merging exists to normalize
away), the **max** of `affected.total_in_scope`, and the **highest**
`confidence` among the group (more independent evidence supporting the same
defect is never weaker
evidence than the single strongest report of it). All other fields (title,
mechanism, impact, evidence text, suggested_action) are taken from whichever
source finding in the group has the highest confidence, then the largest
`affected.count`, as a deterministic tie-break.

## Cross-skill relationship table

Legitimate cross-skill co-occurrence on the same page, from different lenses,
is a real signal — kept, never merged, and cross-referenced via
`related_findings` once both findings have their final `id` (done in
`scripts/score.py`, after ranking, since `related_findings` must point at real
`F-NNN` ids). Two findings are cross-referenced whenever they share **any**
URL in `source_urls ∪ affected.sample_urls` and do **not** share a `check_id`
(same-`check_id` overlap is the merge case above, not a cross-reference case).
Named examples this covers, per each pair of skills' own documented boundary:

| Pair | Why they legitimately co-occur, never merge |
|---|---|
| `D-ENTITY-02` (type never stated, machine-facing) + `E-ORIENT-01` (no brand ID on arrival, human-facing) | Same page, different lens: one is about text a machine can parse, the other about what a cold human visitor sees first |
| `D-CRAWL-09` (fetch blocked) + `E-ANSWER-02` (reader blocked after a successful fetch) | Different gate: D-CRAWL-09 is the fetch never succeeding; E-ANSWER-02 requires a successful render — structurally cannot be the same event |
| `D-ENTITY-04` (cross-page address conflict) + `D-TRUST-03` (cross-page price/stat/date conflict) | Partitioned by fact type (**who** vs. **what/when**), per `PHASE1B` Part 3 — a page with both an address conflict and a price conflict gets two findings, correctly |
| `D-EXTRACT-02` (title/meta uniqueness) + `E-ANSWER-01` (title/body promise) | Both read the title, but D-EXTRACT-02 tests presence/uniqueness while E-ANSWER-01 tests whether the body delivers on it |
| `D-RENDER-01/02` (content render-only) + `E-ANSWER-04` (citation-landing mismatch) | D-RENDER fires on the machine-reachability gap (raw vs. rendered); E-ANSWER-04 fires on the human-visibility gap (buried vs. locatable) even when both lenses agree the content exists |

No pair on this table is ever merged into one finding — the whole point of
`related_findings` is to make a real, non-duplicative relationship visible to
a report reader without collapsing two different mechanisms into one claim.
