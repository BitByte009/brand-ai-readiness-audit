# engagement-audit — Engineering Study Guide

> Companion to `SKILL.md`. Shared vocabulary, the observation store and the
> finding contract are in the root `KNOWLEDGE.md` (§6, §8).

---

## A. PURPOSE AND MENTAL MODEL

**Mental model:** think of this skill as a *simulated cold arrival*. It takes the
observation store plus the entity profile and asks, for each page: **if a person
landed here from an AI answer — with no homepage visit, no navigation history and
no brand context — could they orient, get what they came for, and continue?**

This is the only skill in the marketplace whose subject is a **human**, not a
machine. Everything else asks whether a crawler can reach, read, extract, resolve
or trust the page. This one assumes all of that succeeded and asks what happens
next.

The three families map to the three moments of an arrival:

| Family | Moment | Question |
|---|---|---|
| `E-ORIENT-01/03/04` | landing | "Where am I? Whose site is this? How do I situate this page?" |
| `E-ANSWER-01..04` | reading | "Is the thing I was promised actually here and visible?" |
| `E-CONTINUE-01..04` | after | "Can I go deeper without going back to search?" |

**The defining assumption — deep-link entry.** Several checks skip
`url_depth(url) < 2`. The homepage is not an AI-referral landing page in the
interesting sense; an assistant cites a specific page. `references/ai-referral-persona.md`
is the reference that states this persona.

**What it considers evidence.** Rendered DOM where available (mandatory for the
overlay/paywall checks), raw HTML otherwise; the entity profile's brand tokens;
crawled sibling pages for link-target verification.

**What it does NOT determine.** Whether the crawler could reach the page
(`crawl-render-audit` gate 1), whether the identity is coherent
(`entity-semantic-audit` — this skill *consumes* that verdict), or whether claims
are believable (`trust-freshness-audit`). The explicit boundary from `SKILL.md`:
a wall blocking the **fetch** is `D-CRAWL-09`; a wall blocking the **reader**
after a successful fetch is `E-ANSWER-02`.

---

## B. COMPLETE FILE MAP

### `scripts/detect_engagement.py` (609 lines)
- **Purpose:** all 11 `E-*` checks.
- **Called by:** `run_audit.py::_invoke_detectors` as
  `detect_engagement.detect_engagement(store, entity_profile)`.
- **Constants:** `CATEGORY = "engagement"`, `MIN_NAVIGATION_DESTINATIONS = 2`,
  and two dispatcher lists — `CHECKS_NO_PROFILE` and the profile-taking checks —
  because `E-ORIENT-01` is the only check that needs the entity profile.
- **Local helpers:** `_brand_tokens(entity_profile, for_url=None)`,
  `_outgoing_classifications(url, page)`.

### `scripts/_engagement_util.py` (~440 lines) — the analysis library
| Group | Symbols |
|---|---|
| Page selection | `rendered_pages_only`, `effective_pages` (imported from `lib.common.pages`), `is_utility_path`, `is_terminal_page`, `_TERMINAL_PAGE_TYPES` |
| Content region | `_CHROME_TAGS`, `main_content_soup`, `main_text` |
| Orientation | `brand_token_positions(html, title, tokens, first_screen_chars=800)`, `has_breadcrumb`, `_BREADCRUMB_NAME_RE`, `_TEXTUAL_PATH_RE` |
| Fragments | `internal_fragment_links`, `has_dom_anchor` |
| Blocking UI | `_MODAL_NAME_RE`, `_CONSENT_NAME_RE`, `_PAYWALL_NAME_RE`, `_MODAL_CONTAINER_TAGS`, `_is_hidden`, `_matches_pattern`, `find_blocking_overlay`, `find_paywall_gate` |
| Answer position | `scroll_depth_fraction`, `is_in_collapsed_region`, `has_anchor_nav_to_answer` |
| Links | `content_area_links`, `classify_link`, `_site_host`, `_SOCIAL_SHARE_RE`, `_NAVIGATION_REGIONS`, `navigation_destinations`, `hub_url` |
| Probe | `engagement_question` |

