# Phase 1B — Principal Engineer Architecture Review
**Adobe University Hackathon 2026 · Round 3**
Reviewing: `PHASE1-ANALYSIS.md`. Still no implementation code.

This review found seven defects in my own Phase 1 design. Three are serious: the headline differentiator has no owner, two skills were given the same job description, and the entity checks silently assume every audited site is a commercial brand. All three would have shown up on Day 6 as rework or on grading day as lost points. They are fixed below.

---

## Part 1 — Skill contracts

Notation: **DET** = deterministic script, **LLM** = model reasoning over collected evidence, **HYB** = deterministic trigger with LLM interpretation.

A rule that governs every contract below: **the audit skills partition the question space, not the artifact space.** Three skills all read the JSON-LD blob. That is fine and expected. What must never overlap is the *question they ask of it*. Every "must not detect" clause below is a boundary against a specific sibling.

---

### 1.0 `lib/site_observer` — instrumentation (NOT a skill)

Introduced by this review. See Defect A in Part 2.

**Responsibility.** Produce the immutable observation store. It detects nothing, scores nothing, and emits no findings.

**Produces.** `observations.json` + `pages/` cache: robots ruleset and its fetch status, per-page raw HTML, rendered DOM (where available), HTTP status/headers/timing chain, extracted main-content text for both lenses, parsed structured data, link graph, heading outline, date signals, media inventory, page-type classification, site-archetype classification, and probe results.

**Inputs.** `{url, budget, capabilities}`. **Outputs.** Read-only store + `coverage.json` recording every collection that was attempted, skipped, or failed and why.

**Determinism.** All DET except two HYB instruments: the extraction probe and page/archetype classification, both temperature 0, fixed prompt, structured output, input text hashed into the observation so the derivation is auditable.

**Why not a skill.** It has no audit concern of its own. Making it a seventh skill would be exactly the pipeline-stage padding the rubric penalises. It is a library, invoked once by the entrypoint during scope establishment, and every `SKILL.md` declares it as a dependency.

---

### 1.1 `audit-orchestrator` (ENTRYPOINT)

1. **Responsibility.** Own the audit lifecycle: resolve and validate the target, establish scope and budget, detect runtime capabilities, drive `site_observer` once, invoke the four detectors and then the scorer, enforce the report schema, attach the coverage block, generate the proactive layer, emit exactly one report.
2. **Detects.** Nothing about the website. It detects *audit* faults only: unresolvable target, robots-disallow-all, budget exhaustion, a detector crashing, a finding whose evidence IDs don't resolve, schema violation.
3. **Evidence produced.** Run manifest (target, timestamp, budget consumed, capability matrix, skill versions), the coverage block, and the validation log.
4. **Must NOT detect.** Any site defect. No check logic may live here — if the orchestrator ever computes a finding, the decomposition is cosmetic and the composition rubric line collapses. It must also not score: severity and ranking belong to `evidence-prioritization` (Defect B).
5. **In/Out.** In: `{url, options}`. Out: `report.json` + `report.md`.
6. **DET/LLM.** DET for lifecycle, validation, schema, emission. LLM only for the executive summary prose and the proactive layer, both constrained to what is already in the findings and coverage data.
7. **Genuinely separate because** it is the only component that knows the audit exists as a whole. Every other skill is a pure function from observations to findings and would be identical if invoked from a different marketplace.

**New requirement (Defect G).** The orchestrator must emit a schema-valid report under every failure mode, including unreachable host and total robots disallow. A crash is a zero on every rubric line at once. Failure paths are a Day 6 deliverable, not a Day 10 afterthought.

---

### 1.2 `crawl-render-audit`

1. **Responsibility.** Answer one question: *can a machine reach this page, read it, and pull a specific fact out of it?* The three gates of Appendix A, and nothing beyond them.
2. **Detects.** D-CRAWL (reachability, permission, redirects, canonicals, orphans, duplicate hosts, robots faults), D-RENDER (raw-vs-rendered gaps), D-EXTRACT (metadata presence/uniqueness, structured-data validity and DOM agreement, heading usability, encoding, fact-extractability from text alone).
3. **Evidence produced.** Status/redirect chains, robots rule matches with the matching line quoted, raw-vs-rendered character counts and ratios plus a named excerpt present in one lens and absent in the other, parse errors with line references, probe misses with the exact machine-readable text that was available.
4. **Must NOT detect.**
   - Whether the extracted identity is *correct or unambiguous* → `entity-semantic-audit`.
   - Whether an extracted date is *stale* or a claim *unsupported* → `trust-freshness-audit`. This skill observes that `dateModified` exists; it never judges the date.
   - Whether a human arriving cold can orient → `engagement-audit`. A wall that blocks the *fetch* is D-CRAWL-09; a wall that appears after a successful fetch and blocks the *reader* is E-ANSWER-02.
   - Whether a page's outgoing links serve the visitor → `engagement-audit`. This skill only asks whether the link graph makes pages *reachable*.
   - Severity. It proposes a base severity from the taxonomy; it does not finalise one.
