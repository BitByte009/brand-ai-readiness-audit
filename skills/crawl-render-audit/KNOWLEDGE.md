# crawl-render-audit — Engineering Study Guide

> Companion to `SKILL.md`. `SKILL.md` tells an *agent* how to invoke this skill;
> this file tells a *human engineer* how it actually works.
> Shared vocabulary, the observation store, the safety model and the finding
> contract are documented once in the root `KNOWLEDGE.md` — see §8 (cross-skill
> concepts) and §6 (shared library) there rather than repeated here.

---

## A. PURPOSE AND MENTAL MODEL

**Mental model:** think of this skill as a *machine-accessibility triage tool*
that takes an immutable store of HTTP and rendered-DOM observations and produces
findings about the three sequential gates a machine must pass before it can use
a page at all.

The three gates, which are also the three script files:

| Gate | Question | File | Family |
|---|---|---|---|
| 1. Reach | Is a crawler allowed in, and does the URL resolve? | `scripts/detect_crawl.py` | `D-CRAWL-01..15` |
| 2. Read | Once fetched, is the content actually in the bytes? | `scripts/detect_render.py` | `D-RENDER-01..05` |
| 3. Extract | Can a specific fact be pulled out of what was read? | `scripts/detect_extract.py` | `D-EXTRACT-01..09` |

The gates are ordered and non-substitutable. A page that fails gate 1 cannot fail
gate 3 in any meaningful way, because gate 3 never had bytes to work with. This
is why the skill owns three check families rather than being split into three
skills: they answer one question ("can a machine use this page?") at three
depths, and separating them would force cross-skill coordination for no gain.

**What it considers evidence.** Only `HTTP_FETCH`, `RENDER`, `ROBOTS` and — where
available — `SITEMAP`, `PAGE_CLASSIFICATION` and `PROBE` observations from the
store. It never fetches anything itself (see §D).

**What it does NOT attempt to determine.**
- *Who* the site is, or whether its identity is coherent → `entity-semantic-audit`.
- Whether claims are believable or fresh → `trust-freshness-audit`.
- Whether a human arriving from an AI answer has a good experience →
  `engagement-audit`. The boundary is explicit in `SKILL.md`: a wall blocking the
  *fetch* is `D-CRAWL-09`; a wall blocking the *reader* after a successful fetch
  is `E-ANSWER-02` and belongs to engagement.
- Severity ranking or deduplication → `evidence-prioritization`. The `severity`
  passed to `make_finding` here is a *proposed base* severity, not the final one.

---

## B. COMPLETE FILE MAP

### `skills/crawl-render-audit/SKILL.md`
- **Purpose:** agent-facing instructions + `allowed-tools: Bash Read`. Carries a
  **Capability note** listing the checks that cannot be evaluated in this
  deployment (see §F.4).
- **Called by:** the host agent / `audit-orchestrator`.
- **Side effects:** none.

### `scripts/detect_crawl.py` (887 lines)
- **Purpose:** gate 1. Implements `D-CRAWL-01..15`.
- **Called by:** `audit-orchestrator/scripts/run_audit.py::_invoke_detectors`,
  which calls `detect_crawl.detect_crawl(store)`.
- **Calls:** `lib.common.observations` (`single`, `http_fetches`), `lib.common.extract`
  (`extract_text`, `extract_links`, `extract_canonical_url`), `lib.common.robots.robots_allows`,
  `lib.common.findings.make_finding`/`affected_block`, local `_util`.
- **Inputs:** `store` dict. **Outputs:** `List[finding]`.
- **Important functions:** `detect_crawl` (dispatcher over the module-level
  `CHECKS` list, lines 841–857), `_discovered_urls`, `_derive_link_graph`,
  `_audited_host`, `_orphan_urls`, `_linkless_pages`, `_has_noindex`,
  `_extract_hreflang`, `_has_redirect_loop`.
- **Important data structures:** module constants `_NOINDEX_RE`, `_CHALLENGE_RE`,
  `_REGIONAL_BLOCK_RE`, `_LOCALE_SEGMENT_RE`; `CATEGORY = "discoverability"`.
- **Side effects:** none (pure function of the store). Has a `main()` CLI that
  reads `--store` and writes `--out`.

### `scripts/detect_render.py` (341 lines)
- **Purpose:** gate 2. Implements `D-RENDER-01..05`. Every check requires a
  *paired* raw + rendered observation for the same URL.
- **Important functions:** `_paired_pages` (the generator that enforces pairing
  and skips non-`ok` renders), `_main_text` (chrome-stripped text), `_disclosure_panels`,
  `_listing_item_count`, `_has_pagination_anchor`.
- **Constants:** `MAIN_TEXT_FLOOR = 400`, `RATIO_THRESHOLD = 0.30`,
  `_CHROME_TAGS = {nav, header, footer, script, style, noscript}`, `_NEXT_HREF_RE`.

### `scripts/detect_extract.py` (690 lines)
- **Purpose:** gate 3. Implements `D-EXTRACT-01..07, 09` as findings, and
  `D-EXTRACT-08` as a **proactive-only** function (see §F.5).
