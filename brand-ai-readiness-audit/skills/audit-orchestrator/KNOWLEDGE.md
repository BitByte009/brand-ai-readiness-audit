# audit-orchestrator — Engineering Study Guide

> Companion to `SKILL.md`. This is the marketplace's **only entrypoint**. Shared
> vocabulary, the safety model and the shared library are in the root
> `KNOWLEDGE.md`; per-check detail is in each skill's own `KNOWLEDGE.md`.

---

## 1. PURPOSE

Lifecycle only. The orchestrator resolves a target, detects capabilities, runs
exactly one collection pass, invokes six skills in a fixed order, binds evidence,
enforces the schema and emits one report. `SKILL.md` states what it is
*explicitly not*: it detects no site defect and assigns no severity.

Verify that claim in code before trusting it: `grep -n 'severity' run_audit.py`
returns only `severity = finding.get("severity")` inside `_summarize`, i.e. it
*counts* severities, never sets one.

## 2. WHY IT EXISTS

Four reasons visible in the code:

1. **One collection pass.** `collect()` is called exactly once (`run_audit.py:261`).
   Every detector reads the same immutable store. Without this, four skills would
   each crawl the site.
2. **Failure isolation.** `_run_detector` wraps every detector so one crash cannot
   take the audit down (§12).
3. **Cross-skill composition.** `entity_profile` is built once and handed to two
   skills. Pooled findings from four skills go to one scorer.
4. **Contract enforcement.** Evidence binding and schema validation happen in one
   place, after everything else, so no skill can emit an unvalidated report.

## 3. EXACT ENTRYPOINT

`skills/audit-orchestrator/scripts/run_audit.py`.

- **Python API:** `run_audit(url, options=None, *, fetch=None, robots_fetcher=None,
  render_capability=None, now=None, sleep=None) -> dict`. The keyword-only
  parameters are **test seams**; a real invocation leaves them unset.
- **CLI:** `main(argv=None)`.
- `marketplace.json` marks `audit-orchestrator` with `"entrypoint": true`; it is
  the only entry with that key.

**Path bootstrapping** (`run_audit.py:27-31`): `MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]`,
then both the root and the scripts dir are prepended to `sys.path`. This is what
makes the package self-contained — there is no installation step and no absolute
path anywhere.

## 4. CLI / INTERFACE

```
python scripts/run_audit.py <url> [--out-dir DIR] [--max-pages N]
```
- `url` — required, positional.
- `--out-dir` — default `"."`. Writes `report.json` and `report.md`.
- `--max-pages` — validated: `if not 1 <= args.max_pages <= MAX_REQUESTS_PER_AUDIT:
  parser.error(...)`. This prevents both a zero-page audit (which would read like
  a clean site) and a request beyond the platform's own ceiling.

`main()` re-validates the report against the schema and **exits 2 without writing
anything** if invalid — a malformed report is never emitted from the CLI.

## 5. CONFIGURATION

Only `options["budget"]`, merged over `DEFAULT_BUDGET` in `lib/common/budget.py`:

| Key | Default | Enforced where |
|---|---|---|
| `robots_preflight_s` | 10 | stage deadline |
| `raw_crawl_s` | 90 | `crawl(time_left=…)` |
| `raw_crawl_max_pages` | 30 | `budget.can_fetch_page()` |
| `raw_crawl_concurrency` | 4 | **not implemented** — crawling is sequential; `PERFORMANCE_AUDIT.md` calls it "an upper-bound declaration, not actual four-way crawling" |
| `raw_crawl_timeout_s` | 10 | per-request timeout |
| `raw_crawl_polite_delay_s` | 0.2 | `RequestPolicy.delay` |
| `render_sample_s` | 90 | render stage deadline |
| `render_sample_max_pages` | 8 | `budget.can_render_page()` |
| `corroboration_s`, `detectors_scoring_s`, `report_validation_s` | 45/60/15 | **declared, not enforced** — no detector or report deadline exists |
| `model_calls_max` | 14 | counter only; zero calls are made |

**A config value cannot weaken safety.** `RequestPolicy.__init__` clamps
`max_requests` to `MAX_REQUESTS_PER_AUDIT (200)` and `delay` to `max(0.2, delay)`.

## 6–8. INITIALIZATION, CRAWL AND OBSERVATION LIFECYCLE

