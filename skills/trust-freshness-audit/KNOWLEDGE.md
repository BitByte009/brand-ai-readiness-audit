# trust-freshness-audit — Engineering Study Guide

> Companion to `SKILL.md`. Shared vocabulary, the observation store and the
> finding contract live in the root `KNOWLEDGE.md` (§6, §8).

---

## A. PURPOSE AND MENTAL MODEL

**Mental model:** think of this skill as a *claim extractor followed by a
credibility auditor*. It takes page text, mechanically lifts out the sentences
that make **checkable assertions**, assembles them into a **claim table**, and
then asks six questions about whether an AI system would be willing to repeat
those claims.

The two-stage structure mirrors `entity-semantic-audit`:

```
store ──► build_claim_table.py ──► claim_table ──► detect_trust.py ──► findings
            (extraction)           (fact table)      (judgement)
```

The pivot is the **claim**, not the page. A page is not "stale"; a *dated offer
on it* is expired. That distinction is what lets the evidence name a specific
sentence rather than gesturing at a URL.

**Claim types** (`claim_type`, set during extraction):

| Type | Meaning | Extracted by |
|---|---|---|
| `time_sensitive` | prose that implies currency ("currently", "as of", pricing language) | `_extract_time_sensitive_claims` |
| `dated_event` | forward-framed event with a parseable date ("upcoming … March 3, 2024") | `_extract_dated_forward_claims` |
| `dated_offer` | forward-framed offer with a date | `_extract_dated_forward_claims` |
| `entity_fact` | a keyed factual value: founded year, customer count, employee count | `_extract_entity_fact_claims` |
| `superlative_stat` | a superlative or a bare percentage statistic | `_extract_superlative_claims` |

**What it does NOT determine.** Whether a claim is *true*. It has no ground truth
and does not pretend to. It determines whether a claim is **dated, internally
consistent, attributed, and corroborated** — four proxies for whether a citation
pipeline would repeat it. It also does not judge identity coherence
(`entity-semantic-audit`) or reachability (`crawl-render-audit`).

---

## B. COMPLETE FILE MAP

### `scripts/build_claim_table.py` (196 lines) — extraction
- **Purpose:** `store → claim_table`. No findings.
- **Called by:** `detect_trust.detect_trust` (internally) and available as a CLI.
- **Outputs:** `{claims: [...], date_inventory: {url: {...}}}`.
- **Key functions:** `_claim_id` (a stable `sha1(claim_type|url|text)[:12]`),
  `_claim` (constructor), `_build_date_inventory`, the four `_extract_*` functions,
  `build_claim_table`.
- **Important detail:** `_claim_id` is content-addressed, so the same claim on the
  same URL always gets the same id across runs. That is what makes
  `CLAIM_CORROBORATION` observations joinable to claims by `claim_id`.

### `scripts/detect_trust.py` (414 lines) — judgement
- **Purpose:** `D-TRUST-01..06`.
- **Constants:** `CATEGORY = "trust"`,
  `_SEVERITY_UP = {"low":"medium","medium":"high","high":"high"}` — the comment in
  source notes it never promotes past `high`; `_SEVERITY_DOWN` mirrors it;
  `CHECKS` dispatcher list.
- **Key helpers:** `_freshness_severity(store, base)`, `_has_date_signal(inventory)`.

### `scripts/corroborate.py` (126 lines) — the honest recorder
- **Purpose:** build one `CLAIM_CORROBORATION` observation from *supplied* search
  results. **It never fetches the web itself.**
- **Critical semantic:** `search_results is None` ⇒ `performed: False`,
  `reason: "SEARCH_UNAVAILABLE"`. `search_results == []` ⇒ `performed: True` with
  zero sources. Conflating those two is precisely what
  `references/corroboration-honesty.md` rule 4 forbids.
- **CLI warning:** if results are supplied for a claim that
  `is_corroboration_worthy()` rejects, it prints a warning to stderr rather than
  silently recording a useless lookup.

### `scripts/_trust_util.py` (477 lines) — the pattern library
This is where nearly all the domain knowledge lives. Grouped:

