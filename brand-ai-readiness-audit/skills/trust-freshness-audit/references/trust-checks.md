# D-TRUST — trust & freshness

Twelve-field form for every check this skill owns, per
`<marketplace-root>/references/failure-taxonomy.md`. Implemented in
`scripts/detect_trust.py`, over `scripts/build_claim_table.py`'s output — see
`claim-table-contract.md` for that shape and `store-contract.md` for the raw
observation types read.

Each field below maps onto the seven items this skill's design brief asked for:
**mechanical observation** = `observable_signals` + `detection_test`;
**evidence** = `evidence_required`; **interpretation** = `mechanism` + the
deterministic detection test; **false-positive guardrails** =
`false_positive_rules`; **severity/confidence** = `severity` + `confidence`;
**recommendation** = `recommendation`; **validation** = `validation`.

The six analytical dimensions this skill's brief named map onto the checks as:
explicitness & attribution → D-TRUST-04; freshness/date signals → D-TRUST-01/02;
internal consistency → D-TRUST-03; corroboration → D-TRUST-05; conflicting
information → D-TRUST-03; possible identity confusion → D-TRUST-05's
`entity_match` guard (see below) — reusing `entity-semantic-audit`'s
`entity_profile` rather than re-deriving identity signals.

Governing rule, restated per-check where it applies: **never claim external
corroboration unless it was actually checked**, and **distinguish observed facts
from inference** — every finding here states what was mechanically found, never
what "seems true" or "is probably fine."

---

## D-TRUST-01 — undated time-sensitive claims
- **Meaning:** a sentence uses time-sensitive language ("currently", "this year",
  "now available") with no date signal anywhere on the same page.
- **Mechanism:** Appendix B/D. A citation pipeline repeating a time-framed claim
  with no way to judge its currency risks repeating something already false.
- **Applicability:** the page has `>=1` `time_sensitive` claim in the claim table.
- **Observable signals:** presence of a time-sensitive phrase-pattern match on
  the page; presence of any date signal for that page in `date_inventory`
  (`schema_dates`, `visible_dates`, or `header_date` — any one suffices).
- **Detection test:** fire when `>=1` time-sensitive claim exists on a page
  **and** `date_inventory[page]` has zero schema, visible, and header dates.
  Page-scoped, not sitewide — a date signal elsewhere on the site does not cover
  a claim on a different page.
- **Evidence required:** the claim's `id`/`text`/`observation_id`, and
  confirmation that `date_inventory[page]` is empty.
- **False-positive rules:** evergreen content (no time-sensitive phrase match)
  is never flagged — absence of a date is only interesting paired with a claim
  that needs one. A page with *any* date signal passes regardless of how many
  time-sensitive phrases it contains.
- **False-negative risks:** the phrase-pattern list is fixed and generic; a
  time-sensitive claim phrased outside that list is missed. Deliberate
  precision-over-recall trade, matching `entity-semantic-audit`'s established
  approach to the same tension.
- **Severity:** medium base. **Archetype re-threshold**
  (`archetype-applicability.md`): `publisher-editorial` up (freshness is
  central to that archetype); `documentation` and `personal-portfolio` down.
- **Confidence:** high — phrase-pattern presence and date-signal absence are
  both direct, deterministic tests, read through the rendered lens when
  available.
- **Recommendation:** add a visible "last updated" date or `dateModified`
  schema near the time-sensitive claim.
- **Validation:** re-fetch the page; a date signal is now present.

## D-TRUST-02 — stale signals
- **Meaning:** a forward-framed claim (an "upcoming" event, an offer with an end
  date, a countdown) carries a date that has already passed relative to the
  audit time, or the only date signal on the page is a long-stale copyright year.
- **Mechanism:** Appendix B/D. A stale forward-framed claim is actively
  misleading if repeated, not merely uninformative.
- **Applicability:** a `dated_offer`/`dated_event` claim exists with an
  extractable date, or a page's only date signal is a copyright year.
- **Observable signals:** the claim's extracted date compared against
  `audited_at`; the page's `copyright_year` compared against the audit year.
- **Detection test:** three independent sub-triggers, each requiring the
  forward-framing pattern *and* a date, never a stale date alone: (a) an
  "upcoming"/"next" event dated before `audited_at`; (b) an "ends"/"until"/
  "sale" claim dated before `audited_at`; (c) `copyright_year` more than 2
  years before the audit year **and** no other, more recent date signal exists
  on the page. Sub-triggers (a) and (b) additionally require that the page's
  own date inventory (schema or visible dates) has **no** date on or before
  the claim's extracted date — see the false-positive rule below.
- **Evidence required:** the claim text, the extracted date, `audited_at`, and
  the computed gap.
