# D-ENTITY — identity

Twelve-field form for every check this skill owns, per
`<marketplace-root>/references/failure-taxonomy.md`. Implemented in
`scripts/detect_entity.py`, over `scripts/build_entity_profile.py`'s output — see
`entity-profile-contract.md` for that shape and `store-contract.md` for the raw
observation types read.

Every field below maps onto the seven items this skill's design brief asked for:
**mechanical observation** = `observable_signals` + `detection_test`;
**required evidence** = `evidence_required`; **interpretation rules** = `mechanism`
+ the deterministic-vs-probe split stated in `detection_test`;
**false-positive guardrails** = `false_positive_rules`; **severity/confidence** =
`severity` + `confidence`; **recommendation** = `recommendation`; **validation
after fix** = `validation`.

Governing rule across every check here, restated per-check below where it applies:
**absence is never flagged by itself.** Each check first establishes that the
missing fact is one this archetype, page, or situation actually needs before it
fires — never "field X is empty" as its own trigger. Thresholds are ratios/
counts/structural patterns, never a hostname, brand, vertical, CMS, or framework
name.

---

## D-ENTITY-01 — no canonical entity name stated consistently
- **Meaning:** the entity's name varies across the site with no single dominant,
  consistently-used form.
- **Mechanism:** Appendix D. A citation pipeline that sees two or three different
  name strings for what is actually one entity may cite the "wrong" one, split
  attribution across variants, or decline to name the source at all.
- **Applicability:** `entity_profile.fields.canonical_name.candidates` is non-empty
  (a name was found somewhere) — see the false-negative note below for the
  zero-candidate case, which is a different, more severe observation.
- **Observable signals:** the set of normalized-core name candidates (legal
  suffixes — Inc./LLC/Ltd/Corp/Co. — and punctuation stripped, lowercased) found
  in title, `h1`, JSON-LD `name`, and footer copyright text across sampled pages;
  each candidate's occurrence count and source.
- **Detection test:** fire when `>=2` distinct normalized-core names exist **and**
  no single one accounts for `>=70%` of occurrences. This is a real inconsistency,
  not a stylistic one — the 70% floor is what "no single dominant form" means
  mechanically.
- **Evidence required:** the competing candidates with counts, source, and
  `observation_id`/`source_url` for each occurrence.
- **False-positive rules:** legal-name vs. trading-name variation is normal and
  never flagged. Mechanically: when exactly two normalized-core name groups
  exist, the minority group is a legal/trading-name pair (not a real
  inconsistency) when every candidate in it comes from a legal-register source
  (`schema` or `footer`) **and** the dominant group has at least one candidate
  from a public-facing source (`title` or `h1`) — i.e. the site consistently
  displays one name and only the registered/legal record differs. This is
  deliberately narrow: it never suppresses a case where the minority name is
  *also* public-facing (title/h1 on some other page), which is a real
  inconsistency, not a legal/trading pair. A single outlier occurrence below
  the 70%-minority threshold does not, by itself, break the dominant-form pass.
- **False-negative risks:** a site using a genuinely ambiguous single name (a name
  that reads as two different entities to a human) is invisible to a pure-string
  test; that class of confusion is D-ENTITY-03's job, not this one's.
- **Severity:** high on most archetypes. If zero name candidates were found
  anywhere (no title, `h1`, schema, or footer name at all) — a materially worse
  case than "inconsistent" — this check still fires, with `observed_signal`
  stating the total absence explicitly rather than a variance number; this is
  the one place absence alone fires, because a wholly unnamed entity is
  definitionally never citable. **Archetype re-threshold:** `documentation` and
  `personal-portfolio` (`archetype-applicability.md`) downgrade to medium — a
  sparse or implicit name is normal on a minimal personal or docs-project site,
  not a defect of the same magnitude as on a commercial site.
- **Confidence:** high — a direct count over deterministic extraction, read
  through the rendered lens when available (see `store-contract.md`) so a
  JS-rendered site's client-rendered name isn't mistaken for an absent one.
