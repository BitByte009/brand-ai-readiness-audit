# Phase 1 — Challenge Analysis
**Adobe University Hackathon 2026 · Round 3 — Build the Agent Skill Marketplace**
Status: analysis only. No implementation started. Awaiting approval.

Label key:
- **REQUIRED** — stated explicitly in the handout. Non-negotiable.
- **IMPLIED** — a direct, defensible inference from the handout or the Round-2 appendix. Very likely graded, but not spelled out.
- **OPTIONAL** — our own addition. Differentiator or engineering hygiene. Cuttable under time pressure.

A standing rule for this project: anything not traceable to the handout gets labelled OPTIONAL and stays cuttable. We do not promote our own ideas to REQUIRED.

---

## 1. Requirements matrix

### 1.1 Package & format

| ID | Requirement | Label | Source | Satisfied by |
|---|---|---|---|---|
| R-01 | Submission is a single Agent Skill Marketplace: a zip of the marketplace root | REQUIRED | §1 | Build artifact `brand-ai-readiness-audit/` |
| R-02 | One or more skills, each in agentskills.io format: `SKILL.md` with YAML frontmatter + instructions, optional `scripts/` and `references/` | REQUIRED | §1 | Skill folder template |
| R-03 | Top-level `marketplace.json` listing every skill | REQUIRED | §1 Marketplace rules | Manifest + validator |
| R-04 | Exactly one skill marked `entrypoint: true` | REQUIRED | §1 | `audit-orchestrator` |
| R-05 | Every listed skill folder exists and independently satisfies the agentskills.io spec (name, description, …) | REQUIRED | §1 | `validate_marketplace.py` |
| R-06 | Entrypoint receives the audit request and emits the single final report | REQUIRED | §1 | Orchestrator contract |
| R-07 | Manifest is self-contained — no external service needed to resolve it | REQUIRED | §5 | No registry lookups, no remote skill refs |
| R-08 | Root `README.md` describing each skill and how the entrypoint composes them | REQUIRED | §6 Submission | Phase 13 |
| R-09 | Skills are portable / provider-neutral | REQUIRED | §5 | No Claude-only syntax; plain CLI scripts |
| R-10 | Each skill declares its tool needs (`allowed-tools`) | REQUIRED | §1 SKILL.md format, §5 | Frontmatter on every skill |
| R-11 | Keep `SKILL.md` lean; push checklists to `references/`, executable checks to `scripts/` | REQUIRED | §1 | Phase 7 discipline |
| R-12 | Sanity-check with `skills-ref validate ./skill-folder` where available | OPTIONAL (handout says "not required, just a convenience") | §1 | Run it anyway; also ship our own validator |
| R-13 | Decompose into multiple focused skills, one per concern | IMPLIED — explicitly *rewarded*, explicitly not *mandatory* ("a single skill is a floor, not the target") | §1, §4 | 6-skill architecture, §4 below |

### 1.2 Report contract

| ID | Requirement | Label | Source |
|---|---|---|---|
| R-20 | Report includes `site`, `audited_at`, counts-by-severity `summary`, `findings[]` | REQUIRED | §1 schema |
| R-21 | Every finding has `id`, `title`, `severity`, `evidence`, `suggested_action` | REQUIRED | §1 schema |
| R-22 | `suggested_action` carries at least a summary and a priority | REQUIRED (shape shown in the sample) | §1 schema |
| R-23 | Extra fields are permitted — the schema is a floor, not a ceiling | REQUIRED (permission) | §1 |
| R-24 | Findings carry evidence and a severity, and suggested actions say *what to change and how*, prioritized by impact | REQUIRED | §2 Report |
| R-25 | Suggested actions may go beyond detected problems — proactive improvements where no defect was found | REQUIRED (the handout states this twice, and it is a named rubric line) | §1, §2, §4 |
| R-26 | `audited_at` is ISO-8601 UTC (`…Z`) | IMPLIED from the sample value | §1 |
| R-27 | Severity vocabulary — sample shows `critical`/`high`/`medium` | IMPLIED. We standardise on `critical\|high\|medium\|low` and always emit all four counts plus `total_findings`, even at zero | §1 |
| R-28 | One report per audit, single emission point | REQUIRED | §1, §2 |

**Decision D-1:** coverage gaps and inconclusive checks do **not** go into `findings[]`. They go into a separate top-level `coverage` block. Reason: a grader may count severities or treat every array entry as an asserted defect; polluting `findings[]` with informational entries risks both the schema check and the false-positive score.

### 1.3 Detection scope

| ID | Requirement | Label | Source |
|---|---|---|---|
| R-30 | Detect off-site AI discoverability failures — why the brand isn't found or cited | REQUIRED | §2 |
| R-31 | Detect on-site engagement failures — why arriving visitors don't stay | REQUIRED | §2 |
| R-32 | Reason from how these systems actually work (Round-2 appendix mechanisms) | REQUIRED | §2 |
| R-33 | Derive the concrete checks ourselves — no checklist is provided | REQUIRED (this is the task) | §2 |
| R-34 | Evidence-backed, few misses, **few false positives** | REQUIRED — false positives are named in the rubric | §4 |
| R-35 | Fixes correctly targeted, mechanism-sound, prioritized | REQUIRED | §4 |
| R-36 | Report is actionable by a **non-expert** | REQUIRED | §4 Output design |
| R-37 | Works on unseen sites; pattern-based not example-fitted | REQUIRED | §3, §4, §6 |
| R-38 | Cover the three-gate chain: crawler let in → can read the page → can pick out the specific fact | IMPLIED from Appendix A — this is the spine of discoverability | Appendix A |
| R-39 | Cover raw-vs-rendered and non-textual fact lock-in | IMPLIED | Appendix C |
| R-40 | Cover cross-web corroboration and mistaken identity | IMPLIED | Appendix D |
| R-41 | Cover explicit-vs-implied fact statement ("quotability") | IMPLIED | Appendix B, C |
| R-42 | Treat AI-referred arrivals as a distinct audience with prior context and deep-link entry | IMPLIED from Appendix E + §2 engagement half | Appendix E |
| R-43 | Email-summarization behaviour (Appendix F) | OPTIONAL — F is about inbox summaries, not websites. We take only the transferable principle (substance must be readable text; filler dilutes it) into `D-EXTRACT-08`, and we do **not** build email checks | Appendix F |