5. **In/Out.** In: observation store. Out: `findings[]` (unscored) with bound evidence IDs.
6. **DET/LLM.** Almost entirely DET — status codes, robots matching, ratios, parsers, uniqueness sets. HYB only for interpreting *which* missing content is substantive versus chrome, and for probe-miss interpretation.
7. **Genuinely separate because** it is the only skill whose failures are binary and machine-verifiable. Its findings can be validated by a `curl` command. That property is worth isolating: it is the skill a grader can most easily confirm is real.

---

### 1.3 `entity-semantic-audit`

1. **Responsibility.** Answer one question: *can a machine tell who this is, what they do, and not confuse them with something else?* Appendix D, identity half.
2. **Detects.** Canonical name absence or variance, entity type never stated in plain text, primary offering unclear, cross-page identity inconsistency, missing identity anchors (`Organization`/`sameAs`/official profiles), observed name collision without on-site distinguishers, facts implied rather than stated where the fact is an *identity* fact.
3. **Evidence produced.** The entity fact table (name, type, offering, location, domain, aliases) with per-page provenance and per-field source (prose / heading / title / schema / inferred), the variance report across pages, the probe transcript for identity questions, and observed competing entities with source URLs where an external check actually ran.
4. **Must NOT detect.**
   - That structured data is *malformed* → `crawl-render-audit`. This skill reads schema for identity content only; parse errors are not its business.
   - That a claim is *stale or uncorroborated* → `trust-freshness-audit`. Boundary: this skill owns **who** (name, type, offering, address as an identity attribute); trust owns **what is asserted and when** (prices, statistics, dates, availability). A conflicting address across pages is an entity finding; a conflicting price is a trust finding.
   - That the visitor can't tell what site they're on → `engagement-audit`. Boundary: entity failure is machine-facing (identity not extractable from text); orientation failure is human-facing (brand not visible on arrival). Both may fire on the same page from different lenses, and that co-occurrence is a genuine, non-duplicative signal.
5. **In/Out.** In: store. Out: unscored `findings[]` + `entity_profile` (consumed by trust and by the proactive layer).
6. **DET/LLM.** DET for extraction, variance, presence, cross-page diffing. LLM for judging whether two descriptions are *materially* different versus stylistically different, and for judging offering clarity. Every LLM judgement must quote both strings it compared.
7. **Genuinely separate because** it is the only skill that reasons about the site as one entity rather than as a set of pages, and it is the only one whose output another audit skill consumes as input.

---

### 1.4 `trust-freshness-audit`

1. **Responsibility.** Answer one question: *would a machine believe this claim and repeat it?* Appendix B and D, credibility half.
2. **Detects.** Undated time-sensitive claims, stale signals, internal contradictions in asserted values, unattributed falsifiable claims, single-source claims where corroboration was actually attempted, organisational opacity.
3. **Evidence produced.** The claim table (claim text, page, type, date signal, source attribution), the date inventory, contradiction pairs with both URLs and both values quoted, and — only when a check ran — the corroboration record with query, method, timestamp, and results.
4. **Must NOT detect.**
   - Anything about identity → `entity-semantic-audit`.
   - Missing `dateModified` as a *markup* defect → that's `crawl-render-audit`'s metadata concern. This skill fires only when a *time-sensitive claim* lacks a date, which is a different and much narrower trigger.
   - Corroboration status it did not verify. **Hard rule, enforced structurally:** the corroboration finding class cannot be emitted unless a corroboration record with a real timestamp exists in the store. Absent that record, the check is not "passed" and not "failed" — it is `X-COV-01`.