| Group | Symbols |
|---|---|
| Date parsing | `_ISO_DATE_RE`, `_MONTH_DAY_YEAR_RE`, `_DAY_MONTH_YEAR_RE`, `_COPYRIGHT_YEAR_RE`, `_FRESHNESS_LABEL_RE`, `parse_date`, `find_visible_freshness_dates`, `find_copyright_year` |
| Claim patterns | `TIME_SENSITIVE_PATTERNS`, `_EVENT_FORWARD_RE`, `_OFFER_FORWARD_RE`, `_FOUNDED_RE`, `_CUSTOMER_COUNT_RE`, `_EMPLOYEE_COUNT_RE`, `SUPERLATIVE_PATTERNS`, `_STAT_RE` |
| Attribution | `_CITATION_NEARBY_RE`, `has_nearby_citation(text, start, end, window=80)` |
| Accountability | `_ABOUT_PATH_SEGMENTS`, `_CONTACT_PATH_SEGMENTS`, `_ACCOUNTABILITY_PAGE_TYPES`, `_ORGANIZATION_TYPES`, `_CONTACT_TYPES`, `_EMAIL_RE`, `_PHONE_RE`, `is_about_page`, `is_contact_page`, `has_operator_identity`, `has_contact_method`, `has_contact_info`, `find_author_byline` |
| Corroboration | `claim_corroborations`, `source_matches_entity`, `_DISAMBIGUATION_RE`, `CORROBORATION_WORTHY_CLAIM_TYPES`, `is_corroboration_worthy` |
| Archetype gating | `RETHRESHOLD_FRESHNESS_UP_ARCHETYPES = {publisher-editorial}`, `RETHRESHOLD_FRESHNESS_DOWN_ARCHETYPES = {documentation, personal-portfolio}`, `SUPPRESSED_OPACITY_ARCHETYPES = {personal-portfolio}` |
| Normalization | `normalize_claim_value` |