### 1.4 Safety, scope, performance

| ID | Requirement | Label | Source |
|---|---|---|---|
| R-50 | Recommend-only. No skill ever alters a live site | REQUIRED — stated three times | §1, §2, §5 |
| R-51 | No destructive actions | REQUIRED | §1, §5 |
| R-52 | No authenticated-area actions | REQUIRED | §1, §5 |
| R-53 | No rate-abusing actions | REQUIRED | §5 |
| R-54 | Respect `robots.txt` | REQUIRED | §5 |
| R-55 | Everything runs read-only in a sandbox | REQUIRED | §5 |
| R-56 | Submission zip ≤ 50 MB, no pre-trained model weights | REQUIRED | §5 |
| R-57 | Audit runtime < 5 minutes on a standard machine for a typical website | REQUIRED | §5 |
| R-58 | Deterministic | REQUIRED — named in the rubric under engineering hygiene | §4 |
| R-59 | Minimal dependency surface | IMPLIED from portability + zip limit + "standard machine" | §5 |
| R-60 | Graceful degradation when an optional capability is unavailable (e.g. no headless browser) | OPTIONAL but strongly advised — a crash on the grader's machine zeroes every other criterion | — |

---

## 2. Rubric → implementation mapping

The handout is explicit that **the marketplace itself is graded, not any report it happens to produce**. That single sentence should drive most of our engineering: the artifact under evaluation is the instructions, checks, logic, and composition. A beautiful report from a vague skill scores badly; a legible, mechanism-sound skill scores well even on a site with few defects.

| Rubric criterion | What they said they want | What we build | Primary owner |
|---|---|---|---|
| **Detection accuracy** | Real problems, evidence-backed, both halves, few misses **and few false positives** | Failure taxonomy (§3) where every check has an applicability precondition, a deterministic detection test, and explicit FP guardrails; observation-ID binding so no finding can be asserted without a resolvable observation | all audit skills |
| **Suggested-action quality** | Correctly targeted, mechanism-sound, prioritized; beyond-problem suggestions relevant and non-obvious | Six-question recommendation contract (Phase 6) baked into the finding schema as `mechanism` / `impact` / `how_to_fix` / `validation`; separate proactive-opportunity generator keyed to entity and coverage gaps rather than to defects | evidence-prioritization + orchestrator |
| **Output design** | Clear, structured, actionable by a non-expert | Fixed JSON schema (superset of the required floor) + a rendered Markdown report with executive summary, prioritized fix plan, and plain-language "why this matters"; no jargon without a gloss | orchestrator |
| **Skill-format & engineering hygiene** | agentskills.io compliant, well-formed manifest, exactly one entrypoint, deterministic, safe | `validate_marketplace.py` in CI-style local run; frozen dependency list; fixed seeds/thresholds; robots-respecting fetcher with budget caps; read-only assertions | validator + shared lib |
| **Marketplace composition** | Genuine separation of concerns, clean composition, not padding | Six skills, each owning one *concern* (not one pipeline stage), each independently runnable and independently useful, communicating through a documented artifact contract | architecture §4 |
| **Generalization** | Works on unseen sites, tested by construction | Mechanism-based checks with no site-specific rules; local fixture corpus of 16 synthetic sites (Phase 9); an explicit "no hostname, brand, or vertical appears in any rule" lint | test harness |

Two rubric lines are easy to under-serve and worth deliberate over-investment: **few false positives** (most entrants will over-flag) and **beyond-problem suggestions** (most entrants will only report defects).

---

## 3. Failure-mode taxonomy

### 3.1 Taxonomy schema

Every entry in the catalog is defined with the twelve fields below. This is the shape; §3.3 gives the full catalog compactly and §3.4 works four entries end-to-end. The remaining entries get expanded to full form on Day 2.

| Field | Purpose |
|---|---|
| `id` / `category` | Stable identifier, e.g. `D-RENDER-02` |
| `meaning` | Plain-language statement of the defect |
| `mechanism` | *Why* it breaks an AI system, traced to a named Appendix mechanism |
| `applicability` | Preconditions under which the check runs at all — the primary false-positive control |
| `observable_signals` | What is literally visible in the collected observations |
| `detection_test` | Deterministic procedure + thresholds |
| `evidence_required` | Which observation IDs must be attached |
| `false_positive_rules` | Named conditions that suppress or downgrade the finding |
| `false_negative_risks` | Where the test is blind, and what we do about it |
| `severity` | Base severity + modifiers |
| `confidence` | How the confidence tier is derived |
| `recommendation` / `validation` | The fix, and how to verify it afterwards |

### 3.2 Categories

Discoverability follows the three gates of Appendix A, extended with two cross-cutting concerns:

