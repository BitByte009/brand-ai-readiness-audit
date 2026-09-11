# claim_table contract

`scripts/build_claim_table.py`'s output. Consumed by `scripts/detect_trust.py`.
Mirrors `entity-semantic-audit`'s `entity_profile` contract in spirit: one shared,
deterministic fact table that every check reads rather than each re-deriving its
own extraction.

```
{
  "claims": [
    {
      "id": "CLAIM-<hash>",
      "claim_type": "time_sensitive | dated_offer | dated_event | entity_fact | superlative_stat",
      "text": "<the sentence or phrase asserting the claim>",
      "key": "<normalized comparison key, entity_fact only, e.g. 'founded_year'>",
      "value": "<normalized value, entity_fact only>",
      "date_value": "<ISO date, dated_offer/dated_event only>",
      "attributed": <bool, superlative_stat only>,
      "source_url": "<page the claim was found on>",
      "observation_id": "<HTTP_FETCH or RENDER observation id the text was read from>"
    }, ...
  ],
  "date_inventory": {
    "<url>": {
      "schema_dates": ["<ISO date>", ...],
      "visible_dates": ["<ISO date>", ...],
      "header_date": "<ISO date>|null",
      "copyright_year": <int>|null,
      "observation_id": "<HTTP_FETCH or RENDER observation id this page's dates were read from>"
    }, ...
  },
  "pages_considered": ["<url>", ...]
}
```

## Claim types

- **`time_sensitive`** — a sentence matching the time-sensitive phrase pattern
  (D-TRUST-01). No `key`/`value`; the finding cross-references `date_inventory`
  for the same page.
- **`dated_offer` / `dated_event`** — a forward-framed claim ("sale ends",
  "upcoming") paired with an extracted date (D-TRUST-02).
- **`entity_fact`** — a keyed, normalized, comparable fact (founding year,
  employee/customer count) used for cross-page contradiction detection
  (D-TRUST-03). Only claim types with a `key` are ever compared against each
  other; two claims with different keys are never compared, and per-product/plan
  facts (price, spec) are deliberately never extracted into this claim type — see
  `trust-checks.md` D-TRUST-03's scope note on why.
- **`superlative_stat`** — a falsifiable ranking/statistic claim, carrying whether
  it was found with a nearby citation (D-TRUST-04).

## Provenance discipline

Every claim carries `source_url` and `observation_id` so a finding that cites it
resolves to a real observation — the same evidence-binding discipline used
throughout the marketplace (`PROJECT_CONTEXT.md` D-3).

## What this table deliberately does not contain

Identity facts (name, type, offering, location as an *identity* attribute) belong
to `entity-semantic-audit`'s `entity_profile`, not here — this skill reads that
profile (see `store-contract.md`) rather than re-extracting it. This table holds
only claims this skill's own checks (D-TRUST-01..06) reason about: **what is
asserted and when**, never **who** is asserting it.