### References
`engagement-checks.md` (per-check prose), `ai-referral-persona.md` (**read this
first** — it is the assumption the whole skill rests on), `fp-guardrails.md`,
`store-contract.md`.

### Shared library
- `lib/common/pages.py` — `effective_pages(store)`: 19 lines, returns
  `{url: {html, observation_id, headers, rendered}}` preferring `RENDER` over
  `HTTP_FETCH`.
- `lib/common/extract.py` — `extract_metadata`, `extract_links`, `url_depth`,
  `containment_ratio` (and transitively `significant_words`).
- `lib/common/observations.py`, `lib/common/findings.py`.
- **`entity_profile`** from `entity-semantic-audit` — a genuine cross-skill data
  dependency, and the one that caused this skill's worst bug (§J).

### Tests and fixtures
`tests/test_engagement_audit.py` (~1000 lines after the navigation and
orientation additions). Fixtures: `deep-page-no-orientation`,
`strong-disc-weak-engage`, `weak-disc-strong-engage`, `both-weak`, `both-strong`,
`single-page-site`, `fp-trap-composite`.

---

## C. END-TO-END WORKFLOW

```
store + entity_profile
  │
  ▼ effective_pages(store)      RENDER preferred; else HTTP_FETCH
  │ rendered_pages_only(store)  RENDER only — used by E-ANSWER-02/03/04
  │
┌──────────────────────────────────────────────────────────────────┐
│ detect_engagement(store, entity_profile)                          │
│                                                                   │
│  E-ORIENT-01  needs profile → _brand_tokens(profile, for_url=url) │
│               skip depth<2 → brand_token_positions(first 800 ch)  │
│  E-ORIENT-03  skip if max site depth <3 → has_breadcrumb          │
│  E-ORIENT-04  internal_fragment_links → has_dom_anchor(target)    │
│                                                                   │
│  E-ANSWER-01  containment_ratio(title+desc, main_text) < 0.2      │
│  E-ANSWER-02  rendered only → find_blocking_overlay               │
│  E-ANSWER-03  rendered only → find_paywall_gate + content > 400   │
│  E-ANSWER-04  rendered only + PROBE → scroll_depth_fraction       │
│                                                                   │
│  E-CONTINUE-01 content links exist but none internal → nav check  │
│  E-CONTINUE-02 no content links at all           → nav check      │
│  E-CONTINUE-03 hub page crawled but not linked from the page      │
│  E-CONTINUE-04 content link whose crawled target is >=400         │
└──────────────────────────────────────────────────────────────────┘
  │ findings (category="engagement")
  ▼
```

**Two page-selection modes matter.** `effective_pages` prefers rendered HTML but
falls back to raw. `rendered_pages_only` returns nothing without a renderer —
which is why `E-ANSWER-02/03/04` silently produce nothing on a Playwright-less
run, and why the orchestrator's `RENDERER_UNAVAILABLE` coverage entry matters.

**Failure behaviour.** `_brand_tokens(None)` → `[]` → `E-ORIENT-01` returns `[]`.
Every other check guards on empty page sets. Nothing raises on odd HTML.

---

## D. INPUT CONTRACT

| Input | Type | Origin | Required | If missing / malformed |
|---|---|---|---|---|
| `store["observations"]` | list | `collect.py` | yes | no pages ⇒ every check returns `[]` |
| `RENDER` observations | — | `collect.py:211` | **required for `E-ANSWER-02/03/04`** | those three produce nothing; orchestrator records `RENDERER_UNAVAILABLE` |
| `entity_profile` | dict or `None` | `build_entity_profile` | required for `E-ORIENT-01` only | `None` or no canonical name ⇒ `E-ORIENT-01` returns `[]` with the comment "that gap is D-ENTITY-01's, not this skill's" |
| `PAGE_CLASSIFICATION` | — | **never produced** | no | `is_terminal_page` falls back to `is_utility_path` alone; `E-ORIENT-03`, `E-CONTINUE-01/02/03` still run |
| `PROBE` | — | **never produced** | no | `E-ANSWER-04` hard-gated (`if not probe: continue`). `E-ANSWER-01`/`E-CONTINUE-01` use it only to **soften** — see §F.3 |