- **D-CRAWL** — gate 1: can a machine reach the page at all?
- **D-RENDER** — gate 2: can a machine read what's on it?
- **D-EXTRACT** — gate 3: can a machine pull out the specific fact?
- **D-ENTITY** — can a machine tell *who this is* and not confuse it with something else? (Appendix D)
- **D-TRUST** — will a machine believe and repeat the claim? (Appendix B, D)

Engagement follows the arrival journey of an AI-referred visitor (Appendix E):

- **E-ORIENT** — do they know where they landed?
- **E-ANSWER** — does the page deliver the answer that brought them?
- **E-CONTINUE** — can they go further without starting over?

### 3.3 Catalog

Severity shown is the **base** before scope/confidence modifiers.

**D-CRAWL — reachability**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| D-CRAWL-01 | `robots.txt` disallows content paths | Parse robots, test sampled URLs against rules | critical | Disallowing `/cart`, `/search`, `/admin`, faceted params is correct practice — never flag |
| D-CRAWL-02 | AI crawler user-agents specifically blocked (GPTBot, ClaudeBot, PerplexityBot, CCBot, …) | UA-specific robots group match | high | **This may be a deliberate business decision.** Report neutrally as a discoverability *consequence*, never as an error; downgrade to medium and say so in the finding |
| D-CRAWL-03 | `noindex` / `X-Robots-Tag: noindex` on substantive pages | Meta + header parse | critical | Staging, tag/filter, thank-you, and print pages are legitimately noindexed |
| D-CRAWL-04 | Key pages return 4xx/5xx, or soft-404 (200 with "not found" body) | Status + body heuristic | high | Single transient 5xx — retry once before flagging |
| D-CRAWL-05 | Redirect chains ≥3 hops, loops, or http→https misconfiguration | Follow with hop count | medium | One canonical http→https→www hop is normal |
| D-CRAWL-06 | Canonical conflicts: cross-domain, pointing to 404/noindex, or contradicting the sitemap | Compare canonical target status | high | Cross-domain canonicals are legitimate on syndicated content |
| D-CRAWL-07 | No sitemap, or sitemap listing dead/redirecting URLs | Fetch `/sitemap.xml`, robots `Sitemap:` line, sample entries | medium | **Absence is not a defect on a small, fully-interlinked site** — only flag if orphan pages also exist |
| D-CRAWL-08 | Important pages orphaned (in sitemap, reachable by no internal link) | Link-graph reachability from home | medium | Utility/legal pages don't need link equity |
| D-CRAWL-09 | Bot-hostile serving: 403 to non-browser UA, JS/cookie interstitial, challenge page | Compare responses across UA strings (respectfully, ≤2 variants) | critical | Distinguish a genuine block from rate limiting we caused; back off and retry once |
| D-CRAWL-10 | Fetch cost so high a crawler is likely to time out | TTFB and transfer size percentiles across sampled pages | medium | Needs a stated threshold and ≥5 samples; never flag from one slow request |

**D-RENDER — readability**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| D-RENDER-01 | Primary content absent from raw HTML, present only after JS | Text-diff ratio raw vs rendered, on main-content region only | high | **Normal JS use is not a defect.** Only fires when the *substantive* text is missing, not when widgets, chat, or analytics are client-side |
| D-RENDER-02 | Specific key facts (price, hours, address, contact, spec) exist only post-render | Targeted fact presence in raw vs rendered | high | Fact must be one a user would plausibly ask an assistant for |
| D-RENDER-03 | Internal navigation exists only in JS — link graph invisible to a non-rendering fetch | Anchor count/targets raw vs rendered | high | Decorative or duplicate footer nav doesn't count |
| D-RENDER-04 | Content requires interaction (tabs, accordions) and is absent from the DOM until clicked | DOM presence pre-interaction | medium | Content present-but-hidden via CSS is readable — do **not** flag |
| D-RENDER-05 | Listings only load via infinite scroll / client-side pagination with no crawlable paged URLs | Look for `rel=next`, `?page=` equivalents | medium | Small collections fully present on first load are fine |

**D-EXTRACT — extractability**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| D-EXTRACT-01 | Key facts locked in images, PDFs, or video with no text equivalent | Fact-probe miss + image/PDF density + alt-text emptiness | high | Only when the fact is *unavailable* in text elsewhere on the page |
| D-EXTRACT-02 | Missing, empty, boilerplate, or duplicated `<title>` / meta description across pages | Uniqueness + presence across the crawl set | medium | Duplicates across genuine near-duplicate pages (paginated series) are expected |
| D-EXTRACT-03 | No structured data **where a supported type clearly applies and the fact is also ambiguous in prose** | Compound trigger: page type classified (product/article/org/local/FAQ/event) **AND** fact-probe failed | medium | **Never flag missing schema on its own.** Schema absence with clear, quotable prose is not a defect |
| D-EXTRACT-04 | Structured data present but invalid, incomplete on required properties, or contradicting the visible page | Parse JSON-LD/microdata, validate required props, cross-check values against DOM text | high | Optional-property gaps are not errors; vocabulary extensions are not errors |
| D-EXTRACT-05 | Heading structure doesn't reflect content: no `h1`, or headings used purely as styling | Outline extraction + text-block mapping | low–medium | Multiple `h1`s are valid HTML5 — only flag when the outline is genuinely unusable |
| D-EXTRACT-06 | **Low quotable-answer density** — no self-contained sentence a machine could lift as the answer | Fact-probe over machine-readable text only (see §5, Differentiator 1) | high | Requires the probe to fail on ≥2 canonical questions the page is clearly about |
| D-EXTRACT-07 | Key facts implied rather than stated (identity, offering, location asserted only by context or imagery) | Probe returns "cannot determine from text" | high | The fact must be one the page is *about* |
| D-EXTRACT-08 | Substance diluted: the answer exists but is buried under boilerplate/filler | Substance-to-boilerplate ratio + position of first substantive sentence | low | **Short pages are not a defect.** This is about ratio and ordering, never length |

