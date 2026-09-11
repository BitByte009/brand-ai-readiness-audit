# Corroboration honesty rules

Hard constraint. The single easiest way for this marketplace to produce a false and
unfalsifiable finding is to assert that a claim is uncorroborated without having looked.

1. The corroboration finding class (D-TRUST-05) and the collision half of D-ENTITY-03
   may only be emitted when a corroboration record exists in the store.
2. A corroboration record contains: query string, method, timestamp, result count,
   result URLs. No record, no finding.
3. Absent a record the state is neither pass nor fail. It is X-COV-01 with reason
   SEARCH_UNAVAILABLE.
4. Report language must distinguish "no independent source was found" from
   "no independent source exists." Only the first is ever true of what we did.
5. Absence of results within our budget is reported with the budget stated.
6. A source that mentions the queried name is not corroboration by itself — it
   must be confirmed to describe *this* entity, not a different one that happens
   to share the name. Every source in a corroboration record carries its own
   `entity_match` boolean, cross-checked against `entity-semantic-audit`'s
   `entity_profile` (canonical name, type, location/identity-anchor — the same
   fields that check already extracted, never re-derived here). A record where
   every source has `entity_match: false` is reported as an **identity-confusion**
   finding, not silently folded into "nothing was found" — those are different
   facts about the world and the report must say which one occurred.
7. `scripts/corroborate.py` never fetches the live web itself inside this
   implementation. It is a capability-detected recorder: given search results
   (already obtained by an authorized caller, or injected for testing), it
   builds the `CLAIM_CORROBORATION` observation and runs the `entity_match`
   check deterministically. With no results supplied, it returns an honest
   `performed: false` record — the same graceful-degradation pattern
   `lib/site_observer/render.py` uses for an absent headless-browser capability.
   This keeps the corroboration record itself reproducible and testable even
   though the underlying web search is not.
8. Naming the entity is not enough to confirm a source is about it. A source
   whose text also disambiguates itself from the entity ("not affiliated
   with", "no relation to", "not to be confused with", ...) is never scored
   `entity_match: true`, regardless of any other signal —
   `_trust_util.source_matches_entity`'s `_DISAMBIGUATION_RE` guard exists
   specifically because a hostile review found a disclaimer *warning about* a
   name collision being scored as *confirming* corroboration, which inverts
   this rule's entire purpose.
9. The 45-second corroboration allocation in the [orchestration rules](../../audit-orchestrator/references/orchestration-rules.md)
   is a future integration allowance, not a wired search capability. Only
   `entity_fact` claims and unattributed `superlative_stat`
   claims are things D-TRUST-05 can act on at all.
   `_trust_util.is_corroboration_worthy()` is the selection rule, and
   `corroborate.py`'s CLI warns (without blocking) when it's asked to record
   results for a claim that fails it — a `time_sensitive` claim needs a date,
   not a second opinion, and spending the search budget on one is exactly the
   "unnecessary external lookup" this rule exists to name.