- **Recommendation:** state the canonical name consistently in `<title>`, `<h1>`,
  and structured data sitewide; if a legal/trading-name distinction is
  intentional, link them explicitly in one sentence ("Acme, legally Acme
  Corporation, Inc.").
- **Validation:** re-extract name candidates across the same sample; the
  normalized-core set converges to one value at `>=70%` share, or a
  legal/trading-name pair now appears explicitly linked.

## D-ENTITY-02 — entity type never stated plainly
- **Meaning:** nothing on the site states, in plain text, what kind of thing the
  entity is (a company, a nonprofit, a person, a government agency, a
  publication, a product...).
- **Mechanism:** Appendix D. An assistant that cannot categorize the entity cannot
  frame a citation correctly ("according to the company" vs. "according to the
  nonprofit" vs. "according to this blog").
- **Applicability:** `>=1` page was crawled. This is a site-level determination —
  evaluated once across all sampled pages, never per page, to avoid firing on a
  page that simply doesn't happen to restate the type.
- **Observable signals:** a structural type-word match (company, corporation,
  nonprofit, organization, agency, university, foundation, publication, blog,
  studio, platform, store, clinic, museum, government, and similar generic
  category nouns — never a brand/vertical-specific term) anywhere in extracted
  prose across sampled pages; JSON-LD `@type` mapped to its human-readable label;
  `PROBE` question **Q2** (`references/probe-questions.md`) as the fallback when
  neither deterministic signal is present.
- **Detection test:** deterministic-first — if a type-word or the JSON-LD
  `@type`'s label appears anywhere in sampled prose, the check does not fire (no
  further judgment needed). Only when that deterministic pass finds nothing does
  the check consult `PROBE` Q2, firing if Q2 is `answered: false` on every page a
  `PROBE` observation exists for.
- **Evidence required:** the pages searched and, when the probe fallback applies,
  the `OBS-PROBE-*` id(s) for Q2.
- **False-positive rules:** never fires if a type-word or `@type` label appears
  even once, anywhere in the sample — this is deliberately generous, since the
  question is only "is it stated at all," not "is it prominent." Never fires
  without attempting the deterministic pass first, regardless of `PROBE`
  availability.
- **False-negative risks:** the type-word list cannot be exhaustive; a type
  stated only in an unusual phrasing not on the list, with no `PROBE` observation
  to catch it either, is missed. This is a deliberate precision-over-recall
  trade to avoid a subjective judgment call substituting for a real signal.
- **Severity:** high whenever this check fires (the deterministic pass found
  nothing, and no `PROBE` question on any sampled page contradicts that).
  **Archetype re-threshold:** `personal-portfolio` downgrades to medium — a
  personal site rarely needs to explicitly say "I am a person."
- **Confidence:** high when `>=1` page also carries a `PROBE` observation whose
  Q2 independently confirms the miss (two independent signals agree); medium
  when zero pages carry a `PROBE` observation at all, so the finding rests on
  the deterministic keyword pass alone, whose recall gaps are a real,
  acknowledged limitation. Downgraded one further tier on `personal-portfolio`.
- **Recommendation:** add one plain sentence stating what the entity is (its
  category), near the top of the homepage or about page.
- **Validation:** re-extract; a type-word or the `PROBE` Q2 answer is now present.

## D-ENTITY-03 — ambiguous entity, no distinguishing attribute
- **Meaning:** the entity's name collides with other known entities, and the
  site's own text supplies no attribute that would let a reader (or a machine)
  tell them apart.
- **Mechanism:** Appendix D, mistaken identity. An assistant may attribute a
  competing entity's facts to this one, or decline to cite either.
- **Applicability:** a `CORROBORATION` observation exists with
  `performed: true` for the candidate name. **Absent that record, this check does
  not fire at all** — it is never inferred from a name "sounding generic," and a
  missing corroboration record is never treated as "no collision found."
- **Observable signals:** the corroboration record's `matches` list (candidate
  competing entities, each with `name`, `source_url`, `category`); the entity
  profile's own `distinguishing_attributes` (type/category, location, identity
  anchor).
- **Detection test:** fire when `matches` has `>=2` distinct entities plausibly
  matching the name **and** the entity profile has none of: a stated type
  (D-ENTITY-02 would pass), a stated location, or a populated identity anchor
  (D-ENTITY-05 would pass) — i.e. every distinguisher is absent, not just one.
- **Evidence required:** the corroboration record's query, timestamp, and
  matches with source URLs; the entity profile fields checked for distinguishers.