**D-ENTITY — identity**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| D-ENTITY-01 | No canonical entity name stated consistently in text | Name candidates from title/h1/schema/footer; variance analysis | high | Legal-name vs trading-name variation is normal if one is dominant and they're linked |
| D-ENTITY-02 | Entity *type* never stated plainly ("what kind of thing is this?") | Probe: type from text alone | high | — |
| D-ENTITY-03 | Name collides with other known entities, with no distinguishing attribute on-site | Probe + ambiguity signal; only asserted if collision actually observed | medium | Do not speculate about collisions we haven't observed |
| D-ENTITY-04 | Name/description inconsistent across pages (differing descriptors, addresses, contact details) | Cross-page consistency of extracted entity facts | high | Different product pages describing different products is not inconsistency |
| D-ENTITY-05 | No machine-readable identity anchor: no `sameAs`, no linked official profiles, no `Organization` node | Structured data + outbound official-profile links | medium | Only when combined with an actual identity-clarity failure |
| D-ENTITY-06 | Primary offering unclear — marketing abstraction with no plain statement of what is sold or done | Probe: primary offering | high | Deliberate brand minimalism on a *homepage* is fine if the offering is plain one click away |

**D-TRUST — trust & freshness**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| D-TRUST-01 | Time-sensitive claims with no visible or machine-readable date | Claim classification + `datePublished`/`dateModified`/visible date presence | medium | Evergreen content does not need a date |
| D-TRUST-02 | Stale signals: past-dated "upcoming" content, expired offers, copyright year long past, dead announcements | Date extraction vs `audited_at` | medium | Historical/archival pages are legitimately old — check page intent first |
| D-TRUST-03 | Internal contradiction: two pages assert different values for the same fact | Cross-page fact table diff | high | Regional/variant pricing and multiple locations are not contradictions |
| D-TRUST-04 | Unattributed superlatives or statistics ("#1", "leading", "94% of customers") with no source | Pattern + citation proximity | low–medium | Ordinary marketing adjectives are not claims — restrict to *falsifiable* assertions |
| D-TRUST-05 | Key claim exists only on the brand's own site — no independent corroboration found | External check **actually executed**, method and query recorded | medium | **Never report corroboration status we did not verify.** If no external check ran, this check does not fire at all — it is logged as a coverage gap instead |
| D-TRUST-06 | Organizational opacity: no about, no contact, no named author on substantive content | Presence checks | medium | Personal blogs and single-purpose landing pages have different norms |

**E-ORIENT — orientation on arrival**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| E-ORIENT-01 | A deep page doesn't identify the brand or site it belongs to in its first screen of content | Brand token presence in early DOM order, not just in a logo image | high | A logo *with* alt text counts as identification |
| E-ORIENT-02 | No answer-first framing: the page never restates the question it answers | First-substantive-block analysis | medium | Not applicable to product/category/transactional pages |
| E-ORIENT-03 | No path context: no breadcrumb, no parent link, no indication of where this sits | Breadcrumb markup or textual equivalent | medium | Flat sites with ≤2 levels don't need breadcrumbs |
| E-ORIENT-04 | Deep/fragment links don't resolve to the referenced content | Fetch anchors, confirm target IDs exist | medium | Only if such links are actually published (sitemap/internal) |

**E-ANSWER — answer delivery**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| E-ANSWER-01 | Title/description promises something the body doesn't deliver | Title-vs-body semantic mismatch, LLM-judged with the text as evidence | medium | Requires a clear mismatch, not a stylistic one |
| E-ANSWER-02 | Entry-blocking interstitials: modal, newsletter overlay, or consent wall covering content on first paint | Rendered-DOM overlay detection at viewport | high | A compliant cookie banner that doesn't block content is not a defect. Legally-required consent walls are noted, not scolded |
| E-ANSWER-03 | The content an assistant could see and cite is gated for the human who follows the link | Compare non-JS/first-paint text with post-consent/gated state | high | Legitimate paywalls flagged only as a *citation-mismatch* risk, with the business context stated |

**E-CONTINUE — continuation**

| ID | Meaning | Detection | Base sev | Key FP guardrail |
|---|---|---|---|---|
| E-CONTINUE-01 | Deep page offers no next step: no related content, no contact, no action | Outgoing link classification | medium | A page whose job is complete (contact page) needs no onward step |
| E-CONTINUE-02 | Dead-end: no outgoing internal links at all beyond global nav | Link graph out-degree | medium | — |
| E-CONTINUE-03 | No route from a narrow answer to the broader topic hub | Hub/parent link presence | low–medium | Only where a hub demonstrably exists |
| E-CONTINUE-04 | Broken internal links from sampled deep pages | Status check on sampled internal links | medium | Rate-limit-aware; verify before asserting |
| E-CONTINUE-05 | Reading blocked by viewport/overflow failure | Missing viewport meta **and** measured horizontal overflow at 375px | low | **Never flag on aesthetics.** Two mechanical signals required, or it doesn't fire |

**Meta**

| ID | Meaning | Handling |
|---|---|---|
| X-COV-01 | A check could not run (robots-disallowed, render unavailable, timeout, blocked) | Recorded in the `coverage` block with the reason. Never a finding, never counted in severities |

### 3.4 Worked entries (full twelve-field form)

