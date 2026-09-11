# KNOWLEDGE.md — Master Engineering Study Guide

> For a human engineer who did not write this code and intends to study it, then
> change it. This document covers everything **outside** individual skill detail;
> each skill has its own `KNOWLEDGE.md` with per-check depth.
>
> **Source-of-truth rule used throughout:** claims here were checked against
> executable code first, then schemas, then tests, then references. Where the
> implementation and the documentation disagree, the discrepancy is named rather
> than reconciled.

| Document | Covers |
|---|---|
| this file | architecture, shared library, safety, testing, history, where to start |
| `skills/audit-orchestrator/KNOWLEDGE.md` | the entire orchestration layer, execution order, a full audit walkthrough |
| `skills/crawl-render-audit/KNOWLEDGE.md` | 28 checks: reach / read / extract |
| `skills/entity-semantic-audit/KNOWLEDGE.md` | 6 checks + the entity profile |
| `skills/trust-freshness-audit/KNOWLEDGE.md` | 6 checks + the claim table |
| `skills/engagement-audit/KNOWLEDGE.md` | 11 checks: orient / answer / continue |
| `skills/evidence-prioritization/KNOWLEDGE.md` | normalize, dedupe, score, rank (no check IDs) |

---

## 1. PROJECT PURPOSE

An **Agent Skills marketplace** that audits a public website for two things:

1. **AI discoverability** — can an AI system reach, read, extract from, identify
   and trust this site well enough to cite it?
2. **AI-referred engagement** — when a person arrives from an AI answer, on a deep
   page, with no homepage context, can they orient, get their answer and continue?

It emits one evidence-backed, prioritized, schema-valid report. It is
**read-only**: it recommends, and never modifies a live site.

The requirements source available in this repository is
`design-docs/PHASE1-ANALYSIS.md`, a labelled transcription of the challenge
handout with `REQUIRED`/`IMPLIED`/`OPTIONAL` tags and section references. **The
official PDF is not present on this machine**, so a handful of requirements
(exact schema floor, size/runtime limits, severity vocabulary) cannot be verified
against the original — they are listed in the repository's own compliance notes.

---

## 2. PRODUCT MENTAL MODEL

```
                 ┌─────────────────────────────────────────┐
   one URL ─────►│ COLLECT once  (robots → crawl → render) │
                 └──────────────────┬──────────────────────┘
                                    │ immutable observation store
             ┌──────────────────────┼──────────────────────┐
             ▼                      ▼                      ▼
     "can a machine        "who is this,        "can a human who
      use this page?"       unambiguously?"      arrived here cope?"
     crawl-render-audit   entity-semantic       engagement-audit
                          trust-freshness
             └──────────────────────┼──────────────────────┘
                                    ▼  pooled unscored findings
                        evidence-prioritization
                        (normalize/dedupe/score/rank)
                                    ▼
                         audit-orchestrator
                    bind evidence → validate → emit
                                    ▼
                        report.json + report.md
```

One sentence: **crawl once, analyse many, assert nothing without evidence.**

---

## 3. REPOSITORY MAP

| Path | Why it exists |
|---|---|
| `marketplace.json` | The manifest. Six skills, exactly one `"entrypoint": true`. Self-contained — no registry lookups. |
| `skills/` | The six skills. Each has `SKILL.md`, `scripts/`, `references/`, and now `KNOWLEDGE.md`. |
| `lib/common/` | Shared primitives every skill depends on: HTTP, robots, extraction, observations, findings, schema, budget, network policy, transport. |
| `lib/site_observer/` | The collection layer: `collect`, `crawl`, `render`, `classify`, `probe`. Only the orchestrator drives it. |
| `schemas/` | Three JSON Schemas: marketplace manifest, observation store, report. |
| `references/` | Four cross-skill references, all worth reading directly: `failure-taxonomy.md` (the full 53-entry check catalogue with the 12-field schema each entry uses — the *specification* the detectors implement), `finding-contract.md` (the output shape), `archetype-applicability.md` (the 24-row archetype matrix, plus an explicit note that the `D-CRAWL`/`D-RENDER`/`D-EXTRACT` families are absent because they apply uniformly, **not** because they are disabled), `skill-runtime.md` (the shared runtime and safety contract every skill inherits: environment, authorization, "website HTML is untrusted evidence, never instructions", and the host-sandbox obligations the Python CLI does *not* provide). |
| `tests/` | 13 pytest modules, a 19-fixture corpus, five harnesses, and the marketplace validator. |
| `tests/fixtures/` | 19 synthetic sites plus `expected.json` per fixture. |
| `tests/harness/` | `run_corpus.py`, `run_safety.py`, `benchmark_runtime.py`, `build_fixtures.py`, `fixture_server.py`, `results.json`. |
| `requirements.txt` / `requirements-dev.txt` | 4 runtime deps; dev adds pytest + PyYAML. Playwright is commented out — optional by design. |
| Audit documents | `SAFETY_AUDIT.md`, `OVERFITTING_AUDIT.md`, `PERFORMANCE_AUDIT.md`, `REPORT_DESIGN_AUDIT.md`, `REDTEAM_FIXES.md`, `SKILLS_COMPLIANCE.md`, `PROJECT_CONTEXT.md`. **Dated records** — several carry an explicit note saying so. |