All three live in `lib/site_observer/collect.py`, driven by
`collect(url, budget, fetch, robots_fetcher, render_capability, now, sleep)`.
`collect` is decorated `@render_mod.reuse_browser`, which is what bounds the
Chromium lifetime to one collection pass (§25).

```
_normalize_url(url)          add https:// if the operator gave a bare host;
                             the PATH IS NEVER TOUCHED — a deep-page audit
                             audits that page, not its homepage
_origin(normalized)          scheme://netloc, used only for robots + host record
RequestPolicy(seed, sleep, delay=budget.polite_delay_s())

── stage: robots_preflight ─────────────────────────────────
  policy.time_left = stage_time_left_s("robots_preflight", …)
  robots = robots_fetcher(origin)         → ROBOTS observation
  policy.robots = robots
  policy.delay = max(policy.delay, Crawl-delay of the selected group)
  degradation = _robots_degradation(robots)
      status in {error, unparseable} → stop, X-COV-01 ROBOTS_DISALLOWED
      (a root Disallow does NOT stop the crawl: every path is checked
       individually, so an explicitly allowed deep path still works)

── stage: raw_crawl (only if degradation is None) ──────────
  crawl(seed, fetch, robots, max_pages, time_left, can_fetch_more,
        on_page_fetched, polite_delay_s=0, sleep)
      polite_delay_s is 0 HERE ON PURPOSE: RequestPolicy already paces
      every admitted request, including redirect hops. A second sleep in
      the page loop would double-pace after slow responses.
  → HTTP_FETCH observation per page
  coverage: NETWORK_POLICY (unsafe URLs skipped), ROBOTS_DISALLOWED
            (paths skipped), BUDGET_EXHAUSTED, INSUFFICIENT_PAGES (<3)
  audited_host is updated if the seed redirected elsewhere

── stage: render_sample (only if renderer available and pages exist) ──
  eligible = pages with 2xx status and non-empty html, per cluster
  sample = stratified_sample(eligible, render_sample_max_pages)
  render_page(final_url, timeout_ms=min(15000, time_left*1000), policy)
  → RENDER observation per sampled page
  coverage: BUDGET_EXHAUSTED (stopped early), RENDER_FAILED (per page),
            RENDERER_UNAVAILABLE (capability absent)

── probe capability check ──────────────────────────────────
  probe_mod.detect_capability() → always {"available": False,
                                          "reason": "MODEL_UNAVAILABLE"}
  coverage: SEARCH_UNAVAILABLE

store = {store_version "1.0", collected_at, target{requested_url,
         requested_host, audited_host, origin}, capabilities{renderer,
         corroboration}, archetype, observations[]}
scope = {archetype, pages_crawled, pages_rendered, template_clusters, disallowed}
```

**Observation identity.** `make_observation(type, source_url, value)` in
`lib/common/observations.py` builds an id from **type + source_url + payload** —
not payload alone, so two identical templated pages keep independently resolvable
evidence (an `OVERFITTING_AUDIT.md` fix).

**Only three observation types are ever produced:** `ROBOTS` (line 96),
`HTTP_FETCH` (169), `RENDER` (211). This single fact drives §21.

## 9. DETECTOR INVOCATION ORDER

`_invoke_detectors(store)`, `run_audit.py:75`:

1. `_register_detector_paths()` — prepends the four detector `scripts/` dirs to
   `sys.path`.
2. `build_entity_profile.build_entity_profile(store)` inside its own try/except.
   On failure: `SKILL_FAILED` coverage scoped to *both* entity-semantic-audit and
   engagement-audit, and `entity_profile` stays `None`.
3. Then, in this exact order:
   ```
   detect_crawl.detect_crawl(store)
   detect_render.detect_render(store)
   detect_extract.detect_extract(store)
   detect_entity.detect_entity(store, entity_profile)
   detect_trust.detect_trust(store)
   detect_engagement.detect_engagement(store, entity_profile)
   ```
Order is fixed and has no semantic dependency — each detector is a pure function
of the store — but it makes the pooled list deterministic, which matters because
`evidence-prioritization` breaks merge ties on canonical JSON rather than order.

Returns `{pooled_findings, skill_failures, coverage}`.

## 10. SHARED DATA STRUCTURES