**D-RENDER-01 — Primary content is render-dependent**
- **Mechanism:** Appendix A gate 2 and Appendix C. A fetcher that does not execute JavaScript receives a shell. The page looks complete to a person and empty to the machine, so it cannot be read, and therefore cannot be quoted or cited.
- **Applicability:** page returned 200; page is content-bearing (not a redirect stub, login, or utility page); a rendered observation exists for it.
- **Observable signals:** main-region text length in raw HTML vs rendered DOM; ratio; whether extracted key facts appear in raw.
- **Detection test:** extract main content region from both raw and rendered using the same extractor. Fire when `raw_main_text_len / rendered_main_text_len < 0.30` **and** `rendered_main_text_len > 400 chars`. Sample ≥3 pages of the same template before generalising to a template-wide finding.
- **Evidence required:** `OBS-FETCH-{page}` (raw), `OBS-RENDER-{page}` (rendered), both character counts, the ratio, and a short excerpt of text present in rendered and absent in raw.
- **False-positive rules:** does not fire for client-side widgets, comments, recommendations, chat, or analytics; does not fire when the missing text is navigation chrome; does not fire on a single page if sibling pages of the same template pass; suppressed if the render observation is unavailable (becomes X-COV-01).
- **False-negative risks:** a site that server-renders the homepage but client-renders deep templates — mitigated by sampling across templates, not depth-1 only.
- **Severity:** high base; **critical** if the render-only content includes the entity's primary offering or the site's principal answer content; **medium** if only a secondary module is affected.
- **Confidence:** high when ≥3 same-template pages agree; medium on a single page.
- **Recommendation:** server-render or pre-render the main content region for the affected templates; if the framework supports it, emit the substantive text in the initial HTML payload and hydrate on top. Name the templates and the specific missing text.
- **Validation after fix:** re-fetch with JS disabled (`curl` equivalent); the named excerpt must appear in the raw response body, and the ratio must exceed 0.6.

**D-EXTRACT-03 — Missing structured data (compound trigger only)**
- **Mechanism:** Appendix B/C. Structured data is one way to make a fact unambiguous to a machine — but it is not the only way. The failure that matters is *the fact not being machine-extractable*, not the absence of markup.
- **Applicability:** page classified into a type with a well-supported schema.org mapping (Product, Article, Organization, LocalBusiness, FAQPage, Event) **and** the fact-probe failed to extract ≥1 canonical fact for that type from plain text.
- **Detection test:** both conditions true. If prose states the facts clearly, the check does not fire regardless of markup.
- **False-positive rules:** never fires on markup absence alone; never fires on page types with no clear mapping; never recommends schema types the content doesn't support.
- **Severity:** medium base; high when the page is commercially primary and multiple canonical facts are unextractable.
- **Confidence:** high — both conditions are deterministic.
- **Recommendation:** add the specific type with the specific properties whose facts failed the probe, **and** state the same facts in plain prose. Both, not either.
- **Validation:** re-run the fact probe on text alone (must now answer) and validate the JSON-LD parses with required properties present and matching the visible text.

**D-ENTITY-03 — Ambiguous entity, no distinguishing attribute**
- **Mechanism:** Appendix D, mistaken identity. When several things share a name and nothing distinguishes them, an assistant may attribute another entity's facts to this brand, or decline to cite it.
- **Applicability:** an entity name has been extracted; an external ambiguity check actually ran.
- **Detection test:** external lookup returns ≥2 distinct entities plausibly matching the name **and** the site's own text lacks distinguishing attributes (category + location/domain-of-operation + a unique identifier such as an official profile link).
- **Evidence required:** the extracted name, the observed competing entities with source URLs, and the on-site text searched for distinguishers.
- **False-positive rules:** never asserts a collision we did not observe; never fires on the basis of the LLM's prior belief that a name "sounds generic." If no external check ran, this becomes X-COV-01.
- **Severity:** medium base; high if the competing entity is in an adjacent category.
- **Recommendation:** state category, operating scope, and an identity anchor in plain text; add `Organization` with `sameAs` to authoritative profiles. Specify the exact sentence to add.
- **Validation:** the probe, given only the page text, returns a description that distinguishes the entity from each observed competitor.

**E-ORIENT-01 — Deep-link arrival without site identification**
- **Mechanism:** Appendix E. An AI-referred visitor arrives mid-site with no homepage context and no navigation history. If the first screen doesn't say whose page this is, the visitor cannot evaluate trust and leaves.
- **Applicability:** page is at depth ≥2 and is a plausible citation target (substantive content, indexable).
- **Detection test:** brand token absent from the first N DOM-order text nodes **and** absent from logo `alt`/`aria-label` **and** absent from the `<title>` suffix.
- **False-positive rules:** logo image with correct alt text passes; a brand-token match in any of the three positions passes; not applied to depth-1 pages.
- **Severity:** high when all three are absent; medium when only the visual/textual header is missing.
- **Recommendation:** put the brand name in the title suffix and in accessible header text; state in one line what the site is, adjacent to the H1.
- **Validation:** re-run with the page fetched cold; brand token present in ≥2 of the three positions.

---

## 4. Marketplace architecture

### 4.1 Assessment of the proposed structure

The six-skill layout you proposed is sound and I recommend keeping it, with one framing correction and one warning.

**Framing correction:** the rubric rewards separation of *concerns*, not separation of *pipeline stages*. `crawl-render-audit`, `entity-semantic-audit`, `trust-freshness-audit`, and `engagement-audit` are genuine concerns — each answers a different question, each is independently useful, each could be adopted alone by another marketplace. `evidence-prioritization` is the one at risk of reading as a stage rather than a concern. It survives if we define it as **scoring and prioritization policy** — the thing that owns the severity matrix, the confidence model, deduplication rules, and the rule that prevents everything becoming HIGH. That is a real, separable, and independently reusable concern with its own reference material. We should say so in its `SKILL.md` in one sentence so a grader doesn't have to infer it.