- **False-positive rules:** historical/archival pages are not flagged for being
  old by themselves — the forward-framing pattern must co-occur with the past
  date. **Critically, "the page was published/updated on or before the claim's
  date" also suppresses (a) and (b) entirely**: a news article or blog post
  published in 2020 that discusses "the upcoming election on November 3,
  2020" was true when written — it is an accurate historical record, not a
  stale claim, and firing on it was a confirmed false-positive class (a
  hostile review found this on any site with editorial/press history). The
  sub-trigger fires only when the page has no such earlier date, or was
  itself published/modified *after* the claim's date and is still presenting
  it as forward-looking — the genuine currency bug this check exists to
  catch. The copyright-year sub-trigger never fires if a more recent date
  signal exists anywhere on the same page (an old footer copyright next to a
  fresh "last updated" date is not stale).
- **False-negative risks:** a stale claim phrased without any of the fixed
  forward-framing patterns is missed; same deliberate precision trade as
  D-TRUST-01.
- **Severity:** medium base, same archetype re-threshold as D-TRUST-01.
- **Confidence:** high — date arithmetic against a fixed reference point is
  fully deterministic.
- **Recommendation:** update or remove the stale date-bound claim, offer, or
  event; refresh the copyright year if no other date signal exists.
- **Validation:** re-fetch; the extracted date is no longer past relative to
  its framing, or the stale claim has been removed or updated.

## D-TRUST-03 — internal contradiction
- **Meaning:** two pages assert different normalized values for the same
  entity-level fact.
- **Mechanism:** Appendix B/D. Conflicting asserted values give a citation
  pipeline no reliable single fact to repeat and may cause it to prefer a
  stale or wrong version.
- **Applicability:** `>=2` `entity_fact` claims share the same `key`.
- **Observable signals:** the normalized `value` per claim of a given `key`
  (currency/number formatting, whitespace, and case normalized before
  comparison).
- **Detection test:** fire when two claims sharing a `key` have different
  normalized `value`s.
- **Evidence required:** both claim texts, both values, both `source_url`s and
  `observation_id`s — every finding quotes both sides.
- **False-positive rules:** **scope is deliberately narrow.** Only
  inherently entity-level, rarely-legitimately-variant facts are ever extracted
  as `entity_fact` claims — founding year and employee/customer count. Price,
  spec, and other per-product/plan facts are never extracted into this claim
  type at all, because they legitimately vary by product, plan, or region on
  almost every commercial site; attempting a generic "any two numbers differ"
  test on those would be exactly the kind of false-positive class this
  taxonomy is built to avoid (see `PHASE1-ANALYSIS.md` §5.2). Regional/variant
  pricing and multiple locations are consequently structurally out of this
  check's scope, not merely suppressed by a rule. **Contact phone was
  extracted here in an earlier version and was removed** after a hostile
  review found that a sales line and a support line — a near-universal
  pattern, not an edge case — were flagged as a high-severity, high-confidence
  "contradiction." A bare phone-shaped number has no department/location
  context, so it belongs with price as a structurally-excluded fact, not a
  comparable one; a genuine same-number-should-match-itself use case would
  need context this deterministic pattern can't establish.
- **False-negative risks:** a genuine contradiction stated only in free prose
  (not matching one of the fixed entity-fact patterns) is invisible to this
  deterministic test. A future LLM-instrument extension (judging whether two
  prose sentences assert conflicting facts) is a documented, not required,
  upgrade path — this skill's brief prefers deterministic comparison first,
  and the fixed-pattern set already covers the highest-confidence, lowest-FP
  cases.
- **Severity:** high.
- **Confidence:** high — exact-match comparison after normalization.
- **Recommendation:** reconcile the two values, or state explicitly why they
  differ (e.g. label distinct time periods or entities).
- **Validation:** re-extract; the two values now match or carry an explicit
  distinguishing label.

## D-TRUST-04 — unattributed falsifiable claims
- **Meaning:** a falsifiable ranking claim or statistic ("#1", "leading",
  "94% of customers") appears with no citation nearby.
- **Mechanism:** Appendix B. An assistant repeating an unsourced falsifiable
  claim as fact inherits the risk of it being wrong or outdated, with no way to
  check.
- **Applicability:** `>=1` `superlative_stat` claim exists sitewide.
- **Observable signals:** the matched claim pattern; presence of a citation
  (a link, footnote marker, or "according to ..." phrase) within a fixed word
  window of the match.
- **Detection test:** fire, **once, aggregated sitewide** (never one finding
  per occurrence), when `>=1` `superlative_stat` claim has `attributed: false`.
- **Evidence required:** every unattributed claim's text and `source_url`,
  aggregated into one finding.
- **False-positive rules:** restricted to a fixed pattern set of specific
  falsifiable ranking phrases and numeric statistics — ordinary marketing
  adjectives ("great", "high-quality", "amazing") are never matched at all,
  not merely tolerated. Always a single aggregated finding, never fragmented
  per URL (`PROJECT_CONTEXT.md` Defect D / D-7).
- **False-negative risks:** a falsifiable claim phrased outside the fixed
  pattern set is missed; deliberate precision trade.
- **Severity:** low (capped — per `failure-taxonomy.md` revision log, this
  would otherwise fire on nearly every marketing site alive).
- **Confidence:** high — pattern match and citation-proximity are both direct
  tests.
- **Recommendation:** add a source next to each falsifiable claim, or rephrase
  as non-falsifiable language where no source exists.