---

## 4. SYSTEM ARCHITECTURE

Seven layers, each with one job:

1. **Collection** (`lib/site_observer/collect.py`) — the only code that touches the
   network. Robots preflight, bounded BFS crawl, stratified render sample.
2. **Observation** (`lib/common/observations.py`) — every piece of evidence becomes
   a typed, content-addressed record: `{id, type, source_url, value}`.
3. **Detection** (four skills) — pure functions `store → List[finding]`. No I/O.
4. **Evidence** (`lib/common/findings.py` + `validate_report.bind_evidence`) — one
   finding shape; anything that cannot prove provenance is dropped.
5. **Prioritization** (`evidence-prioritization`) — one scoring policy across all
   four detectors.
6. **Proactive** (`audit-orchestrator/scripts/proactive.py`) — opportunities built
   from *health*, structurally separated from findings.
7. **Reporting** (`render_report.py` + `lib/common/schema.py`) — schema
   enforcement, then a Markdown rendering that escapes and bounds site content.

---

## 5. DATA FLOW — URL to JSON

```
URL string
 └► _normalize_url            add scheme if missing; path untouched
 └► RequestPolicy             GET/HEAD, same-origin, robots, ≥0.2s, ≤200 req
 └► fetch_robots              → ROBOTS observation
 └► crawl                     canonical_resource_url identity, ≤30 pages
      └► fetch_url            → HTTP_FETCH observation {status, headers, html…}
 └► stratified_sample         cluster-diverse selection, ≤8
      └► render_page          → RENDER observation {status, html…}
 └► store {store_version, collected_at, target, capabilities, archetype, observations[]}
      ├► build_entity_profile → entity_profile
      ├► detect_crawl / render / extract / entity / trust / engagement
      │                       → pooled findings (unscored, no ids)
      └► prioritize_findings  → findings / demoted / rejected / logs
           └► bind_evidence   → kept, dropped
                └► proactive  → opportunities
                     └► report dict → validate_report() → report.json + report.md
```

---

## 6. SHARED LIBRARY

### `lib/common/http_client.py`
**Purpose:** the only outbound HTTP path.
**Key functions:** `request_once`, `fetch_url`, `html_encoding`, `resolve_redirect_chain`.
**Constants:** `AUDIT_USER_AGENT` (one honest, self-identifying UA, never spoofed —
`crawl-render-audit`'s bot-hostility check depends on it being the only identity
the site ever sees), `MAX_RESPONSE_BYTES = 2 MiB`, `_META_SCAN_BYTES = 2048`.
**Algorithms:** `request_once` disables `trust_env`, refuses redirects, refuses
compressed responses (rather than decompressing an expansion bomb), reads with
`read1` against a wall-clock deadline, and caps the body.
`html_encoding` resolves charset the way a browser does — transport charset → BOM
→ `<meta charset>` → UTF-8 if the bytes decode → Latin-1.
**Risks:** connect/read timeouts are not absolute response deadlines.

### `lib/common/network_policy.py`
**Purpose:** the per-audit request boundary.
**Key symbols:** `RequestPolicy`, `unsafe_target`, `origin`,
`MAX_REQUESTS_PER_AUDIT = 200`, and three vocabularies —
`ACTION_OR_AUTHENTICATED_SEGMENTS`, `CREDENTIAL_QUERY_KEYS`, `ACTION_QUERY_KEYS`,
`VERB_QUERY_KEYS`.
**Contract:** `admit(url, method, preflight=False)` returns a bool and records a
reason in `policy.blocked` on refusal. Refusal reasons: `unsafe_method`,
`cross_origin`, `unsafe_or_authenticated_target`, `invalid_robots_preflight`,
`request_budget_or_backoff`, `robots_disallowed_or_unknown`, `stage_time_budget`,
`invalid_or_credentialed_url`.
**Risk:** exclusions are pattern-based; arbitrary server-side GET effects remain
outside any crawler's control, and the module docstring says so.

### `lib/common/public_transport.py`
**Purpose:** SSRF prevention. Pins each socket to a **validated public address**
so a hostname is not resolved a second time at connect (DNS rebinding).
**Key:** `public_address`, `PublicOnlyAdapter`, `PublicHTTP(S)Connection`.
**Contract:** any non-global, multicast or scoped address raises `OSError`. A
**mixed** public/private DNS answer fails closed. TLS hostname verification is
unaffected because only the socket target is pinned, not `conn.host`.

