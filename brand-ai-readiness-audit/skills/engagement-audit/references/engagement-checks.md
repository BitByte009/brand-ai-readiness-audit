# E-ORIENT / E-ANSWER / E-CONTINUE — engagement

Twelve-field form for every check this skill owns, per
`<marketplace-root>/references/failure-taxonomy.md`. Implemented in
`scripts/detect_engagement.py`. Store types referenced below are defined in
`store-contract.md`; the arrival model every check is evaluated against is
`ai-referral-persona.md`.

Each field below maps onto the seven items this skill's design brief asked for:
**mechanical observation** = `observable_signals` + `detection_test`;
**evidence** = `evidence_required`; **interpretation** = `mechanism` + the
detection test; **false-positive guardrails** = `false_positive_rules`;
**severity/confidence** = `severity` + `confidence`; **recommendation** =
`recommendation`; **validation** = `validation`.

The seven questions this skill's brief asked every check to answer map onto the
checks as: where they are → `E-ORIENT-01`, `E-ORIENT-03`; what the org/product is →
`E-ORIENT-01`; what the page answers → `E-ANSWER-04`; why the page is relevant →
`E-ANSWER-01`; what to do next → `E-CONTINUE-01`; how to continue exploring →
`E-CONTINUE-02`, `E-CONTINUE-03`, `E-CONTINUE-04`; whether useful context is
preserved → `E-ORIENT-04`, `E-ANSWER-02`, `E-ANSWER-03`.

**Governing rule, restated per-check where it applies:** no finding in this skill
may rest on aesthetics, brevity, or a missing call-to-action where none is
appropriate. Every check requires a positional or structural measurement, and a
demonstrated connection to *AI-referred, deep-linked* arrival specifically — not
a general "this page could be nicer" observation. E-CONTINUE-05 (viewport/overflow)
was cut from the taxonomy for exactly this reason (`failure-taxonomy.md` revision
log) and is never reintroduced here.

---

## E-ORIENT-01 — no brand identification on arrival
- **Meaning:** a deep page's first screen of content never identifies whose site
  this is.
- **Mechanism:** Appendix E. An AI-referred visitor arrives with no homepage
  context and no navigation history. If the first screen doesn't say whose page
  this is, they cannot evaluate trust and leave.
- **Applicability:** page is at depth `>=2` (a plausible deep-link target); the
  entity_profile has a determined `canonical_name`. A page with no determinable
  name is not evaluable by this check (that gap is `entity-semantic-audit`'s
  D-ENTITY-01, not this skill's).
- **Observable signals:** the canonical name (or a recognized alias) present in
  the first N DOM-order text nodes of the rendered (or, absent a render, raw)
  page; in a logo `<img>`'s `alt`/`aria-label`; or in the `<title>` (any
  `title_segments()` segment, reusing `entity-semantic-audit`'s split so a
  "Page - Brand" title still counts).
- **Detection test:** fire when the brand token is absent from **all three**
  positions: early body text, logo alt/aria-label, and title. Match with Unicode
  word boundaries, not substrings of unrelated words (e.g. AI in training).
- **Evidence required:** the page's first-screen text excerpt, the logo `alt`
  value (or its absence), and the title — showing none contain the brand token.
- **False-positive rules:** a logo image *with* correct alt text counts as
  identification on its own — never penalized for being an image rather than
  text. A brand-token match in *any one* of the three positions passes; this
  check never demands all three. Never applied to depth-1 (homepage-adjacent)
  pages, where arrival context is different. Never fires from short page length
  alone — a short page with the brand token present in any position passes
  exactly like a long one.
- **False-negative risks:** a brand token that's a very common word (matched
  loosely) could pass this check while a human still wouldn't recognize the
  site; this check tests literal presence, not recognizability, by design, to
  stay mechanical.
- **Severity:** high when all three positions are absent; the taxonomy caps it
  there — this check never distinguishes a partial case because the detection
  test itself is compound (any one position passing means no finding at all).
- **Confidence:** high — presence/absence in three fixed positions is a direct,
  deterministic test.
- **Recommendation:** put the brand name in the title (as its own segment or
  suffix), in accessible header text, and/or in the logo's alt text.
- **Validation:** re-fetch the page cold; the brand token is present in `>=1` of
  the three positions.