- **False-positive rules:** never asserts a collision that wasn't actually
  observed; never fires from the model's prior belief that a name "sounds
  generic"; requires **all** distinguishers absent, not merely one — a site that
  states its type but not its location is not flagged here (that's a narrower
  problem than this check's severity implies).
- **False-negative risks:** entirely dependent on `CORROBORATION` having run,
  which requires outbound search availability — `PROJECT_CONTEXT.md` OQ-3 is
  still open, so this check is a permanent, honestly-declared coverage gap on any
  audit run without that capability, never a silent pass.
- **Severity:** medium base; high when a competing match's `category` equals this
  entity's own determined type (an adjacent-category collision, the kind most
  likely to actually confuse a citation).
- **Confidence:** high — both trigger conditions are deterministic once the
  corroboration record exists.
- **Recommendation:** state category, operating scope, and an identity anchor
  (`sameAs` to an authoritative profile) in plain text, naming the exact sentence
  to add.
- **Validation:** re-extract the entity profile; type, location, or identity
  anchor is now populated, i.e. `>=1` distinguisher is present.

## D-ENTITY-04 — cross-page identity inconsistency
- **Meaning:** two pages assert different values for the same identity fact —
  description or address — for what purports to be the same entity.
- **Mechanism:** Appendix D. Conflicting self-descriptions or addresses give a
  citation pipeline no reliable single fact to repeat, and may cause it to prefer
  a stale or wrong version.
- **Applicability:** `>=2` pages carry a candidate value for the same field
  (`description` or `location`), where each candidate is an entity-level source
  (homepage/about-page description, or an `Organization`/`LocalBusiness` JSON-LD
  node's `address`) — **never** an arbitrary product page's own description,
  which is a different fact than the entity's identity.
- **Observable signals:** pairwise text similarity between description
  candidates — the greater of `difflib.SequenceMatcher`'s character-sequence
  ratio and an asymmetric word-containment ratio (what fraction of the
  *shorter* description's significant words also appear in the longer one).
  The containment term is deliberate: a short homepage tagline that is a
  near-verbatim prefix of a longer, fully consistent about-page blurb must not
  score as a conflict purely because `SequenceMatcher` penalizes the length
  difference — a very common, non-conflicting real-world pattern. Address
  candidates compare structured-field equality (`streetAddress`,
  `addressLocality`, `postalCode`) after normalizing common abbreviations
  (`St`/`Street`, `Ave`/`Avenue`, `Rd`/`Road`, ...) so the same real address
  written two conventional ways is never a conflict.
- **Detection test:** description pair fires when the (containment-boosted)
  similarity is `< 0.5` — a deterministic proxy for "materially different,"
  chosen deliberately over an LLM judgment per this skill's stated preference
  for deterministic extraction first; see the note in `store-contract.md`.
  Address pair fires when normalized structured fields differ **and** neither
  address node carries its own distinguishing `name` (a branch/location
  label) — i.e. both claim to be *the* address of one undifferentiated
  entity.
- **Evidence required:** both conflicting strings/values, both `source_url`s,
  both `observation_id`s — every finding quotes both sides (`SKILL.md` Evidence
  rules).
- **False-positive rules:** different product pages describing different
  products is not inconsistency — restricted to entity-level description sources
  only. Multiple named locations (each address node carries its own `name`) is
  not inconsistency — it's a legitimate multi-location business, never flagged.
- **False-negative risks:** the `0.5` similarity floor is conservative by design
  (favors missing a real stylistic-only conflict over flagging a paraphrase);
  the description check does not catch subtle factual contradictions inside
  similar-looking prose — that is `trust-freshness-audit`'s D-TRUST-03 territory
  for asserted facts, not this skill's.
- **Severity:** high.
- **Confidence:** high for the structured-address comparison; medium for the
  text-similarity description comparison, since a ratio is a proxy, not a
  semantic judgment.
- **Recommendation:** reconcile the conflicting values sitewide, or, if the
  variation is intentional (e.g. distinct locations), label each one explicitly.
- **Validation:** re-extract; the two candidates now match, or each carries an
  explicit distinguishing label.

## D-ENTITY-05 — no machine-readable identity anchor
- **Meaning:** no `Organization`/`LocalBusiness`/`Person` JSON-LD node exists with
  a `sameAs` link or self-referencing `url` — nothing ties the site's textual
  identity to a structured, machine-followable anchor.
- **Mechanism:** Appendix D. Structured identity anchors are how a citation
  pipeline cross-checks *which* entity a name refers to; their absence removes
  that cross-check entirely.
- **Applicability:** **only when combined with an actual identity-clarity
  failure** — D-ENTITY-01 or D-ENTITY-02 also fired on this same audit. This
  check never evaluates, let alone fires, on its own; a site with a clear,
  consistent name and stated type needs no additional anchor to be adequately
  identified. This is this check's own instance of "never flag absence alone."
- **Observable signals:** presence of an `Organization`/`LocalBusiness`/`Person`
  JSON-LD node; its `sameAs` array (empty or populated); its `url` property.
- **Detection test:** given D-ENTITY-01 or -02 fired, fire this check when no
  such node exists, or it exists with an empty `sameAs` and no self-referencing
  `url`.
- **Evidence required:** the JSON-LD block searched (or its absence), and a
  reference to which sibling check (D-ENTITY-01/02) established the
  identity-clarity failure this check is compounding with.
- **False-positive rules:** never fires standalone — enforced structurally by the
  applicability precondition above, not by a severity discount.
- **False-negative risks:** a site with a subtly wrong `sameAs` (linking to the
  wrong profile) passes this presence-only check; that is a different, harder
  problem this mechanical test does not attempt.
- **Severity:** medium.
- **Confidence:** high — structural presence/absence is a direct test.
- **Recommendation:** add an `Organization`/`Person`/`LocalBusiness` JSON-LD node
  with `sameAs` linking to the entity's official profiles (or at minimum a
  self-referencing `url`).
- **Validation:** re-fetch; the node is present with a non-empty `sameAs` or a
  self-referencing `url`.

## D-ENTITY-06 — primary offering unclear
- **Meaning:** nothing on the homepage, or one click from it, plainly states
  what the entity sells, builds, or does.
- **Mechanism:** Appendix D. An assistant asked "what does X do" needs a plain
  answer; marketing abstraction with no concrete statement of the offering
  produces no quotable answer to that question.
- **Applicability:** archetype-gated — this is the field where "is this even
  important for this kind of site" varies the most. **Suppressed** on
  `documentation`, `personal-portfolio`, and `institutional` archetypes (per
  `<marketplace-root>/references/archetype-applicability.md` — those site kinds
  are not organized around a sellable offering, and demanding one produces
  exactly the false-positive class `PROJECT_CONTEXT.md` Defect C was written to
  eliminate). **Re-thresholded** (confidence capped at medium, never fires at
  high severity) on `publisher-editorial`. Applies normally on `brand-product`,
  `ecommerce`, `local-business`, `web-app`.
- **Observable signals:** JSON-LD `Product`/`Service`/`Offer` node whose
  `name`/`description` also appears in prose; a structural "we
  offer/sell/provide/build/make/help ..." sentence pattern (generic, not
  vertical-specific) in prose; `PROBE` question **Q3** as the fallback.