### `lib/common/robots.py`
**Key:** `parse_robots`, `robots_allows`, `robots_allows_every_interpretation`,
`path_interpretations`, `is_disallow_all`, `fetch_robots`,
`AUDIT_PRODUCT_TOKEN`, `MAX_DECODE_ROUNDS = 3`.
**Two evaluators on purpose:** `robots_allows` is the literal longest-match
evaluator used for the *audit judgement* (`D-CRAWL-01`).
`robots_allows_every_interpretation` is the **fail-closed** evaluator used for
every *fetch decision* — it tests the literal path plus slash-collapsed and
percent-decoded readings, and refuses if any is disallowed.
**Risk:** user-agent group matching is exact-token, not prefix.

### `lib/common/extract.py`
**Purpose:** all deterministic HTML extraction.
**Key:** `extract_metadata`, `extract_canonical_url`, `extract_jsonld`,
`flatten_jsonld`, `normalize_schema_type`, `schema_type_matches`, `extract_links`,
`extract_text`, `page_inventory`, `compare_raw_vs_rendered`, `heading_sections`,
`text_weight`, `significant_words`, `containment_ratio`, `title_segments`,
`url_depth`, `parse_cache` / `with_parse_cache`.
**Algorithms worth knowing:**
- `_soup` uses **`html.parser`** (stdlib) — never `lxml`, so no external entity
  resolution is possible. `parse_cache` is an audit-local LRU of read-only trees
  bounded by `max_chars`/`max_entries`; `PERFORMANCE_AUDIT.md` records it cutting
  parses from 1,290 to 358.
- `significant_words` tokenizes with `[^\W_]+` (Unicode-aware) and approximates
  spaceless scripts (CJK) with **character bigrams**. ASCII output is byte-identical
  to the ASCII-only version it replaced.
- `text_weight` charges spaceless runs at one word per three characters so
  word-count thresholds are reachable in Japanese/Chinese; spaced text scores
  exactly as `len(text.split())`.
**Risk:** CJK bigrams are an approximation, not segmentation.

### `lib/common/observations.py`
`make_observation(type, source_url, value)` builds `{id, type, source_url, value}`.
**The id includes type + source_url + payload** — payload alone would give two
identical templated pages the same id and destroy independently resolvable
evidence. Accessors: `iter_type`, `single`, `http_fetches`, `renders`,
`page_classifications`, `probes`.

### `lib/common/pages.py` (19 lines)
`effective_pages(store)` — the render-preferred page selection used by
`entity-semantic-audit`, `trust-freshness-audit` and `engagement-audit`. Returns
`{url: {html, observation_id, headers, rendered}}`, choosing a `RENDER` only when
it is `ok`, 2xx and non-empty. **Headers always come from the fetch**, because a
render has no HTTP headers of its own.

### `lib/common/findings.py`
`make_finding(...)` — the single definition of the unscored finding shape.
`affected_block(urls, total_in_scope=None)` → `{count, sample_urls[≤5], total_in_scope}`.
`total_in_scope` stays `None` when unmeasured; consumers must not manufacture
sitewide scope from a sample.

### `lib/common/schema.py`
`load_schema` (cached), `validate_document`, `validate_report`,
`validate_observation`, and a registered `date-time` format checker.
`validate_report` adds eight invariants beyond JSON Schema — see orchestrator
KNOWLEDGE §17.

### `lib/common/budget.py`
`Budget` + `DEFAULT_BUDGET`. **Every limit is a check, never a raise** — budget
exhaustion is a normal outcome that must degrade to coverage, not crash.

### `lib/site_observer/`
`collect.py` (the lifecycle), `crawl.py` (`canonical_resource_url`,
`template_shape`, `crawl`, `stratified_sample`, `registrable_host`), `render.py`
(`reuse_browser`, `_browser_instance`, `detect_capability`, `render_page`),
`classify.py` (`classify_archetype` — one label from 8 `ARCHETYPES` using JSON-LD
types and path signals), `probe.py` (**always unavailable by construction**).

---

## 7. SCHEMAS

| Schema | Producer → Consumer | Required | Notes |
|---|---|---|---|
| `marketplace.schema.json` | `marketplace.json` → `tests/validate_marketplace.py` | `name, version, description, skills` | Local strict gate; `--official` runs `skills-ref` and **fails** rather than skipping if absent |
| `observation.schema.json` | `collect()` → `lib/common/schema.validate_observation` | `store_version, collected_at, target, observations` | Defines the store contract the detectors read |
| `report.schema.json` | `run_audit` → `validate_report` → `render_report` | `site, audited_at, summary, findings` | `$defs`: `text` (`pattern: "\\S"`), `finding`, `proactive_opportunity` |

The `finding` def requires `id, title, severity, evidence, suggested_action`;
`suggested_action` requires `summary, priority`. The `proactive_opportunity` def
requires `source, title, evidence, why_it_matters, suggested_action, validation,
confidence` — so an ungrounded opportunity fails validation rather than reaching
the report.

---

## 8. CROSS-SKILL SHARED CONCEPTS