## E-ORIENT-03 — no path context
- **Meaning:** a deep page gives no indication of where it sits in the site —
  no breadcrumb, no parent-topic link, no textual equivalent.
- **Mechanism:** Appendix E. An AI-referred visitor dropped mid-site has no
  navigation history to infer structure from; without an explicit signal, they
  cannot orient beyond the single page.
- **Applicability:** the site has `>=3` levels of URL depth demonstrated
  elsewhere in the crawl (a flat `<=2`-level site has nothing to show a
  breadcrumb *for* — never fires there). Page itself is at depth `>=2` and is
  not classified `landing_page` — a campaign/landing page that deliberately
  omits navigation (a recognized conversion-optimization practice) is exempt
  the same way a terminal page is (`is_terminal_page()`), added after a
  hostile review found deep campaign pages flagged for an intentional,
  well-regarded design choice.
- **Observable signals:** a `BreadcrumbList` JSON-LD node; a `<nav>`/`<ol>`/`<ul>`
  element whose class/id/`aria-label` names it a breadcrumb; or a textual
  `Parent > Child`-shaped path equivalent near the top of the page.
- **Detection test:** fire when none of the three signals is present.
- **Evidence required:** confirmation that no breadcrumb markup, breadcrumb-named
  element, or textual path equivalent was found.
- **False-positive rules:** flat sites (`<=2` levels sitewide) never fire —
  applicability precondition, not a downgrade. Never fires from visual
  simplicity; the test is presence of a structural/textual signal, not its
  styling.
- **False-negative risks:** a breadcrumb rendered as an unlabeled, unstructured
  row of links (no aria-label, no schema, no `>` separators) is invisible to
  this mechanical test.
- **Severity:** medium.
- **Confidence:** high — presence/absence of the three signal types is direct.
- **Recommendation:** add a breadcrumb (structural markup preferred, e.g.
  `BreadcrumbList`) or a clear parent-topic link near the top of the page.
- **Validation:** re-fetch; one of the three path-context signals is now present.

## E-ORIENT-04 — fragment links don't resolve
- **Meaning:** a published internal link with a `#fragment` doesn't resolve to
  actual content on its target page.
- **Mechanism:** Appendix E. A citation pipeline or a visitor following a
  deep-linked anchor lands on the target page with no way to reach the specific
  content the fragment promised.
- **Applicability:** `>=1` internal link with a non-empty `#fragment` is
  discovered in the crawl (sitemap or internal links) — never fires if no such
  link is actually published.
- **Observable signals:** the fragment identifier; presence of an element with a
  matching `id` (or a legacy `name`) anywhere in the target page's DOM.
- **Detection test:** fire when the target page was crawled (its `HTTP_FETCH`/
  `RENDER` observation exists) and no element with the matching `id`/`name`
  exists in its DOM.
- **Evidence required:** the fragment link's source and target URLs, and
  confirmation the target ID is absent from the target page's DOM.
- **False-positive rules:** never fires for a fragment link whose target page
  was never actually crawled (applicability unmet — we can't confirm either
  way, so we say nothing rather than guess). Never fires on a fragment that
  targets the page's own top (`#top`, `#`) or a browser-default anchor.
- **False-negative risks:** an `id` present but attached to an empty/hidden
  element still counts as "resolves" by this presence-only test — matching
  D-CRAWL/D-RENDER's precedent of testing presence, not adequacy, to stay
  mechanical.
- **Severity:** medium.
- **Confidence:** high — DOM `id`/`name` presence is a direct, deterministic test.
- **Recommendation:** add the missing anchor `id`/`name` to the target page at
  the referenced content, or fix the link if the target moved.
- **Validation:** re-fetch the target page; an element with the matching `id`
  now exists.

## E-ANSWER-01 — title/description promises what the body doesn't deliver
- **Meaning:** the `<title>`/meta description sets an expectation the page body
  doesn't fulfill.
- **Mechanism:** Appendix E. An AI-referred visitor arrives having read a
  citation built from the title/description; a body that doesn't deliver on it
  breaks the promise that got them to click through.
- **Applicability:** `HTTP_FETCH`/`RENDER` observation exists with a non-empty
  title or description.
