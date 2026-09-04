# False-positive guardrails

Evaluated BEFORE the detection test. If the applicability precondition fails, the
check does not fire and is not recorded as a pass. Full mechanism/threshold detail
lives with each check in `engagement-checks.md`; this file is the compiled
cross-reference.

## Never flag (marketplace-wide, verbatim from the design brief)
- irrelevant absence of a feature the site does not need
- normal JavaScript use
- structured data that is unnecessary for the page type
- short pages
- unusual visual design
- an LLM subjective opinion unsupported by a measurement

## This skill's own explicit "never flag" list (from the design brief)
- a page merely because it is short
- a page merely because it has few buttons
- a page merely because it looks visually simple
- a missing call-to-action when no CTA is appropriate for that page

No check in this skill may fire from any of the above alone. Every detection
test below requires a positional or structural measurement **and** a
demonstrated connection to AI-referred, deep-linked arrival specifically.

## Skill-specific suppressions

| Check ID | Suppression condition | Effect |
|---|---|---|
| E-ORIENT-01 | Brand token present in any one of {early body text, logo alt, title} | never fires |
| E-ORIENT-01 | Page is at depth 1 (homepage-adjacent) | never fires — different arrival context |
| E-ORIENT-01 | Entity profile has no determined canonical name | never fires — that gap is D-ENTITY-01's, not this skill's |
| E-ORIENT-03 | Site has `<=2` levels of URL depth sitewide | never fires — nothing to show a breadcrumb for |
| E-ORIENT-03 | Page is classified `landing_page` | never fires — deliberate navigation-free design, not a defect |
| E-ORIENT-04 | Fragment link's target page was never crawled | never fires — cannot confirm either way |
| E-ORIENT-04 | Fragment targets `#top`/`#` | never fires |
| E-ANSWER-01 | Containment overlap `>= 0.2` | never fires |
| E-ANSWER-01 | Page is a listing/grid page (not content-bearing prose) | never fires — title/body divergence is normal structure there |
| E-ANSWER-02 | No `RENDER` observation with `status == "ok"` | never fires — inapplicable, not approximated from raw HTML |
| E-ANSWER-02 | Element is a compliant, non-occluding cookie/consent banner | never fires |
| E-ANSWER-02 | Element is explicitly hidden at render time | never fires |
| E-ANSWER-02 | Element is a `<button>`/`<a>`/`<input>` trigger, not a container | never fires — a hostile review found a visible "modal-trigger" button flagged as the dialog itself |
| E-ANSWER-03 | No `RENDER` observation with `status == "ok"` | never fires |
| E-ANSWER-03 | Content outside the gate is below the 400-char floor (an honest preview) | never fires |
| E-ANSWER-03 | — | **never scolds a legitimate paywall** — framed only as a citation-mismatch risk |
| E-ANSWER-04 | No answered `PROBE` question with `relevant` **explicitly** `true` | never fires — unset is never treated as relevant |
| E-ANSWER-04 | Scroll-depth fraction `<= 0.5` and not in a collapsed region | never fires |
| E-ANSWER-04 | A direct in-page anchor-nav link to the answer's section exists | never fires — a long page that jumps straight there isn't "buried" |
| E-CONTINUE-01 | Site has `<2` crawled pages (a genuinely single-page site) | never fires — nowhere "deeper" to go, by design |
| E-CONTINUE-01 | Page is a terminal/utility page (contact, thank-you, landing_page) | never fires — applicability excludes it entirely |
| E-CONTINUE-01 | `>=1` outgoing content-area link classifies as internal content or a same-organization subdomain | never fires |
| E-CONTINUE-02 | Site has `<2` crawled pages | never fires |
| E-CONTINUE-02 | Page is a terminal/utility page | never fires |
| E-CONTINUE-02 | Global nav/header/footer links | never counted toward or against this check |
| E-CONTINUE-03 | No hub URL was itself crawled | never fires — never invented from URL shape alone |
| E-CONTINUE-04 | Link target was never crawled | never fires — never re-fetched to "double check" |

## Compound-trigger / fallback-only checks
E-ORIENT-01 (compound: all three positions absent), E-ANSWER-01 (deterministic
overlap, with `PROBE` Q5 consulted only when inconclusive and available),
E-ANSWER-04 (a real `PROBE` answer + a positional/structural measurement),
E-CONTINUE-01 (deterministic link classification, with `PROBE` Q8 consulted
only when zero internal content links are found).