5. **In/Out.** In: store + `entity_profile`. Out: unscored `findings[]`.
6. **DET/LLM.** DET for date extraction, staleness arithmetic, cross-page value diffing, attribution proximity. LLM for classifying a sentence as a falsifiable claim versus marketing language, and for judging whether two values genuinely conflict versus describing different things (regional pricing, multiple locations). This is our highest-FP-risk skill and gets the tightest evidence rules.
7. **Genuinely separate because** it is the only skill that reasons about the world beyond the site, and the only one with an external-dependency failure path that must degrade to a coverage gap rather than a guess.

---

### 1.5 `engagement-audit`

1. **Responsibility.** Answer one question: *a visitor lands here cold, from an AI answer, with no homepage context and no session — can they orient, get the answer, and continue?* Appendix E.
2. **Detects.** E-ORIENT (site identification on a deep page, path context, fragment resolution), E-ANSWER (title–body promise mismatch, entry-blocking interstitials, gate mismatch between what a machine could cite and what a human sees, and the cited fact not being locatable on arrival), E-CONTINUE (no next step, dead ends, no route to a topic hub, broken internal links).
3. **Evidence produced.** Cold-arrival rendering of the page at a mobile and a desktop viewport, first-screen text in DOM order, brand-token positions, overlay/occlusion measurements at first paint, scroll depth of the answering sentence, outgoing-link classification, breadcrumb or textual path presence.
4. **Must NOT detect.**
   - Visual design quality, colour, hierarchy, "feels cluttered," CTA styling. **Not one finding in this skill may rest on aesthetics.** Every check requires a positional or structural measurement.
   - Machine reachability of links → `crawl-render-audit`.
   - Whether the brand is identifiable *to a machine* → `entity-semantic-audit`.
   - Performance as a user-experience complaint. Fetch cost belongs to crawl as a crawler-timeout mechanism; this skill does not re-litigate speed.
5. **In/Out.** In: store (rendered lens) + `entity_profile` (for brand tokens). Out: unscored `findings[]`.
6. **DET/LLM.** DET for brand-token positions, overlay geometry, link out-degree, breadcrumb presence, fragment resolution, answer scroll depth. LLM for title–body promise mismatch and for judging whether an onward link is *relevant* continuation. Both capped at medium confidence and required to quote the strings compared.
7. **Genuinely separate because** it is the only skill that runs against the human lens. Every other skill audits what a machine receives; this one audits what a person receives after the machine sent them. That is the actual second half of the brief, and giving it its own skill is the clearest signal to a grader that we treated it as a first-class concern rather than a bolt-on.

---

### 1.6 `evidence-prioritization`

1. **Responsibility.** Own the scoring and prioritisation *policy*: normalisation, aggregation, deduplication, confidence assignment, severity computation, ranking. It is the single place where a finding's importance is decided.
2. **Detects.** Nothing about the site. It detects finding-set pathologies: duplicates across skills, per-URL repetition of one template-level defect, severity inflation, low-confidence assertions that should be demoted to proactive opportunities.
3. **Evidence produced.** The scoring trace per finding — which matrix cell applied, which modifiers fired, which findings were merged into it and why, and the calibration log if the distribution guard triggered.
4. **Must NOT detect.** Any site defect, and it must never *create* a finding — only merge, demote, rank, or drop. It also must not fetch anything.
5. **In/Out.** In: unscored `findings[]` from four skills + store metadata (for scope and page importance). Out: scored, deduplicated, ranked `findings[]` + `demoted[]`.
6. **DET/LLM.** Fully DET. This is deliberate: it means severity is reproducible and defensible, and a grader can read `severity-matrix.md` and predict the output. The only LLM involvement is nil.
7. **Genuinely separate because** scoring policy is the one thing that must be *consistent across all four detectors*. If it lived inside each skill, four different severity philosophies would emerge by Day 8. It is a cross-cutting policy, and its full determinism makes it the easiest skill in the marketplace to defend as real engineering.

**Note on the padding risk.** This is the skill most likely to read as a pipeline stage. Its `SKILL.md` opens with one sentence stating that it owns scoring policy, not a processing step, and it ships `severity-matrix.md`, `confidence-model.md`, and `dedupe-rules.md` as substantive reference material. Policy with published rules is a concern; a function is not.

---

## Part 2 — Defects found in the Phase 1 design