**Warning:** the orchestrator must not perform detection. The moment it starts running its own checks, the decomposition becomes cosmetic and the composition score suffers. Its job is scope, invocation, normalisation, validation, and emission — nothing else.

### 4.2 Layout

```
brand-ai-readiness-audit/          <- marketplace root (this is what we zip)
  marketplace.json                 <- manifest, exactly one entrypoint
  README.md                        <- Phase 13
  skills/
    audit-orchestrator/            <- ENTRYPOINT
      SKILL.md
      scripts/     run_audit.py, validate_report.py, render_report.py
      references/  report-schema.json, orchestration-rules.md, coverage-policy.md
    crawl-render-audit/
      SKILL.md
      scripts/     fetch.py, robots.py, crawl.py, render.py, raw_vs_rendered.py
      references/  crawl-checks.md, render-checks.md, fp-guardrails.md
    entity-semantic-audit/
      SKILL.md
      scripts/     extract_entity_facts.py, consistency.py
      references/  entity-checks.md, probe-questions.md
    trust-freshness-audit/
      SKILL.md
      scripts/     dates.py, claims.py, corroborate.py
      references/  trust-checks.md, corroboration-honesty.md
    engagement-audit/
      SKILL.md
      scripts/     orientation.py, continuation.py, interstitials.py
      references/  engagement-checks.md, ai-referral-persona.md
    evidence-prioritization/
      SKILL.md
      scripts/     score.py, dedupe.py
      references/  severity-matrix.md, confidence-model.md, dedupe-rules.md
  lib/                             <- shared, imported by skill scripts
    observations.py, http.py, budget.py, extract.py
```

**Open question OQ-1:** a shared `lib/` outside `skills/` keeps the code DRY but means skill folders are not individually portable, which brushes against R-09. Two options: (a) shared `lib/` with each `SKILL.md` declaring the dependency; (b) each skill vendors what it needs, accepting duplication. I lean (a) for maintainability across 10 days, but (b) is the safer read of "portable." **Needs your call.**

### 4.3 Data flow

```
URL
 └─> audit-orchestrator: scope, budget, robots preflight
      └─> crawl-render-audit: ONE crawl pass → OBSERVATION STORE (immutable JSON)
           ├─> entity-semantic-audit  ─┐
           ├─> trust-freshness-audit  ─┤ all read the same observations
           └─> engagement-audit       ─┘ (no re-crawling)
                └─> evidence-prioritization: normalize, dedupe, score, rank
                     └─> audit-orchestrator: proactive layer, schema validate, emit
```

**Decision D-2 — crawl once, analyse many.** The observation store is written exactly once by `crawl-render-audit` and is read-only thereafter. Three reasons: it is the only way to hit the <5-minute budget (R-57), it is the only honest way to claim non-rate-abusing behaviour (R-53), and it makes the audit reproducible from a cached store, which makes the test corpus deterministic (R-58).

**Decision D-3 — evidence binding.** Every observation gets a stable ID (`OBS-<type>-<hash>`). Every finding must cite ≥1 observation ID. The orchestrator's validator **rejects any finding whose evidence IDs do not resolve in the store**. This makes fabricated evidence structurally impossible rather than merely discouraged, and it is the single strongest false-positive control we have.

**Decision D-4 — the LLM never observes.** Deterministic scripts produce observations. The LLM interprets, diagnoses, classifies page intent, judges semantic mismatch, and writes recommendations. It is never the source of a fact about the site. This is the direct implementation of your "deterministic where possible" instruction, and it also makes the audit largely reproducible.

**Decision D-5 — severity is computed, not chosen.** `severity = f(mechanism_gate, scope, confidence, page_importance)` via a published matrix in `references/severity-matrix.md`, with a distribution guard: if >30% of findings land in high+critical, the scorer re-checks scope and importance modifiers and logs the recalibration. This directly answers "prevent every finding from becoming HIGH."

### 4.4 Budget allocation (R-57, target <5 min)

| Phase | Budget | Notes |
|---|---|---|
| Robots + preflight | 10 s | Fail fast on unreachable hosts |
| Raw crawl | 90 s | ≤30 pages, concurrency ≤4, per-request timeout 10 s, polite delay |
| Render sample | 90 s | 6–8 pages selected by template diversity, not depth order |
| External corroboration | 45 s | Hard-capped; skipped → X-COV-01, never faked |
| Analysis + scoring | 60 s | LLM reasoning over observations |
| Report + validation | 15 s | |

**Open question OQ-2:** headless rendering (Playwright/Chromium) is the heaviest dependency and cuts against R-59. Browsers aren't shipped in the zip so R-56 is safe, but if the grader's machine has no browser the audit must not crash. Proposal: render is a *capability*, detected at runtime; absent it, we run raw-only and every render-dependent check becomes X-COV-01 with an honest note. **Confirm you want the Playwright dependency at all** — the alternative is a lighter approximation (comparing raw HTML against text extracted from framework-hydration payloads), which is weaker but dependency-free.

---

## 5. Constraints, guardrails, and risks

### 5.1 Hard guardrails (REQUIRED)

- GET/HEAD only. No POST, no form submission, no state-changing requests. (R-50, R-51)
- No credentials, cookies-for-auth, or authenticated areas. If a page requires login, stop and record X-COV-01. (R-52)
- `robots.txt` fetched and parsed before any other request; disallowed paths are never fetched, even to prove a point. Crawl-delay honoured. (R-54)
- Concurrency ≤4, polite inter-request delay, exponential backoff on 429/503, global request cap. (R-53)
- Writes only to a sandboxed working directory; never to the target. (R-55)
- No pre-trained weights in the package; zip stays well under 50 MB. (R-56)