- **Important functions:** `_jsonld_blocks` (parses and captures JSON errors
  rather than discarding them), `_get_path_values` / `_prop_present` (dot-path
  resolution across list branches), `_heading_outline`, `_relevant_factual_questions`,
  `_has_missing_alt_image`, `_has_bare_pdf_link`, `proactive_opportunities`.
- **Constants:** `TYPE_SCHEMA_MAP`, `_MOJIBAKE_RE`, `_BOILERPLATE_RE`.

### `scripts/_util.py` (120 lines) — shared by all three detectors
- `SHORT_PAGE_TEXT_FLOOR = 400` — the "is this page substantive?" floor.
- `is_utility_path(url)` — structural, **not** brand/CMS-specific: matches
  `cart|checkout|search|login|logout|signin|signup|register|account|wishlist|admin|basket|my-account`
  as a leading path segment, **or any URL carrying a query string**.
- `registrable_host(value)` — strips `www.`, lowercases. Explicitly *not* a
  public-suffix-list implementation.
- `cluster_key(url)` — the local template-shape fallback. Collapses numeric and
  long-slug segments to `*`, stripping and reattaching a trailing extension so
  `/product/123.html` clusters as `/product/*.html`. Without the extension
  handling the most common templated-URL shape would never cluster.
- `group_by_cluster(store, urls)` — one finding per template cluster, which is
  the mechanism that stops a 200-product site producing 200 findings.
- `RECOGNIZED_AI_BOTS` — a literal set of 8 product tokens (`gptbot`,
  `chatgpt-user`, `google-extended`, `openai-bot`, `perplexitybot`, `ccbot`,
  `claudebot`, `anthropic-ai`). This is a named vocabulary, and it is the one
  place in this skill where a hard-coded external identifier list exists.

### References (`references/`)
| File | What it contains |
|---|---|
| `crawl-checks.md` | Per-check prose for `D-CRAWL-*`, including the Appendix-A gate rationale. |
| `render-checks.md` | Per-check prose for `D-RENDER-*`. |
| `extract-checks.md` | Per-check prose for `D-EXTRACT-*`. |
| `fp-guardrails.md` | The suppression table — for each check, the condition under which it deliberately does not fire. |
| `store-contract.md` | The exact observation shapes this skill reads. |

### Shared library modules that materially affect this skill
- `lib/common/observations.py` — `single`, `http_fetches`, `renders`,
  `page_classifications`, `probes`. These are the *only* way the skill reaches
  the store; `probes()` and `page_classifications()` return `{}` in this
  deployment, which is the mechanism behind the unevaluable checks in §F.4.
- `lib/common/extract.py` — `extract_text`, `extract_links`, `extract_metadata`,
  `extract_canonical_url`, `extract_jsonld`, `schema_type_matches`,
  `is_jsonld_mime_type`, `page_inventory`, `compare_raw_vs_rendered`, and the
  `parse_cache` that makes repeated parsing of the same HTML affordable.
- `lib/common/robots.py` — `robots_allows` (used by `D-CRAWL-01` to re-evaluate
  robots rules against discovered URLs *as an audit judgement*, distinct from the
  fetch-time `robots_allows_every_interpretation` used by the crawler).
- `lib/common/findings.py` — `make_finding`, `affected_block`.

### Tests and fixtures
- `tests/test_crawl_render_audit.py` (1044 lines) — the largest test module.
- Fixtures whose expectations centre on this skill: `js-render-gap`,
  `facts-render-only`, `invalid-structured-data`, `image-locked-facts`,
  `robots-5xx`, `both-weak`, `large-site`, `unusual-site-structure`,
  `no-structured-data-ok`, `fp-trap-composite`.

### Schemas
- `schemas/observation.schema.json` — the input shape.
- `schemas/report.schema.json` — the finding shape this skill's output must
  eventually satisfy (enforced by the orchestrator, not here).

---

## C. END-TO-END WORKFLOW

```
   URL
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ lib/site_observer/collect.py   (NOT this skill)              │
│   robots preflight → BFS crawl → stratified render sample    │
│   emits ROBOTS, HTTP_FETCH, RENDER observations              │
└──────────────────────────────────────────────────────────────┘
    │  store {observations:[...], target:{...}, archetype:...}
    ▼
┌──────────────────────────────────────────────────────────────┐
│ run_audit.py::_invoke_detectors                              │
│   detect_crawl(store) → detect_render(store) → detect_extract│
└──────────────────────────────────────────────────────────────┘
    │
    ├─► detect_crawl:   CHECKS list, 15 functions, each store→[finding]
    │     └─ _discovered_urls / _derive_link_graph build the URL universe
    │     └─ group_by_cluster collapses per-URL hits into per-template findings
    │
    ├─► detect_render:  _paired_pages yields (url, fetch, render) triples only
    │     └─ every check no-ops when no RENDER observation exists
    │
    └─► detect_extract: per-URL loops over http_fetches / probes / classifications
          └─ probe-dependent checks no-op when probes(store) is {}
    │
    ▼  List[unscored finding]  (severity here is a PROPOSED base severity)
┌──────────────────────────────────────────────────────────────┐
│ evidence-prioritization: normalize → dedupe → score → rank   │
└──────────────────────────────────────────────────────────────┘
    ▼
┌──────────────────────────────────────────────────────────────┐
│ run_audit: bind_evidence → schema validate → report.json/md  │
└──────────────────────────────────────────────────────────────┘
```

