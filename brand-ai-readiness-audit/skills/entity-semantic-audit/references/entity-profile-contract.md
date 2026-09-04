# entity_profile contract

`scripts/build_entity_profile.py`'s output. Consumed by `scripts/detect_entity.py`
in this skill, and — per `SKILL.md` Outputs and `PHASE1B` Part 1.3 — by
`trust-freshness-audit` and the orchestrator's proactive layer. Changing this shape
changes three skills' inputs; treat it as a public contract, not an implementation
detail.

```
{
  "fields": {
    "<field>": {
      "value": <str|null>,           # the dominant/canonical value, or null if none found
      "candidates": [
        {"value": <str>, "source": "title|h1|schema|footer|meta|probe",
         "source_url": <str>, "observation_id": <str>}
      ],
      "consistent": <bool>,          # true iff candidates converge (see entity-checks.md D-ENTITY-01/04)
      "determined_by": "deterministic|probe|none"
    },
    ...
  },
  "field_names": ["canonical_name", "entity_type", "description", "primary_offering",
                  "location", "official_domain", "aliases", "distinguishing_attributes"],
  "identity_anchor": {
    "present": <bool>,
    "same_as": [<str>, ...],
    "self_url": <str|null>,
    "observation_ids": [<str>, ...]
  },
  "archetype": <str>,
  "pages_considered": [<str>, ...]
}
```

## Field notes

- **canonical_name** — candidates from title/h1/schema/footer across every crawled
  page; `consistent` is true when the normalized-core name (legal suffixes and
  punctuation stripped) converges to one dominant value. See D-ENTITY-01.
- **entity_type** — one site-level determination, not per-page: a type-word found
  anywhere in prose, or JSON-LD `@type`, or (fallback) `PROBE` question **Q2**. See
  D-ENTITY-02.
- **description** — per-page candidate (meta description / `og:description` /
  JSON-LD `description` on an `Organization` node), kept per-page (not collapsed)
  because D-ENTITY-04 compares pairs of these directly.
- **primary_offering** — JSON-LD `Product`/`Service`/`Offer`, a structural "we
  offer/sell/provide/build/make/help ..." sentence, or (fallback) `PROBE` **Q3**.
  Archetype-gated at detection time, not at profile-build time — the profile
  records what was found or not found; `detect_entity.py` decides whether that
  absence matters for this archetype. See D-ENTITY-06.
- **location** — JSON-LD `PostalAddress`, kept per-page-that-asserts-one (not
  collapsed) for the same reason as `description`. A `branch_name` field (the
  JSON-LD node's own `name`, if any) rides along so legitimate multi-location
  businesses are distinguishable from a genuine conflict. See D-ENTITY-04.
- **official_domain / aliases** — populated from `identity_anchor.same_as` entries
  and any secondary name candidates not treated as the canonical value.
- **distinguishing_attributes** — category/type + location/domain-of-operation +
  the identity anchor, assembled for D-ENTITY-03's compound trigger; not a field
  this skill extracts independently.

## Provenance discipline

Every candidate keeps its `source` (`title|h1|schema|footer|probe`) and, where it
came from a fetched page, the `observation_id` it can be traced back to. A finding
that cites a `canonical_name`/`description`/`location` conflict always resolves to
real `HTTP_FETCH` (or `PROBE`) observation IDs through this trail — the same
evidence-binding discipline `crawl-render-audit` uses (`PROJECT_CONTEXT.md` D-3).