Two regexes carry explanatory comments worth reading in source, because both
document a subtle bug that was fixed: `_ISO_DATE_RE` deliberately omits a
trailing `\b` (an ISO datetime's `T` is a word char, so `\b` would never match),
and `_STAT_RE` likewise (`%` is not a word char, so `%\b` never matches).

### References
`claim-table-contract.md` (the claim/date-inventory shape — read first),
`trust-checks.md`, `corroboration-honesty.md` (the four honesty rules),
`fp-guardrails.md`, `store-contract.md`.

### Tests and fixtures
`tests/test_trust_freshness_audit.py` (767 lines), including subprocess tests
that run `build_claim_table.py` and `corroborate.py` as CLIs.
Fixtures: `stale-content`, `conflicting-content`, `fp-trap-composite`, `both-weak`.

---

## C. END-TO-END WORKFLOW

```
store
 │
 ▼ effective_pages(store) → {url: {html, observation_id}}   (render preferred)
┌────────────────────────────────────────────────────────────────┐
│ build_claim_table.build_claim_table(store)                      │
│   per page:                                                     │
│     text = extract_text(html)                                   │
│     date_inventory[url] = {schema_dates, visible_dates,          │
│                            header_date, copyright_year}          │
│     claims += _extract_time_sensitive_claims(...)                │
│     claims += _extract_dated_forward_claims(...)                 │
│     claims += _extract_entity_fact_claims(...)                   │
│     claims += _extract_superlative_claims(...)                   │
└────────────────────────────────────────────────────────────────┘
 │  claim_table {claims[], date_inventory{}}
 ▼
┌────────────────────────────────────────────────────────────────┐
│ detect_trust(store, claim_table) → CHECKS dispatcher            │
│  01 undated time-sensitive │ 02 expired dated claim              │
│  03 cross-page conflict    │ 04 unattributed superlative/stat    │
│  05 corroboration (dead)   │ 06 no operator/contact              │
└────────────────────────────────────────────────────────────────┘
 │  findings
 ▼
```

**Failure behaviour.** Extraction never raises on odd text — every `_extract_*`
is a regex sweep returning a possibly-empty list. A page with no parseable text
contributes nothing. `parse_date` returns `None` on anything it cannot parse, and
every caller checks for `None`.

---

## D. INPUT CONTRACT

| Input | Type | Origin | Required | If missing / malformed |
|---|---|---|---|---|
| `store["observations"]` | list | `collect.py` | yes | no pages ⇒ `D-TRUST-06` returns `[]`; all others produce nothing |
| page `html` | str | `HTTP_FETCH` / `RENDER` | yes | text extraction yields `""` ⇒ no claims |
| `store["collected_at"]` | ISO-8601 str | `collect.py` (`now().isoformat()`) | **yes for `D-TRUST-02`** | `parse_date` fails ⇒ `D-TRUST-02` returns `[]` immediately — no date arithmetic without a reference point |
| `store["archetype"]` | str | `classify.py` | optional | `""` ⇒ no severity re-thresholding, no suppression |
| `PAGE_CLASSIFICATION` | — | **never produced** | no | `is_about_page`/`is_contact_page` fall back to **path-segment** heuristics only |
| `CLAIM_CORROBORATION` | — | **never produced** by the collector | no | `D-TRUST-05` returns nothing |
| `claim_table` | dict | `build_claim_table` | yes | built internally by `detect_trust` |

---

## E. OUTPUT CONTRACT

**`claim_table`:**
```
claims: [ {id, claim_type, text, source_url, observation_id,
           key?, value?, date_value?, attributed?} ]
date_inventory: { url: {schema_dates: [iso], visible_dates: [iso],
                        header_date: iso|null, copyright_year: int|null} }
```
`key`/`value` exist on `entity_fact` claims and are what `D-TRUST-03` groups on.
`attributed` is set on `superlative_stat` claims by the nearby-citation test.

**`CLAIM_CORROBORATION` observation** (from `corroborate.py`):
```
{claim_id, performed: bool, query, method, timestamp,
 sources: [{url, title, snippet, entity_match: bool}], reason?}
```

**Findings:** standard shape, `category = "trust"`.

---

## F. CHECK-BY-CHECK BREAKDOWN

### F.1 Evaluability

| Class | Checks |
|---|---|
| Always evaluable | `D-TRUST-01`, `D-TRUST-03`, `D-TRUST-04`, `D-TRUST-06` |
| Evaluable, needs `collected_at` | `D-TRUST-02` |
| **Not evaluable** | `D-TRUST-05` — needs a `CLAIM_CORROBORATION` with `performed: true` |

`D-TRUST-06` uses `page_classifications()` as a **soft refinement**: when absent
it falls back to path segments and JSON-LD types, and it demonstrably fires
without it (it is in the corpus's fired set).

### F.2 The table

| Check | Purpose | Mechanical test | Severity | Confidence | Guardrails |
|---|---|---|---|---|---|
| **D-TRUST-01** | time-sensitive claim with no date | group `time_sensitive` claims by page; fire when `not _has_date_signal(inventory)` | `_freshness_severity(store)` base `medium` | high | Any of schema date / visible date / HTTP header date suppresses it. Evergreen prose is never a `time_sensitive` claim to begin with |
| **D-TRUST-02** | dated claim already expired | `claim_type ∈ {dated_event, dated_offer}`, `parse_date(date_value) < collected_at`, and no *later* page date rescues it | `_freshness_severity(store)` | high | Requires a **forward-framed** claim ("upcoming", "join us", offer language) — a historical date is not staleness. A newer page date suppresses |
| **D-TRUST-03** | two pages assert different values for one fact | group `entity_fact` claims by `key`; fire on the first pair with differing `value` | high | high | Grouping is on a normalized `key` **and** `normalize_claim_value(value)`, so "1,200" vs "1200" is not a conflict |
| **D-TRUST-04** | superlative/statistic with no attribution | any `superlative_stat` claim with `attributed` false | **low** | high | `has_nearby_citation(text, start, end, window=80)` — an 80-char window around the match accepts "according to", "source:", "[1]", or a URL. Severity is deliberately low: it is a rhetorical style signal |
| **D-TRUST-05** | claim exists only on the entity's own site | corroboration `performed`, claim resolves, and **no** source has `entity_match` | medium | high | **Not evaluable.** Two distinct titles: "exists only on own site" vs "apparent corroboration is a different entity" when sources exist but none match |
| **D-TRUST-06** | no operator identity or contact method | archetype not suppressed; **no** page satisfies `is_about_page ∨ has_operator_identity`, and no page satisfies contact | medium | high | Suppressed for `personal-portfolio`. Accepts JSON-LD org types, an email, a phone-shaped string, or an about/contact route — four independent ways to pass |

### F.3 Prose on the ones that repay study

**`D-TRUST-02` is the most carefully guarded check in the skill.** Three separate
conditions must hold: the claim must be *forward-framed* (`_EVENT_FORWARD_RE` /
`_OFFER_FORWARD_RE` require "upcoming"/"next"/"join us"/offer language *near* the
date), the date must be in the past relative to `collected_at`, and the page must
not carry a *later* date that supersedes it. The middle condition alone would
flag every historical article on the web.

This check also carries an explicit historical correction: an earlier version
treated a copyright year more than two years old as proof of staleness.
`OVERFITTING_AUDIT.md` records the reasoning for removing it — a rights date is
not a content-review date. `find_copyright_year` still exists and is still
collected into the date inventory, but no longer establishes staleness on its own.

**`D-TRUST-04`'s severity is `low` and should stay that way.** An unattributed
"the fastest widget in Europe" is a marketing convention, not a defect of the
same order as a broken canonical. The check earns its place by being cheap and by
feeding the proactive/demotion path, not by ranking highly.

**`D-TRUST-06` is the accountability check and the one most reworked for
generalization.** `has_operator_identity` accepts JSON-LD `_ORGANIZATION_TYPES`,
an operator-description pattern, or a footer name. `has_contact_method` requires
either a *phone-shaped visible string* or a **non-empty actionable destination** —
an empty `mailto:` or `tel:` link does not count, and a long number that is
actually an order ID does not count. `find_author_byline` accepts named metadata,
`itemprop`, `rel=author` and graph-resolved authors, not only an English "By …"
byline. Those broadenings are all recorded in `OVERFITTING_AUDIT.md`.

---

## G. SUPPORTING FUNCTIONS AND ALGORITHMS

### `parse_date(text)` — `_trust_util.py:61`
Tries ISO, `Month D, YYYY`, and `D Month YYYY` in order; returns a `date` or
`None`. **Why written this way:** three explicit formats rather than a
dependency-based parser keeps the dependency list at four and makes failure
predictable. The cost is that it parses **English month names only**.

### `find_visible_freshness_dates(text)` — `_trust_util.py:95`
Finds dates that follow a *freshness label* (`updated|published|posted|last
modified|revised|as of`). Crucially it does **not** treat every date on a page as
a freshness signal — an article that merely mentions "in March 2019" is not
thereby dated. This is the difference between a date inventory and a date scrape.

### `_build_date_inventory(url, page, text)` — `build_claim_table.py:59`
Assembles four independent signals: `schema_dates` (JSON-LD
`datePublished`/`dateModified`), `visible_dates` (from the labelled scan),
`header_date` (HTTP `Last-Modified`), `copyright_year`. `_has_date_signal` in
`detect_trust` accepts any of the first three — deliberately **not** the copyright
year, per the correction above.

### `has_nearby_citation(text, start, end, window=80)` — `_trust_util.py:163`
Slices `text[start-window : end+window]` and matches `_CITATION_NEARBY_RE`.
**Edge case:** proximity is a proxy for attribution, not proof — a citation for a
*different* sentence 60 characters away will suppress a genuine finding. This is
a deliberate false-negative bias; `references/fp-guardrails.md` records it.

### `source_matches_entity(source, entity_profile)` — `_trust_util.py:418`
The identity-confusion guard for `D-TRUST-05`. Compares a search result against
the entity profile's canonical name/aliases, and applies `_DISAMBIGUATION_RE`
("not affiliated with", "not to be confused with") so a disambiguation page never
counts as corroboration. Deterministic; it is why `corroborate.py` can be honest
without a model.

### `is_corroboration_worthy(claim)` — `_trust_util.py:466`
`claim_type ∈ CORROBORATION_WORTHY_CLAIM_TYPES = {entity_fact, superlative_stat}`.
`D-TRUST-05` cannot act on a `time_sensitive` claim, so looking one up would waste
a live search. The CLI warns rather than silently proceeding.

### `_freshness_severity(store, base="medium")` — `detect_trust.py`
Archetype-dependent one-tier shift. `publisher-editorial` shifts **up** (a news
site with undated content is worse); `documentation` and `personal-portfolio`
shift **down**. Both maps saturate rather than wrapping.

---

## H. ALGORITHMS AND HEURISTICS

| Heuristic | Assumes | Threshold | Below | Above | Status |
|---|---|---|---|---|---|
| Freshness label required for a visible date | a bare date in prose is content, not metadata | pattern match, no numeric threshold | date ignored | date counts as a freshness signal | Design rule, well-founded |
| Forward framing required for staleness | a past date is only stale if the page still presents it as upcoming | `.{0,60}` proximity between the framing word and the date | not a dated claim | `dated_event`/`dated_offer` | Chosen proximity window |
| Citation proximity | attribution is written near the claim | `window = 80` chars each side | claim is `attributed: False` | suppressed | **Chosen.** No calibration exists |
| Value normalization before conflict | formatting differences are not contradictions | `normalize_claim_value` | — | — | Design rule |
| Archetype severity shift | the same defect matters more on a news site | one tier, saturating | — | — | Chosen policy; depends on a single-label classifier |
| Copyright year is **not** staleness evidence | a rights date is not a review date | n/a | — | — | A **correction** of an earlier heuristic; see §J |

**Honest summary:** the date and claim *patterns* are principled — each encodes a
stated linguistic distinction. The two numeric constants (`80`-char citation
window, `60`-char forward-framing proximity) are chosen operating points with no
dataset behind them.

---

## I. EVIDENCE MODEL

Because the unit is a claim, evidence can quote the sentence.

1. `build_claim_table` attaches `source_url` and `observation_id` to **every**
   claim at construction.
2. A check builds `evidence` from `claim["text"]` (the actual sentence) plus the
   decisive value.
3. `observation_ids` carries the originating fetch/render observation.
4. `bind_evidence` in the orchestrator drops anything unresolvable.

**Example 1 — `D-TRUST-06` on the `both-weak` fixture (an absence finding):**
```
evidence        : No classified accountability role, named operator, contact
                  method, or exact role-path fallback found on any sampled page
observed_signal : (same shape)
observation_ids : []          source_urls: 3        affected: 3 / null
```
`observation_ids` is empty because the finding *is* an absence. The evidence
enumerates the four things that were searched for, so a reader can reproduce the
negative. This is the permitted absence-finding shape (root KNOWLEDGE §8).

**Example 2 — `D-TRUST-03` conflict:** the finding names the shared `key`, both
conflicting `value`s, and both `source_url`s. A reader can open two pages and see
the contradiction without re-running anything. This is the strongest evidence
shape in the skill, and it is a direct consequence of extracting keyed claims
rather than flagging pages.

---

## J. FALSE POSITIVES / FALSE NEGATIVES — historical record

| Issue | Old behaviour | Why wrong | Fix | Regression test |
|---|---|---|---|---|
| **Copyright year as staleness** | a `©` year >2 years old proved stale content | A rights date is not a content-review date; every well-maintained site with a stale footer was flagged | Require an **expired forward-framed claim**; copyright year stays in the inventory but no longer triggers | `test_d_trust_02_copyright_alone_does_not_establish_staleness` |
| **English byline assumption** | authors detected only via an English "By …" byline | Non-English and metadata-only attribution missed | Accept named metadata, `itemprop`, `rel=author`, graph-resolved authors; an empty author link is not a name | `test_author_signals_are_not_english_byline_specific`; `test_empty_contact_and_author_links_are_not_named_channels` |
| **One attributed article absolved the site** | a single attributed article suppressed the check sitewide | Hid a mostly-anonymous publication | Evaluate fetched classified articles independently; emit only the anonymous subset with its real denominator | `test_author_findings_scope_only_anonymous_articles` |
| **Any long number / `mailto:` prefix = contact** | loose matching | Order IDs and copyright ranges counted as phone numbers; empty `mailto:` counted as a channel | Require phone-shaped visible evidence or a non-empty actionable destination | `test_empty_contact_and_author_links_are_not_named_channels` |
| **`about`/`contact` substring matching** | any URL containing those substrings | `/products/about-face-cream` counted as accountability | Exact conventional **route segments** as a weak fallback, plus role observations | `test_accountability_does_not_require_english_page_names`; `test_product_path_substrings_do_not_establish_accountability` |
| **`_ISO_DATE_RE` / `_STAT_RE` trailing `\b`** | patterns ended with `\b` | ISO datetimes (`…T10:00`) and percentages (`45%`) never matched, silently losing claims | trailing `\b` removed, with an explaining comment at each regex | covered by the date/stat extraction tests |

**Standing false negative:** `D-TRUST-05` cannot fire. Disclosed at runtime as
`UNAVAILABLE_INSTRUMENT`.

---

## K. TESTING

- **`tests/test_trust_freshness_audit.py` (767 lines)** — fire/suppress pairs per
  check, extensive date-parsing cases, and the accountability counterexamples
  listed in §J.
- **Subprocess/CLI tests** — `build_claim_table.py` and `corroborate.py` are run
  as real processes (five `subprocess.run` sites), including a two-stage flow
  (build table → corroborate one claim) and a single-stage comparison. This
  protects the documented CLI contract in `SKILL.md`, which unit-level imports
  would not.
- **Corroboration-honesty tests** — assert that `search_results=None` produces
  `performed: False` and that `[]` produces `performed: True` with zero sources.
  This is the single most important behavioural test in the skill, because the
  whole corroboration design rests on that distinction.
- **Corpus fixtures** — `stale-content` (D-TRUST-01/02), `conflicting-content`
  (D-TRUST-03), `fp-trap-composite` (expects **zero** findings; contains a 2019
  news post that must *not* be flagged as stale).

**Weak spots.** All date parsing is English-month-name only and no test asserts
behaviour on non-English dates. `has_nearby_citation`'s 80-char window has no
adversarial test for the "citation belongs to a different sentence" case.
`D-TRUST-05` has unit tests only via hand-injected observations.

---

## L. LIMITATIONS

**Implementation.** English-only claim, month-name, superlative, offering and
byline patterns. Citation attribution is proximity, not linkage. `D-TRUST-03`
reports the first conflicting pair per key, not all of them.

**Data/observation.** No `CLAIM_CORROBORATION` ⇒ `D-TRUST-05` dead. No
`PAGE_CLASSIFICATION` ⇒ accountability falls back to path/JSON-LD signals.

**Environment.** Rendered HTML is preferred when present; claims that only exist
after hydration are invisible without a renderer.

**Generalization.** Archetype gating depends on a single-label classifier.
`OVERFITTING_AUDIT.md` additionally records that a *named embedded organization*
can still be mistaken for the site operator, and that date/claim evidence is bound
to the page rather than to the specific claim subject.

**Deliberately unsupported.** No truth checking. No live search from the skill —
`corroborate.py` records supplied results only, by design.

---

## M. HOW A HUMAN WOULD IMPROVE THIS SKILL

### Low-risk
- **Bind attribution to a citation *element* rather than a character window.**
  Current: `has_nearby_citation` slices ±80 chars. Better: walk the DOM for a
  `<cite>`, footnote link or `<a>` inside the claim's containing block. Files:
  `_trust_util.py`, `build_claim_table.py`. Tests: `D-TRUST-04` cases. Risk: low —
  strictly more precise, may reduce firing.
- **Record which of the four date signals suppressed `D-TRUST-01`** in the
  evidence string, so a reader can see why a page passed. Files: `detect_trust.py`.

### Architectural
- **Language-tagged date and claim vocabularies.** Current: English regexes.
  Better: select pattern sets by `<html lang>`. Tradeoff: per-language
  maintenance; the claim taxonomy itself is language-independent, so the change is
  contained to `_trust_util`. Risk: moderate.
- **Bind date evidence to the claim's subject, not the page.** Current: the whole
  page's date inventory can rescue any claim on it. Better: locate the nearest
  dated ancestor. Named in `OVERFITTING_AUDIT.md` as the appropriate next
  mechanism. Files: `build_claim_table.py`. Tests: most of `D-TRUST-01/02`.
- **Report all conflicting pairs in `D-TRUST-03`,** not the first. Tradeoff: more
  findings per key, needs a scope-aware `affected` block.

### Research / future work
- Wiring a real corroboration instrument. Note this is a *safety and honesty*
  change as much as a feature: `corroborate.py` and
  `corroboration-honesty.md` already define the contract it must satisfy, and
  `D-TRUST-05` must remain unable to fire on an unperformed lookup.

---

## N. READ THESE FILES NEXT

1. `references/claim-table-contract.md` — the shape everything manipulates.
2. `references/corroboration-honesty.md` — four short rules; they explain the
   single most unusual design choice in the skill.
3. `scripts/_trust_util.py` — read the regex block (lines ~46–160) with the
   comments, especially the two trailing-`\b` notes.
4. `scripts/build_claim_table.py::build_claim_table` then `_build_date_inventory`.
5. `scripts/detect_trust.py::check_d_trust_02` — the most guarded check.
6. `scripts/corroborate.py::record_corroboration` — the `None` vs `[]` branch.
7. `tests/test_trust_freshness_audit.py` — the corroboration-honesty tests and the
   `fp_trap` suppression cases.
8. Root `KNOWLEDGE.md` §8 (shared concepts) and §16 (limitations).