**Stage detail.**

1. **Observation intake.** `store` arrives as a plain dict. No validation happens
   inside this skill; a malformed store surfaces as an exception, which
   `run_audit::_run_detector` catches and converts into a `SKILL_FAILED` coverage
   entry (see the orchestrator KNOWLEDGE §12).
2. **URL universe construction.** `_discovered_urls(store)` builds the set of URLs
   the audit knows about. `_derive_link_graph(store)` reconstructs who links to
   whom from the fetched HTML, because the store carries observations, not the
   crawler's internal link graph.
3. **Per-check evaluation.** `detect_crawl` iterates the `CHECKS` list. Each check
   is an independent `store → List[finding]` function with no shared mutable state.
   A check that finds nothing returns `[]`.
4. **Clustering.** Checks that can hit many URLs (`01, 03, 04, 05, 08, 09`) pass
   their hits through `group_by_cluster` so the output is one finding per URL
   *template*, carrying an `affected` block with a sample.
5. **Finding construction.** `make_finding(...)` builds the common contract:
   `check_id, category, title, severity, confidence, mechanism, impact,
   observed_signal, evidence, observation_ids, source_urls, affected,
   suggested_action`.
6. **Return.** The list is pooled with the other three detectors' output.

**Failure behaviour at each stage:** every check guards its own preconditions and
returns `[]` rather than raising. The observed exception path is a malformed
store, and it is contained by the orchestrator, not by this skill.

---

## D. INPUT CONTRACT

This skill is a **pure function of the store**. `SKILL.md` states it "performs no
fetching of its own"; the implementation matches — there is no `requests` import
anywhere in `skills/crawl-render-audit/`.

| Input | Type | Origin | Required | Meaning | If missing | If malformed |
|---|---|---|---|---|---|---|
| `store["observations"]` | `list[dict]` | `collect.py` | yes | All evidence | Every check returns `[]` | Exception → `SKILL_FAILED` coverage |
| `HTTP_FETCH` obs | one per crawled URL | `collect.py:169` | yes in practice | `{status_code, final_url, redirect_chain, headers, encoding, elapsed_ms, evidence, html}` | Gate-1 and gate-3 checks all no-op | Missing keys default via `.get()` |
| `RENDER` obs | one per sampled URL | `collect.py:211` | optional | `{status, reason, final_url, status_code, html, evidence}` | **All 5 `D-RENDER` checks silently produce nothing**; the orchestrator emits `RENDERER_UNAVAILABLE` coverage | `_paired_pages` skips any render whose `status != "ok"` |
| `ROBOTS` obs | exactly one | `collect.py:96` | optional | parsed robots model | `D-CRAWL-01/02` return `[]`; `D-CRAWL-15` returns `[]` | `status != "ok"` → `01/02` no-op |
| `SITEMAP` obs | — | **never produced** | — | — | `D-CRAWL-07`'s sitemap branch is unreachable | — |
| `PAGE_CLASSIFICATION` obs | — | **never produced** | — | — | `D-EXTRACT-03/07` no-op | — |
| `PROBE` obs | — | **never produced** | — | — | `D-EXTRACT-01/03/06/07`, `D-RENDER-02` no-op | — |
| `store["capabilities"]["crawl"]["budget_exhausted"]` | bool | **never written** | — | — | `D-CRAWL-14` returns `[]` immediately | — |

**Tracing the gaps to their producer.** `lib/site_observer/collect.py` contains
exactly three `make_observation` call sites (lines 96, 169, 211) emitting
`ROBOTS`, `HTTP_FETCH` and `RENDER`. `lib/site_observer/probe.py::detect_capability()`
returns `{"available": False, "reason": "MODEL_UNAVAILABLE"}` unconditionally —
it is not environment-detected. Nothing writes `capabilities["crawl"]`.

---

## E. OUTPUT CONTRACT

The skill returns `List[dict]` in the `make_finding` shape. Fields it populates
and what they mean here:

| Field | This skill's usage |
|---|---|
| `check_id` | `D-CRAWL-nn` / `D-RENDER-nn` / `D-EXTRACT-nn` |
| `category` | always the literal `"discoverability"` (all three files set `CATEGORY`) |
| `severity` | **proposed base** severity; `evidence-prioritization` computes the final |
| `confidence` | mostly hard-coded `"high"`; `D-RENDER-01` and `D-CRAWL-10/14` use `"medium"` |
| `evidence` | a human-readable string built from the actual observed values |
| `observation_ids` | the `id` of every observation the claim rests on |
| `source_urls` | the affected URLs |
| `affected` | `affected_block(urls, total_in_scope)` → `{count, sample_urls[≤5], total_in_scope}` |
| `suggested_action` | `{summary, priority, how_to_fix, validation}` |

