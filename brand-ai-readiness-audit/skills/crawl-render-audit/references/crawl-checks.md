# D-CRAWL — reachability (gate 1)

Twelve-field form for every check this skill owns in this category, per
`<marketplace-root>/references/failure-taxonomy.md`. Implemented in `scripts/detect_crawl.py`.
Store types referenced below are defined in `store-contract.md`.

All thresholds are ratios/percentiles or fixed structural tests, never a hostname,
brand, vertical, CMS, or framework name (`PROJECT_CONTEXT.md` generalization rule).
Finding unit is `(check_id, template_cluster)`; `affected` always carries
`{count, sample_urls[<=5], total_in_scope}`.

---

## D-CRAWL-01 — robots.txt disallows content paths
- **Meaning:** `robots.txt` blocks a path that leads to substantive, citable content.
- **Mechanism:** Appendix A gate 1. A disallowed path is never fetched by a compliant
  crawler; the content behind it does not exist for that system at all.
- **Applicability:** `ROBOTS` observation present with `status == "ok"`; at least one
  discovered internal URL (from the link graph or `SITEMAP`) is not a utility path.
- **Observable signals:** `robots_allows(robots, path)` result per discovered URL.
- **Detection test:** for every discovered internal URL that is not a utility path
  (see `store-contract.md`), evaluate `robots_allows`. Fire per template cluster where
  `>=1` non-utility URL is disallowed.
- **Evidence required:** `OBS-ROBOTS-*`, the matching `disallow` line, the disallowed
  URL(s).
- **False-positive rules:** never fires on a utility path (cart, search, checkout,
  login, account, wishlist, admin, or any URL carrying a query string) — disallowing
  those is correct practice. Never fires if `ROBOTS.status != "ok"` (that is
  D-CRAWL-15's concern, not this check's).
- **False-negative risks:** a robots rule scoped to a sub-path we never discovered a
  link to is invisible to this check; mitigated by also testing `SITEMAP` entries.
- **Severity:** critical (the taxonomy's total-invisibility list — disallowed content
  literally cannot be reached).
- **Confidence:** high — robots evaluation is a pure deterministic string test.
- **Recommendation:** remove the `Disallow` rule for the named path, or, if the
  content genuinely should be blocked, confirm it carries no unique substantive
  content reachable no other way.
- **Validation:** re-fetch `robots.txt`; `robots_allows()` on the named path returns
  `true`.

## D-CRAWL-02 — AI crawler user-agents specifically blocked
- **Meaning:** a named AI-crawler group (`GPTBot`, `ChatGPT-User`, `Google-Extended`,
  `PerplexityBot`, `CCBot`, ...) carries `Disallow` rules stricter than the `*` group.
- **Mechanism:** Appendix A gate 1, selective exclusion. The site is reachable to
  generic crawlers but has deliberately opted an AI system out.
- **Applicability:** `ROBOTS.status == "ok"`; at least one named AI-bot group exists
  in `document.groups`.
- **Observable signals:** disallow-rule set of each AI-bot group versus the `*` group.
- **Detection test:** for each AI-bot group whose user-agent is in the recognized set
  (`gptbot`, `chatgpt-user`, `google-extended`, `openai-bot`, `perplexitybot`,
  `ccbot`, `claudebot`, `anthropic-ai`), fire if its disallow rule set is a superset
  of the `*` group's (i.e. it blocks paths `*` does not).
- **Evidence required:** `OBS-ROBOTS-*`, the specific group block quoted verbatim.
- **False-positive rules:** **this may be a deliberate business decision.** Always
  reported neutrally as a discoverability *consequence*, never as an error; base
  severity is downgraded from the gate default and the finding text says so
  explicitly, never implying the site owner made a mistake.
- **False-negative risks:** a bot blocked by IP/WAF rather than robots.txt is
  invisible to this check — that is D-CRAWL-09's job (server-level blocking).
- **Severity:** medium (downgraded from the gate's high default per the guardrail
  above — see revision log in `failure-taxonomy.md`).
- **Confidence:** high.
- **Recommendation:** state, factually, which AI systems are opted out and what
  citation reach is forgone; change only if the exclusion was not intentional.