### Defect A (serious) — the extraction probe had no owner
Phase 1 named the agent's-eye probe as differentiator #1, then listed it as driving checks across two different skills, and never said who runs it. Left alone, either both skills implement it (divergence, double findings) or neither does.

**Root cause:** it is an *instrument*, not a check. It produces observations, not findings.

**Fix:** the probe moves into `lib/site_observer` and runs once during collection. Its output — per page, per canonical question: answered / not-answered, the answer, the evidence span, the text that was available — is an observation any skill may read. `crawl-render-audit` interprets misses on factual questions, `entity-semantic-audit` on identity questions, `engagement-audit` uses answer position for E-ANSWER-04.

**Consequence:** this forces an honesty correction. Phase 1 decision D-4 said "the LLM never observes." That is now false for the probe and for page classification. Restated precisely: **the observation layer is deterministic except for two named instruments, which run at temperature 0 with fixed prompts and structured output, and whose inputs are hashed into the observation so any derivation can be re-checked.** Claiming end-to-end determinism when we ship LLM instruments is the kind of overclaim a red-teamer would eat us alive for on Day 9 — and the handout explicitly says the README must not claim capabilities we don't have.

### Defect B (serious) — orchestrator and evidence-prioritization had the same job
Phase 1 gave the orchestrator "normalize → deduplicate → validate evidence → assign severity/confidence → prioritize" and then gave `evidence-prioritization` normalisation, scoring, and prioritisation. That is a straight duplication in my own specification, and it is precisely the "fake skill decomposition" failure the brief warns about.

**Fix:** the orchestrator's list is cut to **invoke, collect, bind-validate, schema-enforce, emit**. All normalisation, aggregation, dedupe, confidence, severity, and ranking move wholly into `evidence-prioritization`. Evidence *binding* validation stays with the orchestrator because it is schema enforcement, not scoring.

### Defect C (serious) — entity checks assume a commercial brand
Every D-ENTITY check is written as though the audited site sells something under a brand name. Point it at a government department, a university lab, a documentation site, a personal blog, a marketplace with thousands of third-party sellers, or a nonprofit, and it will report "primary offering unclear" and "no canonical entity name" on sites where those concepts barely apply. This is the largest generalization hole in Phase 1, and generalization is a named rubric line.

**Fix:** add **site-archetype classification** to the observation layer, before any check runs. Archetypes: `brand-product`, `ecommerce`, `publisher-editorial`, `documentation`, `local-business`, `personal-portfolio`, `institutional` (gov/edu/nonprofit), `web-app`. Ship `references/archetype-applicability.md` — a matrix of which checks apply, which are suppressed, and which change threshold per archetype. Example rows: `D-ENTITY-06` (offering unclear) does not fire on `documentation` or `institutional`; `D-TRUST-01` (undated claims) raises severity on `publisher-editorial` and lowers it on `documentation`; `E-CONTINUE-01` does not fire on `personal-portfolio`. Archetype is stated in the report so a reader can see what frame we audited under.

This one fix converts our largest unseen-site liability into a visible strength.

### Defect D — aggregation was never specified
Phase 1 defined dedupe but never said what the unit of a finding is. Without a rule, twelve product pages missing schema become twelve findings and the report is unreadable.

**Fix:** the finding unit is `(check_id, template_cluster)`, not `(check_id, url)`. URLs are clustered by shape and DOM skeleton similarity. One finding carries `affected: {count, sample_urls[≤5], total_in_scope}`. Scope then feeds severity: 12/12 is worse than 1/12, and the matrix must see that number.

### Defect E — UA-variant probing was both risky and unnecessary
D-CRAWL-09 as written compared responses across user-agent strings. Sending a Googlebot or GPTBot UA we are not is deceptive, arguably violates the spirit of robots compliance, and is a red-team finding waiting to happen on a submission whose guardrails say "safe."

**Fix:** one honest, self-identifying UA for the whole audit. We observe whether *our* honest fetch is blocked and report that factually. We additionally read robots.txt for AI-crawler groups declaratively — reading the file is free and honest, and it answers the same question better than spoofing would.

### Defect F — the determinism claim was too broad
Covered in Defect A. The README wording is fixed now, not on Day 10.

### Defect G — no defined behaviour on catastrophic failure
Unreachable host, DNS failure, robots disallow-all, no renderer, Cloudflare challenge. Phase 1 had no path for these.

