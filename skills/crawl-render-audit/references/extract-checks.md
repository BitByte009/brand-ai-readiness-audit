# D-EXTRACT — extractability (gate 3)

Twelve-field form for every check this skill owns in this category, per
`<marketplace-root>/references/failure-taxonomy.md`. Implemented in
`scripts/detect_extract.py`. Store types referenced below are defined in
`store-contract.md`.

Checks D-EXTRACT-01, -06 and -07 read `PROBE` observations (the extraction-probe
instrument, `lib/site_observer/probe.py`) and interpret only questions with
`category == "factual"`. Identity-category questions belong to
`entity-semantic-audit`; this skill never interprets them (`SKILL.md` boundary).

---

## D-EXTRACT-01 — key facts locked in non-text media
- **Meaning:** a fact the page is plausibly about exists only inside an image, PDF,
  or video, with no text equivalent anywhere on the page.
- **Mechanism:** Appendix B/C. A text-only reader extracts nothing from a raster
  image, a PDF it doesn't open, or a video it doesn't transcribe.
- **Applicability:** a `PROBE` observation exists for the page with `>=1` factual
  question marked `relevant == true`.
- **Observable signals:** the relevant question's `answered` value; presence of
  `<img>` elements with empty/missing `alt` on the page; presence of a linked PDF
  with no adjacent descriptive text.
- **Detection test:** fire when a relevant factual question is `answered == false`
  **and** the page has `>=1` image with empty/missing `alt` text or `>=1` linked PDF
  with no surrounding descriptive sentence — i.e. the probe miss co-occurs with a
  plausible non-text carrier, never on the probe miss alone.
- **Evidence required:** `OBS-PROBE-*` (question id, `answered: false`),
  `OBS-HTTP-FETCH-*` (the empty-alt image or bare PDF link).
- **False-positive rules:** only fires when the fact is unavailable in text
  *elsewhere on the same page* — a probe miss with no non-text carrier present is
  D-EXTRACT-06/07's territory instead, not this check's.
- **False-negative risks:** a fact conveyed in a video with no transcript is not
  independently confirmed as the *source* of the miss — the co-occurrence test is a
  proxy, not a proof of causation, so confidence is capped at medium.
- **Severity:** high.
- **Confidence:** medium.
- **Recommendation:** state the fact in plain text on the page (a caption, alt text
  carrying the actual data, or a text summary alongside the PDF/video), in addition
  to the existing media.
- **Validation:** re-run the probe on text alone; the question now answers.

## D-EXTRACT-02 — missing, empty, boilerplate, or duplicated title/meta description
- **Meaning:** `<title>` or the meta description is absent, empty, identical
  boilerplate, or duplicated verbatim across distinct pages.
- **Mechanism:** Appendix B. Title and description are the first-line summary most
  citation and search pipelines surface; losing uniqueness collapses distinct pages
  into one signal.
- **Applicability:** `>=2` crawled pages exist (duplication needs a comparison set);
  presence/emptiness fires even at `n=1`.
- **Observable signals:** `extract_metadata(html)["title"]` / `["description"]` per
  page; multiset of non-empty values across the crawl.
- **Detection test:** fire per template cluster where `>=1` page has an empty title
  or description, **or** where `>=2` distinct pages (not legitimate near-duplicates,
  see below) share an identical non-empty title or description.
- **Evidence required:** `OBS-HTTP-FETCH-*` for each affected page, the shared/empty
  value quoted.
- **False-positive rules:** paginated series of the same content (`?page=2`, `/2/`)
  sharing a title stem are expected and excluded — duplication is only flagged
  between pages in *different* template clusters or clearly distinct content within
  the same cluster (different slugs beyond a pagination/sort parameter).
- **False-negative risks:** titles that are unique strings but semantically
  uninformative ("Home", "Page") pass this check; that gap is covered qualitatively
  by E-ANSWER-01 (title-body promise) in a sibling skill, not duplicated here.
- **Severity:** medium.
- **Confidence:** high.
- **Recommendation:** write a unique, descriptive title and meta description per
  page, naming the page's specific subject.
- **Validation:** re-fetch; the title/description is non-empty and no longer matches
  another page outside a legitimate pagination series.