- **Validation:** re-fetch; the claim now carries a nearby citation or has
  been rephrased.

## D-TRUST-05 — uncorroborated claim, with an identity-confusion guard
- **Meaning:** a claim exists only on the entity's own site, with no
  independent, verified-same-entity source found elsewhere — *and that absence
  was actually checked*, never assumed.
- **Mechanism:** Appendix B/D. A claim repeated only by its own source is
  weaker evidence than one corroborated independently; conversely, a
  "corroborating" source that is actually about a *different, similarly named*
  entity is worse than no corroboration at all — it would misattribute that
  entity's facts to this one.
- **Applicability:** a `CLAIM_CORROBORATION` observation exists for the claim
  with `performed: true`. **Absent that record, this check does not fire at
  all** — never inferred, never treated as "no corroboration exists"
  (`corroboration-honesty.md`, hard rule).
- **Observable signals:** the corroboration record's `sources` list; each
  source's `entity_match` — whether it was confirmed to describe *this* entity
  (cross-checked against `entity_profile`'s canonical name, type, and location/
  identity-anchor — the same fields `entity-semantic-audit` builds), not a
  same-named but different one.
- **Detection test:** fire when `sources` is empty, **or** every source in
  `sources` has `entity_match: false` — i.e. any apparent corroboration found
  is actually about a confusable different entity, which this check treats as
  equivalent to no real corroboration, and reports as such explicitly (the
  identity-confusion case gets its own `observed_signal` wording, never
  conflated with "genuinely nothing found").
- **Evidence required:** the corroboration record's `query`, `method`,
  `timestamp`, and full `sources` list (even the non-matching ones, so the
  identity-confusion case is auditable).
- **False-positive rules:** never fires without a real, `performed: true`
  record. Never treats an `entity_match: false` source as if it were
  corroboration (the opposite failure mode is just as dishonest as claiming
  unchecked corroboration). `entity_match` itself is never granted from a bare
  name match: a source whose text explicitly disambiguates itself from the
  entity ("not affiliated with", "not to be confused with", ...) is never
  scored a match regardless of any other signal — a hostile review found that
  without this guard, a disclaimer *warning about* a name collision was being
  scored as *confirming* corroboration, exactly inverting this check's
  purpose (`_trust_util.source_matches_entity`'s `_DISAMBIGUATION_RE` guard).
  Corroboration lookups themselves are also scoped: only `entity_fact` claims
  and unattributed `superlative_stat` claims are ever worth checking
  externally (`_trust_util.is_corroboration_worthy`) — a `time_sensitive` or
  `dated_offer`/`dated_event` claim needs a date, not a second opinion, and
  spending the shared corroboration budget on one is a wasted, unnecessary
  lookup.
- **False-negative risks:** entirely dependent on the corroboration lookup
  having run at all, which requires an outbound search capability
  (`PROJECT_CONTEXT.md` OQ-3, still open) — a permanent, honestly-declared
  coverage gap on any run without it, never a silent pass.
- **Severity:** medium.
- **Confidence:** high — given the record exists, both trigger conditions are
  deterministic checks over its contents.
- **Recommendation:** for high-visibility claims lacking corroboration, build
  an external presence (press mention, directory listing, review platform)
  that states the same fact independently and unambiguously about this entity.
- **Validation:** re-run corroboration; `>=1` source now exists with
  `entity_match: true`.

## D-TRUST-06 — organizational opacity
- **Meaning:** no about page, no contact information, and/or substantive
  article content with no named author, anywhere on the site.
- **Mechanism:** Appendix B/D. A citation pipeline weighing whether to trust and
  repeat a claim has no visible accountability trail to check.
- **Applicability:** always evaluable; archetype-gated at the detection test
  (see below), never suppressed by absence alone without that gate.
- **Observable signals:** presence of an about page and a contact page/contact
  method (path or heading match, or an email/phone/address pattern); presence
  of a named-author byline or JSON-LD `author` on `article`-classified pages.
- **Detection test:** two independent sub-triggers. (a) fires when **both**
  an about page and a contact page/method are absent sitewide — never on
  either alone. (b) fires when `>=1` `article`-classified page exists and
  **none** carry a named author.
- **Evidence required:** the pages searched for about/contact signals; the
  article pages checked for authorship.
- **False-positive rules:** personal blogs and single-purpose landing pages
  have different norms — **suppressed entirely on `personal-portfolio`**
  (the site's own existence typically functions as the "about", and its
  author is self-evident). Sub-trigger (a) requires *both* signals absent, never
  either alone. Sub-trigger (b) requires `>=1` article page to even be
  applicable — a site with no article-type content is never penalized for
  lacking bylines.
- **False-negative risks:** an about/contact page that exists but is
  extremely thin (e.g. a single sentence) still counts as present — this
  check tests presence, not adequacy, by design, to stay mechanical and
  low-FP.
- **Severity:** medium.
- **Confidence:** high — presence/absence checks are direct and deterministic.
- **Recommendation:** add an about page stating who operates the site, a
  contact method, and named authorship on article content.
- **Validation:** re-crawl; about/contact pages exist and/or articles carry a
  named author.