**Fix:** a **degraded audit mode**. Any of these produces a schema-valid report with the appropriate critical finding, a populated coverage block explaining what could not be assessed, and a normal exit. The audit never crashes and never returns an empty findings array without explanation.

---

## Part 3 — Duplicated responsibilities, resolved

| Shared artifact | Skills touching it | Partition rule |
|---|---|---|
| JSON-LD / microdata | crawl, entity, trust | crawl: does it parse, is it valid, does it contradict the DOM. entity: does it establish identity. trust: does it carry dates and claim provenance |
| Dates | crawl, trust | crawl: is the date signal present and machine-readable. trust: is the date *stale*, and does a time-sensitive claim need one |
| Link graph | crawl, engagement | crawl: does linking make pages *reachable by a machine*. engagement: does linking let a *human* continue |
| Interstitials / walls | crawl, engagement | crawl: blocks the fetch (pre-content). engagement: appears after a successful fetch and blocks the reader |
| Title & meta description | crawl, engagement | crawl: present, unique, non-boilerplate. engagement: does the promise match the body |
| Cross-page consistency | entity, trust | entity: **who** (name, type, offering, address). trust: **what is asserted and when** (price, statistic, date, availability) |
| Probe results | crawl, entity, engagement | crawl: factual extractability. entity: identity extractability. engagement: position of the answer on arrival |
| Normalisation & scoring | orchestrator, prioritization | prioritization owns all of it; orchestrator owns only schema and evidence-binding enforcement |

Each row becomes a line in the relevant `SKILL.md`'s scope section, so the boundary is visible to a grader and to us on Day 8.

---

## Part 4 — Taxonomy revisions

### 4.1 Added

| ID | Meaning | Why it was missing | Sev | Det |
|---|---|---|---|---|
| **D-CRAWL-15** | `robots.txt` returns 5xx, times out, or is syntactically broken | Many crawlers treat an unreachable robots.txt as disallow-all. This is a total-invisibility failure that is invisible to every SEO tool and trivially detectable | critical | DET |
| **D-CRAWL-11** | Multi-locale content without `hreflang` or with conflicting locale signals | Splits citation signal across duplicates and can serve the wrong language to a crawler | medium | DET |
| **D-CRAWL-12** | Content or availability varies by requester geography | We audit from one location; an assistant fetches from another. Recorded as a caveat, escalated to a finding only if we observe an outright regional block | low + coverage note | DET |
| **D-CRAWL-13** | Same content served at multiple 200-status hosts/paths (www and apex, trailing slash, params) with no canonical resolution | Classic signal-splitting; cheap to detect, real citation impact | medium | DET |
| **D-CRAWL-14** | Crawl budget consumed by faceted/parameter URL explosion before substantive pages are reached | Explains sites that are technically fine but effectively unreachable at depth | medium | DET |
| **D-EXTRACT-09** | Encoding or content-type faults: wrong charset, mojibake, markup served as `text/plain` | Cheap, deterministic, and a total extraction failure when present | high | DET |
| **E-ANSWER-04** | **Citation-landing mismatch** — the fact a machine could cite is not locatable on arrival (below the fold, inside a collapsed region, in a linked PDF) | The best new check in this review. It joins the two halves of the brief with one measurement: the probe found the answer, and the rendered page buries it | high | HYB |

`llms.txt`, feed/API availability, and author-expertise enrichment are added as **proactive opportunities only**, never findings. Flagging the absence of a non-standard file as a defect is exactly the "irrelevant absence" false positive we are trying to beat the field on.

### 4.2 Cut

| ID | Reason |
|---|---|
| **E-CONTINUE-05** (viewport/overflow) | Weakest mechanism link in the catalog and the closest thing we had to an aesthetics check. It is an accessibility concern, not an AI-discoverability or AI-referral-engagement one. Cutting it removes a whole class of "the site looks bad" findings and costs us nothing the rubric rewards |

### 4.3 Demoted

| ID | Change | Reason |
|---|---|---|
| D-TRUST-04 (unattributed superlatives) | Severity capped at **low**; aggregated into exactly one finding site-wide; primarily a proactive suggestion | Would otherwise fire on every marketing site alive. High FP volume, low mechanism strength |
| D-EXTRACT-08 (filler dilution) | Moved to **proactive-only** | Language-dependent, subjective, and the closest thing in the catalog to an LLM opinion |
| E-ORIENT-02 (answer-first framing) | Fires only when archetype is `publisher-editorial` or `documentation` **and** the probe located the answer below 50% scroll depth — i.e. it merges into the E-ANSWER-04 measurement | As originally written it would have fired on well-built pages constantly |
| D-CRAWL-10 (fetch cost) | Capped at **medium**, requires ≥5 samples and a 3× margin over threshold | Our network conditions are not the user's; thin evidence |
| E-ANSWER-01 (promise mismatch) | Confidence capped at **medium**, severity capped at **medium**, must quote both strings | Purely LLM-judged |