**A design point worth noticing:** `E-ORIENT-01` deliberately declines to report
"no brand anywhere" when the entity profile has no canonical name. That would be
`D-ENTITY-01`'s finding. The two skills do not double-report the same defect.

---

## E. OUTPUT CONTRACT

Standard `make_finding` shape with `category = "engagement"`. Nothing unusual,
with one exception worth knowing: `E-ORIENT-04` and `E-CONTINUE-04` put **two**
observation ids per broken link into `observation_ids` — the source page's *and*
the target page's — because the claim ("this link points at something broken")
rests on both observations. Look at `obs_ids = [oid for …] + [oid for …]` in
`check_e_orient_04`.

---

## F. CHECK-BY-CHECK BREAKDOWN

### F.1 Evaluability

| Class | Checks |
|---|---|
| Always evaluable | `E-ORIENT-03`, `E-ORIENT-04`, `E-CONTINUE-02`, `E-CONTINUE-03`, `E-CONTINUE-04` |
| Needs the entity profile | `E-ORIENT-01` |
| Needs a renderer | `E-ANSWER-02`, `E-ANSWER-03` |
| Needs a renderer **and** a probe — not evaluable | `E-ANSWER-04` |
| Evaluable; probe **softly** refines | `E-ANSWER-01`, `E-CONTINUE-01` |

### F.2 The table

| Check | Purpose | Mechanical test | Sev/Conf | Guardrails |
|---|---|---|---|---|
| **E-ORIENT-01** | no brand identification on arrival | depth ≥2; `brand_token_positions(html, title, tokens)` all False | high/high | Skips homepage and depth-1. Returns `[]` entirely if no canonical name. `for_url=` drops aliases whose only evidence is this page (§J) |
| **E-ORIENT-03** | no breadcrumb on a deep page | site `max_depth >= 3`; page depth ≥2; not terminal; `not has_breadcrumb(html)` | medium/high | Flat sites exempt — "nothing to show a breadcrumb for". Terminal/landing pages exempt: omitting nav there is a design choice |
| **E-ORIENT-04** | fragment link with no matching anchor | for each internal `#fragment` link, the **crawled** target lacks a matching `id`/`name` | medium/high | Uncrawled target ⇒ `continue` (applicability unmet). `#` and `#top` ignored |
| **E-ANSWER-01** | title/description promises what the body doesn't deliver | `title_desc` non-empty; `len(main_text) > 400`; `containment_ratio(title_desc, body) < 0.2` | medium/variable | The 400-char floor exempts listing/grid pages where divergence is normal. A probe Q5 answer that *does* overlap suppresses it |
| **E-ANSWER-02** | entry-blocking interstitial | rendered only; `find_blocking_overlay(html)` returns a visible modal-shaped node | high/high | `_is_hidden` excludes `display:none`/`hidden`/`aria-hidden`. Compliant cookie banners are matched by `_CONSENT_NAME_RE` and excluded |
| **E-ANSWER-03** | paywall over substantive content | rendered only; `find_paywall_gate(html)` **and** `len(main_text) > 400` | high/high | ≤400 chars is "an honest preview, not a mismatch" |
| **E-ANSWER-04** | answer buried below the fold | rendered + probe; `scroll_depth_fraction(html, span)` beyond threshold | high/high | **Not evaluable.** `is_in_collapsed_region` and `has_anchor_nav_to_answer` exist as suppressors |
| **E-CONTINUE-01** | no relevant next step | ≥2 pages; not terminal; content links exist but **none** `internal_content`; **and** `navigation_destinations < 2` | medium/variable | Probe Q8 answered ⇒ suppressed. Navigation suppression added later (§J) |
| **E-CONTINUE-02** | dead end | ≥2 pages; not terminal; **no** content-area links at all; **and** `navigation_destinations < 2` | medium/high | Single-page sites exempt by design. Navigation suppression is the main guardrail |
| **E-CONTINUE-03** | no route back to the hub | hub URL derived by `hub_url(url)` **and demonstrably crawled**; hub not among the page's content links | low/high | "never invented from URL shape alone — hub must be demonstrably crawled" |
| **E-CONTINUE-04** | broken internal content link | a content-area link whose **already-fetched** target returned ≥400 | medium/high | "never fetched to verify; only reasons over what's already observed" — the skill never triggers a fetch |

