# D-RENDER — readability (gate 2)

Twelve-field form for every check this skill owns in this category, per
`<marketplace-root>/references/failure-taxonomy.md`. Implemented in
`scripts/detect_render.py`. Store types referenced below are defined in
`store-contract.md`.

Every check in this category requires both a `HTTP_FETCH` (raw) and a `RENDER`
(rendered) observation for the same URL. When `RENDER.status != "ok"` — capability
absent or render failed — the whole category is inapplicable for that page: it does
not fire and is not recorded as a pass (`X-COV-01` is the orchestrator's concern, not
a silent pass fabricated by this skill).

---

## D-RENDER-01 — primary content is render-dependent
- **Meaning:** the page's main-content text is present in the rendered DOM but absent
  from raw HTML.
- **Mechanism:** Appendix A gate 2 / Appendix C. A non-executing fetcher receives a
  shell; the page looks complete to a person and empty to the machine.
- **Applicability:** `HTTP_FETCH.status_code == 200`; `RENDER.status == "ok"`; page is
  content-bearing (rendered main-region text `> 400` chars, ruling out utility/login
  stubs).
- **Observable signals:** main-content text length in raw vs. rendered, using the
  same extractor (`lib.common.extract.extract_text`) on both lenses.
- **Detection test:** fire when `raw_text_len / rendered_text_len < 0.30` **and**
  `rendered_text_len > 400`. Requires `>=3` pages of the same template cluster before
  generalizing the finding to the whole template; a single page reports at reduced
  (medium) confidence.
- **Evidence required:** `OBS-HTTP-FETCH-*`, `OBS-RENDER-*`, both character counts,
  the ratio, and a short excerpt present in rendered text and absent from raw text.
- **False-positive rules:** never fires for client-side widgets, comments,
  recommendation modules, chat, or analytics — the trigger is the *ratio of
  main-content text*, not any client-side JS use. Never fires when the missing text
  is navigation chrome (that is D-RENDER-03). Suppressed when the sibling pages of
  the same template pass (isolates a single-page anomaly rather than a template-wide
  defect).
- **False-negative risks:** a site that server-renders its homepage but
  client-renders deep templates is missed by depth-1-only sampling; mitigated by
  sampling across template clusters, not by depth.
- **Severity:** high base; **critical** if the render-only text includes the entity's
  primary offering or the page's principal answer content (cross-checked against a
  `PROBE` observation, when present, whose answered question's `evidence_span` falls
  only in the rendered text); **medium** if only a secondary module is affected.
- **Confidence:** high when `>=3` same-template pages agree; medium on a single page.
- **Recommendation:** server-render or pre-render the main-content region for the
  affected template; emit the substantive text in the initial HTML payload and
  hydrate on top. Name the template and the specific missing text.
- **Validation:** re-fetch with JS disabled; the named excerpt appears in the raw
  response body and the ratio exceeds `0.6`.

## D-RENDER-02 — specific key facts are render-only
- **Meaning:** a targeted fact (price, hours, address, contact detail, spec) exists
  only after render, not in raw HTML.
- **Mechanism:** Appendix A gate 2 / Appendix C. Even when most of the page reads
  fine raw, the one fact a user would actually ask an assistant for can be the part
  that's missing.
- **Applicability:** `RENDER.status == "ok"`; a `PROBE` observation exists for the
  page with `>=1` question marked `category == "factual"` and `answered == true`.
- **Observable signals:** whether the probe's `evidence_span` for an answered
  factual question appears in the raw HTML text.
- **Detection test:** fire per factual question whose `evidence_span` (normalized
  whitespace) is found in rendered text but not in raw text.
- **Evidence required:** `OBS-PROBE-*` (the question id and evidence span),
  `OBS-HTTP-FETCH-*`, `OBS-RENDER-*`.
- **False-positive rules:** only fires for facts "a user would plausibly ask an
  assistant for" — enforced structurally by requiring the fact to come from a
  `category == "factual"` probe question, not an arbitrary DOM diff. Never fires from
  a raw/rendered structural diff alone (that's D-RENDER-01's more general test).
- **False-negative risks:** facts the probe was never asked about are invisible to
  this check; the probe's canonical question set is the limiting factor, not this
  check's logic.
- **Severity:** high.
- **Confidence:** high — text-containment is a direct, deterministic test.
- **Recommendation:** move the named fact into server-rendered markup, even if the
  surrounding presentation stays client-rendered.
- **Validation:** re-fetch raw; the named evidence span is present verbatim.

## D-RENDER-03 — internal navigation is render-only
- **Meaning:** the link graph reachable from raw HTML is materially smaller than the
  one reachable after render — navigation exists only in JS.
- **Mechanism:** Appendix A gate 1/2. A non-rendering fetcher cannot discover pages
  reachable only through client-rendered links, shrinking effective site coverage.
- **Applicability:** `RENDER.status == "ok"`.
- **Observable signals:** count and target set of `<a href>` anchors extracted from
  raw HTML vs. rendered HTML (`lib.common.extract.extract_links` on both).