### 4.4 Reassigned

- D-ENTITY-04 keeps cross-page **address** consistency; D-TRUST-03 keeps cross-page **price/statistic/date** consistency. Previously both would have fired on an address conflict.
- D-EXTRACT-02 (title/meta) stays with crawl; the promise-mismatch aspect moves cleanly to E-ANSWER-01.
- D-CRAWL-09 rewritten per Defect E: observe our own honest fetch, plus declarative robots reading. No UA spoofing.

### 4.5 Severity calibration

`critical` is reserved for **total or near-total invisibility**, and the matrix enforces it: site unreachable, robots disallow-all or robots 5xx, site-wide noindex, all substantive content render-only with no renderer path, or primary content unextractable across every sampled template. Nothing else can reach critical regardless of modifiers. Without this ceiling the distribution guard is the only thing standing between us and an inflated report, and one control is not enough.

---

## Part 5 — What still fails on unseen sites, and what we do about it

| Scenario | Failure without a fix | Mitigation |
|---|---|---|
| Non-commercial site (gov, docs, personal, institutional) | Entity checks misfire wholesale | Archetype gating (Defect C) |
| Non-English or RTL site | Claim classification, filler detection, and brand-token matching all degrade silently | Language detection in the observation layer; language-dependent checks self-disable and log a coverage gap; script-aware token matching |
| Very large site | 30-page sample unrepresentative; findings over-generalised | Template-stratified sampling; every finding reports `total_in_scope`; confidence lowered when a template cluster has <3 samples |
| Single-page site or link-in-bio | Most checks inapplicable; risk of a report full of noise | Archetype + a minimum-corpus rule: below 3 pages, cross-page checks disable and say so |
| Bot-protection challenge (Cloudflare etc.) | Audit crashes or reports a fabricated picture | Degraded mode (Defect G); challenge detected and reported as the finding it is |
| robots.txt disallows everything | Either we crawl anyway (disqualifying) or we return nothing | Report one critical finding, crawl nothing, exit clean |
| Login-walled application | Empty or misleading audit | Detected at scope; audit limited to public surface; coverage block states the boundary |
| Target redirects cross-domain | Ambiguity about what was audited | Resolve, report both requested and audited host, note the redirect as an observation |
| JS-only navigation with no sitemap | Discovery yields one page | Route discovery from rendered link graph; if that fails too, coverage gap — **we never guess URL patterns**, that is both unreliable and a rate-abuse risk |
| Renderer unavailable in grading environment | A third of the catalog silently passes | Capability detection; render-dependent checks become coverage gaps, never silent passes |

The through-line: **a check that cannot run must never look like a check that passed.** Most entrants will conflate the two. The coverage block is how we don't.

---

## Part 6 — Revised architecture (final)

```
brand-ai-readiness-audit/
  marketplace.json
  README.md
  lib/                         <- instrumentation, not a skill
    site_observer/             collection, probe, classification, budget
    common/                    http, robots, extract, schema, observations
  skills/
    audit-orchestrator/        ENTRYPOINT - lifecycle, binding, schema, emission
    crawl-render-audit/        gates 1-3: reach, read, extract
    entity-semantic-audit/     who is this, unambiguously
    trust-freshness-audit/     would a machine believe it
    engagement-audit/          the cold AI-referred arrival
    evidence-prioritization/   scoring and prioritisation policy
```

Flow: `URL → orchestrator (scope, capabilities, budget) → site_observer (ONE pass → immutable store + coverage) → four detectors read the store in parallel → evidence-prioritization scores and ranks → orchestrator validates bindings, enforces schema, adds proactive layer, emits report.json + report.md`

**Tradeoff stated openly (OQ-1 resolved):** collection lives in `lib/`, so skill folders are not individually copy-pasteable. Each `SKILL.md` declares the dependency explicitly. The gain is that all five audit skills become symmetric pure functions over one immutable store, which is a far stronger separation-of-concerns story than five skills that each crawl. Portability is preserved at the *marketplace* level, which is what the brief actually asks for — the manifest is self-contained and needs no external service.