## D-EXTRACT-03 — missing structured data (compound trigger only)
- **Meaning:** no structured data of a supported type, **and** the fact-probe failed
  to extract the corresponding canonical fact from prose.
- **Mechanism:** Appendix B/C. Structured data is one path to machine-unambiguous
  facts, not the only one; the failure that matters is the fact being
  unextractable, not the markup being absent.
- **Applicability:** `PAGE_CLASSIFICATION` exists and maps to a supported schema.org
  type (`product -> Product`, `article -> Article`, `organization -> Organization`,
  `local_business -> LocalBusiness`, `faq -> FAQPage`, `event -> Event`) **and** a
  `PROBE` observation exists with `>=1` relevant factual question for that type.
- **Observable signals:** presence of a matching `@type` in `extract_jsonld(html)`;
  the relevant probe question(s)' `answered` value.
- **Detection test:** fire only when **both** conditions hold: no JSON-LD node with
  the matching `@type` exists, **and** `>=1` relevant factual question is
  `answered == false`. If prose states the facts clearly (probe answers), the check
  does not fire regardless of markup.
- **Evidence required:** the classified page type, `OBS-HTTP-FETCH-*` (JSON-LD
  absence), `OBS-PROBE-*` (the failed question).
- **False-positive rules:** never fires on markup absence alone; never fires on page
  types with no clear schema.org mapping; never recommends a schema type the content
  doesn't actually support.
- **False-negative risks:** a page misclassified by `PAGE_CLASSIFICATION` inherits
  that error; this check does not second-guess the classification, only consumes it.
- **Severity:** medium base; high when the page is commercially primary (in-scope,
  high link centrality) and multiple canonical facts are unextractable.
- **Confidence:** high — both trigger conditions are deterministic given their inputs.
- **Recommendation:** add the specific schema.org type with the specific properties
  whose facts failed the probe, **and** state the same facts in plain prose — both,
  not either.
- **Validation:** re-run the probe on text alone (must now answer); validate the
  added JSON-LD parses with required properties present and matching visible text.

## D-EXTRACT-04 — structured data invalid or contradicts the page
- **Meaning:** JSON-LD/microdata is present but fails to parse, is missing a
  required property for its declared type, or asserts a value that contradicts the
  visible DOM text.
- **Mechanism:** Appendix B. A machine that trusts structured data over prose (most
  do) picks up the wrong or incomplete fact, or discards the block entirely on a
  parse failure.
- **Applicability:** `>=1` JSON-LD block exists on the page.
- **Observable signals:** JSON parse success; required-property presence for the
  declared `@type` (a small fixed map: `Product` needs `name`+`offers.price` or
  `offers.priceCurrency`; `Article` needs `headline`+`datePublished`; `LocalBusiness`
  needs `name`+`address`; `Event` needs `name`+`startDate`); numeric/date value
  agreement against text extracted from the DOM near the equivalent visible field.
- **Detection test:** fire on JSON parse failure; fire when a required property for
  the declared type is absent; fire when a structured value (price, date) differs
  from a plainly visible on-page value stating the same fact.
- **Evidence required:** `OBS-HTTP-FETCH-*`, the raw JSON-LD block (or the parse
  error with line reference), the visible-text value it contradicts where applicable.
- **False-positive rules:** optional-property gaps are never flagged — only the
  declared type's required properties. Vocabulary extensions (extra, non-standard
  properties) are never flagged.
- **False-negative risks:** a contradiction between structured data and a fact stated
  only in an image or PDF (not DOM text) cannot be cross-checked by this test; it is
  out of scope, not silently asserted as passing.
- **Severity:** high.
- **Confidence:** high for parse failures and required-property gaps (fully
  mechanical); medium for value-contradiction (text-matching heuristic).
- **Recommendation:** fix the JSON syntax error, add the missing required property,
  or correct the structured value to match the visible, authoritative one.
- **Validation:** re-fetch; the block parses, required properties are present, and
  the structured value matches the visible text.

## D-EXTRACT-05 — unusable heading structure
- **Meaning:** the page has no `<h1>`, or headings are used purely for visual styling
  with no relationship to the content outline.
- **Mechanism:** Appendix B. Headings are the cheapest machine-readable outline of
  "what is this page actually organized around"; a broken outline forces a reader
  (machine or human) to infer structure from font size alone.