### F.3 Soft vs hard probe gates — a distinction that matters

Four checks reference `probes(store)`. Only **one** is disabled by its absence.

- **`E-ANSWER-04`** — `if not probe: continue`. **Hard.** Disclosed as
  `UNAVAILABLE_INSTRUMENT`.
- **`E-ANSWER-01`** — computes the deterministic overlap first, then consults
  probe Q5 only to *suppress* a finding and to lower confidence from `high` to
  `medium`. Without a probe the check runs at `medium` confidence.
- **`E-CONTINUE-01`** — same pattern with Q8.
- **`E-ORIENT-03`, `E-CONTINUE-01/02/03`** use `page_classifications()`, also
  absent, also soft: `is_terminal_page` degrades to `is_utility_path`.

This is why the orchestrator's disclosure list contains `E-ANSWER-04` but not the
others — the disclosure is deliberately precise rather than listing every check
that merely *mentions* an unavailable instrument.

---

## G. SUPPORTING FUNCTIONS AND ALGORITHMS

### `_brand_tokens(entity_profile, for_url=None)` — `detect_engagement.py:52`
**Why it exists:** `E-ORIENT-01` needs the set of strings that would tell a
visitor whose site this is.
**Algorithm:** canonical name + comma-split aliases. When `for_url` is given, it
groups the alias field's `candidates` by value, collects `{value: {source_urls}}`,
and **drops any alias whose entire provenance is `{for_url}`**.
**Why:** a page cannot identify its owner by repeating its own title. Finding
"Rate Limit Configuration" on `/docs/rate-limits` proves nothing about ownership.
The canonical name is never dropped — if a page's title *is* the brand name, that
is real identification.
**Called by:** `check_e_orient_01`, once per page (note the per-page call, not a
hoisted one).

### `brand_token_positions(html, title, tokens, first_screen_chars=800)` — `_engagement_util.py:120`
Returns `{title: bool, first_screen: bool, …}`. The `800`-character window is a
proxy for "the first screen". **Edge case:** 800 characters of *text*, not
rendered pixels — a page with a large image header has no way to express that
here. Uses Unicode word-boundary matching so short brand names ("AI", "Arc") do
not match inside unrelated words (§J).

### `main_content_soup(html)` / `main_text(html)` — `_engagement_util.py:95`
Scopes to `<body>` when present, then `decompose()`s `_CHROME_TAGS`
(`nav, header, footer, script, style, noscript`).
**Read the docstring in source** — it records a real bug: without the `<body>`
scoping, `get_text()` also walks `<head>` including `<title>`, so "body text"
silently contained the page's own title. That defeats `E-ANSWER-01`'s
title-vs-body comparison entirely and offsets `E-ANSWER-04`'s scroll-depth
measurement by the title length.

### `navigation_destinations(html, base_url)` — `_engagement_util.py:399`
**Why it exists:** the fix for the dead-end false positive (§J).
**Algorithm:**
1. Parse, scope to `<body>`.
2. Collect `_NAVIGATION_REGIONS` (`nav`, `header`, `footer`) **plus** any element
   with `role="navigation"` (the ARIA spelling, common in generated markup).
3. For each link in those regions: skip `unsafe_action`; require
   `classify_link(...) == "internal_content"`; strip the fragment; skip links
   whose path equals the current page's path.
4. Return the sorted set.
**Edge cases it deliberately handles:** empty `<nav>`, anchors with no `href`,
fragment-only hrefs, self-links, and external-only navigation all yield too few
destinations to suppress anything.

### `classify_link(link, base_url)` — `_engagement_util.py:372`
Returns one of `social_or_mail`, `external`, `same_page_anchor`,
`internal_content`. Same-site is decided by `_site_host` (www-normalized) and
accepts **descendant** hosts, without guessing registrable domains from the last
two labels — see the `OVERFITTING_AUDIT.md` row on `co.uk` and hosted tenants.