- **Observable signals:** word-containment overlap between the significant
  words of title+description and the significant words of the page's main
  content text (the same asymmetric containment measure
  `entity-semantic-audit` uses for description conflicts — chosen deliberately
  over a raw character-sequence ratio, which penalizes length mismatch rather
  than content mismatch); `PROBE` **Q5** as a fallback only when the
  deterministic overlap is inconclusive (very low on both measures) and a
  `PROBE` observation exists.
- **Detection test:** fire when containment overlap is below `0.2` **and**,
  where a `PROBE` observation exists, Q5's answer does not reference the
  title/description's key terms either. Both signals must agree when both are
  available; the deterministic overlap alone is sufficient to fire when no
  `PROBE` observation exists for the page.
- **Evidence required:** the title/description text and the main-content excerpt
  compared, quoted verbatim — every finding from this check quotes both strings
  (`SKILL.md` Evidence rules).
- **False-positive rules:** requires a clear, quantified mismatch (`<0.2`
  overlap), never a stylistic difference — a title that summarizes rather than
  quotes the body passes easily under a containment measure. Never fires on
  page types where title and body are expected to diverge structurally (a
  product listing title vs. a body full of specs is not a "mismatch," it's
  normal information density) — applicability requires the page be
  content-bearing prose, not a listing/grid page (checked via a text-length
  floor).
- **False-negative risks:** a title that keyword-stuffs matching terms while
  the body's actual claim is subtly different in meaning passes this
  containment-based test; catching that requires real semantic judgment, which
  this skill's brief prefers not to assert deterministically. Documented,
  not-required LLM-instrument upgrade path.
- **Severity:** medium, capped (never escalated) per `failure-taxonomy.md`'s
  explicit demotion of this check.
- **Confidence:** medium, capped — never asserted at high, per the same
  demotion (LLM-adjacent judgment, even when deterministic overlap alone
  decides it).
- **Recommendation:** rewrite the title/description to match what the body
  actually delivers, or add the promised content to the body.
- **Validation:** re-extract; containment overlap between title/description and
  body exceeds `0.2`.

## E-ANSWER-02 — entry-blocking interstitial
- **Meaning:** a modal, newsletter overlay, or consent wall covers the content
  at first paint, before any interaction.
- **Mechanism:** Appendix E. An AI-referred visitor arriving expecting a
  specific answer, met instead with a blocking overlay, cannot see that answer
  without first dismissing something they didn't ask for.
- **Applicability:** a `RENDER` observation exists with `status == "ok"` — this
  check never falls back to raw HTML (see `store-contract.md`); what appears at
  first paint is only observable through the render lens.
- **Observable signals:** a rendered-DOM element with `role="dialog"` or
  `aria-modal="true"` (unrestricted by tag), or a **container-shaped** element
  (`div`/`section`/`aside`/`dialog`/`form` — never a `button`/`a`/`input`
  trigger element) whose class/id/text names it a modal/overlay/popup/
  newsletter prompt, that is not marked `hidden`, `aria-hidden="true"`, or
  styled `display:none` in its inline style — i.e. present and
  visible-by-default in the captured render.
- **Detection test:** fire when such an element exists and is not a compliant
  cookie/consent banner that leaves the main content visible (see false-positive
  rule).
- **Evidence required:** the matched element's role/class/id and its visibility
  state in the rendered DOM.
- **False-positive rules:** a compliant cookie or consent banner that does not
  occlude the main content — detected structurally as a banner confined to a
  page edge (top/bottom strip pattern) rather than a centered/full-viewport
  dialog — is never flagged; legally-required consent walls are noted as a
  business-context fact, not scolded, when they do block content (framed
  neutrally in the finding text, not as an error). Never fires on an element
  explicitly hidden by markup at render time. **Never fires on a mere trigger
  element** (a `<button>`/`<a>` that opens a dialog defined elsewhere) — a
  hostile review found a harmless, visible `<button class="modal-trigger-btn">`
  being flagged as the blocking dialog itself, purely because it matched the
  same keyword pattern as the (correctly hidden) dialog it opens; the
  keyword-based search is restricted to container-shaped tags for exactly
  this reason.
- **False-negative risks:** an overlay that appears only after a delay (a
  timed popup) is invisible to a single first-paint render capture; out of
  scope for a single-snapshot render lens.