**Revised LLM budget** (was unbounded in Phase 1, a real runtime risk): ≤14 model calls per audit — 8 probe calls (one per rendered page, all canonical questions batched into one structured-output call), 1 archetype/classification call, 4 detector interpretation calls, 1 report-prose call. Batching is the difference between comfortably inside 5 minutes and nowhere near it.

---

## Part 7 — Seven-day implementation blueprint

Phase 1 plus this review has completed the Day 1–3 design work. Seven days remain, and they are all build, test, and harden.

**Day 1 — Contracts and skeleton.** `report-schema.json`, `observation-schema.json`, `marketplace.json`, six `SKILL.md` files with real frontmatter and scope sections (including the "must not detect" boundaries from Part 1), `severity-matrix.md`, `archetype-applicability.md`, `validate_marketplace.py`.
*Exit:* validator passes on empty skills; our schema validates the handout's own sample report unmodified.

**Day 2 — Observation layer.** `lib/common` (robots parser, budget-enforcing HTTP client, extractors) and `lib/site_observer` collection: crawl, render with capability detection, structured data, links, dates, media, encoding, template clustering.
*Exit:* three real sites each produce a complete store inside budget, with robots respected and the coverage block populated. Renderer forcibly disabled once, and the run still succeeds.

**Day 3 — Probe, classification, and `crawl-render-audit`.** The two HYB instruments, then the first and largest detector.
*Exit:* probe outputs are stable across two runs on the same store; crawl findings carry resolvable evidence IDs; a deliberately fabricated evidence ID is rejected by the binding validator.

**Day 4 — Entity, trust, engagement detectors.** All three built against the same store, in parallel where possible.
*Exit:* all four detectors run on three real sites with zero cross-skill duplicate findings, checked against the Part 3 partition table. **Feature freeze on new checks at end of day.**

**Day 5 — Scoring and orchestration.** `evidence-prioritization` (matrix, confidence, aggregation by template cluster, dedupe, distribution guard), then orchestrator composition, the degraded-mode failure paths, and the proactive layer.
*Exit:* end-to-end schema-valid report on three real sites in under 5 minutes; severity distribution sane; all five catastrophic-failure paths produce valid reports.

**Day 6 — Report quality and fixture corpus.** Markdown rendering, the six-question recommendation contract with validation steps, then the offline fixture sites and the harness tracking expected/actual/FP/FN/evidence-correct/recommendation-correct/severity-reasonable.
*Exit:* FP and FN rates **measured** on the corpus, not estimated. A non-expert reader can act on the top five findings unaided.

**Day 7 — Red team, then package.** Two hostile passes producing `RISK → WHY IT MATTERS → RUBRIC IMPACT → FIX`, fixes implemented between passes. Then Phase 11 validation, README, `PROJECT_CONTEXT.md`, clean-machine run, zip.
*Exit:* every critical and high risk closed or accepted in writing; full validation checklist green; clean-machine run succeeds from the zip.

**Compression order if we slip:** fixture corpus 16 → 10 first (keeping both-weak, both-strong, JS-heavy, ambiguous-entity, irrelevant-absence, non-commercial-archetype, deep-page-no-orientation), then the second red-team pass, then the Markdown renderer. Never cut: the binding validator, archetype gating, the coverage block, or the degraded-mode paths — each of those is load-bearing for a rubric line.

---

## Part 8 — Still open

- **OQ-2 (renderer):** my recommendation is now firm — take the Playwright dependency, detect at runtime, degrade gracefully. Defect G makes the downside survivable.
- **OQ-3 (outbound search):** still blocking. D-TRUST-05 and D-ENTITY-03 are designed either way, but I need to know by Day 1 whether to build the corroboration path or ship it as a permanent, honestly-declared coverage gap.
- **OQ-4 (invocation environment):** shell access to `scripts/`, or a model reading `SKILL.md`? Everything above assumes the former. If it is the latter, the deterministic layer has to move into prose procedures and the whole design changes shape. This is the single most consequential unknown remaining.
- **OQ-5 (Round-2 material):** if your Round-2 failure modes differ from this taxonomy, they should win — the brief frames Round 3 as encoding *that* reasoning.