- **Observation** — a typed, content-addressed evidence record. Only three types
  are ever produced: `ROBOTS`, `HTTP_FETCH`, `RENDER`.
- **Evidence** — a human-readable string containing *actual observed values*, plus
  `observation_ids` and `source_urls`.
- **Absence finding** — a finding whose signal is that something is missing. It
  legitimately has empty `observation_ids` and binds via known `source_urls`.
- **Finding ID** — `F-001…` assigned by prioritization; demoted get `D-…`.
  Detectors never assign IDs.
- **Severity** — `critical|high|medium|low`. Detectors propose a *base*;
  prioritization computes the final. Only four checks may reach `critical`.
- **Confidence** — `high|medium|low`, describing strength of evidence, **not** a
  probability. `low` is demoted out of `findings[]` entirely.
- **Scope** — `affected {count, sample_urls, total_in_scope}`. `None` total means
  unmeasured and is never treated as sitewide.
- **Template cluster** — URL-shape grouping so one templated defect is one finding.
- **Mechanism / impact / how_to_fix / validation** — the four-part recommendation
  contract from `references/finding-contract.md`.
- **Coverage** — `X-COV-01` bookkeeping rows recording work that could not be done.
- **Proactive opportunity** — the site is healthy on this point and there is still
  a specific improvement. Never counted in severity totals.
- **Deduplication** — four distinct mechanisms; see orchestrator KNOWLEDGE §16.

---

## 9. SAFETY MODEL

Full detail in `SAFETY_AUDIT.md`. The code paths:

| Threat | Mechanism | Where |
|---|---|---|
| **SSRF / private addresses** | every socket pinned to a validated **public** address; no second resolution at connect; mixed answers fail closed | `public_transport.public_address`, `PublicOnlyAdapter` |
| **Destructive / state-changing GET** | `unsafe_target` rejects cart/checkout/account/admin/login/signup/edit/create/update/delete path **segments**, credential query keys, action query keys, and verb params with non-read values | `network_policy.unsafe_target` |
| **Authenticated areas** | same vocabularies + `origin()` rejecting `user:pass@` URLs | `network_policy` |
| **Writes to the site** | only `GET`/`HEAD` admitted; browser routes abort every other method; forms are never submitted | `RequestPolicy.admit`, `render.route_request` |
| **Rate abuse** | ≥0.2s pacing (clamped), `Crawl-delay` honoured, ≤200 requests/audit, immediate stop on 429/503 | `RequestPolicy` |
| **robots.txt** | fail-closed: unknown/error/unparseable ⇒ no crawling. Fetch decisions use `robots_allows_every_interpretation` so `//private` and `/%2Fprivate` cannot evade a `Disallow: /private` | `robots.py`, `RequestPolicy.admit` |
| **Malicious content** | 2 MiB cap, compression refused, wall-clock deadline on trickling reads, `html.parser` (no external entities), JSON-LD via `json.loads` with `RecursionError` caught | `http_client`, `extract` |
| **Unsafe rendering** | `chromium_sandbox=True`, `service_workers="block"`, `accept_downloads=False`, resource-type allowlist, secondary navigation blocked, `Set-Cookie`/`Refresh` stripped, and `Worker`/`SharedWorker`/`ServiceWorker`/`RTCPeerConnection`/`WebTransport`/`EventSource`/`sendBeacon` neutered — `WebTransport` in particular opens a QUIC channel page routes never see | `render._render_with_playwright` |
| **Prompt injection via the report** | escaping of HTML/Markdown/terminal/bidi controls, a 400-char cap applied to the *escaped* form, and an explicit untrusted-content notice | `render_report._text`, `UNTRUSTED_CONTENT_NOTICE` |

**No private-address bypass exists in production.** `grep` for
`127.0.0.1|localhost|is_private|bypass` across `lib/` and `skills/` returns
nothing; the loopback resolver is injected only by test harnesses, from outside.

---

## 10. CRAWLING AND RENDERING

- **HTTP client** — anonymous, no cookies, no proxy inheritance, one hop at a time,
  each redirect re-authorized (max 10, loop-detected).
- **URL normalization** — `canonical_resource_url` lowercases scheme/host, drops the
  default port and fragment, and collapses a trailing directory-index filename.
  Deliberately **not** normalized: query strings, and trailing slashes on
  non-index paths.
- **Frontier** — same-host BFS, `max_frontier = max_pages * 6` (180 by default).
- **Caps** — 30 pages, 8 renders, 200 requests, 90s crawl / 90s render stages.
- **Chromium lifecycle** — one process per collection pass via `reuse_browser`;
  a fresh context per page; verified no process leak.
- **Timeouts** — per-request `raw_crawl_timeout_s`, render `min(15s, time_left)`.
- **Failures** — a fetch error becomes an evidence record with
  `evidence.coverage_gap`; a render failure becomes `RENDER_FAILED` coverage.