- **Detection test:** fire when the rendered-only link target set (targets present
  after render, absent raw) has `>=3` entries **and** those targets are not decorative
  duplicates of links already present raw (same href appearing twice, e.g. a
  duplicate footer nav) — dedupe by absolute URL before counting.
- **Evidence required:** `OBS-HTTP-FETCH-*`, `OBS-RENDER-*`, the deduplicated
  rendered-only target list.
- **False-positive rules:** decorative or duplicate footer nav that repeats an
  already-raw-visible link is excluded by the dedupe step. A single rendered-only
  utility link (e.g. one "back to top" JS anchor) stays below the `3`-entry floor and
  does not fire.
- **False-negative risks:** if raw already contains `>=1` path to every rendered-only
  target indirectly (through a page we didn't sample), this check cannot see that and
  may over-report; template-cluster aggregation limits the blast radius of any one
  miscount.
- **Severity:** high.
- **Confidence:** high.
- **Recommendation:** render primary navigation as real anchor tags in the initial
  HTML (progressive enhancement), even if JS later intercepts clicks for a SPA
  transition.
- **Validation:** re-fetch raw; the previously rendered-only targets now appear as
  `<a href>` values.

## D-RENDER-04 — interaction-gated content absent from the DOM
- **Meaning:** content behind a tab, accordion, or similar interaction is entirely
  absent from the DOM until the user clicks — not merely hidden by CSS.
- **Mechanism:** Appendix A gate 2. A fetcher (and most non-interactive citation
  pipelines) never triggers the click, so DOM-absent content is unreadable to them
  even though the rendered lens theoretically "has" the page.
- **Applicability:** `RENDER.status == "ok"`; the rendered DOM contains a recognized
  interactive-disclosure pattern (elements with `role="tab"`/`aria-expanded="false"`/
  common accordion/tab class hooks) whose associated panel is empty or missing in the
  captured rendered DOM.
- **Observable signals:** presence of the trigger element; presence/emptiness of its
  associated content panel in the rendered (pre-interaction) DOM.
- **Detection test:** fire when a trigger's `aria-controls` (or equivalent structural
  link) target element exists in the DOM but has empty/whitespace-only text content
  pre-interaction.
- **Evidence required:** `OBS-RENDER-*`, the trigger element and its target panel's
  (empty) text content.
- **False-positive rules:** content that is present in the DOM but hidden via CSS
  (`display:none`, `hidden` attribute toggled by a class) **is readable** and must
  never be flagged — the test is DOM text-content emptiness, not visibility.
- **False-negative risks:** disclosure patterns that don't use `aria-controls` or a
  recognizable class hook are undetectable without executing the interaction, which
  this skill does not do (out of budget, and moves toward E-ANSWER territory).
- **Severity:** medium.
- **Confidence:** medium — the aria/structural heuristic can miss nonstandard widgets.
- **Recommendation:** render the panel content into the DOM at load (even visually
  collapsed) rather than deferring its existence to the interaction.
- **Validation:** re-render; the panel's pre-interaction DOM text content is
  non-empty.

## D-RENDER-05 — listings without crawlable pagination
- **Meaning:** a listing loads only via infinite scroll or client-side pagination,
  with no `rel="next"`-equivalent or `?page=`-equivalent crawlable URLs for pages
  beyond the first.
- **Mechanism:** Appendix A gate 1/2. A crawler that doesn't scroll or click "load
  more" sees only the first page of the collection, permanently.
- **Applicability:** `RENDER.status == "ok"`; the page is classified (or structurally
  recognizable) as a listing — repeated sibling item markup, count `>=10` in the
  rendered DOM.
- **Observable signals:** presence of `<link rel="next">`, a paginated `?page=`-shaped
  href in the raw or rendered anchor set, or additional item nodes appearing after a
  simulated scroll/load-more trigger with no corresponding URL change.
- **Detection test:** fire when the listing has `>=10` items rendered, no
  `rel="next"` equivalent exists, an enabled visible load-more control or explicit has-more/next-page attribute exists, and no anchor in raw or rendered HTML carries a
  page-shaped query/path parameter.
- **Evidence required:** `OBS-RENDER-*`, the item count, the absence of any
  pagination-shaped anchor.
- **False-positive rules:** a small collection (`<10` items) fully present on first
  load is fine and never flagged — the mechanism is specifically about content
  unreachable beyond the first page, not about scroll UX.
- **False-negative risks:** a listing whose true size we cannot determine (no visible
  "N results" count, no way to confirm more exist beyond the rendered page) is
  under-detected; the `>=10`-item floor is a deliberately conservative proxy.
- **Severity:** medium.
- **Confidence:** medium.
- **Recommendation:** expose paginated, crawlable URLs (`?page=2`, `/page/2`, or
  equivalent) alongside the infinite-scroll UI, and link them with `rel="next"`.
- **Validation:** re-fetch raw; a second-page URL is discoverable and returns
  additional items not present on page one.

Current guardrails also exclude rendered-only external links from D-RENDER-03 and
require D-RENDER-02 answer spans to exist in rendered text as well as be absent raw.
D-RENDER-05 does not simulate clicks or scrolling: continuation attributes/controls
are structural evidence. Finite listings without continuation evidence stay silent.