### 5.2 False-positive control (Phase 5, our biggest scoring lever)

Six mechanisms, in order of strength:

1. **Applicability preconditions** — every check declares when it *doesn't* apply, and that clause is evaluated first.
2. **Evidence binding** — unresolvable evidence ID means the finding is dropped by the validator (D-3).
3. **Compound triggers** — the checks most prone to over-firing (missing schema, JS usage, short pages) require two independent signals.
4. **Named suppressions** — the explicit "do not flag" list from your Phase 5: irrelevant absence, normal JavaScript, unnecessary schema, short pages, unusual visual design, LLM subjective opinion. Each appears verbatim in the relevant `references/fp-guardrails.md`.
5. **Confidence floor** — findings below the confidence threshold are demoted to the proactive-opportunities section rather than asserted as defects. This gives borderline observations somewhere honest to go instead of forcing a binary.
6. **Distribution guard** — the severity recalibration in D-5.

### 5.3 False-negative risks (and mitigations)

| Risk | Mitigation |
|---|---|
| Deep templates differ from sampled pages | Sample by template diversity (URL-shape clustering), not by depth |
| Render-only content missed when rendering is unavailable | Explicit coverage gap, never silent |
| Corroboration skipped under budget | Explicit coverage gap, never a "no problem found" |
| Site too small for statistical checks | Thresholds degrade to presence/absence, and we say confidence is lower |
| Non-English content | Detect language; language-dependent heuristics (claim patterns, filler detection) disable themselves and log a gap |
| Single-page apps where the whole site is one URL | Route-discovery from sitemap + rendered link graph; if neither, coverage gap |

### 5.4 Our own likely failure modes

| Risk | Mitigation |
|---|---|
| Skills become thin wrappers around one giant prompt | Every check must be traceable to a script + a taxonomy entry; a Day-9 lint that fails any `SKILL.md` asking the LLM to "assess the site" |
| Runtime blows past 5 minutes on a large site | Hard budget caps enforced in `lib/budget.py`, not in prose instructions |
| Report schema drifts as we add fields | `report-schema.json` is authoritative; validator runs on every test-corpus run from Day 4 |
| Over-engineering the taxonomy and shipping nothing | Day 6 freeze on new checks; Days 7–10 are integration, testing, and hardening only |
| Grader's environment lacks a dependency | Capability detection + graceful degradation (R-60) |
| We accidentally memorise our own fixtures | Lint forbidding hostnames/brands/verticals in any rule; half the corpus written on Day 8 by a different pass than the checks |

---

## 6. Likely competitor weaknesses

Judging from what the handout warns about (it warns about exactly the things people do wrong), the field will cluster around:

1. **One giant skill that is really one giant prompt.** The handout permits a single skill but rewards decomposition; most single-skill entries will also be non-deterministic and unevidenced. Both composition and hygiene suffer.
2. **A Lighthouse/SEO-audit clone.** Core Web Vitals, alt text, meta lengths. Technically fine, but it audits *search-engine* readiness circa 2015 and never engages with the citation mechanism the appendix describes. Detection accuracy against the *real* problem suffers.
3. **Everything is HIGH.** No severity model, so the report is unprioritised and Output design and Suggested-action quality both drop.
4. **Fabricated evidence.** The LLM writes plausible evidence strings ("crawled 12 pages, 0 had schema") without a crawl actually having happened. Detection accuracy collapses on unseen sites and this is exactly what "evidence-backed" is testing.
5. **Claimed corroboration.** Reporting that a claim "is not corroborated elsewhere on the web" without having looked. Your Phase 4 instruction anticipates this; most entrants won't.
6. **Engagement judged as visual design.** "The hero image is weak, the CTA should be orange." Unfalsifiable, unevidenced, and not what §2 asks for.
7. **Fit-to-examples.** Rules tuned to the handful of sites they field-researched. The handout says twice that grading is on unseen sites.
8. **Absence treated as defect.** Flagging missing sitemaps, missing schema, and missing FAQ markup on sites that don't need them. This is the most common false-positive class and it's a named rubric penalty.
9. **Padding the decomposition.** Eight skills that are really eight functions, with an orchestrator that does the actual work. The rubric names padding explicitly.
10. **Safety hand-waving.** "We respect robots.txt" in the README with no parser in the code.
11. **No runtime discipline.** Unbounded crawls that exceed 5 minutes on any real site.
12. **Proactive suggestions skipped entirely,** or reduced to generic advice ("blog more", "add FAQs"). A whole rubric line, cheaply won.

## 7. Differentiators

Ranked by expected scoring impact per unit of effort.