- **Graceful degradation** — no Playwright ⇒ `RENDERER_UNAVAILABLE`, the
  `D-RENDER` family and `E-ANSWER-02/03/04` produce nothing, and the report is
  still schema-valid.

**Known breadth limitation:** a page with many faceted query links can crowd the
frontier. Measured on a stress fixture: 29 of 30 fetched pages were
`?facet=N` variants. `PERFORMANCE_AUDIT.md` names this.

---

## 11. TESTING ARCHITECTURE

| Layer | What it is | What it proves | What it cannot prove |
|---|---|---|---|
| **Unit tests** (13 modules) | hand-built stores, direct function calls | per-check fire/suppress logic | that anything is *wired* — this is exactly how the detector-wiring bug survived 63 passing tests |
| **Fixture corpus** (`run_corpus.py`) | 19 synthetic sites over a loopback HTTP server, real `run_audit()` | end-to-end wiring, FP/FN against authored expectations, evidence/recommendation/severity gates | real-world accuracy |
| **Safety harness** (`run_safety.py`) | 9 scenarios against **real Chromium** | that the browser boundary holds under actual JS | non-browser threats |
| **Offline safety tests** (`test_safety.py`) | injected transport, no sockets | SSRF, robots evasion, oversized/compressed/trickling responses, action URLs | live-network behaviour |
| **Performance harness** (`benchmark_runtime.py`) | CPU-only and loopback-browser, with cProfile | parse counts, request counts, render counts | wall-clock across machines |
| **Marketplace validator** (`validate_marketplace.py`) | 248 lines, offline | manifest, frontmatter, resource links, composition, schemas, size | official `skills-ref` conformance unless `--official` |
| **Corpus gate** (`test_corpus_gate.py`) | tests the gate itself | that measured FP/FN/guardrail/coverage/skill/schema failures exit non-zero | — |

**A property worth internalizing:** the unit tests and the corpus protect against
*different* failures. The corpus exists because unit tests cannot catch
orchestration gaps; the unit tests exist because the corpus cannot isolate a
single check's guardrail.

---

## 12. FIXTURE CORPUS

- **19 fixtures**, each `tests/fixtures/<name>/` with a `site/` directory and an
  `expected.json`.
- **Generated** by `tests/harness/build_fixtures.py` (1292 lines) — the source of
  truth for fixture content *and* for the `expected.json` notes. Editing an
  `expected.json` without editing the builder means a regeneration silently
  reverts it.
- **Served** by `fixture_server.py`, which deliberately strips `Last-Modified` and
  `ETag` so fixture results are driven by authored content rather than filesystem
  mtimes (which would otherwise suppress freshness checks sitewide).
- **`expected.json` keys:** `description`, `notes`, `expected_findings`,
  `expected_non_findings`, `expected_coverage`, plus honesty keys —
  `confirmed_false_negative`, `resolved_false_negative`, `structurally_untestable`,
  `expected_false_negative`, `notes_on_own_authoring`.

**What the corpus proves:** that the implementation still does what it was built
to do, end to end, through the real entrypoint.

**What it does NOT prove — state this plainly to anyone who asks:** the fixtures
and their expectations were authored in this repository alongside the code. A
29/29 result with no false positives measures **self-consistency**, not real-world
accuracy. Every fixture is English and ASCII, so the corpus is silent on other
languages and scripts — and indeed a whole class of cross-script false positives
existed while the corpus was green. It is a **regression gate**. The README states
this in the same terms.

**Corpus requires Chromium.** Without it: 28/29 with 1 FP / 2 FN and a non-zero
exit, because three fixtures exercise render-dependent checks. This is deliberately
*not* special-cased away — a gate that passes by ignoring its own missing
capability is worth nothing.

---

## 13. REPORT FORMAT

`report.json` top level: `site`, `audited_at`, `summary`, `findings`, `scope`,
`coverage`, `proactive_opportunities`, `demoted`, `run`.

`run` carries: `capabilities`, `budget`, `skill_failures`,
`evidence_binding_drops`, `merge_log`, `calibration_log`, `rejected_findings`,
`schema_valid` (and `schema_errors` when invalid).

`report.md` is produced by `render_report.render_markdown`: summary, an untrusted
content notice, findings grouped by severity, a coverage section, and a proactive
section prefaced by `OPPORTUNITY_DEFINITION` — which states in the document itself
that opportunities are not defects and are not counted in the totals.

---

## 14. PACKAGE / INSTALLATION MODEL

- **4 runtime dependencies:** `requests`, `urllib3<3`, `beautifulsoup4`,
  `jsonschema`. All four are genuinely imported by shipped code.
- **Dev:** `pytest`, `PyYAML` (frontmatter validation only). Neither is imported by
  product code.
- **Playwright is optional and commented out** in `requirements.txt`. Every
  `playwright` import in `lib/site_observer/render.py` is **function-scoped** —
  zero module-level imports — which is what makes optionality real rather than
  claimed.
