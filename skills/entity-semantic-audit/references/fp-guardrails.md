# False-positive guardrails

Evaluated BEFORE the detection test. If the applicability precondition fails, the
check does not fire and is not recorded as a pass. Full mechanism/threshold detail
lives with each check in `entity-checks.md`; this file is the compiled
cross-reference.

## Never flag (marketplace-wide, verbatim from the design brief)
- irrelevant absence of a feature the site does not need
- normal JavaScript use
- structured data that is unnecessary for the page type
- short pages
- unusual visual design
- an LLM subjective opinion unsupported by a measurement

## This skill's governing principle
**Absence is never the trigger by itself.** Every check below first establishes
that the missing fact is one this archetype/page/situation actually needs — via
an archetype gate, a compound trigger with a sibling check, or a requirement that
a real corroboration record exists — before it fires. The one deliberate
exception is D-ENTITY-01's zero-candidate case: an entity with no name anywhere
is never citable on any archetype, so that absence fires unconditionally.

## Skill-specific suppressions

| Check ID | Suppression condition | Effect |
|---|---|---|
| D-ENTITY-01 | A single dominant name form (`>=70%` share) exists | never fires |
| D-ENTITY-01 | Exactly 2 name forms, the minority sourced only from `schema`/`footer` (legal register) and the majority present in `title`/`h1` (public-facing) | never fires — recognized as a legal/trading-name pair, not an inconsistency |
| D-ENTITY-01 | Zero name candidates found anywhere | **still fires** — the one absence-alone exception, justified in entity-checks.md |
| D-ENTITY-01 | Archetype is `documentation` or `personal-portfolio` | fires at medium severity, not high |
| D-ENTITY-02 | A type-word or JSON-LD `@type` label appears anywhere in sampled prose | never fires |
| D-ENTITY-02 | No deterministic attempt was made first | never fires from the probe fallback alone |
| D-ENTITY-02 | Archetype is `personal-portfolio` | fires at medium severity with confidence downgraded one tier |
| D-ENTITY-03 | No `CORROBORATION` observation with `performed: true` | never fires — never inferred, never treated as "no collision found" |
| D-ENTITY-03 | Any one distinguisher (type, location, or identity anchor) is present | never fires |
| D-ENTITY-03 | Name "sounds generic" with no actual observed collision | never fires |
| D-ENTITY-04 | Different product pages describing different products | never fires — restricted to entity-level description sources only |
| D-ENTITY-04 | Multiple named locations (each address node has its own `name`) | never fires — legitimate multi-location business |
| D-ENTITY-04 | Address fields differ only by abbreviation/formatting (`St`/`Street`, `Ave`/`Avenue`, ...) | never fires — compared after normalization |
| D-ENTITY-04 | Description containment-boosted similarity `>= 0.5` | never fires — a short tagline that is a near-verbatim prefix of a longer, consistent blurb is not penalized for length |
| D-ENTITY-05 | Neither D-ENTITY-01 nor D-ENTITY-02 fired on this audit | never fires — compound trigger, never standalone |
| D-ENTITY-06 | Archetype is `documentation`, `personal-portfolio`, or `institutional` | never fires |
| D-ENTITY-06 | Offering stated on the homepage, or any page linked directly from it (depth-1) | never fires |
| D-ENTITY-06 | Archetype is `publisher-editorial` | fires only at medium confidence, never high severity |

## Compound-trigger checks (two independent signals required)
Per `PHASE1-ANALYSIS.md` §5.2: D-ENTITY-03 (corroborated collision + all
distinguishers absent), D-ENTITY-04 (two entity-level candidates + similarity/
structural-equality test), D-ENTITY-05 (identity-anchor absence + a sibling
identity-clarity failure already confirmed), D-ENTITY-06 (deterministic pattern
miss on homepage-and-depth-1 + probe miss where a probe ran).