- **Applicability:** `HTTP_FETCH.status_code == 200`; page is content-bearing
  (extracted text `> 400` chars).
- **Observable signals:** heading tag inventory and nesting order; ratio of headings
  whose immediately-following text block is non-empty.
- **Detection test:** fire when no `<h1>` exists anywhere on the page; separately,
  fire when `>=50%` of headings are immediately followed by no associated text block
  before the next heading of equal-or-higher level (a proxy for headings used only
  as visual dividers with no organizational role).
- **Evidence required:** `OBS-HTTP-FETCH-*`, the heading outline extracted.
- **False-positive rules:** multiple `<h1>`s are valid HTML5 and never flagged on
  their own; only a genuinely unusable outline (zero `h1`, or the empty-section
  majority test) fires.
- **False-negative risks:** a page with exactly one `h1` and reasonable-looking
  nesting but semantically wrong heading levels (e.g. `h1` then `h4`) is not detected
  by this presence/text-adjacency test; that class of error is lower-impact and
  deliberately out of scope to keep the test mechanical.
- **Severity:** low base, medium when combined with the no-`h1` condition on a
  primary (high-centrality) page.
- **Confidence:** high.
- **Recommendation:** add exactly one `h1` stating the page's subject, and ensure
  each heading introduces the text block that follows it.
- **Validation:** re-fetch; `>=1` `h1` is present and the empty-section ratio drops
  below `50%`.

## D-EXTRACT-06 — low quotable-answer density
- **Meaning:** no self-contained sentence anywhere in the machine-readable text could
  be lifted as a direct answer to what the page is evidently about.
- **Mechanism:** Appendix B/C, the extraction-probe differentiator. This is a direct
  mechanical simulation of what a citation pipeline does: read the text, try to
  answer canonical questions from it, and see what fails.
- **Applicability:** a `PROBE` observation exists for the page with `>=2` questions
  marked `relevant == true` (questions the page is clearly about, per the probe
  instrument's own relevance judgment — this skill does not second-guess relevance).
- **Observable signals:** count of relevant factual questions with `answered ==
  false`.
- **Detection test:** fire when `>=2` relevant factual questions are unanswered from
  text alone.
- **Evidence required:** `OBS-PROBE-*` — every unanswered relevant question id and
  the machine-readable text that was available to the probe (via
  `source_text_hash`/the stored input).
- **False-positive rules:** requires `>=2` failed relevant questions, never one;
  never fires on a page with no relevant questions at all (a page the probe judged
  not to be "about" the canonical topics is not penalized for not answering them).
- **False-negative risks:** the probe's canonical question set is fixed and finite;
  a fact outside that set that's genuinely unquotable is invisible to this
  mechanical test.
- **Severity:** high.
- **Confidence:** high — the trigger is a direct count of a recorded LLM-instrument
  observation, not a fresh judgment by this skill.
- **Recommendation:** add a short, self-contained sentence directly answering each
  named unanswered question, near the top of the relevant content section.
- **Validation:** re-run the probe on the revised text; the previously-unanswered
  questions now answer.

## D-EXTRACT-07 — facts implied rather than explicitly stated
- **Meaning:** a fact central to the page's classified type (identity, offering,
  location) is conveyed only by context or imagery, never asserted in a plain
  sentence.
- **Mechanism:** Appendix B/C. An assistant reasoning from text alone cannot infer
  from layout or imagery what a human visually assembles instantly.
- **Applicability:** `PAGE_CLASSIFICATION` exists; a `PROBE` observation exists with
  `>=1` question marked both `relevant == true` and `expects_explicit_statement ==
  true` for that page type (the small set of facts a type is expected to state
  outright, e.g. a product page stating what the product is).
- **Observable signals:** that question's `answered` value; page content-bearing
  floor (`> 400` chars, so an empty page is D-CRAWL-04/D-EXTRACT-06's territory, not
  this one).
- **Detection test:** fire when an `expects_explicit_statement` question is
  `answered == false` while the page is otherwise content-bearing.
- **Evidence required:** `OBS-PROBE-*` (question id, page type), `OBS-HTTP-FETCH-*`
  (content-length floor evidence).