1. **The agent's-eye extraction probe.** For each sampled page we assemble the *machine-readable text only* — what a non-rendering fetcher would receive — and run a fixed set of canonical questions against it: what is this entity, what does it offer, where does it operate, what does this page answer, what does it cost, when was it updated, how do I contact it. A question the probe cannot answer from text alone is a discoverability defect **with its own evidence attached** — the exact text that was available and the answer that couldn't be formed. This is a direct mechanical simulation of Appendix B and C, it generalises to any site in any vertical because it contains no site-specific knowledge, and it produces evidence a non-expert immediately understands. It also drives D-EXTRACT-03, -06, -07 and D-ENTITY-02, -06, which means one mechanism underwrites six checks.
2. **Two-lens auditing.** Every page is examined through the machine lens (raw fetch) and the human-arrival lens (rendered, cold, deep-link entry, no referrer, no session). Discoverability findings come from lens one; engagement findings from lens two. The gap between the lenses *is* the audit. This gives the two halves of the problem a shared mechanical foundation rather than treating engagement as a soft afterthought.
3. **Evidence binding with a rejecting validator (D-3).** Fabrication becomes structurally impossible, not just discouraged.
4. **Applicability preconditions on every check.** The check declares when it should stay silent before it declares how it fires. Directly targets the field's dominant weakness.
5. **Honest coverage reporting.** A `coverage` block naming every check that ran, every check that didn't, and why. Most entrants will present partial audits as complete ones. This costs little and signals engineering maturity, and it is the mechanism that keeps us from ever faking corroboration.
6. **Computed severity with a published matrix and a distribution guard (D-5).**
7. **Proactive-opportunity generator keyed to gaps rather than defects.** Derived from what the probe *couldn't* ask (facts the site never addresses), entity anchors it doesn't have, and corroboration surface it doesn't occupy. Non-obvious by construction, because it comes from absence rather than from error.
8. **Offline fixture corpus.** 16 synthetic sites served from local files covering the Phase 9 matrix. Deterministic, network-free, fast enough to run on every change, and it makes the generalization claim testable rather than asserted.
9. **Validation-after-fix on every recommendation.** A one-line reproducible check the site owner can run. Turns recommendations into something a non-expert can close the loop on — Output design and Suggested-action quality in one field.

---

## 8. Generalization requirements

Non-negotiable rules for every rule we write:

- No hostname, brand name, vertical, CMS, or framework name may appear in any detection rule. Framework detection may appear in *recommendations* only ("if you are on Next.js, this is the specific config"), never in triggers.
- Every check keys off a **mechanism** (a broken gate in the reach→read→extract chain, or a broken stage in the arrival journey), not a **pattern** (a specific markup shape).
- Every threshold is justified in the reference file with the reasoning behind the number, and is expressed as a ratio or percentile where possible so it scales from a 5-page site to a 5,000-page one.
- Page *importance* is derived structurally (link centrality, sitemap priority, depth, template frequency), never from a hardcoded list of path names.
- Page *type* is classified from content, never from URL patterns alone.
- Small-site degradation is a first-class path: when N is too small for a distribution check, the check switches to presence/absence and lowers its confidence rather than staying silent or over-firing.

---

## 9. Ten-day execution plan

Your day allocation is right. Below it is with concrete deliverables and an exit criterion per day — a day doesn't close until its criterion passes.

| Day | Deliverable | Exit criterion |
|---|---|---|
| 1 | This analysis + `PROJECT_CONTEXT.md` seeded | You approve the architecture and the two open questions are closed |
| 2 | Full 12-field taxonomy for all ~40 checks in `references/` | Every check has an applicability precondition and ≥1 named FP rule. No exceptions |
| 3 | `report-schema.json`, observation schema, `marketplace.json`, six `SKILL.md` skeletons, severity matrix | `validate_marketplace.py` passes on empty skills; schema validates the handout's own sample report |
| 4 | `lib/` + deterministic collectors: robots, fetch, crawl, render, extract, structured data, links, dates | One real site produces a complete observation store inside budget, with robots respected |
| 5 | The four audit skills producing findings from observations | Every finding carries resolvable evidence IDs; validator rejects a deliberately fabricated one |
| 6 | `evidence-prioritization` + orchestrator composition. **Feature freeze on new checks.** | End-to-end run on 3 real sites emits a schema-valid report under 5 min |
| 7 | Proactive layer, Markdown rendering, recommendation contract, validation steps | A non-expert reader can act on the top 5 findings without asking a question |
| 8 | 16-fixture corpus + harness tracking the seven metrics | FP rate and FN rate measured and recorded, not estimated |
| 9 | Red team pass 1 and 2: RISK → WHY → RUBRIC IMPACT → FIX, then implement | Every critical and high risk closed or explicitly accepted in writing |
| 10 | Final validation, README, `PROJECT_CONTEXT.md`, package | Full checklist in Phase 11 green; clean-machine run succeeds; zip built |

Slack: Day 7 and Day 9 are the compressible ones. If we slip, the corpus shrinks from 16 fixtures to 10 (keeping both-weak, both-strong, JS-heavy, ambiguous-entity, irrelevant-absence, and deep-page-no-orientation) before anything else is cut.

---

## 10. Open questions for you

1. **OQ-1 — shared `lib/` vs vendored per skill.** Portability (R-09) vs maintainability. My lean: shared `lib/`, dependency declared in each `SKILL.md`.
2. **OQ-2 — headless browser dependency.** Playwright gives us the render lens and roughly a third of the discoverability catalog. It's also the one heavy dependency. My lean: include it, detect at runtime, degrade gracefully.
3. **OQ-3 — external corroboration.** D-TRUST-05 and D-ENTITY-03 need outbound search. Do we have a search capability we can rely on in the grading environment? If not, both checks become permanent coverage gaps and we should design for that now rather than discovering it on Day 9.
4. **OQ-4 — target invocation environment.** Are we assuming the grader runs this inside an agent with shell access to `scripts/`, or that a model reads `SKILL.md` and improvises? It changes how much logic lives in code vs instructions. The handout implies the former ("if you have Python/npm available") but doesn't commit.
5. **OQ-5 — Round-2 material.** You mention Round-2 concepts. If you have your own Round-2 submission, its failure modes should feed the taxonomy directly — the handout says Round 3 is encoding *that* reasoning.

Nothing gets implemented until you sign off on §4 and close OQ-1 through OQ-4.