- **No install step.** `run_audit.py` bootstraps `sys.path` from
  `Path(__file__).resolve().parents[2]`. There are no absolute developer paths
  anywhere in the package.
- **Verified from a fresh extraction:** validator passes, 718 tests pass, and the
  entrypoint runs — all without Playwright installed.

---

## 15. DESIGN DECISIONS

| Decision | Alternatives | Why | Tradeoff |
|---|---|---|---|
| **Crawl once, analyse many** | each skill fetches what it needs | 4× the requests, inconsistent views of the site, impossible to bound politeness | Detectors cannot ask follow-up questions; a missing observation disables a check permanently |
| **Six skills partitioning the *question* space** | one monolith; or splitting by artifact | Three skills read the same JSON-LD blob; what never overlaps is the question asked of it | `crawl-render-audit` owns three check families, which looks asymmetric next to the others |
| **Detectors propose, prioritization decides** | each detector assigns final severity | Only a global view can dedupe and compare scope | An extra contract to maintain |
| **Absence findings allowed without observation IDs** | require a positive ID always | There is no observation that proves something is *missing* | A weaker anchor; mitigated by requiring known source URLs |
| **Confidence floor demotes rather than deletes** | drop low-confidence findings | Preserves the signal as a reviewable opportunity | `demoted[]` needs its own presentation |
| **Fail-closed robots on ambiguity** | literal matching only | `//private` and `/%2Fprivate` evade a literal rule while servers still serve the resource | Slightly over-blocks pathological URLs |
| **Two robots evaluators** | one shared | The crawler must be conservative; the *report* must describe the site's rules, not our policy | Two functions that look confusingly similar |
| **`html.parser`, not `lxml`** | lxml for speed | No external entity resolution; pure-Python; one fewer C dependency | Slower; parsing dominates CPU |
| **Optional renderer** | require Chromium | Package installs and runs anywhere | Render checks unavailable; corpus needs it for full marks |
| **Unavailable instruments disclosed, not stubbed** | fake answers, or silence | Silence reads as a pass | Ten checks visibly cannot run |
| **Proactive requires evidence of *health*** | generic advice | Prevents an opportunity being a demoted defect in softer wording | Minimalist healthy sites correctly get nothing |

---

## 16. KNOWN LIMITATIONS

**Real implementation limitations.** `registrable_host` is not a public-suffix
implementation. Template clustering is a URL-shape proxy, not template equivalence.
`affected.count` after a merge is a lower bound. `related_findings` is URL overlap
with no causal model. Mechanism prose is a fallback dedupe key. Breadcrumb
detection accepts an empty container. Viewport is approximated by an 800-character
window.

**Unavailable instrumentation (10 checks).** `PROBE`: `D-EXTRACT-01/03/06/07`,
`D-RENDER-02`, `E-ANSWER-04`. `CLAIM_CORROBORATION`: `D-ENTITY-03`, `D-TRUST-05`.
`SITEMAP`: `D-CRAWL-07`'s sitemap half. Crawl telemetry: `D-CRAWL-14`. All
disclosed per report as `UNAVAILABLE_INSTRUMENT`.
Additionally, `detect_extract.proactive_opportunities` (`D-EXTRACT-08`) is
implemented and tested but **never called** by the pipeline — a
documentation/implementation discrepancy worth knowing.

**Multilingual limitations.** Charset decoding and tokenization are fixed and
cross-script. **Vocabularies are not:** type keywords, offering patterns, month
names, claim/superlative/boilerplate patterns, challenge/soft-404/regional-block
regexes, modal/consent/paywall class patterns, and the English byline fallback.

**Breadth limitations.** Faceted query spaces can crowd the frontier. Orphan
detection sees only same-host links from fetched pages. Archetype is one label.

**Performance edge cases.** HTTP timeouts are not absolute response deadlines; a
deliberately slow or huge response can exceed the envelope. Parsing, browser
lifecycle and report processing are not interruptible through the `Budget` API.
Stress-measured: 61 × 64 KB pages with 200 nav links, 150 query links, 50 JSON-LD
blocks and 120-level nesting completed in ~7 s at 46 MB peak.

**Deliberately unsupported.** No live model or search calls. No sitemap fetching.
No truth checking. Cross-domain canonicals never flagged. Multiple `h1`s never
flagged. Missing structured data alone never flagged. Sitemap absence alone never
flagged. `D-ENTITY-05` never fires standalone.

---

## 17. HISTORY OF IMPORTANT BUGS AND FIXES

Preserved because each encodes a lesson that is not obvious from the current code.