### `find_blocking_overlay(html)` — `_engagement_util.py:238`
Scans `_MODAL_CONTAINER_TAGS` (`div, section, aside, dialog, form`), matching
`_MODAL_NAME_RE` on class/id/role, requiring `not _is_hidden(tag)`, and excluding
anything matching `_CONSENT_NAME_RE`. **Why the consent exclusion:** a compliant
cookie banner is a legal requirement, not an engagement defect.

### `has_breadcrumb(html)` — `_engagement_util.py:154`
Two independent detectors: a `breadcrumb`-named class/id/aria-label, **or**
`_TEXTUAL_PATH_RE` matching a visible `A > B` / `A › B` path. The textual fallback
is scoped to `main_text(html)[:600]` so a `>` deep in body prose does not count.
**Known weakness:** an *empty* breadcrumb container passes.

### `hub_url(url)` — `_engagement_util.py:437`
Returns the parent directory URL, or `None` when there are fewer than two path
segments. `E-CONTINUE-03` then requires that hub to be **in `pages`** — the check
never invents a hub that was not crawled.

### `scroll_depth_fraction(html, evidence_span)` — `_engagement_util.py:285`
Character offset of the span within `main_text`, divided by total length. A
character-count proxy for scroll depth, with no viewport model. Unreachable in
this deployment (needs a probe span).

---

## H. ALGORITHMS AND HEURISTICS

| Heuristic | Assumes | Threshold | Below | Above | Status |
|---|---|---|---|---|---|
| Deep-link persona | an AI cites a specific page, not the homepage | `url_depth < 2` skipped | not evaluated | evaluated | Design rule from `ai-referral-persona.md` |
| First screen | the first 800 chars of text approximate the first screen | `800` | brand token counts as "on first screen" | not counted | **Chosen proxy.** No viewport model exists |
| Content-bearing prose | under 400 chars is a listing/grid | `400` | `E-ANSWER-01`/`-03` skip | evaluated | Chosen; shared with `crawl-render-audit`'s floor |
| Title-body overlap | ≥20% significant-word containment means the title describes the body | `0.2` | finding | suppressed | **Chosen.** Depends on `containment_ratio`/`significant_words` — see §J for the cross-script bug |
| Navigation is continuation | ≥2 internal nav destinations means the visitor can continue | `MIN_NAVIGATION_DESTINATIONS = 2` | check may fire | suppressed | Reasoned: **one** destination is satisfied by a bare "Home" link, which returns the visitor to the start rather than letting them continue |
| Breadcrumb relevance | a site under 3 levels deep needs no breadcrumb | `max_depth >= 3` | check disabled sitewide | enabled | Chosen |
| Textual breadcrumb scope | a path separator early in the text is navigation | first `600` chars | not a breadcrumb | may count | Chosen |

Only `MIN_NAVIGATION_DESTINATIONS = 2` has a stated reason beyond convention.
The rest are chosen operating points; the repository does not claim otherwise.

---

## I. EVIDENCE MODEL

**Example 1 — `E-ANSWER-02` (from a live run):**
```
title    : Entry-blocking interstitial on http://…/
evidence : Blocking element found on http://…/:
           {'tag': 'div', 'class': 'modal-overlay', 'id': '', 'role': 'dialog'}
obs ids  : 1 (the RENDER observation)     source_urls: 1
```
The evidence is the **actual DOM node signature** that matched. A reader can open
the rendered DOM and find that node. This is the strongest evidence shape in the
skill because it names a specific element rather than describing a condition.

**Example 2 — `E-CONTINUE-02` after the navigation fix:**
```
observed_signal : no in-content internal links and fewer than 2 internal
                  destination(s) in site navigation
evidence        : Outgoing content-area link kinds on …/gadget.html: [];
                  internal navigation destinations: []
```
Note that the evidence proves **both halves** of the claim — that the content
area had no links *and* that navigation offered nothing. Before the fix, the
evidence only reported the first half, which is precisely why the finding was
indefensible on a site whose nav was fine.

**Evidence sizing.** `_engagement_util` truncates extracted text at `[:200]` and
`[:120]` when building node descriptors, bounding site-controlled text before it
reaches a finding.

---

## J. FALSE POSITIVES / FALSE NEGATIVES — historical record