- **Validation:** re-fetch `robots.txt`; the named group's disallow set no longer
  exceeds `*`.

## D-CRAWL-03 — noindex on substantive pages
- **Meaning:** `<meta name="robots" content="noindex">` or `X-Robots-Tag: noindex`
  appears on a page carrying substantive, citable content.
- **Mechanism:** Appendix A gate 1. `noindex` is an explicit instruction to exclude
  the page from indexes, which most citation pipelines respect.
- **Applicability:** `HTTP_FETCH.status_code == 200`; page is not a utility path;
  rendered/raw text length exceeds the short-page floor (400 chars) used elsewhere in
  this taxonomy, so a stub page isn't mistaken for a suppressed substantive one.
- **Observable signals:** `<meta name="robots">`/`<meta name="googlebot">` content
  and the `X-Robots-Tag` response header, parsed for the `noindex` token.
- **Detection test:** fire per template cluster where `>=1` non-utility, substantive
  page carries `noindex` in either signal.
- **Evidence required:** `OBS-HTTP-FETCH-*`, the matched tag or header value quoted.
- **False-positive rules:** never fires on staging/preview hosts (the audited host
  itself, not a defect of this page); never fires on tag/filter, thank-you, cart,
  search, checkout, or print pages — those are legitimately noindexed.
- **False-negative risks:** a `noindex` served only to specific crawler UAs via
  server config is invisible to an honest single-UA fetch; out of scope per D-CRAWL-09
  (no UA spoofing).
- **Severity:** critical (total-invisibility list).
- **Confidence:** high.
- **Recommendation:** remove the `noindex` directive from the named page(s) unless
  they are intentionally excluded (thank-you/cart/search/print), in which case no
  action is needed.
- **Validation:** re-fetch the page; neither the meta tag nor the header carries
  `noindex`.

## D-CRAWL-04 — dead or soft-404 pages
- **Meaning:** a page returns 4xx/5xx, or 200 with a body indicating the resource
  does not exist (soft-404).
- **Mechanism:** Appendix A gate 1. A dead page cannot be read regardless of what a
  sitemap or internal link claims.
- **Applicability:** URL was discovered via the link graph or `SITEMAP` and an
  `HTTP_FETCH` observation exists for it.