| Structure | Producer | Consumers |
|---|---|---|
| `store` | `collect()` | all six skills, `bind_evidence`, `proactive` |
| `entity_profile` | `build_entity_profile` | `detect_entity`, `detect_engagement` |
| pooled findings | 4 detectors | `evidence-prioritization` |
| `prioritized` dict | `score.prioritize_findings` | `bind_evidence`, `proactive`, report |
| `coverage[]` | `collect` + orchestrator | report |
| `report` | orchestrator | schema validator, `render_report` |

## 11. HOW THE FIVE SKILLS COMMUNICATE

They do not call each other. All communication is through data structures the
orchestrator passes:

```
        ┌──────────── store ────────────┬──────────────┬─────────────┐
        ▼               ▼               ▼              ▼             │
  crawl-render    entity-semantic   trust-fresh    engagement        │
        │               │  └─entity_profile─────────►│               │
        │               │               │            │               │
        └───────────────┴──── pooled findings ───────┘               │
                                │                                     │
                        evidence-prioritization ◄────────────────────┘
                                │                          (store, optional)
                                ▼
                        orchestrator: bind → validate → emit
```

The only cross-skill data dependency is `entity_profile`. Everything else is the
store or the pooled list.

## 12. HOW DETECTOR FAILURES ARE ISOLATED

`_run_detector(name, fn, *args, failures, coverage)` (`run_audit.py:53`) wraps each
call in `try/except Exception`. On failure it records the error **twice** —
once in `run.skill_failures` for operators, once as an `X-COV-01 / SKILL_FAILED`
coverage entry so the report itself explains the missing checks — and returns `[]`.

`_prioritize` has the same shape. On failure it returns
`{"findings": [], "demoted": [], "rejected": pooled_findings, …}` — every finding
is preserved in `rejected` rather than lost.

The design intent, from the docstring: a crash "scores zero on every rubric line
simultaneously", so degradation is always preferred.

## 13. HOW EVIDENCE MOVES

`validate_report_mod.bind_evidence(prioritized["findings"], store)` →
`(kept, dropped)`.

A finding is **dropped — not demoted, not rescored, simply removed** — unless it
binds one of two ways:
1. `observation_ids` that resolve against `{obs.id}` in the store; **or**
2. `source_urls` naming pages the store actually observed, used with an empty
   `observation_ids` by every **absence** check across three skills.

The docstring explains why (2) exists: there is no single observation ID that
proves something is *missing*; the evidence is "we fetched these pages and the
signal was not there". Requiring a positive ID would silently drop a large,
deliberate class of legitimate findings.

Then `related_findings` are pruned to surviving IDs, and a `dropped` list produces
an `EVIDENCE_UNRESOLVED` coverage entry.

## 14. SCORING

Delegated entirely to `evidence-prioritization`. See that skill's KNOWLEDGE §G–H.
The orchestrator supplies `store` (used only by `_importance_modifier`) and
consumes `{findings, demoted, rejected, merge_log, calibration_log}`.

## 15. PROACTIVE OPPORTUNITIES

`proactive_mod.generate_proactive_opportunities(store, prioritized["demoted"], kept_findings)`
— `scripts/proactive.py`.

Four implemented sources; `references/proactive-layer.md` documents all seven:

| Source | Fires when | Confidence |
|---|---|---|
| `identity_anchor_gap` (2) | Organization/Person JSON-LD with no `sameAs` | high |
| `demoted_finding` (4) | a finding was demoted below the confidence floor | low |
| `answer_markup_gap` (6) | ≥3 question-shaped headings each with ≥25 words of answer prose, and no FAQPage/QAPage markup | high at ≥5, else medium |
| `section_anchor_gap` (7) | ≥4 sections of ≥40 words and **no** heading carries an `id` | medium |

Sources 1 and 3 need the probe/corroboration instrument and produce nothing;
source 5's items would need an extra fetch.

**The FINDING/OPPORTUNITY distinction is structural, not stylistic.** Every source
requires *positive evidence of health* as a precondition — prose that actually
answers its own question, sections that actually carry content. That is what
prevents an opportunity from being a demoted defect in softer wording. Returning
zero opportunities is a correct outcome.

Three emission guards: `_is_grounded` (rejects anything missing title, evidence,
why-it-matters, action, validation, a valid confidence, or an anchor),
`_deduplicate` (on `(source, title, scope)`), and suppression on any page that
already carries a `D-EXTRACT` finding.

## 16. DEDUPLICATION — three different mechanisms

Do not confuse them:

| Layer | What it dedupes | Where |
|---|---|---|
| Findings | same defect from multiple detectors | `aggregate_dedupe._dedupe_key` + overlapping affected instances |
| Coverage | identical `(reason, scope)` rows | `run_audit._deduplicate_coverage` |
| Proactive | identical `(source, title, source_urls)` | `proactive._deduplicate` |
| Report-level | *exact* repeated finding content | `lib/common/schema.validate_report` fingerprint check |

## 17. REPORT VALIDATION

`lib/common/schema.validate_report(report)` does more than JSON Schema:
1. `json.dumps(report, allow_nan=False)` — rejects NaN/Infinity outright.
2. Draft 2020-12 validation against `schemas/report.schema.json`.
3. Duplicate finding **IDs**.
4. Duplicate finding **content** (fingerprint over everything except `id`,
   `related_findings`, `scoring_trace`).
5. Summary counts match actual severity counts.
6. `suggested_action.priority == severity` for every finding.
7. `related_findings` resolve and are not self-references.
8. `affected.count <= total_in_scope`, and `len(sample_urls) <= count`.

Also registers a `date-time` format checker so `audited_at` must be a zoned
RFC-3339 timestamp — with no optional format package.

## 18. FINAL REPORT ASSEMBLY

`run_audit.py:301-320`, in order:

```python
report = {
  "site": store["target"]["audited_host"],
  "audited_at": store["collected_at"],
  "summary": _summarize(kept_findings),
  "findings": kept_findings,
  "scope": collected["scope"],
  "coverage": coverage,
  "proactive_opportunities": proactive_opportunities,
  "demoted": prioritized["demoted"],
  "run": {capabilities, budget, skill_failures, evidence_binding_drops,
          merge_log, calibration_log, rejected_findings},
}
is_valid, errors = validate_report_schema(report)
report["run"]["schema_valid"] = is_valid
if not is_valid: report["run"]["schema_errors"] = errors
```

`run_audit()` **never raises** and always returns a schema-shaped dict.
`report["run"]["schema_valid"]` is the honest signal — `SKILL.md` warns that "exit
zero alone does not prove a complete or valid audit".

## 19. SEVERITY COUNTS

`_summarize(findings)` counts `critical/high/medium/low` over `kept_findings` only
and adds `total_findings`. Consequences worth internalizing:
- **Demoted findings are not counted.** A low-confidence critical defect does not
  appear in the totals; it appears in `demoted[]`.
- **Dropped (unbound) findings are not counted.**
- **Rejected (malformed) findings are not counted.**
- **Proactive opportunities are never counted** — enforced by the schema check
  that summary equals the actual `findings` array.

## 20. COVERAGE GAPS

Every entry is `{check_id: "X-COV-01", status, reason, detail, scope}`.
`X-COV-01` is a bookkeeping ID, not a finding ID. Reason codes in use:
`ROBOTS_DISALLOWED, RENDERER_UNAVAILABLE, SEARCH_UNAVAILABLE, BUDGET_EXHAUSTED,
INSUFFICIENT_PAGES, NETWORK_POLICY, RENDER_FAILED, SKILL_FAILED,
EVIDENCE_UNRESOLVED, UNAVAILABLE_INSTRUMENT`.

Core principle from `references/coverage-policy.md`: **a check that could not run
must never look like a check that passed.**

## 21. UNAVAILABLE INSTRUMENTS

`_unavailable_instrument_coverage(store)` (`run_audit.py:173`). Availability is
derived from **the observations actually collected**, not a hardcoded flag — wire
a real instrument later and the entries disappear on their own.

| Missing observation | Checks named | Scope |
|---|---|---|
| `PROBE` | `D-EXTRACT-01, 03, 06, 07`, `D-RENDER-02`, `E-ANSWER-04` | whether a specific fact is extractable from the page's text |
| `CLAIM_CORROBORATION` | `D-ENTITY-03`, `D-TRUST-05` | whether claims/identity are supported beyond the site |
| `SITEMAP` | `D-CRAWL-07` | sitemap quality; the orphan half is still evaluated |
| crawl telemetry (`capabilities.crawl`) | `D-CRAWL-14` | whether the crawl was cut short by budget |

Ten check IDs. The detail text says "These checks did not pass; they did not run."
`coverage-policy.md` names this the **third state**: not evaluated-and-passed, not
evaluated-and-failed, but *not evaluable*.