| Bug | Root cause | Fix | Test added | Lesson |
|---|---|---|---|---|
| **Detector wiring gap** | `_invoke_detectors` called only `detect_crawl`; `detect_render`/`detect_extract` were never invoked | both now called | end-to-end corpus fixtures | 63 passing unit tests could not see it — **unit tests cannot catch orchestration gaps** |
| **Charset mis-decoding** | `requests` defaults `text/html` with no charset to ISO-8859-1 | `html_encoding` browser-style ladder | `test_html_is_decoded_the_way_a_browser_decodes_it` (5 declaration styles) | A library default can be RFC-correct and still wrong for the format |
| **ASCII-only tokenizer** | `significant_words` used `[a-z0-9]+` | Unicode class + CJK bigrams | `test_identical_text_is_recognized_as_identical_in_any_script` | It failed *silently* — `containment_ratio(x,x)` returned 0.0 for Greek, so `E-ANSWER-01` fired on **3 of 3** pages of a healthy Greek site |
| **Robots evasion** | rules matched literally, so `//private` and `/%2Fprivate` slipped past | `path_interpretations` + fail-closed evaluator | `test_robots_exclusion_survives_path_rewriting` | Reproduced end to end first: `/%2Fprivate` was actually fetched |
| **Dead-end false positives** | `E-CONTINUE-02` ignored `<nav>` | `navigation_destinations`, `MIN_NAVIGATION_DESTINATIONS = 2` | brochure/docs/header/footer/ARIA + 5 malformed-nav cases | A healthy 4-page site produced **5** high-confidence "Dead end" findings |
| **Alias pollution** | every page title became a sitewide brand alias | ≥2-page or declared requirement + `_brand_tokens(for_url=…)` | `test_a_deep_pages_own_title_does_not_identify_its_owner` | Caused a **false negative**: `E-ORIENT-01` could not fire on any realistically-titled page |
| **No JSON-LD authority** | title/h1 outvoted `Organization.name` | `_structured_identity` with five earned conditions | one test per removed condition | A healthy site with valid markup got two identity findings |
| **`/` vs `/index.html`** | frontier keyed on the raw URL | `canonical_resource_url` | 9 collapse + 9 must-not-merge cases | Produced duplicate findings *and* inflated scope denominators |
| **Severity quota** | reports capped high/critical at ~30% by rewriting severities | ratio became a warning | `test_finding_severity_is_invariant_to_unrelated_findings` | Severity must be a property of evidence, not of report composition |
| **Sample = population** | unmeasured `total_in_scope` treated as sitewide | stays `None` | `test_unknown_population_does_not_infer_sitewide_scope` | Manufacturing a denominator manufactures severity |
| **Copyright year = staleness** | old `©` proved stale content | require an expired forward-framed claim | `test_d_trust_02_copyright_alone_does_not_establish_staleness` | A rights date is not a content-review date |
| **Stale documentation** | fixtures claimed a "CRITICAL, CONFIRMED ORCHESTRATOR BUG" that had been fixed; `OVERFITTING_AUDIT.md` called the working validator a `NotImplementedError` stub; `archetype-applicability.md` shipped a `TODO` and the false line "A check with no row does not run" | corrected at source, including `build_fixtures.py` so regeneration cannot resurrect them | validator link checks | **Documentation rots faster than code, and a self-accusation is read as fact** |
| **Capability silence** | ten unevaluable checks looked like passes | `UNAVAILABLE_INSTRUMENT` coverage naming exact check IDs | drift test asserting declared ⊆ implemented | A check that could not run must never look like a check that passed |

---

## 18. WHERE TO START READING THE CODE

1. `marketplace.json` — 15 lines. Six skills, one entrypoint.
2. `README.md` §"The skills" and §"How the entrypoint composes them".
3. `references/finding-contract.md` — the shape everything produces.
4. `lib/common/observations.py` (85 lines) — the shape everything consumes.
5. `lib/site_observer/collect.py` (274 lines) — **the single most important file**;
   read it top to bottom, it is the whole lifecycle.
6. `skills/audit-orchestrator/scripts/run_audit.py::run_audit` — eleven statements.
7. **One detector, end to end:** `skills/crawl-render-audit/scripts/detect_crawl.py`
   → the `CHECKS` list → `check_d_crawl_01` → `check_d_crawl_06` (simplest, then
   most guarded).
8. `lib/common/extract.py` — `_soup`, `parse_cache`, `significant_words`.
9. `lib/common/network_policy.py` + `public_transport.py` — the safety boundary.
10. `schemas/report.schema.json` then `lib/common/schema.py::validate_report`.
11. `skills/evidence-prioritization/scripts/score.py::prioritize_findings`.
12. `tests/test_safety.py` — the adversarial cases explain *why* the boundary looks
    the way it does.
13. `tests/harness/run_corpus.py` — how end-to-end evidence is produced.

---

## 19. HUMAN MODIFICATION MAP