| Issue | Old behaviour | Why wrong | Fix | Regression test |
|---|---|---|---|---|
| **Dead-end false positives** | `E-CONTINUE-02` fired whenever the *content region* had no internal links | Brochure, documentation and catalogue sites keep their whole internal link graph in `<nav>`. A healthy 4-page site produced **5** "Dead end" findings at `confidence: high` — the single most visible false positive in the project | `navigation_destinations` + `MIN_NAVIGATION_DESTINATIONS`; mechanism/evidence text updated to state both halves | `test_e_continue_02_does_not_fire_on_a_brochure_page_with_nav_only_links`, header/footer/`role=navigation` variants, and five malformed-nav cases |
| **Same flaw in `E-CONTINUE-01`** | content links existed but all external ⇒ "no way to go deeper without returning to search" | A populated nav falsifies that exact claim | Same nav evidence applied — after confirming the check's stated mechanism, not by copying | `test_e_continue_01_does_not_fire_when_navigation_offers_a_way_deeper` + malformed/external-only cases |
| **Alias pollution disabling `E-ORIENT-01`** | `_brand_tokens` consumed every alias from the entity profile, and the profile admitted every page's own title as an alias | A deep page always self-matched one of its own "brand aliases", so `E-ORIENT-01` could not fire on any realistically-titled page. Recorded as a `confirmed_false_negative` in two fixtures | Upstream: aliases now need ≥2 pages or a structured declaration. Here: `_brand_tokens(for_url=…)` drops page-local aliases | `test_a_deep_pages_own_title_does_not_identify_its_owner`; corpus `deep-page-no-orientation` and `strong-disc-weak-engage` now **expect** `E-ORIENT-01` |
| **Cross-script `E-ANSWER-01`** | `containment_ratio` used an ASCII-only tokenizer, so Greek/CJK/Cyrillic produced an empty token set and overlap was always `0.0` | The `overlap >= 0.2` suppression never fired, so the check reported **3 of 3** pages of a healthy Greek site as a title/body mismatch — a systematic false positive across whole language families | Unicode-aware `significant_words` (CJK via bigrams) in `lib/common/extract.py` | `test_e_answer_01_never_fires_when_a_non_ascii_title_matches_its_body` (greek/japanese/french) + `test_e_answer_01_still_fires_on_a_genuine_non_ascii_mismatch` |
| **Title leaking into body text** | `main_text` walked `<head>` | The title always "matched" the body, defeating `E-ANSWER-01` | `main_content_soup` scopes to `<body>` | documented in the function docstring; covered by `E-ANSWER-01` cases |
| **Short brand substring matches** | plain substring search | "AI"/"Arc"/"One" matched inside unrelated words | Unicode word-boundary matching in `brand_token_positions` | `test_short_brands_do_not_match_inside_unrelated_words` |
| **Query strings ⇒ utility page** | any query URL was "utility" | Query-addressed primary content was excluded from engagement checks | separated the rules | `test_query_addressed_content_is_not_automatically_utility` |

**Standing false negative:** `E-ANSWER-04` cannot fire. Disclosed at runtime.

---

## K. TESTING

- **`tests/test_engagement_audit.py`** — fire/suppress pairs per check. The
  navigation block is the largest addition: brochure/docs/header/footer/ARIA
  suppression cases, a true dead end, a nav-with-only-Home case, five
  malformed-nav parametrized cases, and an external-only case.
- **Cross-script block** — Greek, Japanese and accented French title/body pairs,
  each structurally different (a non-Latin alphabet that uses spaces, a script
  with no spaces, accented Latin), plus a genuine non-ASCII mismatch as a
  control so the fix cannot be "suppress everything".
- **Orientation block** — the own-title, sitewide-alias and canonical-name cases
  for `_brand_tokens`.
- **Corpus fixtures** — `deep-page-no-orientation` isolates `E-ORIENT-01` on a
  single deep page; `weak-disc-strong-engage` and `strong-disc-weak-engage` are
  deliberate cross-products proving the two halves of the brief are independent.