- **Detection test:** deterministic-first, checked on the homepage **and** any
  page linked directly from it (depth-1) — deliberate brand minimalism on the
  homepage itself is not a defect if the offering is plain one click away. Fire
  only when neither the homepage nor any depth-1 page shows the JSON-LD/prose
  signal, and — where a `PROBE` observation exists for those pages — Q3 is also
  `answered: false` on all of them.
- **Evidence required:** the homepage and depth-1 URLs checked, and the
  `OBS-PROBE-*` id(s) for Q3 where consulted.
- **False-positive rules:** never fires on a suppressed archetype regardless of
  signal. Never fires from the homepage alone failing — depth-1 pages are always
  also checked before this fires.
- **False-negative risks:** an offering stated only past depth-1 (e.g. only on a
  dedicated "/products" page two clicks deep) is not checked by this test; that
  is a deliberate scope limit, not an oversight — depth-1 is the "one click
  away" the guardrail language describes.
- **Severity:** high base; capped at medium confidence (never critical) on
  `publisher-editorial`, per the archetype re-threshold.
- **Confidence:** high when the deterministic pass and (if consulted) `PROBE`
  agree; medium when the finding rests on `PROBE` alone.
- **Recommendation:** state plainly, on the homepage or the page one click from
  it, what the entity offers or does — name the specific page and the missing
  sentence.
- **Validation:** re-fetch the homepage and its depth-1 pages; the offering
  pattern or `PROBE` Q3 now succeeds on at least one of them.