The list is precise, not over-broad: `D-CRAWL-08`, `D-ENTITY-02`, `E-ANSWER-01`
and `E-CONTINUE-01` all *mention* an unavailable instrument but use it as a soft
refinement and demonstrably fire without it, so they are deliberately excluded.
`tests/test_audit_orchestrator.py::test_declared_unevaluable_checks_actually_exist_in_the_detectors`
guards the list against drift.

## 22. ROBOTS.TXT FLOW

1. `fetch_robots(origin, timeout, policy)` — `policy.admit(url, preflight=True)`
   permits **only** `/robots.txt` with no query.
2. Status mapping: `404 → "missing"` (allow all); `200 → parse_robots(text)`;
   **anything else → `"error"`**, including redirects (`allow_redirects=False`).
3. `_robots_degradation`: `error`/`unparseable` stop crawling entirely.
   A root `Disallow: /` does **not** — every path is checked individually so an
   explicitly allowed deep path still works.
4. Per-request: `RequestPolicy.admit` calls
   `robots_allows_every_interpretation(robots, path+query)`, which fails closed if
   *any* server-side reading of the path is disallowed (§ root KNOWLEDGE §9).
5. `Crawl-delay` from the selected group raises `policy.delay`.

**Two different robots evaluators, on purpose.** The fetch decision uses the
fail-closed `robots_allows_every_interpretation`. `D-CRAWL-01` uses the plain
`robots_allows`, because the *audit judgement* must report what the site's rules
literally say, not what our safety policy chose to avoid.

## 23. URL NORMALIZATION

Two distinct normalizations:
- **`collect._normalize_url`** — adds a scheme to a bare host. **Never touches the
  path.**
- **`crawl.canonical_resource_url`** — the crawl-frontier identity: lowercases
  scheme+host, drops the default port, drops the fragment, and collapses a trailing
  directory-index filename (`index.html/htm/php`, `default.html/htm`).
  Deliberately **not** normalized: the query string, and trailing slashes on
  non-index paths — both can address genuinely different resources.

## 24. REQUEST AND RENDER BUDGETS

Layered, and the outer layer cannot be widened by configuration:
```
MAX_REQUESTS_PER_AUDIT = 200   hard ceiling, both lenses, clamped in RequestPolicy
raw_crawl_max_pages    = 30    page budget
render_sample_max_pages = 8    render budget
delay                  >= 0.2s clamped; raised by Crawl-delay
stage deadlines        robots 10s / crawl 90s / render 90s
observe_status         429 or 503 ⇒ policy.stopped = True (no retry)
```

## 25. CHROMIUM LIFECYCLE

`collect` is wrapped in `@render_mod.reuse_browser`, which sets a `ContextVar`
holding an `ExitStack`. `_browser_instance()` launches Chromium **once per
collection pass** with `chromium_sandbox=True` and registers `browser.close` on the
stack; each page gets a **fresh context** (`service_workers="block"`,
`accept_downloads=False`) closed in a `finally`.

Measured: one browser process per pass, and 55 Chromium processes before a run,
55 after — no leak. `render_page` never raises: capability-absent, error and
success all return the same record shape.

## 26. ERROR HANDLING

| Failure | Handling |
|---|---|
| detector raises | `_run_detector` → `SKILL_FAILED` coverage + `skill_failures` |
| entity profile raises | try/except → `SKILL_FAILED` scoped to two skills, `profile=None` |
| prioritization raises | `_prioritize` → all findings preserved in `rejected` |
| collection network failure | `fetch_url` returns an error record with `evidence.coverage_gap` |
| render failure | `RENDER_FAILED` coverage; audit continues |
| schema invalid | `run.schema_valid = False` + `schema_errors`; CLI exits 2 without writing |
| robots unreachable | `ROBOTS_DISALLOWED` coverage, zero pages |

## 27. GRACEFUL DEGRADATION

Verified from a freshly extracted archive with no Playwright installed: the audit
produced a schema-valid report, zero `skill_failures`, and three disclosure
reasons (`RENDERER_UNAVAILABLE`, `SEARCH_UNAVAILABLE`, `UNAVAILABLE_INSTRUMENT`).
Missing capability becomes coverage, never a silent pass and never a crash.

## 28. DETERMINISM

- Zero model calls (`model_calls_made: 0` in every run).
- `now` and `sleep` are injectable; `collected_at` is the only clock read.
- Observation IDs are content-derived.
- Merge ties break on canonical JSON, not execution order.
- `rank_findings`'s sort key ends with `check_id`, making the sort total.
- `test_run_audit_is_deterministic_given_the_same_inputs` asserts two identical
  runs produce identical reports.