**A test bug worth knowing about.** While adding the cross-script control, the
`page_html` helper's default `h1=None` sets the `h1` **to the title**, so a
"mismatch" fixture accidentally contained the title inside the body and the
control did not fire. The fix was to the test, not the code. If you write new
`E-ANSWER-01` cases, pass `h1=` explicitly.

**Weak spots.** `scroll_depth_fraction`, `is_in_collapsed_region` and
`has_anchor_nav_to_answer` are only reachable with a hand-injected probe. Empty
breadcrumb containers pass `has_breadcrumb` and no test covers that.

---

## L. LIMITATIONS

**Implementation.** `800` chars stands in for a viewport. Breadcrumb detection
accepts an empty container. `hub_url` is a URL-shape derivation. Overlay/paywall
detection is class/id/role pattern matching — a framework using neutral class
names is invisible to it.

**Data/observation.** No `PAGE_CLASSIFICATION` ⇒ `is_terminal_page` degrades to
path matching. No `PROBE` ⇒ `E-ANSWER-04` dead and two checks lose their
suppressor.

**Environment.** Without Playwright, `E-ANSWER-02/03/04` produce nothing.

**Generalization.** `_MODAL_NAME_RE`, `_CONSENT_NAME_RE`, `_PAYWALL_NAME_RE` and
`_SOCIAL_SHARE_RE` are English. `_TEXTUAL_PATH_RE` assumes Western separators.
`OVERFITTING_AUDIT.md` additionally records that brand word boundaries remain
imperfect for scripts without word spacing.

**Deliberately unsupported.** Single-page sites are exempt from `E-CONTINUE-01/02`.
Terminal/landing pages are exempt from orientation and continuation checks. No
check ever triggers a fetch to verify a link — `E-CONTINUE-04` reasons only over
already-observed targets.

---

## M. HOW A HUMAN WOULD IMPROVE THIS SKILL

### Low-risk
- **Require a non-empty breadcrumb.** Current: a container with a breadcrumb class
  passes even when empty. Better: require ≥2 resolvable items. Files:
  `_engagement_util.has_breadcrumb`. Tests: `E-ORIENT-03`. Risk: low — it can only
  increase firing on genuinely empty markup, so add a suppression test first.
- **Surface which nav destinations suppressed a continuation check** in a demoted
  record, so a reader can see the suppression. Files: `detect_engagement.py`.

### Architectural
- **Real viewport/occlusion measurement instead of the 800-char proxy.** Current:
  character counting. Better: Playwright bounding boxes captured at render time
  into the `RENDER` observation. Tradeoff: changes the observation contract and
  couples engagement to the renderer. Files: `lib/site_observer/render.py`,
  `store-contract.md`, `_engagement_util`. Tests: orientation and `E-ANSWER-04`.
  Risk: **high** — touches the safety-reviewed render path.
- **Structural overlay detection** (computed z-index/position/coverage) rather than
  class-name patterns. Same dependency on richer render observations.
- **Apply the navigation-evidence principle to `E-ORIENT-03`.** A page with full
  nav but no breadcrumb is arguably less lost than the check assumes. This is a
  judgement call, not an obvious win — decide what `E-ORIENT-03` measures first.

### Research / future work
- An empirical basis for `800`, `400`, `0.2`. All are chosen operating points.
- Non-English overlay/paywall/consent vocabularies.

---

## N. READ THESE FILES NEXT

1. `references/ai-referral-persona.md` — short, and every check follows from it.
2. `lib/common/pages.py` — 19 lines; the render-preferred page selection that
   determines what every check sees.
3. `scripts/_engagement_util.py::main_content_soup` — read the docstring, then
   `main_text`, then `content_area_links` and `classify_link`.
4. `scripts/_engagement_util.py::navigation_destinations` — the newest and most
   consequential helper.
5. `scripts/detect_engagement.py::check_e_continue_02` then `check_e_continue_01` —
   read them together; the difference between them is the whole design.
6. `scripts/detect_engagement.py::_brand_tokens` then `check_e_orient_01`.
7. `references/fp-guardrails.md` — after the code.
8. `tests/test_engagement_audit.py` — the navigation and cross-script blocks.
9. `skills/entity-semantic-audit/KNOWLEDGE.md` §J — the upstream half of the
   alias-pollution bug.