### Safest to experiment with
| Area | Current | Why it exists | Understand first | Key files | Tests to run |
|---|---|---|---|---|---|
| Report wording / Markdown layout | `render_markdown` + `_text` | non-expert readability | escaping and the 400-char cap are **security controls**, not formatting | `render_report.py` | `test_report_design.py`, `test_safety.py -k report` |
| Reference documentation | prose per skill | explains intent | must not contradict code | `skills/*/references/*.md` | `validate_marketplace.py` (link checks) |
| Adding a *suppression* case to a check | `continue` guards | false-positive control | suppressions can create false negatives | one detector | that skill's test module + corpus |
| Proactive evidence strings | `proactive.py` | reader clarity | `_is_grounded` requires all fields | `proactive.py` | `test_audit_orchestrator.py -k proactive` |

### Moderate risk
| Area | Current | Understand first | Key files | Tests |
|---|---|---|---|---|
| Check thresholds | §H tables in each skill doc | almost all are **chosen**, not calibrated — changing one moves corpus results | detector + its reference | that skill's tests + `run_corpus.py` |
| Archetype gating | one label, suppress/re-threshold | a misclassification silently changes severity | `classify.py`, `_entity_util`, `_trust_util` | entity + trust tests + corpus |
| Dedupe keys | `(check_id, mechanism)` | prose keys can collide | `aggregate_dedupe.py` | `test_evidence_prioritization.py` + corpus |
| Adding a new check | `CHECKS` list + `make_finding` | must add fp-guardrails, a fire test, a suppress test, and a taxonomy row | one detector | that skill's tests + corpus |

### High risk
| Area | Current | Understand first | Key files | Tests |
|---|---|---|---|---|
| Network policy / robots | fail-closed, layered | every relaxation is a safety regression; read `SAFETY_AUDIT.md` V-1 and V-2 first | `network_policy.py`, `robots.py` | `test_safety.py` (120), `run_safety.py` |
| Render boundary | routed transport + neutered globals | `WebTransport` is unroutable — a resource allowlist alone is insufficient | `render.py` | `run_safety.py` (needs Chromium) |
| Transport / SSRF | pinned public sockets | re-resolution reintroduces DNS rebinding | `public_transport.py`, `http_client.py` | `test_safety.py` |
| Scoring policy | modifier cell table | severity must not depend on report composition | `score.py` | `test_evidence_prioritization.py` + corpus |
| Evidence binding | drop-if-unbound | absence findings legitimately have empty `observation_ids` | `validate_report.py` | orchestrator tests + corpus |

### Architecture level
| Area | Understand first | Why it is architectural |
|---|---|---|
| Adding an observation type (`SITEMAP`, `PROBE`, `PAGE_CLASSIFICATION`) | the "exactly one collection pass" invariant, budgets, coverage policy | changes the store contract every detector reads, and the disclosure list |
| Changing the finding contract | `findings.py`, `report.schema.json`, prioritization, renderer | four producers and three consumers |
| Skill boundaries | each `SKILL.md`'s "Explicitly NOT this skill's job" | the boundaries are the marketplace's thesis |
| Concurrency in the crawler | `RequestPolicy` pacing | more concurrency without a scheduler risks pacing violations |

---

## 20. GLOSSARY

| Term | Meaning |
|---|---|
| **Archetype** | One of 8 site categories from `classify_archetype`, used to suppress or re-threshold checks. |
| **Absence finding** | A finding whose evidence is that a signal was *not* present; binds via `source_urls`. |
| **Affected block** | `{count, sample_urls[≤5], total_in_scope}`. |
| **Check ID** | `D-CRAWL-01`, `E-ORIENT-03`, … `D` = discoverability, `E` = engagement. |
| **Claim table** | `trust-freshness-audit`'s extracted assertions plus a per-page date inventory. |
| **Coverage entry** | An `X-COV-01` row recording work that could not be done. |
| **Demoted** | A well-formed finding below the confidence floor; in `demoted[]`, not `findings[]`. |
| **Effective pages** | Render-preferred page selection (`lib/common/pages.py`). |
| **Entity profile** | `entity-semantic-audit`'s identity fact table with per-field provenance. |
| **Evidence binding** | Dropping any finding that cannot resolve to a real observation or known URL. |
| **Finding** | An assertion that something is wrong or missing, with evidence and a fix. |
| **Gate 1/2/3** | Reach / read / extract — the three `crawl-render-audit` families. |
| **Lens** | Raw (HTTP) vs rendered (browser) view of a page. |
| **Observation** | A typed, content-addressed evidence record. |
| **Opportunity** | The site is healthy on this point and there is still a defensible improvement. Never counted in severity totals. |
| **Product token** | `brand-ai-readiness-audit`, the auditor's robots.txt identity. |
| **Rejected** | A malformed finding, dropped by `normalize_findings`. |
| **Scoring trace** | Human-readable notes recording which modifiers changed a severity. |
| **Store** | The immutable observation store produced by one collection pass. |
| **Template cluster** | URL-shape grouping so one templated defect is one finding. |
| **UNAVAILABLE_INSTRUMENT** | The coverage reason naming checks that could not be evaluated. |
| **X-COV-01** | The bookkeeping ID on every coverage entry. Not a finding ID. |