## 29. SAFETY BOUNDARIES

The orchestrator does not implement safety; it *inherits* it by routing all
network access through `collect` → `RequestPolicy` → `request_once` →
`PublicOnlyAdapter`. See root KNOWLEDGE §9. The orchestrator's own contributions:
the `--max-pages` bound, and the fact that no skill may fetch anything (verified:
no `requests` import in any `skills/*/scripts/` file except a docstring mention in
`corroborate.py`).

## 30. FINAL OUTPUT CONTRACT

`report.json` (schema-validated) and `report.md` (`render_report.render_markdown`).
The Markdown renderer escapes HTML/Markdown/terminal/bidi control characters, caps
each rendered string at `MAX_QUOTED_CHARS = 400` truncating on the *escaped* form,
and emits `UNTRUSTED_CONTENT_NOTICE` plus `OPPORTUNITY_DEFINITION`.

---

## ARCHITECTURE DIAGRAM

```
                              run_audit.py  main()
                                     │  --max-pages bounded 1..200
                                     ▼
                              run_audit(url, options)
                                     │
        ┌────────────────────────────▼─────────────────────────────┐
        │ collect()   @reuse_browser        ONE PASS, ONE BROWSER   │
        │  ┌────────────────────────────────────────────────────┐  │
        │  │ RequestPolicy: GET/HEAD, same-origin, robots,      │  │
        │  │   ≥0.2s pacing, ≤200 requests, 429/503 backoff     │  │
        │  │ PublicOnlyAdapter: sockets pinned to public IPs    │  │
        │  └────────────────────────────────────────────────────┘  │
        │  robots → BFS crawl (≤30) → stratified render (≤8)       │
        └────────────────────────────┬─────────────────────────────┘
                                     │ store + coverage + budget + scope
                                     ▼
        ┌──────────────────────── _invoke_detectors ───────────────┐
        │  build_entity_profile ──┐                                │
        │  detect_crawl           │                                │
        │  detect_render          ├─► pooled findings (unscored)   │
        │  detect_extract         │                                │
        │  detect_entity ◄────────┤ entity_profile                 │
        │  detect_trust           │                                │
        │  detect_engagement ◄────┘                                │
        │  each wrapped by _run_detector → SKILL_FAILED coverage   │
        └────────────────────────────┬─────────────────────────────┘
                                     ▼
                 evidence-prioritization.prioritize_findings
                 normalize → dedupe → score → demote → guard
                          → rank → assign F-ids → link
                                     │
              findings / demoted / rejected / merge_log / calibration_log
                                     ▼
                 bind_evidence(findings, store) → kept, dropped
                                     ▼
             coverage += _unavailable_instrument_coverage(store)
                       coverage = _deduplicate_coverage(coverage)
                                     ▼
          proactive.generate_proactive_opportunities(store, demoted, kept)
                                     ▼
                      assemble report → validate_report()
                                     ▼
                        report.json  +  report.md
```

---

## FUNCTION-BY-FUNCTION WALKTHROUGH — what calls what, in what order

```
main(argv)
 ├─ argparse; validate --max-pages against MAX_REQUESTS_PER_AUDIT
 ├─ run_audit(url, options)
 │   ├─ Budget(options["budget"])
 │   ├─ collect(url, budget, …)                         [lib/site_observer]
 │   │    ├─ _normalize_url / _origin
 │   │    ├─ RequestPolicy(seed, sleep, delay)
 │   │    ├─ fetch_robots → make_observation("ROBOTS")
 │   │    ├─ _robots_degradation
 │   │    ├─ crawl(...) → fetch_url per page → make_observation("HTTP_FETCH")
 │   │    ├─ stratified_sample → render_page → make_observation("RENDER")
 │   │    └─ probe.detect_capability() → SEARCH_UNAVAILABLE coverage
 │   ├─ _invoke_detectors(store)
 │   │    ├─ _register_detector_paths()
 │   │    ├─ build_entity_profile(store)                [try/except]
 │   │    └─ _run_detector × 6                          [try/except each]
 │   ├─ _prioritize(pooled, store, failures, coverage)  [try/except]
 │   │    └─ score.prioritize_findings                  [evidence-prioritization]
 │   ├─ validate_report_mod.bind_evidence(findings, store)
 │   ├─ prune related_findings to surviving ids
 │   ├─ coverage += _unavailable_instrument_coverage(store)
 │   ├─ coverage  = _deduplicate_coverage(coverage)
 │   ├─ proactive.generate_proactive_opportunities(store, demoted, kept)
 │   ├─ assemble report dict
 │   └─ validate_report_schema(report) → run.schema_valid
 ├─ validate_report_schema again; parser.exit(2) if invalid
 ├─ write report.json
 └─ render_report.render_markdown(report) → report.md
```