- **Severity:** high.
- **Confidence:** high — DOM presence and visibility state are direct,
  deterministic tests.
- **Recommendation:** defer the overlay until after the visitor has seen the
  primary content, or make it dismissible without obscuring the answer.
- **Validation:** re-render; no blocking dialog/modal element is
  present-and-visible at first paint.

## E-ANSWER-03 — citation content gated for the human visitor
- **Meaning:** content that a machine could read and cite is present in the
  page's markup but visually gated behind a paywall/login prompt for the human
  who follows the link.
- **Mechanism:** Appendix E. A citation pipeline may quote text a human visitor
  is then asked to pay or sign in to see — the visitor cannot verify the very
  thing they were told, which reads as bait-and-switch even when the paywall
  itself is legitimate.
- **Applicability:** a `RENDER` observation exists with `status == "ok"`; the
  page's rendered DOM contains substantive text (`>400` chars) outside any
  gating element.
- **Observable signals:** a rendered-DOM element matching a paywall/subscription/
  login-gate pattern (class/id/text containing "paywall", "subscribe to
  continue", "sign in to read", "member", "premium content") that is
  present-and-visible at render time and structurally overlaps or precedes the
  substantive content region.
- **Detection test:** fire when such a gating element is present-and-visible
  alongside substantive content in the same render.
- **Evidence required:** the gating element's matched text/class, and the
  substantive content it gates.
- **False-positive rules:** flagged **only as a citation-mismatch risk**, with
  the business context stated plainly (a legitimate paywall is not scolded as
  a defect) — the finding text is written neutrally, never implying the
  paywall itself is wrong. Never fires when the "substantive content" is
  itself just a teaser/preview (below the 400-char floor) — that's an honest
  preview, not a mismatch.
- **False-negative risks:** a paywall implemented as a hard server-side gate
  (content never in the DOM at all until payment) is invisible to this check —
  and correctly so, since then a machine cannot see it either and there is no
  citation-mismatch (the machine and the human are equally blocked).
- **Severity:** high.
- **Confidence:** high — DOM co-presence of gating markup and substantive text
  is a direct, deterministic test.
- **Recommendation:** state plainly, above the gate, what the paywalled content
  covers, so the citation and the visible preview agree; consider a
  structured-data-only summary for machine consumption that matches what a
  human sees before the gate.
- **Validation:** re-render; the gating pattern and substantive content no
  longer structurally overlap, or the pre-gate text now matches what's citable.

## E-ANSWER-04 — citation-landing mismatch
- **Meaning:** a fact the extraction probe found in the page's text is not
  where an arriving human can actually see it — below the fold, inside a
  collapsed region, or otherwise buried.
- **Mechanism:** Appendix E, the join between the discoverability and
  engagement halves of the brief: the probe confirms the fact is *extractable*;
  this check measures whether it's also *locatable* on arrival. Absorbs the
  original E-ORIENT-02 "answer-first framing" check per
  `failure-taxonomy.md`'s revision log — a page that never restates its
  answer near the top is exactly a page whose answer scores poorly here.
- **Applicability:** a `RENDER` observation exists with `status == "ok"`; a
  `PROBE` observation exists for the page with `>=1` answered, relevant
  question whose `evidence_span` is locatable in the rendered text.
- **Observable signals:** the `evidence_span`'s character-offset position in
  DOM-order rendered text, expressed as a fraction of total text length (a
  scroll-depth proxy); whether the span sits inside a collapsed
  disclosure region (reusing `crawl-render-audit`'s D-RENDER-04 detection:
  an `aria-expanded="false"`/`hidden` ancestor).
- **Detection test:** fire when the scroll-depth fraction exceeds `0.5`, **or**
  the span is inside a collapsed region at render time — **unless** the page
  also provides a direct in-page anchor link (`<a href="#section-id">`) to the
  section containing the answer, in which case it never fires regardless of
  how far down the answer sits.
- **Evidence required:** the `PROBE` question id and `evidence_span`, the
  computed scroll-depth fraction or the collapsed-region finding.
- **False-positive rules:** requires an actual answered `PROBE` question with
  `relevant` **explicitly** `true` — never defaulted, matching
  `crawl-render-audit`'s convention; an unset `relevant` field is never fair
  game for a finding, closing an over-firing risk a hostile review named
  directly ("where the LLM might invent a problem"). Never guesses at "the
  answer" without the probe's confirmation of what it is. **Never fires when
  a direct anchor-nav link to the answer's section exists** — a long,
  single-page site with a sticky nav that jumps straight to "Pricing" is a
  deliberate, common, well-regarded structure; a hostile review found the raw
  scroll-depth fraction alone penalizing exactly this pattern purely for
  being long, not for being poorly organized. Archetype/page-type note: on
  `publisher-editorial` and `documentation` pages this is the primary
  freshness-adjacent orientation signal (absorbing the old E-ORIENT-02); on
  transactional/listing pages (e.g. `ecommerce` category pages) a
  `PROBE`-confirmed answer appearing later in a long list is expected
  structure, not burial — applicability's `>0.5` threshold already tolerates
  the first half of any page, and this check does not further penalize
  listing pages beyond that shared floor.
- **False-negative risks:** entirely bounded by the `PROBE`'s canonical
  question set and by having a successful render; a true answer buried in a
  region the probe never asked about is invisible here.
- **Severity:** high.
- **Confidence:** high — character-offset position and collapsed-region
  membership are both direct, deterministic measurements once the `PROBE`
  answer exists.
- **Recommendation:** move the confirmed-answer sentence earlier in the
  rendered content, or render it outside any collapsed-by-default region.
- **Validation:** re-render; the same `evidence_span` now sits above the
  `0.5` scroll-depth fraction and outside any collapsed region.

## E-CONTINUE-01 — no relevant next step
- **Meaning:** a deep page has outgoing content-area links, but none of them
  is a genuine next step (a plausible continuation), only navigation
  boilerplate, social-share icons, or self-referential anchors.
- **Mechanism:** Appendix E. A visitor who got their answer (or didn't) has no
  way to go deeper or sideways without returning to search — the AI referral
  channel is a dead end for the site even when the single page succeeded.
- **Applicability:** the site has `>=2` crawled pages — a genuinely
  single-page site has nowhere "deeper" to send a visitor *by design*, and a
  hostile review found single-page SaaS/landing sites flagged purely for
  being one page (mirrors the marketplace's established minimum-corpus
  convention for cross-page checks). The page is not classified as a
  terminal/utility page whose job is complete (`contact`, `thank_you`,
  `landing_page`, or a path-based utility match) — such pages need no next
  step and this check does not evaluate them at all. Page has `>=1` outgoing
  content-area link (below this, see `E-CONTINUE-02` instead).
- **Observable signals:** the classification of each outgoing content-area
  link's target: same-page anchor, external social-share pattern
  (`share`/`tweet`/`mailto:`), the audited host or its descendant subdomains,
  vs. another host. Normalize the conventional www alias. Do not infer
  ownership from the last two DNS labels: unrelated co.uk domains and sibling
  tenants of a shared hosting service must remain external. This is a site-scope
  heuristic, not proof of legal ownership or registrable-domain resolution.
- **Detection test:** fire when every outgoing content-area link classifies as
  same-page-anchor or social-share — i.e. zero links point to another internal
  or same-organization content page.
- **Evidence required:** the full list of outgoing content-area links and their
  classifications.
- **False-positive rules:** terminal/utility pages are entirely out of scope
  (applicability, not a downgrade) — a contact page whose job is complete
  needs no onward step and is never flagged for lacking one, and neither does
  a landing page that deliberately minimizes navigation. Never fires from
  a low link *count* alone — one genuine content link is sufficient to pass;
  this is never about quantity or visual button density. Never fires on a
  genuinely single-page site (applicability, not a downgrade).
- **False-negative risks:** a technically-internal link that is contextually
  irrelevant (e.g. links only to an unrelated legal page) still counts as
  "a next step" under this structural test; judging topical relevance would
  need the LLM-adjacent fallback (`PROBE` Q8), used only when the
  deterministic pass finds literally zero internal content links, to avoid
  asserting relevance without a real signal.
- **Severity:** medium.
- **Confidence:** high when the deterministic link classification alone
  decides it; medium when the `PROBE` Q8 fallback was consulted.
- **Recommendation:** add a link to related content, a topic hub, or a clear
  onward action relevant to what this page just answered.
- **Validation:** re-fetch; `>=1` outgoing link now points to genuine internal
  content.

## E-CONTINUE-02 — dead end
- **Meaning:** a deep page has zero outgoing content-area links at all, beyond
  global navigation chrome.
- **Mechanism:** Appendix E. The strictest case of `E-CONTINUE-01` — there is
  structurally nothing to click that leads deeper into the site from this
  page's own content.
- **Applicability:** same `>=2`-crawled-pages and terminal/utility-page
  exclusion as `E-CONTINUE-01` (including the `landing_page` carve-out).
- **Observable signals:** count of outgoing links found in the main-content
  region only (nav/header/footer chrome stripped, reusing
  `crawl-render-audit`'s D-RENDER-01 chrome-stripping approach).
- **Detection test:** fire when the content-region out-degree is exactly `0`.
- **Evidence required:** confirmation that zero links exist in the
  chrome-stripped content region.
- **False-positive rules:** global nav/header/footer links never count toward
  or against this check either way — only content-region links are evaluated,
  so a page with a normal site nav but no in-content links still correctly
  fires (nav is not a "next step" specific to what this page just delivered).
  Terminal/utility pages are out of scope entirely.
- **False-negative risks:** none material beyond the shared chrome-stripping
  heuristic's own limits.
- **Severity:** medium.
- **Confidence:** high — a direct count.
- **Recommendation:** add at least one in-content link to related material.
- **Validation:** re-fetch; content-region out-degree is `>=1`.

## E-CONTINUE-03 — no route to the broader topic hub
- **Meaning:** a narrow, deep page offers no path to the broader topic or
  category it belongs to, even though that hub demonstrably exists.
- **Mechanism:** Appendix E. A visitor satisfied by the specific answer but
  wanting the wider picture has no way to get there without leaving the site.
- **Applicability:** a plausible hub URL — the current page's path with its
  last segment removed — was itself crawled (has an `HTTP_FETCH`/`RENDER`
  observation). **Never fires when no such hub was demonstrably found** — this
  check does not invent or guess at a hub's existence.
- **Observable signals:** whether the hub URL appears among the page's
  outgoing content-area links.
- **Detection test:** fire when the hub URL exists in the crawl but is not
  linked from the current page's content region.
- **Evidence required:** the hub URL and confirmation it is absent from the
  page's outgoing links.
- **False-positive rules:** only fires where a hub demonstrably exists in the
  crawl — never inferred from URL shape alone without confirming the hub page
  was actually reachable and observed.
- **False-negative risks:** a hub reachable only through a differently-shaped
  URL (not a simple parent-path truncation) is invisible to this structural
  test.
- **Severity:** low–medium.
- **Confidence:** high — link presence/absence to a confirmed hub URL is a
  direct test.
- **Recommendation:** add a link back to the broader topic/category page.
- **Validation:** re-fetch; the hub URL now appears among the page's outgoing
  links.

## E-CONTINUE-04 — broken internal links from sampled deep pages
- **Meaning:** an outgoing internal link from a sampled deep page targets a
  URL that returns an error status.
- **Mechanism:** Appendix E. A visitor who takes the offered next step and
  hits a dead link has, functionally, the same dead-end experience as
  `E-CONTINUE-02` — the site just didn't admit it up front.
- **Applicability:** the link's target URL was itself crawled (has an
  `HTTP_FETCH` observation) — this skill never fetches to verify a link live;
  it only reasons over what was already observed (`PROJECT_CONTEXT.md` D-6,
  and this check's own "verify before asserting" guardrail).
- **Observable signals:** the target's `HTTP_FETCH.status_code`.
- **Detection test:** fire when the target's status is `>=400`.
- **Evidence required:** the source page, the link, the target's status code.
- **False-positive rules:** never fires for a link whose target was not
  crawled — applicability unmet, not a guess. Never re-fetches to "double
  check" — a transient failure this skill can't distinguish from a real one is
  `crawl-render-audit`'s D-CRAWL-04 concern (which does retry once); this
  check reports what the store already recorded.
- **False-negative risks:** a target outside the crawl sample is invisible to
  this check.
- **Severity:** medium.
- **Confidence:** high — a direct status-code read.
- **Recommendation:** fix or remove the broken outgoing link.
- **Validation:** re-fetch the target; status is `<400`.
