# entity-semantic-audit — Engineering Study Guide

> Companion to `SKILL.md`. Shared vocabulary, the observation store and the
> finding contract are in the root `KNOWLEDGE.md` (§6, §8); orchestration is in
> `skills/audit-orchestrator/KNOWLEDGE.md`.

---

## A. PURPOSE AND MENTAL MODEL

**Mental model:** think of this skill as an *entity-resolution auditor* that
takes the observation store, builds one **entity profile** — a fact table about
"who operates this site", with per-field provenance — and then asks six questions
about whether a machine could resolve this site to a single, correctly-typed,
unambiguous entity.

The two-stage structure is the important thing:

```
store ──► build_entity_profile.py ──► entity_profile ──► detect_entity.py ──► findings
             (construction)            (fact table)         (judgement)
```

`build_entity_profile` never emits findings. `detect_entity` never re-reads raw
HTML for identity facts — it reads the profile. This separation is why the
profile is also handed to `engagement-audit` (for `E-ORIENT-01`'s brand tokens):
one identity construction, two consumers.

**The question it answers.** "If an AI system read this site, could it say *what
this is* and *not confuse it with something else*?"

**What it considers evidence.** Name candidates harvested from `<title>`
segments, the first `<h1>`, JSON-LD identity nodes, and footer copyright lines;
type keywords in prose; offering patterns; addresses; `sameAs`/`url` anchors.

**What it does NOT determine.** Reachability or readability (`crawl-render-audit`),
whether claims are true or fresh (`trust-freshness-audit`), or the human arrival
experience (`engagement-audit`). It also does not perform entity resolution
against the outside world — `D-ENTITY-03` needs a corroboration instrument that
does not exist here (§F.3).

---

## B. COMPLETE FILE MAP

### `scripts/build_entity_profile.py` (~460 lines) — the constructor
- **Purpose:** produce `entity_profile` from the store.
- **Called by:** `run_audit.py::_invoke_detectors` (before the detectors, in its
  own try/except so a profile failure degrades rather than killing the audit),
  and by `detect_entity` / `detect_engagement` as a consumer input.
- **Calls:** `_entity_util` (all helpers), `lib.common.extract`
  (`extract_metadata`, `extract_text`, `schema_type_matches`).
- **Outputs:** `{fields: {...}, identity_anchor: {...}, pages_considered: [...], archetype: ...}`.
- **Important functions:** `_collect_name_candidates`, `_structured_identity`,
  `_canonical_name_field`, `_aliases_field`, `_entity_type_field`,
  `_description_field`, `_offering_field`, `_is_entity_level_page`,
  `_is_entity_subject_page`, `_official_domain_field`, `_format_address`.
- **Constants:** `FIELD_NAMES` (8 fields), `MIN_STRUCTURED_IDENTITY_PAGES = 2`,
  `MIN_ALIAS_PAGES = 2`, `_ADDRESS_PARTS`.

### `scripts/detect_entity.py` (439 lines) — the judge
- **Purpose:** `D-ENTITY-01..06`.
- **Inputs:** `(store, profile)`. `check_d_entity_05` additionally takes
  `sibling_fired: bool`.
- **Constants:** `CATEGORY = "identity"`,
  `_SEVERITY_DOWNGRADE = {"high":"medium","medium":"low","low":"low"}`,
  `_CONFIDENCE_DOWNGRADE` (same shape).
- **Important helpers:** `_min_similarity_pair`, `_addresses_conflict`.

### `scripts/_entity_util.py` (199 lines) — the vocabulary and text tools
| Symbol | Role |
|---|---|
| `IDENTITY_NODE_TYPES` | `{Organization, LocalBusiness, Person}` — what counts as an identity declaration |
| `normalize_name` | strips legal suffixes + punctuation, lowercases, collapses whitespace |
| `text_similarity` | `max(SequenceMatcher ratio, containment_ratio)` |
| `normalize_address_part` | lowercases, strips punctuation, expands street abbreviations |
| `TYPE_KEYWORDS` / `type_keyword_match` | English category words ("platform", "shop", …) |
| `TYPE_LABEL_MAP` | schema `@type` → human label |
| `_OFFERING_PATTERN_RE` / `offering_pattern_match` | English "we sell/build/provide X" patterns |
| `_COPYRIGHT_RE` / `footer_copyright_name` | extracts the operator name from a `©` line |
| `jsonld_nodes_of_type` | typed JSON-LD node extraction |
| `homepage_url`, `depth1_urls` | scope helpers for `D-ENTITY-06` |
| `corroboration` | fetches the `CLAIM_CORROBORATION` observation — returns `None` here |
| `SUPPRESSED_OFFERING_ARCHETYPES`, `RETHRESHOLD_*_ARCHETYPES` | archetype gating |
| `LEGAL_REGISTER_SOURCES = {schema, footer}` / `PUBLIC_FACING_SOURCES = {title, h1}` | the legal-vs-trading-name distinction |

### References
`entity-checks.md` (per-check prose), `entity-profile-contract.md` (the exact
profile shape — **read this before the code**), `probe-questions.md` (Q2/Q3/Q4,
the identity questions the unavailable probe would answer), `fp-guardrails.md`,
`store-contract.md`.

### Shared library
`lib/common/extract.py` — `extract_metadata`, `extract_text`, `title_segments`,
`significant_words`, `containment_ratio`, `schema_type_matches`, `extract_jsonld`.
`lib/common/findings.py`, `lib/common/observations.py`.

### Tests and fixtures
`tests/test_entity_semantic_audit.py` (~985 lines after the authority tests).
Fixtures: `ambiguous-entity`, `conflicting-content`, `both-weak`,
`no-structured-data-ok`, `single-page-site`, `unusual-site-structure`.

---

## C. END-TO-END WORKFLOW

```
store (HTTP_FETCH × N, RENDER × M)
  │
  ▼  effective_pages(store)   — rendered HTML preferred over raw where present
┌─────────────────────────────────────────────────────────────────┐
│ build_entity_profile.py                                          │
│  1. _collect_name_candidates  → [{value, source, source_url, id}]│
│       sources: title-segment | h1 | schema | footer               │
│  2. _structured_identity      → authority verdict (5 conditions)  │
│  3. _canonical_name_field(candidates, identity)                   │
│  4. _aliases_field(candidates, canonical)   (≥2 pages OR declared)│
│  5. _entity_type_field   (prose keyword → schema label → probe)   │
│  6. _description_field(pages, identity)                           │
│  7. _offering_field, _location, _official_domain, distinguishers  │
└─────────────────────────────────────────────────────────────────┘
  │  entity_profile
  ▼
┌─────────────────────────────────────────────────────────────────┐
│ detect_entity.detect_entity(store, profile)                      │
│   01 name → 02 type → 03 collision → 04 consistency → 06 offering│
│   05 anchor  (only if a sibling fired: compound trigger)          │
└─────────────────────────────────────────────────────────────────┘
  │  findings
  ▼  pooled with the other detectors
```

**Also consumed by engagement:** `run_audit` passes the same `entity_profile`
object to `detect_engagement.detect_engagement(store, entity_profile)`.

**Failure behaviour.** If `build_entity_profile` raises, `run_audit` records a
`SKILL_FAILED` coverage entry scoped to *both* `entity-semantic-audit` and
`engagement-audit` (they share the profile) and passes `entity_profile=None`
onward. `_brand_tokens(None)` returns `[]`, so `E-ORIENT-01` no-ops.

---

## D. INPUT CONTRACT

| Input | Type | Origin | Required | If missing / malformed |
|---|---|---|---|---|
| `store["observations"]` | list | `collect.py` | yes | zero candidates → `D-ENTITY-01` fires its "no name found anywhere" branch |
| `HTTP_FETCH` / `RENDER` html | str | collector | yes | no pages ⇒ `pages_considered` empty |
| `store["archetype"]` | str | `lib/site_observer/classify.py` | optional | `""` ⇒ no archetype downgrade or suppression applies |
| `PROBE` obs | — | **never produced** | no | `_entity_type_field` never reaches its probe fallback; `D-ENTITY-02` confidence drops `high → medium`; `D-ENTITY-06`'s probe-miss path is unavailable |
| `CLAIM_CORROBORATION` obs | — | **never produced** | no | `D-ENTITY-03` returns `[]` at its first guard |
| `profile` | dict | `build_entity_profile` | yes for detect | `None` ⇒ orchestrator records `SKILL_FAILED` |

---

## E. OUTPUT CONTRACT

**`entity_profile`** (consumed by two skills, so treat it as a real interface):
```
fields: {
  canonical_name: {value, candidates[], consistent: bool, determined_by}
  aliases:        {value: "a, b", candidates[], consistent: None, determined_by}
  entity_type:    {value, candidates[], consistent, determined_by}
  description:    {value, candidates[], consistent: None, determined_by}
  primary_offering, location, official_domain, distinguishing_attributes
}
identity_anchor: {present: bool, ...}
pages_considered: [url]
archetype: str
```
`determined_by` ∈ `{"deterministic", "structured_identity", "probe", "none"}`.
`"structured_identity"` is the value introduced by the JSON-LD authority rule
(§H.1) and is the one to look for when debugging why `D-ENTITY-01` did or did not
fire.

`consistent` is `None` for `aliases` and `description` on purpose: those are
compared **pairwise by the checks**, not collapsed to one boolean at
construction time.

**Findings:** standard `make_finding` shape, `category = "identity"`.

---

## F. CHECK-BY-CHECK BREAKDOWN

### F.1 Evaluability

| Class | Checks |
|---|---|
| Always evaluable | `D-ENTITY-01`, `D-ENTITY-04`, `D-ENTITY-05` (compound), `D-ENTITY-06` |
| Evaluable, probe **softly** refines | `D-ENTITY-02` (confidence only), `D-ENTITY-06` (a probe miss is one of several triggers) |
| Not evaluable | `D-ENTITY-03` — hard-gated on `CLAIM_CORROBORATION` |

### F.2 The table

| Check | Purpose | Mechanical test | Severity | Confidence | Guardrails |
|---|---|---|---|---|---|
| **D-ENTITY-01** | no canonical name / no consistent name | branch A: `candidates == []`. branch B: `field["consistent"] is False` | `high`, downgraded to `medium` for `documentation`/`personal-portfolio` | high | Structured-identity authority (§H.1) sets `consistent=True`; the legal/trading-name pair rule; ≥70% dominance share |
| **D-ENTITY-02** | entity type never stated plainly | `field["value"]` is falsy | `high`, downgraded for `personal-portfolio` | `high` if a probe exists else `medium`, then downgraded | Prose keyword **or** schema-label-present-in-text satisfies it — a site saying "a modern data platform" passes |
| **D-ENTITY-03** | unresolved name collision | corroboration `performed` **and** ≥2 distinct source entities **and** no distinguishing attribute present | `high` if a match shares the entity type, else `medium` | high | **Never inferred.** Absent corroboration returns `[]` — explicitly *not* treated as "no collision found" |
| **D-ENTITY-04** | description conflicts across pages | `_min_similarity_pair(desc_candidates)` and `min_ratio < 0.5`; separately `_addresses_conflict` for locations | `high`, `medium` for `personal-portfolio` | `medium`, downgraded | Pairs on the *same* `source_url` are skipped; different `branch_name`s are a multi-location business, not a conflict; authoritative structured description short-circuits meta candidates |
| **D-ENTITY-05** | no machine-readable identity anchor | `sibling_fired` **and** `identity_anchor["present"] is False` | medium | high | **Compound only.** Never fires standalone — a site with clear prose identity and no `sameAs` is not a defect |
| **D-ENTITY-06** | primary offering unclear | archetype not suppressed; homepage exists; **no** offering candidate within `{home} ∪ depth1` | from profile | from profile | Suppressed entirely for `documentation`, `personal-portfolio`, `institutional`; scope is homepage **plus one click**, so brand-minimalist homepages pass if the offering is one click away |

### F.3 Prose on the ones that repay study

**`D-ENTITY-01` is the check most shaped by history.** Its branch B fires on
`consistent is False`, and `consistent` is computed in `_canonical_name_field` by
grouping candidates on `normalize_name` and requiring the dominant group to hold
`>= 0.7` share. Because *every page contributes its own title segments and h1*,
a perfectly healthy 4-page site with correct per-page titles used to fall below
0.7 and fire. See §H.1 and §J.

**`D-ENTITY-03`'s guard is a design statement, not a bug.** `if not corrob or not
corrob["value"]["performed"]: return []`. The alternative — treating "we did not
look" as "we looked and found nothing" — is exactly the dishonesty
`trust-freshness-audit/references/corroboration-honesty.md` exists to forbid.

**`D-ENTITY-05` is the only compound-trigger check in the skill.** `run_audit`'s
detector call passes `sibling_fired` computed from whether `D-ENTITY-01` or
`-02` produced anything. The rationale: a missing `sameAs` matters only when the
identity is *already* unclear.

**`D-ENTITY-06`'s scope helpers.** `homepage_url(store)` and `depth1_urls(store,
home)` bound the check to the homepage and its immediate children. Without that
bound, a site whose offering is stated on `/products/widgets/model-3` but not on
the homepage would be flagged, which contradicts the stated guardrail that
"deliberate brand minimalism on a homepage is fine if the offering is plain one
click away".

---

## G. SUPPORTING FUNCTIONS AND ALGORITHMS

### `_collect_name_candidates(pages)` — `build_entity_profile.py:64`
Harvests, per page: every `title_segments(...)` segment, the first `h1`, every
`jsonld_nodes_of_type(html, IDENTITY_NODE_TYPES)` `name`, and
`footer_copyright_name(html)`. Each candidate carries `{value, source,
source_url, observation_id}` — **provenance is attached at harvest time**, which
is what later makes the per-page alias filter possible.

### `_structured_identity(pages)` — `build_entity_profile.py`
The JSON-LD authority rule. Returns `None` unless **all five** hold:
1. at least one identity-typed node with a non-empty `name`;
2. exactly one distinct `normalize_name` across all such nodes;
3. present on `>= MIN_STRUCTURED_IDENTITY_PAGES (2)` pages **and** on `>= half`
   of `pages`;
4. any declared `url` resolves to this site — compared on a **www-stripped**
   host, with descendant hosts allowed;
5. the name is visible: `normalize_name(name)` appears in some page's
   `title + extract_text(html)`, also normalized.

Returns `{name, description, pages, observation_ids}`.

**Why each condition exists** — 2 stops arbitrary selection between competing
organizations; 3 stops one page's markup becoming sitewide truth; 4 stops an
embedded third-party node (a payment vendor, a review platform) being adopted as
the operator; 5 stops markup that contradicts the visible site from silencing the
very check that should report the contradiction.

### `_canonical_name_field(candidates, identity=None)`
If `identity` is not `None`: returns `{value: identity["name"], candidates:
<unchanged>, consistent: True, determined_by: "structured_identity"}`. **The
candidate list is preserved verbatim** — authority changes which name wins, never
what was observed, so the evidence trail stays complete.

Otherwise: group by `normalize_name`, take the largest group, `share = len(top)/total`,
`consistent = len(groups) <= 1 or share >= 0.7`. Then one rescue: if exactly two
groups and the minority is *only* from `LEGAL_REGISTER_SOURCES` while the
dominant includes a `PUBLIC_FACING_SOURCE`, treat it as a legal/trading-name pair
and set `consistent = True`.

### `_aliases_field(candidates, canonical_field)`
Groups non-dominant candidates by normalized name, then keeps a group only if it
appears on `>= MIN_ALIAS_PAGES (2)` distinct `source_url`s **or** any member came
from a `LEGAL_REGISTER_SOURCE`. This is the fix for alias pollution (§J).

### `_entity_type_field(store, pages)`
Ordered fallback, first hit wins: (1) `type_keyword_match(extract_text(html))`;
(2) a JSON-LD node whose `TYPE_LABEL_MAP` label *also appears in the page text* —
note the double requirement, markup alone is not enough; (3) probe Q2 —
unreachable here. Otherwise `{value: None, determined_by: "none"}`.

### `_description_field(pages, identity=None)`
Only `_is_entity_level_page(url, html)` pages contribute. Within those:
- `<meta name=description>` is collected **only** when `_is_entity_subject_page(url)`
  (path is `/` or contains `about`) **and** no authoritative structured
  description exists;
- an `Organization`/`LocalBusiness` node's `description` is always eligible.

The semantic distinction: a meta description describes *the page*; an
`Organization.description` describes *the entity*.

### `_min_similarity_pair(candidates)` — `detect_entity.py`
O(n²) over candidate pairs, skipping same-URL pairs, returning the *minimum*
`text_similarity`. Minimum rather than average because one genuine contradiction
should not be diluted by several agreeing descriptions.

### `_addresses_conflict(a, b)` — `detect_entity.py`
Returns `False` immediately when both carry different `branch_name`s. Otherwise
compares each shared field under `normalize_address_part`.

### `text_similarity(a, b)` — `_entity_util.py:102`
`max(SequenceMatcher(a,b).ratio(), containment_ratio(a,b))`. The containment
boost stops a short description that is a subset of a long one from reading as a
conflict. **Cross-script note:** `containment_ratio` depends on
`significant_words`, which was ASCII-only until the Unicode fix (root KNOWLEDGE
§17); `SequenceMatcher` degraded gracefully, so this function survived that bug
better than engagement's `E-ANSWER-01` did.

---

## H. ALGORITHMS AND HEURISTICS

### H.1 Structured-identity authority
- **Assumes:** a typed, singular, repeated, site-owned, visibly-corroborated
  JSON-LD `name` is better evidence of entity identity than a page title.
- **Logic:** the five conditions above; all must hold.
- **Thresholds:** `MIN_STRUCTURED_IDENTITY_PAGES = 2` and `>= half of pages`.
- **Below:** falls back to the 0.7 dominance vote. **Above:** `consistent = True`,
  `determined_by = "structured_identity"`.
- **Edge cases:** a site audited on a staging host whose JSON-LD declares the
  production URL fails condition 4 and loses authority — conservative, and it
  reduces to prior behaviour rather than creating a new false positive.

### H.2 The 0.7 dominance share
- **Assumes** one name form should dominate the harvested candidates.
- **Threshold `0.7`:** **chosen, not calibrated.** Nothing in the repository
  derives it from data.
- **Edge case it still has:** a site with many pages and no structured identity
  can dip below 0.7 purely from title variety.

### H.3 The 0.5 description-similarity floor
- **Assumes** two self-descriptions below 0.5 similarity are contradictory rather
  than differently-worded. **Chosen.** This is the weakest threshold in the skill
  and the one most likely to misfire on legitimately varied prose.

### H.4 Alias admission (≥2 pages OR declared)
- **Assumes** a real alternate identity is either repeated or explicitly declared.
- **Edge case:** a genuine trading name that appears on exactly one page and only
  in an `h1` is now rejected. That is a deliberate trade — the false-negative
  cost is smaller than the alias-pollution false-negative it replaced.

### H.5 Archetype gating
`SUPPRESSED_OFFERING_ARCHETYPES` disables `D-ENTITY-06` outright for docs,
portfolio and institutional sites. `RETHRESHOLD_*` sets downgrade severity and
confidence one tier via the `_SEVERITY_DOWNGRADE` / `_CONFIDENCE_DOWNGRADE` maps.
**Risk:** archetype comes from `lib/site_observer/classify.py`, a single-label
classifier; `OVERFITTING_AUDIT.md` names this as weak for hybrid and multilingual
sites. A misclassification silently changes severity.

---

## I. EVIDENCE MODEL

Every candidate carries `{value, source, source_url, observation_id}` from the
moment it is harvested, so a finding can name *where each competing name came
from*.

**Example 1 — `D-ENTITY-01` branch B, real output from the `both-weak` fixture:**
```
evidence: Competing name forms: "Shop" (2/7), "Shop Glenmark Supply" (2/7),
          "Glenmark Supply" (1/7), "Widget" (1/7), "Gadget" (1/7)
obs ids : 3        source_urls: 3        affected: 3 / null
```
The counts are the actual candidate tallies. A reader can re-harvest and confirm.

**Example 2 — `D-ENTITY-01` branch A (absence finding):**
```
observed_signal: 0 name candidates found in title, h1, schema, or footer
evidence       : No name candidate found on any sampled page
observation_ids: []            source_urls: pages_considered
```
Note `observation_ids == []`. This is the **absence-finding** case the evidence
contract explicitly permits: there is no observation to point at when the signal
is the absence of one. `validate_report.bind_evidence` accepts such a finding on
the strength of known `source_urls`. Any finding with neither is dropped.

---

## J. FALSE POSITIVES / FALSE NEGATIVES — historical record

| Issue | Old behaviour | Why wrong | Fix | Regression test |
|---|---|---|---|---|
| **Alias pollution** | `_aliases_field` admitted every non-dominant candidate — i.e. every page's own title — as a sitewide alias | `detect_engagement._brand_tokens` fed those back into `E-ORIENT-01`, so a deep page identified its owner with its own title. `E-ORIENT-01` became unable to fire on any realistically-titled page — a confirmed false negative recorded in two fixtures | ≥2-page or structured-declaration requirement; plus `_brand_tokens(for_url=…)` drops aliases whose only provenance is the page being judged | `test_a_single_page_title_does_not_become_a_sitewide_alias`; `test_a_deep_pages_own_title_does_not_identify_its_owner`; corpus `deep-page-no-orientation` and `strong-disc-weak-engage` now expect `E-ORIENT-01` |
| **JSON-LD had no authority** | title/h1 candidates outvoted explicit `Organization.name` | A healthy 4-page site with identical valid JSON-LD on every page produced `D-ENTITY-01` **and** `D-ENTITY-04` | `_structured_identity` + `_canonical_name_field(identity=…)` | `test_consistent_structured_identity_outranks_per_page_titles`, plus one test per removed condition (A–G in the test file) |
| **Per-page meta descriptions read as entity conflicts** | `_is_entity_level_page` returned `True` for any page carrying `Organization` markup — and sitewide markup is the norm — so every page's meta description became an entity self-description | Correct per-page descriptions read as the company contradicting itself | `_is_entity_subject_page` split + authoritative-description short-circuit | `test_per_page_meta_descriptions_are_not_conflicting_entity_descriptions` |
| **www treated as a foreign host** | authority condition 4 compared raw hostnames | `url: https://example.com` while auditing `https://www.example.com` lost authority — the commonest real spelling | `bare_host()` strips `www.` | `test_the_www_spelling_of_the_same_site_is_not_treated_as_foreign` |
| **Short brand names matched inside words** | substring match | "AI"/"Arc"/"One" matched unrelated words | Unicode word-boundary matching | `test_short_brands_do_not_match_inside_unrelated_words` |

**Standing false negative:** `D-ENTITY-03` cannot fire. Recorded in
`tests/fixtures/ambiguous-entity/expected.json` under `structurally_untestable`,
and disclosed at runtime as `UNAVAILABLE_INSTRUMENT`.

---

## K. TESTING

- **`tests/test_entity_semantic_audit.py`** — fire/suppress pairs per check, plus
  a dedicated authority block that removes one authority condition per test
  (unparseable / nameless / blank markup, single-page markup, competing
  organizations, foreign `url`, non-identity `@type`, non-ASCII names).
- **Two-stage integration tests** invoke `build_entity_profile.py` and
  `detect_entity.py` as **subprocesses** (`subprocess.run`) to prove the CLI
  contract works, not just the Python API.
- **Corpus fixtures.** `ambiguous-entity` is the interesting one: its
  `notes_on_own_authoring` records that `D-ENTITY-02` correctly does *not* fire
  because "platform" is a `TYPE_KEYWORD` — a useful negative result showing
  `D-ENTITY-01` and `-02` are genuinely orthogonal.

**Weak spots.** The profile's `location`, `official_domain` and
`distinguishing_attributes` fields have far less direct coverage than
`canonical_name`. `_addresses_conflict` is exercised by few cases. And no test
asserts what happens when `archetype` is *mis*classified — the downgrade paths
are tested with the archetype set explicitly.

---

## L. LIMITATIONS

**Implementation.** `TYPE_KEYWORDS`, `_OFFERING_PATTERN_RE` and `_COPYRIGHT_RE`
are English-only. `normalize_name`'s legal-suffix list is Western-centric.
`_min_similarity_pair` is O(n²). Archetype is a single label.

**Data/observation.** No `PROBE` ⇒ `_entity_type_field` and `_offering_field`
never reach their probe fallbacks. No `CLAIM_CORROBORATION` ⇒ `D-ENTITY-03` dead.

**Environment.** Rendered HTML is used when present; without a renderer, identity
on JS-rendered pages is invisible.

**Generalization.** Character-level `SequenceMatcher` behaves differently across
scripts. CJK is handled by bigram tokenization in `significant_words`, which is
approximate by design.

**Deliberately unsupported.** No JSON-LD `@context` expansion (arbitrary aliases
are not resolved). No outside-world entity resolution. `D-ENTITY-05` never
standalone.

---

## M. HOW A HUMAN WOULD IMPROVE THIS SKILL

### Low-risk
- **Emit `structured_identity` provenance into the finding evidence** so a reader
  can see *why* a name won. Files: `detect_entity.py` evidence strings only.
- **Add `alternateName` to alias harvesting.** JSON-LD has a dedicated field for
  exactly what `_aliases_field` is guessing at. Files: `_collect_name_candidates`,
  `_aliases_field`. Risk: low; it is a declared field.

### Architectural
- **Replace the 0.7 dominance vote with per-subject provenance.** Current: all
  candidates vote in one pool, so a page *topic* can outvote the operator's name.
  Better: bind each candidate to the subject it describes and compare only
  same-subject candidates. Tradeoff: needs a subject model the store does not
  carry. Files: the whole profile constructor. Tests: most of the entity suite.
- **Multilingual type/offering vocabularies.** Current: English regex/keyword
  lists. Better: language-tagged vocabularies selected by `<html lang>`.
  Tradeoff: vocabulary maintenance per language. Risk: moderate; changes which
  sites `D-ENTITY-02/06` fire on.
- **Faceted page-purpose evidence instead of one archetype.** Named in
  `OVERFITTING_AUDIT.md` as the appropriate next mechanism; it is a contract
  migration across all four detectors.

### Research
- Calibrating 0.7 and 0.5 against labelled sites. Both are currently chosen
  operating points and should be described as such until data exists.

---

## N. READ THESE FILES NEXT

1. `references/entity-profile-contract.md` — the data structure everything else
   manipulates.
2. `scripts/_entity_util.py` — 199 lines; read `normalize_name`, `text_similarity`
   and the archetype constant sets.
3. `scripts/build_entity_profile.py::_collect_name_candidates` then
   `_structured_identity` then `_canonical_name_field` — in that order; this is
   the causal chain behind `D-ENTITY-01`.
4. `scripts/detect_entity.py::check_d_entity_01` — both branches.
5. `references/entity-checks.md` and `fp-guardrails.md` — after the code.
6. `tests/test_entity_semantic_audit.py` — the authority block (tests A–G),
   because each one isolates a single condition.
7. `skills/engagement-audit/KNOWLEDGE.md` §G (`_brand_tokens`) — the second
   consumer of the profile, and where alias pollution actually did its damage.
8. Root `KNOWLEDGE.md` §17 for the full bug history.