It does **not** produce: report `id` (assigned by prioritization), coverage
entries (the orchestrator's job), or proactive opportunities — with the single
exception of `detect_extract.proactive_opportunities(store)`, which returns a
different shape and, in the current wiring, is **never called** (§F.5).

---

## F. CHECK-BY-CHECK BREAKDOWN

### F.1 Evaluability classification

| Class | Checks |
|---|---|
| **Always evaluable** (needs only `HTTP_FETCH`) | `D-CRAWL-03, 04, 05, 06, 09, 10, 11, 12, 13`; `D-EXTRACT-02, 04, 05, 09` |
| **Evaluable when `ROBOTS` parsed** | `D-CRAWL-01, 02, 15` |
| **Evaluable when a `RENDER` pair exists** | `D-RENDER-01, 03, 04, 05` |
| **Partly evaluable** | `D-CRAWL-07` — orphan branch works, sitemap branch dead; `D-CRAWL-08` — works, sitemap only enriches evidence |
| **Not evaluable in this deployment** | `D-CRAWL-14` (crawl telemetry), `D-EXTRACT-01, 03, 06, 07`, `D-RENDER-02` (probe) |
| **Proactive-only, never a finding** | `D-EXTRACT-08` |

The unevaluable set is disclosed at runtime as `UNAVAILABLE_INSTRUMENT` coverage
entries naming the exact check IDs — see orchestrator KNOWLEDGE §21.

### F.2 `D-CRAWL` — gate 1, reachability

| Check | Purpose | Mechanical test (from code) | Sev/Conf | Guardrails |
|---|---|---|---|---|
| **D-CRAWL-01** | robots.txt disallows content paths | `ROBOTS.status == "ok"`; for each discovered URL, `not is_utility_path(u)` **and** `not robots_allows(path+query)` | critical/high | `is_utility_path` exempts cart/search/login/admin **and any query URL** — disallowing those is correct practice |
| **D-CRAWL-02** | an AI crawler is singled out | for each robots group whose UA ∈ `RECOGNIZED_AI_BOTS`, `set(group.disallow) - set(star.disallow)` non-empty | medium/high | Reported **neutrally**: the `impact` string says "may be a deliberate business decision… not an error". Only the *delta* beyond `*` counts |
| **D-CRAWL-03** | `noindex` on substantive pages | `status==200`, not utility, `len(extract_text(html)) > 400`, and `_has_noindex(html, headers)` | critical/high | The 400-char floor excludes thin/utility pages that are legitimately noindexed |
| **D-CRAWL-04** | dead or soft-404 pages | `status is None or >= 400`; **or** `status==200 and len(text)<400 and _SOFT_404_RE matches` | high/high | Skips any fetch whose `evidence.coverage_gap` is set — a transport failure is our problem, not the site's |
| **D-CRAWL-05** | redirect chains / loops | `len(redirect_chain) >= 3` or `_has_redirect_loop(chain)` | medium/high | 1–2 hops (http→https→www) never flagged |
| **D-CRAWL-06** | canonical conflicts | canonical present, differs from `final_url` (ignoring trailing `/`), **same registrable host**, target was crawled, and target is `>=400` or noindex | high/high | Cross-domain canonicals `continue` — legitimate on syndicated content. Uncrawled target ⇒ applicability unmet, `continue` |
| **D-CRAWL-07** | sitemap rot / missing sitemap | branch A: `SITEMAP.status=="ok"` and ≥20% entries non-2xx. branch B: no sitemap **and** orphans exist | medium/high, medium/medium | Branch B requires orphans — absence of a sitemap alone is never a defect |
| **D-CRAWL-08** | orphaned pages | `_orphan_urls(store)` non-empty | medium/high | Uses the derived link graph; sitemap presence only changes the evidence text |
| **D-CRAWL-09** | bot-hostile serving | `status==403`, **or** `len(html)<1000 and _CHALLENGE_RE matches` | critical/high | The `<1000` byte bound is what separates a challenge *shell* from a real page that discusses verification |
| **D-CRAWL-10** | fetch cost | `>=5` samples with `elapsed_ms`; `median > 3000*3` ms | medium/medium | The ≥5-sample floor prevents flagging from one slow request |
| **D-CRAWL-11** | locale variants without `hreflang` | group URLs by locale-segment shape; `>=2` URLs in a shape and **all** have no hreflang | medium/high | `all(not tags)` — partial tagging is not flagged |
| **D-CRAWL-12** | regional blocking text | `_REGIONAL_BLOCK_RE` matches page HTML | low/high | Low severity: it is a text signal, not a proven geo-block |
| **D-CRAWL-13** | duplicate host serving | a non-primary host returns 200 and its canonical does **not** point at the primary host | medium/high | A correct cross-host canonical suppresses it |
| **D-CRAWL-14** | crawl budget consumed by query space | `capabilities.crawl.budget_exhausted` **and** per-cluster query-URL ratio > 0.4 | medium/medium | **Not evaluable** — the flag is never set |
| **D-CRAWL-15** | robots.txt unreachable/unparseable | `ROBOTS.status ∈ {"error","unparseable"}` | critical/high | Fires only on those two statuses; `missing` (404) is allow-all and correct |

**Prose notes on the non-obvious ones.**

- **D-CRAWL-01** re-evaluates robots *as an audit judgement* using
  `robots_allows`, which is the plain longest-match evaluator. This is
  deliberately **not** the fetch-time
  `robots_allows_every_interpretation` used by `RequestPolicy.admit`. The
  crawler must fail closed on ambiguity; the auditor must report what the rules
  literally say. Conflating them would make the report describe our safety
  policy rather than the site's configuration.
- **D-CRAWL-04**'s soft-404 branch is a compound test — a 200 status, a *short*
  page, and a "not found"-shaped body. Any one alone would be far too loose.
- **D-CRAWL-06** has four sequential `continue` guards before it can fire. That
  is the check's entire false-positive control, and it is why the check is high
  confidence when it does fire.

### F.3 `D-RENDER` — gate 2, readability

Every check begins with `_paired_pages(store)`, which yields only `(url, fetch,
render)` triples where a `RENDER` observation exists **and** `render.status ==
"ok"`. No renderer ⇒ the entire family produces nothing.

| Check | Purpose | Mechanical test | Sev/Conf | Guardrails |
|---|---|---|---|---|
| **D-RENDER-01** | primary content is JS-only | `len(rendered_main_text) > MAIN_TEXT_FLOOR (400)` and `len(raw)/len(rendered) < RATIO_THRESHOLD (0.30)` | high/variable | `_main_text` strips `nav/header/footer/script/style/noscript` first, so client-side chat widgets and analytics do not count as "content" |
| **D-RENDER-02** | a specific *fact* is render-only | needs `PROBE`; for each answered factual question, its `evidence_span` is present in rendered text but absent from raw | high/high | **Not evaluable** — hard-gated `if not probe: continue` |
| **D-RENDER-03** | navigation is JS-only | `len(rendered_links - raw_links) >= 3` | high/high | The ≥3 floor stops a single client-side widget link from firing it |
| **D-RENDER-04** | content behind interaction | `_disclosure_panels(html)` finds trigger/panel pairs where the panel's `get_text(strip=True)` is empty | medium/medium | Only *empty* panels count. Content present-but-CSS-hidden is readable and is deliberately not flagged |
| **D-RENDER-05** | infinite scroll with no crawlable pages | `_listing_item_count >= 10` **and** no pagination anchor in raw **or** rendered HTML | medium/medium | `_has_pagination_anchor` accepts `rel=next`, `?page=N`, `/page/N` |

`_listing_item_count` is worth understanding: it counts, for every element, the
tuple `(id(parent), tag_name, sorted(classes))` and returns the maximum count.
That is a structural proxy for "a repeated list item" that needs no CSS
selectors and no framework knowledge.

### F.4 `D-EXTRACT` — gate 3, extractability

| Check | Purpose | Mechanical test | Sev/Conf | Guardrails |
|---|---|---|---|---|
| **D-EXTRACT-01** | facts locked in images/PDFs | needs `PROBE`: an unanswered relevant factual question **and** (`_has_missing_alt_image` or `_has_bare_pdf_link`) | high/medium | **Not evaluable.** The compound trigger means an alt-less image alone never fires it |
| **D-EXTRACT-02** | missing / duplicate title+meta | branch A: `title` or `description` blank on a 200 page. branch B: same title/description repeated across URLs | medium/high | Clustered, so a paginated series produces one finding |
| **D-EXTRACT-03** | no structured data where a type applies **and** the fact is unextractable | needs `PAGE_CLASSIFICATION` + `PROBE`: classified type ∈ `TYPE_SCHEMA_MAP`, no matching JSON-LD `@type`, and ≥1 unanswered relevant question | medium/high | **Not evaluable.** Compound by design: schema absence with clear prose is explicitly *not* a defect |
| **D-EXTRACT-04** | invalid / incomplete structured data | `_jsonld_blocks` returns a block with `"error"` (JSON parse failure), **or** a node of a known `@type` missing a required property per `TYPE_SCHEMA_MAP` | high/high | `_prop_present` resolves dot-paths across **all** list branches, and a list requirement (`["offers.price","offers.priceCurrency"]`) is satisfied by any one member |
| **D-EXTRACT-05** | unusable heading outline | page text > 400 chars **and** (no `h1`, or a high ratio of headings with no body text) | medium/high, low/medium | Multiple `h1`s are valid HTML5 and are not flagged |
| **D-EXTRACT-06** | low quotable-answer density | needs `PROBE`: `>= 2` unanswered relevant factual questions | high/high | **Not evaluable.** The ≥2 floor is the guardrail |
| **D-EXTRACT-07** | facts implied, not stated | needs `PROBE` + `PAGE_CLASSIFICATION`, page text > 400 chars | high/high | **Not evaluable** |
| **D-EXTRACT-09** | content-type / encoding faults | branch A: `Content-Type` present and not `text/html`, and URL does not end `.json/.xml/.pdf/.rss`. branch B: `_MOJIBAKE_RE` density > 1% of text | high/high | The extension allowlist prevents flagging legitimately non-HTML resources |

**On `D-EXTRACT-09` branch B and the charset fix.** `_MOJIBAKE_RE` matches `�`,
`Ã.` and `â€.`. Before the HTML5 charset resolution added to
`lib/common/http_client.py::html_encoding`, a page served `text/html` with only a
`<meta charset>` was decoded as ISO-8859-1 by `requests`, which *manufactured*
mojibake — meaning this check could blame the site for our decoding bug. That is
now fixed upstream; see root KNOWLEDGE §17.

### F.5 `D-EXTRACT-08` — proactive-only, and currently unreachable

`detect_extract.proactive_opportunities(store)` (line 539) implements
`D-EXTRACT-08` ("substance diluted by boilerplate"). Two facts a reader needs:

1. It returns a **different shape** from a finding (`{check_id, category, title,
   observed_signal, source_urls, observation_ids, suggestion}`) and is documented
   as structurally unable to false-positive as a defect.
2. **It is never called.** `grep` for `proactive_opportunities` shows call sites
   only in `tests/test_crawl_render_audit.py`. `run_audit.py` builds proactive
   opportunities exclusively from `audit-orchestrator/scripts/proactive.py`.
   Wiring it in would not change behaviour, because its trigger requires
   `answer_offset_ratio is not None`, which requires a `PROBE` observation.

**This is a documentation/implementation discrepancy worth stating plainly:**
`references/extract-checks.md` describes `D-EXTRACT-08` as part of the check
catalogue; the implementation exists but is not connected to the pipeline. It is
neither a finding nor a proactive opportunity in any real run.

---

## G. SUPPORTING FUNCTIONS AND ALGORITHMS

### `_discovered_urls(store)` — `detect_crawl.py:116`
**Why:** several checks must reason about URLs the crawler *knew about*, not only
ones it fetched. **Algorithm:** unions fetched URLs with hrefs extracted from
fetched HTML. **Called by:** `D-CRAWL-01, 04, 14`.

### `_derive_link_graph(store)` — `detect_crawl.py:88`
**Why:** the store carries observations, not the crawler's internal frontier
state, so the link graph has to be rebuilt from the HTML. **Output:** `{url: {referrers}}`.
**Consumers:** `_orphan_urls`, `_linkless_pages`. **Edge case:** only same-host
links count; a page linked solely from an uncrawled page looks orphaned.

### `_orphan_urls(store)` — `detect_crawl.py:491`
Pages with no inbound internal link in the derived graph. Feeds `D-CRAWL-08` and
gates `D-CRAWL-07`'s branch B.

### `_has_noindex(html, headers)` — `detect_crawl.py:65`
Checks both `<meta name=robots>`-style content **and** the `X-Robots-Tag` header.
Checking only one would miss the header-only case that CDNs commonly use.

### `_main_text(html)` — `detect_render.py`
Strips `_CHROME_TAGS` then normalizes whitespace. This is the single most
load-bearing helper in the render family: `D-RENDER-01`'s ratio is meaningless
without chrome removal, because a JS-heavy page's static nav would inflate the
raw-text length and mask a genuine content gap.

### `_jsonld_blocks(html)` — `detect_extract.py`
**Why written this way:** a `json.JSONDecodeError` is *appended as a block with an
`error` key* rather than skipped. Discarding it would turn "the site ships broken
JSON-LD" — a real, high-severity defect — into silence. This is the mechanism
behind `D-EXTRACT-04` branch A.

### `_get_path_values(obj, dotted)` / `_prop_present(node, requirement)`
Resolves a dot-path such as `offers.price` through nested dicts **and lists**,
flattening as it goes. A requirement expressed as a list means "any one of these
satisfies it". This exists because real JSON-LD routinely puts `offers` as an
array, and a naive `node["offers"]["price"]` lookup would report a false
missing-property on valid markup.

### `_heading_outline(html)` — `detect_extract.py`
Returns `[{level, has_body}]`. `has_body` is computed by walking `find_all_next()`
until the next heading. **Edge case:** this walks the whole document order, not
siblings, so it is more tolerant of nesting than the sibling-walk used by
`lib/common/extract.heading_sections`. The two helpers are similar but not
interchangeable.

### `cluster_key` / `group_by_cluster` — `_util.py`
The aggregation contract. Without it, one templated defect on a 200-page catalogue
becomes 200 findings and the report is unusable. See root KNOWLEDGE §8.

---

## H. ALGORITHMS AND HEURISTICS — thresholds and their honesty

| Threshold | Where | Assumes | Below | Above | Justification status |
|---|---|---|---|---|---|
| `400` chars (`SHORT_PAGE_TEXT_FLOOR`, `MAIN_TEXT_FLOOR`) | `_util`, `detect_render` | a page with less text is not substantive prose | check no-ops | check may fire | **Chosen, not calibrated.** No dataset in the repo justifies 400 |
| `0.30` (`RATIO_THRESHOLD`) | `detect_render` | raw text below 30% of rendered means the substance is client-side | no finding | `D-RENDER-01` fires | **Chosen.** `references/render-checks.md` states normal JS use is not a defect; 0.30 is the operating point |
| `>= 3` rendered-only links | `D-RENDER-03` | fewer than 3 is a widget, not navigation | no finding | fires | Chosen |
| `>= 10` repeated items | `D-RENDER-05` | fewer is a small collection that is fine on first load | no finding | fires | Chosen |
| `>= 3` redirect hops | `D-CRAWL-05` | 1–2 is normal http→https→www | no finding | fires | Derived from a stated real-world pattern |
| `3000 * 3` ms median | `D-CRAWL-10` | 3× a 3s budget is a crawler-timeout risk | no finding | fires | Chosen; the `>=5` sample floor is the real guardrail |
| `>= 5` timing samples | `D-CRAWL-10` | one slow request proves nothing | no finding | evaluation proceeds | Statistical hygiene |
| `>= 0.2` rotten sitemap ratio | `D-CRAWL-07` | under 20% rot is maintenance noise | no finding | fires | Chosen |
| `> 0.4` query-URL ratio | `D-CRAWL-14` | a mostly-query cluster is faceted space | no finding | fires | Chosen; moot (unevaluable) |
| `< 1000` bytes | `D-CRAWL-09` | a challenge page is a shell | not a challenge | may fire | Chosen |
| `> 0.01` mojibake density | `D-EXTRACT-09` | 1% corrupted chars is systematic | no finding | fires | Chosen |
| `>= 2` unanswered questions | `D-EXTRACT-06` | one miss is not low density | no finding | fires | Chosen; moot (unevaluable) |

**Read this table as the honest answer to "are these numbers principled?"** They
are consistent and documented, and several encode a real-world observation (the
redirect and sample-count ones). None is fitted to a labelled dataset, because no
such dataset exists in this repository. `OVERFITTING_AUDIT.md` makes the same
admission for the prioritization thresholds.

---

## I. EVIDENCE MODEL

`observation → evidence → finding` in this skill:

1. A check reads observations through `lib/common/observations` accessors, which
   return the full observation dict including its `id`.
2. The check builds `evidence` as a **string containing the actual observed
   values** — not a restatement of the rule.
3. `observation_ids` carries the `id` of every observation the claim rests on.
4. The orchestrator later runs `validate_report.bind_evidence`, which **drops any
   finding whose `observation_ids` do not resolve against the store**. A finding
   that cannot prove its provenance does not reach the report.

**Example 1 — `D-CRAWL-01`, from a live run against the `both-weak` fixture:**
```
check_id     D-CRAWL-01
evidence     robots.txt disallows: http://127.0.0.1:PORT/catalog/
observed     robots rule matched against the discovered path
obs ids      1  (the ROBOTS observation)
source_urls  1
affected     {count: 1, total_in_scope: null}
```
The evidence names the rule *and* the path it blocked. A reader can re-run
`robots_allows()` on that pair and confirm it.

**Example 2 — `D-EXTRACT-04` invalid JSON-LD:** `evidence=block["raw"][:200]` —
the literal first 200 characters of the offending script block. This is the
strongest evidence shape in the skill: the reader sees the actual broken markup.

**Evidence-loss prevention.** The `[:200]` truncations in `detect_extract.py`
(lines 326, 363, 630) bound how much site-controlled text enters a finding. The
report renderer applies a further 400-char cap and escapes the result — see root
KNOWLEDGE §9.

---

## J. FALSE POSITIVES / FALSE NEGATIVES — historical record

| Issue | Old behaviour | Why wrong | Fix | Regression test |
|---|---|---|---|---|
| **Detector wiring gap** | `run_audit::_invoke_detectors` called only `detect_crawl`; `detect_render` and `detect_extract` were never invoked | All 5 `D-RENDER` + all `D-EXTRACT` checks were dead in every real audit while 63 unit tests passed, because the tests called the functions directly | Both are now invoked (`run_audit.py`, the `detect_render.detect_render` / `detect_extract.detect_extract` lines) | End-to-end corpus fixtures; `D-RENDER-01` fires from a full `run_audit()` on `js-render-gap` |
| **Charset mis-decoding** | `requests`' ISO-8859-1 default applied to `text/html` with no charset param | Manufactured mojibake on any non-ASCII site, corrupting all text checks and potentially firing `D-EXTRACT-09` against the site for our own bug | `html_encoding()` ladder in `lib/common/http_client.py` | `test_deterministic_foundation.py::test_html_is_decoded_the_way_a_browser_decodes_it` (5 declaration styles) |
| **JSON-LD list branches** | required-property lookup examined only the first list element | Valid markup with `offers` as an array reported a false missing property | `_get_path_values` resolves across all branches | `test_d_extract_04_checks_dotted_property_across_all_list_elements` |
| **Query strings ⇒ utility** | any query string meant "utility page" | Query-addressed primary content was excluded from checks | `is_utility_path` keeps the query rule but conventional path checks were separated; see `OVERFITTING_AUDIT.md` | `test_is_utility_path`; engagement's `test_query_addressed_content_is_not_automatically_utility` |
| **Template extension clustering** | `cluster_key` tested `123.html` as a whole segment | The commonest templated-URL shape never clustered, so aggregation silently failed | extension stripped then reattached | covered by cluster tests in `test_crawl_render_audit.py` |

**Known remaining false negatives.** Every probe-dependent check
(`D-EXTRACT-01/03/06/07`, `D-RENDER-02`) is a standing false negative in this
deployment. The corpus records this explicitly in
`tests/fixtures/facts-render-only/expected.json` and
`tests/fixtures/image-locked-facts/expected.json`.

---

## K. TESTING

- **`tests/test_crawl_render_audit.py` (1044 lines)** — the primary protection.
  For each check it holds a *fire* case and a *suppress* case. The suppress cases
  are the more valuable half: they pin the false-positive guardrails from
  `references/fp-guardrails.md`.
  *Weakness:* these tests build stores by hand and call the check functions
  directly. That is exactly how the detector-wiring gap went unnoticed — unit
  tests cannot catch an orchestration failure.
- **Fixture corpus** (`tests/harness/run_corpus.py`) — the counterweight. It runs
  the real `run_audit()` end to end over a loopback HTTP server, so it exercises
  the wiring the unit tests cannot. `js-render-gap` and `invalid-structured-data`
  are the two fixtures that specifically verify a check's logic directly *and*
  end to end, precisely because of the historical wiring bug.
- **`tests/test_redteam_fixes.py`** — adversarial cases for robots semantics and
  redirect authorization.
- **Browser tests** (`tests/harness/run_safety.py`) — relevant to this skill only
  indirectly: they prove the `RENDER` observations this skill consumes were
  produced safely.

**Weak spots in coverage.**
1. No test asserts the *evidence string content* is semantically correct — only
   that it is non-empty and length-bounded.
2. The corpus is entirely English and ASCII, so no fixture exercises
   `D-EXTRACT-09`'s mojibake branch against genuinely non-Latin content.
3. `D-CRAWL-14` and all probe-dependent checks have unit tests that inject the
   missing observation by hand; nothing exercises them end to end, and nothing can.

---

## L. LIMITATIONS

**1. Implementation limitations.** `registrable_host` is not a public-suffix
implementation. `_LOCALE_SEGMENT_RE` treats any two-letter path segment as a
locale. `_derive_link_graph` sees only same-host links from *fetched* pages.
`_heading_outline` and `heading_sections` implement similar ideas differently.

**2. Data/observation limitations.** No `SITEMAP`, `PAGE_CLASSIFICATION` or
`PROBE` observation is ever produced, disabling 6 checks and half of a 7th.

**3. Environment limitations.** Playwright is optional. Without it the entire
`D-RENDER` family produces nothing and the orchestrator records
`RENDERER_UNAVAILABLE`.

**4. Generalization limitations.** `RECOGNIZED_AI_BOTS` is a fixed list and will
age. `_CHALLENGE_RE` / `_REGIONAL_BLOCK_RE` / `_SOFT_404_RE` are English phrase
patterns. `_BOILERPLATE_RE` is English-only.

**5. Deliberately unsupported.** Cross-domain canonicals are never flagged.
Multiple `h1`s are never flagged. Missing structured data alone is never flagged.
Absence of a sitemap alone is never flagged. These are choices recorded in
`references/fp-guardrails.md`, not gaps.

---

## M. HOW A HUMAN WOULD IMPROVE THIS SKILL

### Low-risk
- **Make `_LOCALE_SEGMENT_RE` evidence-based.** Current: any `[a-z]{2}` segment is
  a locale. Better: require a corroborating `lang` attribute or `hreflang`.
  *Files:* `detect_crawl.py`. *Tests:* `D-CRAWL-11` cases. *Risk:* low — it can
  only reduce firing.
- **Externalize `RECOGNIZED_AI_BOTS`** into a reference file so the vocabulary can
  age without a code change. *Risk:* low. *Tradeoff:* one more file to load.

### Architectural
- **Produce a real `SITEMAP` observation.** Current: `D-CRAWL-07`'s better half is
  dead. Better: a fetch stage in `collect.py` that emits `SITEMAP`. *Tradeoff:*
  breaks the "exactly one collection pass" invariant (`PROJECT_CONTEXT` D-2) and
  adds requests. *Files:* `collect.py`, budget config, coverage policy.
  *Risk:* moderate — touches the safety/budget boundary.
- **Replace `cluster_key` with real template equivalence.** Current: URL-shape
  proxy. Better: DOM-structure similarity clustering. *Tradeoff:* significant CPU;
  `PERFORMANCE_AUDIT.md` already identifies parsing as the dominant cost.
- **Give `_main_text` a content-region heuristic** (`<main>`, `role=main`,
  largest text block) instead of chrome subtraction. *Risk:* moderate — directly
  moves `D-RENDER-01`'s ratio and would need corpus re-baselining.

### Research / future work
- A calibrated dataset for the thresholds in §H. Everything there is currently a
  chosen operating point.
- Non-English pattern sets for the challenge/soft-404/boilerplate regexes.

---

## N. READ THESE FILES NEXT

1. `references/crawl-checks.md` — the intent behind gate 1, in prose.
2. `scripts/_util.py` — small, and `cluster_key` + `is_utility_path` explain the
   aggregation and suppression behaviour you will see everywhere else.
3. `scripts/detect_crawl.py::detect_crawl` and the `CHECKS` list — then read
   `check_d_crawl_01` and `check_d_crawl_06` in full; they are the simplest and
   the most guarded checks respectively.
4. `lib/common/observations.py` — 85 lines; explains how every check reaches data.
5. `scripts/detect_render.py::_paired_pages` — then `check_d_render_01`.
6. `scripts/detect_extract.py::_jsonld_blocks` + `_get_path_values` — then
   `check_d_extract_04`.
7. `references/fp-guardrails.md` — read it *after* the code, and check each row
   against the `continue` statements you saw.
8. `tests/test_crawl_render_audit.py` — read the `*_never_fires_*` tests first.
9. Root `KNOWLEDGE.md` §8, §9, §17 for the shared concepts, safety model and bug
   history.