---

## SINGLE AUDIT WALKTHROUGH — a hypothetical site

`python scripts/run_audit.py https://meridian.example/ --out-dir ./out`

A 4-page brochure site: `/`, `/support.html` (5 Q&A sections), `/guide.html`
(5 long sections), `/about.html`. Valid `Organization` JSON-LD with `sameAs` on
every page. Nav in `<nav>`. Playwright installed.

| # | Step | Result | Deterministic? |
|---|---|---|---|
| 1 | `--max-pages` unset | budget defaults | yes |
| 2 | `_normalize_url` | already has a scheme | yes |
| 3 | robots preflight | `/robots.txt` 200, `Allow: /` → `ROBOTS` obs | yes (network-dependent) |
| 4 | BFS crawl | `/` and `/index.html` **collapse to one resource** via `canonical_resource_url`; 4 pages fetched, 4 `HTTP_FETCH` obs, ≥0.2s apart | yes |
| 5 | render sample | clusters stratified, ≤8 pages rendered in one browser process | yes |
| 6 | probe | unavailable → `SEARCH_UNAVAILABLE` coverage | yes |
| 7 | `build_entity_profile` | `_structured_identity` passes all five conditions → `canonical_name.determined_by = "structured_identity"`, `consistent = True` | yes |
| 8 | `detect_crawl` | robots fine, no dead pages, no canonical conflicts → `[]` | yes |
| 9 | `detect_render` | raw/rendered ratios above 0.30 → `[]` | yes |
| 10 | `detect_extract` | titles/descriptions unique, JSON-LD valid → `[]`; probe-gated checks silently produce nothing | yes |
| 11 | `detect_entity` | `consistent=True` ⇒ no `D-ENTITY-01`; authoritative description ⇒ no `D-ENTITY-04`; `sameAs` present ⇒ no `D-ENTITY-05` → `[]` | yes |
| 12 | `detect_trust` | no undated time-sensitive claims, no conflicts → `[]` | yes |
| 13 | `detect_engagement` | nav reaches ≥2 internal destinations ⇒ no `E-CONTINUE-01/02`; brand tokens present ⇒ no `E-ORIENT-01` → `[]` | yes |
| 14 | prioritization | empty in, empty out | yes |
| 15 | `bind_evidence` | nothing to bind | yes |
| 16 | unavailable-instrument coverage | 4 entries naming 10 check IDs | yes |
| 17 | proactive | `answer_markup_gap` on `/support.html` (5 answered questions, no FAQPage) — **high**; `section_anchor_gap` on `/guide.html` (5 sections ≥40 words, no heading ids) — **medium** | yes |
| 18 | assemble + validate | `summary: 0 findings`, 2 opportunities, `schema_valid: true` | yes |

**Final:** zero findings, two evidence-grounded opportunities. That is the correct
output for a healthy site, and it exercises the FINDING/OPPORTUNITY distinction
end to end.

**Steps that would depend on unavailable capabilities:** 10, 11 and 13 would
additionally evaluate the ten probe/corroboration-gated checks. Step 3 is the only
network-dependent step whose outcome could vary between runs.

---

## READ THESE FILES NEXT

1. `references/orchestration-rules.md` — the budget table and stage contract.
2. `references/coverage-policy.md` — the three states a check can be in.
3. `lib/site_observer/collect.py` — 274 lines, top to bottom. This *is* the
   lifecycle.
4. `scripts/run_audit.py::run_audit` — follow the eleven statements in order.
5. `scripts/validate_report.py::bind_evidence` — read the docstring in full.
6. `lib/common/schema.py::validate_report` — the eight post-schema invariants.
7. `scripts/proactive.py` — module docstring, then `_is_grounded`.
8. `references/degraded-mode.md` and `proactive-layer.md`.
9. `tests/test_audit_orchestrator.py` — the integration tests at the end.
10. Root `KNOWLEDGE.md` §9 (safety) and §17 (bug history).