- **Observable signals:** `status_code`; for `200` responses, a soft-404 heuristic —
  extracted text under the short-page floor **and** containing a not-found phrase
  pattern (structural: a 3-5 word phrase combining "not found"/"does not exist"/
  "no longer available" with the page's own H1 or title empty).
- **Detection test:** fire per template cluster where `status_code >= 400`, or the
  soft-404 heuristic matches, on `>=1` page — after one retry on a single transient
  5xx (retry recorded, not re-fetched a second time if it succeeds).
- **Evidence required:** `OBS-HTTP-FETCH-*`, status code, retry outcome if applicable.
- **False-positive rules:** a single transient 5xx that succeeds on retry is not
  flagged. Utility paths that intentionally 404 (e.g. a removed promo) are still
  flagged if discovered via `SITEMAP` — a sitemap listing a dead URL is itself the
  defect (see D-CRAWL-07's sibling rule).
- **False-negative risks:** soft-404 pages using an unusual phrasing not matched by
  the heuristic are undercounted; the ratio-based short-page signal still catches the
  emptiness half independently in D-EXTRACT checks.
- **Severity:** high.
- **Confidence:** high for hard status codes; medium for the soft-404 heuristic.
- **Recommendation:** fix the broken route, 301 to the correct resource, or remove
  the dead link/sitemap entry that points at it.
- **Validation:** re-fetch; status is `200` and the soft-404 phrase pattern no longer
  matches.

## D-CRAWL-05 — redirect chain faults
- **Meaning:** a URL redirects through `>=3` hops, loops back on itself, or performs
  an unnecessary `http→https→www`-style multi-hop where one hop would do.
- **Mechanism:** Appendix A gate 1. Each hop is a chance for a crawler to give up,
  and adds latency against the crawl-budget ceiling every citation pipeline has.
- **Applicability:** `HTTP_FETCH.redirect_chain` is non-empty.
- **Observable signals:** hop count; whether any `to` URL repeats an earlier `from`
  URL in the same chain (loop).
- **Detection test:** fire when hop count `>= 3`, or a loop is detected, on any
  sampled URL.
- **Evidence required:** `OBS-HTTP-FETCH-*`, the full `redirect_chain`.
- **False-positive rules:** exactly one canonical hop (e.g. `http -> https`, or
  apex `-> www`, or trailing-slash normalization) is normal and never flagged alone;
  only the combination reaching `>=3` total hops, or an actual loop, fires.
- **False-negative risks:** none material — the chain is fully observed by the fetcher.
- **Severity:** medium.
- **Confidence:** high.
- **Recommendation:** collapse the chain to a single redirect from the requested URL
  directly to the final canonical URL.
- **Validation:** re-fetch the original URL; `redirect_chain` length is `<=1`.

## D-CRAWL-06 — canonical conflicts
- **Meaning:** `<link rel="canonical">` points cross-domain, at a URL that itself
  404s or is noindexed, or contradicts the sitemap's own listing of the page.
- **Mechanism:** Appendix A gate 1. A citation pipeline that follows the canonical
  signal ends up at content that doesn't exist or isn't indexable, losing the page.
- **Applicability:** `HTTP_FETCH.status_code == 200`; `extract_canonical_url` returns
  a value different from the page's own final URL.
- **Observable signals:** canonical target's registrable domain vs. the audited
  host's; canonical target's own `HTTP_FETCH.status_code` and `noindex` state, where
  that target was itself crawled.
- **Detection test:** fire when the canonical target is same-domain and (a) its own
  fetch returns `>=400`, or (b) it carries `noindex`, or (c) it is same-domain but
  listed under a different URL in `SITEMAP` with no explanation (a straightforward
  same-domain mismatch).
- **Evidence required:** `OBS-HTTP-FETCH-*` for the source page and, where crawled,
  for the canonical target; both URLs quoted.
- **False-positive rules:** a cross-domain canonical is never flagged on its own —
  legitimate on syndicated content. Only same-domain canonicals pointing at broken or
  noindexed targets fire.
- **False-negative risks:** if the canonical target was never crawled, this check
  cannot confirm its status and does not fire (applicability requires the target's
  own `HTTP_FETCH` for the 404/noindex sub-tests).
- **Severity:** high.
- **Confidence:** high when the target was crawled; the check does not fire at lower
  confidence — it stays silent instead (per the applicability precondition).
- **Recommendation:** point the canonical at a URL that actually resolves and is
  indexable, or remove the tag if the page is genuinely self-canonical.
- **Validation:** re-fetch the source page; the canonical target now returns `200`
  with no `noindex`.

## D-CRAWL-07 — sitemap absence or rot
- **Meaning:** no `sitemap.xml` is discoverable, or the sitemap lists dead/redirecting
  URLs.
- **Mechanism:** Appendix A gate 1. The sitemap is a crawler's primary discovery
  shortcut; its absence forces link-graph-only discovery, and rot wastes crawl budget
  on dead ends.
- **Applicability:** a crawl attempt for `/sitemap.xml` and any `Sitemap:` line in
  `robots.txt` both occurred (`SITEMAP` observation present, or `ROBOTS` present and
  parsed with no `Sitemap:` line and a direct `/sitemap.xml` fetch also absent).
- **Observable signals:** `SITEMAP.status`; per-entry `status_code` for a sampled
  subset of listed URLs.
- **Detection test:** **absence only fires together with orphan pages** (see
  D-CRAWL-08) — on its own it does not fire. Rot fires independently: `>=20%` of
  sampled sitemap entries return `>=400` or redirect.
- **Evidence required:** `OBS-SITEMAP-*` (rot case); for the absence case, also
  `OBS-CRAWL-ORPHAN-*` evidence from D-CRAWL-08's own detection.
- **False-positive rules:** **absence is not a defect on a small, fully-interlinked
  site** — only flagged when orphan pages also exist, per the applicability/detection
  split above.
- **False-negative risks:** a sitemap present but not linked from `robots.txt` and
  guessed at a non-standard path is not discovered; we do not guess paths beyond
  `/sitemap.xml` (never guess URL patterns, `PHASE1B` Part 5).
- **Severity:** medium.
- **Confidence:** high for rot (direct status check); medium for the absence+orphan
  combination.
- **Recommendation:** publish `/sitemap.xml` and reference it from `robots.txt`
  (absence case); remove or fix the dead/redirecting entries (rot case).
- **Validation:** re-fetch `/sitemap.xml`; it exists and `<20%` of a fresh sample
  returns non-200.

## D-CRAWL-08 — orphaned important pages
- **Meaning:** a page listed in the sitemap is reachable by no internal link from
  anywhere else on the crawled site.
- **Mechanism:** Appendix A gate 1. A crawler that discovers pages primarily by
  following links (no sitemap, or one it distrusts) never reaches this page at all.
- **Applicability:** `SITEMAP` observation present with `status == "ok"`; the derived
  link graph (see `store-contract.md`) covers `>=3` crawled pages (minimum-corpus
  rule).
- **Observable signals:** in-degree of each sitemap URL within the derived internal
  link graph.
- **Detection test:** fire per template cluster where `>=1` sitemap URL has in-degree
  `0` (no internal link, from any crawled page, targets it) and it is not itself a
  utility path.
- **Evidence required:** `OBS-SITEMAP-*`, the derived link-graph edge list summary
  (or its absence for the named URL).
- **False-positive rules:** utility/legal pages (privacy, terms, cookie policy) don't
  need link equity and are excluded from this check by the utility-path test. The
  root path is never counted — it is definitionally the crawl's entry point, not a
  page reached by an internal link.
- **False-negative risks:** below the 3-page minimum-corpus floor this check disables
  entirely rather than reporting on a statistically meaningless graph.
- **Severity:** medium.
- **Confidence:** high — link-graph membership is a direct structural fact.
- **Recommendation:** add an internal link to the orphaned page from a relevant,
  already-linked page (its topical parent or the primary nav).
- **Validation:** re-crawl; the page's in-degree in the derived link graph is `>=1`.

## D-CRAWL-09 — bot-hostile serving
- **Meaning:** our own honest, single-UA fetch is blocked, challenged, or served an
  interstitial that a non-browser client cannot pass.
- **Mechanism:** Appendix A gate 1. No named-crawler spoofing is performed
  (`PROJECT_CONTEXT.md` D-10) — this check reports only what our one honest fetch
  actually experienced.
- **Applicability:** an `HTTP_FETCH` observation exists for the URL.
- **Observable signals:** `status_code == 403`; a `Content-Type` mismatch where the
  body is a known challenge shell (short body, `<title>` matching a
  challenge/verification phrase pattern, and a `Set-Cookie`/meta-refresh pointing at
  a challenge endpoint) rather than the requested content.
- **Detection test:** fire when, after one retry with backoff (to rule out rate
  limiting we ourselves triggered), the same block/challenge signature recurs.
- **Evidence required:** `OBS-HTTP-FETCH-*` for both the original and retry attempt,
  status codes, and the matched challenge signature.
- **False-positive rules:** a single 403/429 that clears on a backed-off retry is
  rate limiting, not a block, and is never flagged; never spoof a different UA to
  "confirm" the block (D-10) — the finding is scoped strictly to what our declared,
  honest identity experienced.
- **False-negative risks:** a WAF that allow-lists common crawler UAs and blocks only
  unrecognized ones (ours) may over-fire relative to what GPTBot itself would
  experience; the finding text is scoped to "our fetch," never generalized to "all
  crawlers," to keep the claim honest.
- **Severity:** critical (total-invisibility list).
- **Confidence:** high.
- **Recommendation:** allow-list a documented, honest crawler identity, or move the
  challenge behind authenticated/high-risk paths only rather than the whole site.
- **Validation:** re-fetch with the same UA; status is `200` and the body is the
  requested content, not a challenge shell.

## D-CRAWL-10 — fetch cost likely to cause crawler timeout
- **Meaning:** time-to-first-byte or transfer size is high enough that a
  budget-constrained crawler is likely to abandon the page.
- **Mechanism:** Appendix A gate 1. Citation pipelines run under their own timeouts;
  a slow origin is functionally unreachable even with zero blocking rules.
- **Applicability:** `>=5` sampled `HTTP_FETCH` observations exist (per revision log:
  never flag from one slow request).
- **Observable signals:** TTFB and transfer-size distribution across the sample.
- **Detection test:** fire only when the median sampled TTFB exceeds a stated
  threshold (3s) by a `3x` margin **and** `>=5` samples support it (capped at medium
  per `failure-taxonomy.md` revision log — thin evidence, our network conditions are
  not the user's).
- **Evidence required:** `OBS-HTTP-FETCH-*` timing for each sample, the computed
  median and margin.
- **False-positive rules:** never fires from a single slow request; never fires below
  the 5-sample floor.
- **False-negative risks:** our vantage point is one network location (`D-CRAWL-12`
  records this as a standing caveat); a slow-only-from-elsewhere origin is invisible.
- **Severity:** medium (capped).
- **Confidence:** medium.
- **Recommendation:** investigate origin TTFB (caching, CDN, server-side rendering
  cost) for the affected template.
- **Validation:** re-sample `>=5` pages of the same template; median TTFB within `2x`
  of the 3s threshold.

## D-CRAWL-11 — locale signal conflicts
- **Meaning:** multi-locale content exists with no `hreflang` annotations, or with
  `hreflang` values that contradict each other (two tags claiming the same locale for
  different URLs, or a self-referencing tag missing).
- **Mechanism:** Appendix A gate 1. Ambiguous locale signals split citation authority
  across duplicates and risk serving the wrong-language version to a crawler.
- **Applicability:** `>=2` crawled URLs are near-duplicate content (same template
  cluster, high text-similarity) differing primarily in a locale path/subdomain
  segment.
- **Observable signals:** presence and target consistency of `<link rel="alternate"
  hreflang="...">` across the locale variants.
- **Detection test:** fire when no variant in the group carries `hreflang`
  annotations, or when two variants declare the same `hreflang` value for different
  URLs.
- **Evidence required:** `OBS-HTTP-FETCH-*` for each variant, the `hreflang` set
  found on each.
- **False-positive rules:** a single-locale site is never evaluated (applicability
  requires `>=2` detected locale variants of the same content).
- **False-negative risks:** locale variants not discovered because they sit behind a
  client-side language switcher with no crawlable URL are invisible here — that
  overlaps D-RENDER-03 (render-only navigation) instead.
- **Severity:** medium.
- **Confidence:** high once `>=2` variants are confirmed.
- **Recommendation:** add self-referencing and cross-referencing `hreflang` tags
  across every locale variant of the page.
- **Validation:** re-fetch each variant; every variant in the group carries a
  consistent, mutually-referencing `hreflang` set.

## D-CRAWL-12 — geographic serving variance
- **Meaning:** content or availability appears to vary by requester geography.
- **Mechanism:** Appendix A gate 1. We audit from one vantage point; an assistant's
  fetch may originate elsewhere and see different content, which we cannot directly
  observe.
- **Applicability:** always — this check mostly emits a scope caveat, not a defect.
- **Observable signals:** none directly measurable from a single vantage point.
- **Detection test:** never fires as a defect on its own observation; only escalates
  to a (low-severity) finding if an explicit regional block is observed (e.g. a 403
  whose body text names a geographic restriction, or a redirect to a "not available
  in your region" page).
- **Evidence required:** `OBS-HTTP-FETCH-*` showing the explicit regional-block
  response, when that is the only case that fires.
- **False-positive rules:** the caveat itself is never presented as a finding; only
  an outright observed regional block is.
- **False-negative risks:** geo-variance we cannot see from one vantage point is
  structurally unobservable and is disclosed as a standing limitation
  (`PROJECT_CONTEXT.md` "Known weaknesses"), not guessed at.
- **Severity:** low.
- **Confidence:** high (when it fires at all, the block text is directly observed).
- **Recommendation:** confirm the regional restriction is intentional; if not, remove
  the geo-block or provide a graceful, indexable explanation page.
- **Validation:** re-fetch; the explicit regional-block response no longer appears.

## D-CRAWL-13 — duplicate-host signal splitting
- **Meaning:** the same content is served with `200` status at multiple hosts/paths
  (apex vs `www`, with/without trailing slash, `http` and `https` both live) with no
  canonical resolution between them.
- **Mechanism:** Appendix A gate 1. Citation authority splits across duplicates
  instead of consolidating on one URL.
- **Applicability:** the audited host was reached via one form (from `target` in the
  store); at least one alternate host/path form was also probed.
- **Observable signals:** status code and canonical target of each alternate form.
- **Detection test:** fire when an alternate form also returns `200` (rather than
  redirecting to the canonical host) **and** its own canonical tag does not point back
  to the canonical host.
- **Evidence required:** `OBS-HTTP-FETCH-*` for the canonical host and each
  duplicate-serving alternate.
- **False-positive rules:** an alternate form that 301s to the canonical host is
  correct practice and is never flagged.
- **False-negative risks:** alternate forms we did not think to probe (unusual
  duplication schemes) are outside this check's fixed, small probe set.
- **Severity:** medium.
- **Confidence:** high.
- **Recommendation:** 301-redirect every alternate host/path form to the single
  canonical host, or at minimum set a correct canonical tag on each.
- **Validation:** re-fetch each alternate form; it now redirects to, or canonicalizes
  to, the single audited host.
- **Note on generalization:** this check is the deterministic complement to
  D-ENTITY-01 (canonical *name*): D-CRAWL-13 tests host/URL identity, never brand
  naming.

## D-CRAWL-14 — crawl budget burned by facet/parameter explosion
- **Meaning:** faceted or parameterized URLs (filters, sort, pagination combinations)
  consume a disproportionate share of the crawl before substantive pages are reached.
- **Mechanism:** Appendix A gate 1. A crawler with a fixed page budget that spends it
  on `?color=red&size=m&sort=price` combinations never reaches the actual content
  pages behind them.
- **Applicability:** the crawl hit its page budget before completing discovery (a
  `coverage`-level signal from the crawl pass, carried in `target`/`capabilities`
  metadata as `budget_exhausted: true`), or `>=40%` of discovered same-template URLs
  carry query strings.
- **Observable signals:** ratio of query-string-bearing URLs to total discovered
  URLs within a template cluster.
- **Detection test:** fire when that ratio exceeds `0.4` **and** the crawl budget was
  exhausted before all sitemap-listed substantive URLs were reached.
- **Evidence required:** the ratio, the budget-exhaustion flag, sample
  parameter-bearing URLs.
- **False-positive rules:** a site whose crawl completed within budget with room to
  spare never fires this check regardless of parameter ratio — the mechanism is
  specifically about budget being consumed before substantive pages are reached.
- **False-negative risks:** if budget metadata is absent from the store, this check
  does not fire (applicability precondition unmet).
- **Severity:** medium.
- **Confidence:** medium.
- **Recommendation:** disallow low-value parameter combinations in `robots.txt`, or
  canonicalize them, so crawl budget is spent on substantive URLs.
- **Validation:** re-crawl under the same budget; discovery reaches the previously
  unreached substantive URLs.

## D-CRAWL-15 — robots.txt itself unreachable or unparseable
- **Meaning:** `robots.txt` returns `5xx`, times out, or is syntactically broken
  beyond recognition.
- **Mechanism:** Appendix A gate 1. Many crawlers treat an unreachable robots.txt as
  disallow-all — a total-invisibility failure invisible to tools that only check
  rendered pages.
- **Applicability:** a `ROBOTS` fetch was attempted.
- **Observable signals:** `ROBOTS.status`.
- **Detection test:** fire when `ROBOTS.status` is `error` (5xx/timeout) or
  `unparseable`.
- **Evidence required:** `OBS-ROBOTS-*`, the status and, where available, the raw
  response.
- **False-positive rules:** `status == "missing"` (a clean `404`) is not this check —
  a missing robots.txt conventionally means allow-all and is not a defect.
- **False-negative risks:** none material — fetch status is directly observed.
- **Severity:** critical (total-invisibility list, named explicitly in
  `severity-matrix.md`).
- **Confidence:** high.
- **Recommendation:** serve a syntactically valid `robots.txt` with a `200` status,
  even if its content is simply `User-agent: *\nAllow: /`.
- **Validation:** re-fetch `/robots.txt`; status is `200` and it parses.