- **False-positive rules:** the fact must be one the page is *about* — enforced by
  requiring `relevant == true` from the probe instrument, never asserted by this
  skill's own judgment of relevance.
- **False-negative risks:** shares the probe's canonical-question ceiling with
  D-EXTRACT-06; a type-specific expected fact not in the fixed question set is
  invisible here.
- **Severity:** high.
- **Confidence:** high.
- **Recommendation:** add one explicit sentence stating the fact in plain language,
  adjacent to the page's primary content, in addition to any visual/contextual cues.
- **Validation:** re-run the probe; the named question now answers.

## D-EXTRACT-08 — substance diluted by boilerplate (proactive-only)
- **Meaning:** the answer exists on the page but is buried under filler/boilerplate,
  measured by the ratio of substantive to boilerplate text and the position of the
  first substantive sentence.
- **Mechanism:** Appendix F (transferable principle only — no email checks are
  built). Filler dilutes the signal a summarizing system extracts, even when the
  fact is technically present.
- **Applicability:** always computable once raw text is extracted, but this check
  never becomes a finding (`failure-taxonomy.md`, "Proactive-only" section;
  `PHASE1B` Defect/demotion table: "language-dependent, subjective, and the closest
  thing in the catalog to an LLM opinion").
- **Observable signals:** ratio of sentences matching a boilerplate pattern (nav/
  legal/cookie/share-prompt phrasing) to total sentences; character offset of the
  first sentence containing an answer the probe located.
- **Detection test:** never fires as a finding. Surfaced only in the
  `proactive_opportunities` channel when the boilerplate ratio is high and a probe
  answer sits deep in the page.
- **Evidence required:** same as observable signals, attached to the proactive
  suggestion, not to a finding.
- **False-positive rules:** structurally cannot become a false-positive finding
  because it never emits a finding at all — this is the guardrail.
- **False-negative risks:** not applicable (not a defect-detection check).
- **Severity:** not applicable (proactive-only, no severity assigned).
- **Confidence:** not applicable.
- **Recommendation:** move the substantive answer earlier in reading order and trim
  repeated boilerplate blocks.
- **Validation:** not applicable — proactive suggestions carry no pass/fail
  validation step, per `evidence-prioritization`'s proactive-layer contract.

## D-EXTRACT-09 — encoding or content-type faults
- **Meaning:** the page is served with the wrong charset, renders as mojibake, or is
  served as `text/plain`/an unexpected MIME type instead of HTML.
- **Mechanism:** Appendix B/C. A parser fed the wrong encoding or content type can
  fail to extract any text at all, a total and silent extraction failure.
- **Applicability:** an `HTTP_FETCH` observation exists.
- **Observable signals:** `Content-Type` header's declared charset vs. a detected
  charset from the byte content; presence of the Unicode replacement character
  (`�`) or common mojibake byte patterns in extracted text; whether
  `Content-Type` starts with `text/html` at all.
- **Detection test:** fire when `Content-Type` does not start with `text/html` (and
  the URL is not itself a non-HTML resource by declared purpose, e.g. a `.json`
  API endpoint linked as data, not as a page); fire when the replacement character
  or a mojibake pattern appears in extracted text above a `1%`-of-characters floor.
- **Evidence required:** `OBS-HTTP-FETCH-*`, the `Content-Type` header, the
  detected-charset mismatch or the mojibake excerpt.
- **False-positive rules:** never fires on intentionally non-HTML resources (a JSON
  feed, an RSS endpoint, a PDF) that are linked as data rather than presented as the
  page itself.
- **False-negative risks:** low-frequency mojibake below the `1%` floor is
  undetected; the floor is set to avoid false-firing on a single foreign-language
  loanword or symbol.
- **Severity:** high.
- **Confidence:** high.
- **Recommendation:** declare and serve the correct charset (`UTF-8` unless there is
  a specific reason otherwise) and ensure the response `Content-Type` is
  `text/html; charset=utf-8` for page routes.
- **Validation:** re-fetch; `Content-Type` is `text/html` with a matching charset and
  no replacement-character/mojibake pattern remains in extracted text.

## Current D-EXTRACT-02 guardrail

Missing title is a finding; absence of an optional meta description alone is not.
Duplicate summaries require the same title and description on distinct content,
with canonical-alias, identical-representation and pagination suppressions.
