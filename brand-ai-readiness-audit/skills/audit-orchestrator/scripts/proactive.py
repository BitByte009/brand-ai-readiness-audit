"""Generates proactive opportunities from gaps, not defects.

Inputs:  store, demoted findings (from evidence-prioritization), kept findings
Outputs: proactive_opportunities[]
Nature:  deterministic

See ../references/proactive-layer.md for the sources and the rules (never a
defect framing, never generic, never counted in severity totals).

FINDING vs OPPORTUNITY -- the distinction this module exists to hold:

    FINDING      something is wrong or missing; the site is worse off than a
                 reasonable baseline, and the evidence shows the defect.
    OPPORTUNITY  the observed state is healthy and no check failed; there is
                 still a specific, evidence-backed way to make the site easier
                 for an AI system to quote, cite, or land a visitor inside.

Every source here therefore requires *positive* evidence of health as a
precondition -- prose that actually answers its own question, sections that
actually carry content -- so an opportunity can never be a demoted defect
wearing softer wording. A site with nothing to say gets nothing said about it:
producing zero opportunities is a correct outcome, and is preferred over any
generic advice.

Two documented sources (1: unanswered probe questions, 3: corroboration-surface
gaps) require the CORROBORATION/probe instrument, which is not wired into this
environment (see lib/site_observer/probe.py). This module honestly produces
nothing for those rather than fabricate a plausible-sounding gap it never
actually checked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
if str(MARKETPLACE_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKETPLACE_ROOT))

from lib.common.extract import extract_jsonld, heading_sections, schema_type_matches  # noqa: E402

# Evidence thresholds. Each is a floor on *observed health*, not on defect
# severity: below them the page has not demonstrated the thing the opportunity
# would build on, so nothing is offered. Deliberately conservative -- a missed
# opportunity costs nothing, a forced one is exactly the generic advice the
# brief rules out.
MIN_ANSWERED_QUESTIONS = 3   # question-shaped sections needed before markup is worth suggesting
MIN_ANSWER_WORDS = 25        # prose after a question heading that counts as a real answer
MIN_ANCHORABLE_SECTIONS = 4  # sections needed before a page is long enough to deep-link into
MIN_SECTION_WORDS = 40       # prose under a heading that makes it a citable destination
MAX_PAGES_PER_SOURCE = 3     # keep the report readable; the evidence names the full count

# Opportunities are suppressed on a page that already carries an extractability
# finding: the page has a defect to fix first, and an enhancement alongside it
# would read as noise.
SUPPRESSING_CHECK_PREFIX = "D-EXTRACT"


def _opportunity(
    *,
    source: str,
    title: str,
    evidence: str,
    why_it_matters: str,
    suggested_action: str,
    validation: str,
    confidence: str,
    source_urls: Optional[List[str]] = None,
    observation_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One opportunity in the shape the report contract requires.

    `opportunity`/`expected_mechanism`/`expected_effect` are retained
    alongside the named fields so consumers written against the original
    three-field shape keep working.
    """
    return {
        "source": source,
        "title": title,
        "evidence": evidence,
        "why_it_matters": why_it_matters,
        "suggested_action": suggested_action,
        "validation": validation,
        "confidence": confidence,
        "source_urls": sorted(set(source_urls or [])),
        "observation_ids": sorted(set(observation_ids or [])),
        "opportunity": suggested_action,
        "expected_mechanism": why_it_matters,
        "expected_effect": validation,
    }


def _page_html(store: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """{url: (html, observation_id)}, preferring the rendered DOM.

    The rendered lens is what an AI system with a browser sees; the raw lens is
    the floor. Using rendered-when-present keeps an opportunity from being
    offered against markup the site actually does ship after hydration.
    """
    pages: Dict[str, Tuple[str, str]] = {}
    for observation in store.get("observations", []) or []:
        kind = observation.get("type")
        if kind not in ("HTTP_FETCH", "RENDER"):
            continue
        html = (observation.get("value", {}) or {}).get("html", "")
        url = observation.get("source_url")
        if not html or not url:
            continue
        if kind == "RENDER" or url not in pages:
            pages[url] = (html, observation.get("id", ""))
    return pages


def _suppressed_urls(findings: Optional[List[Dict[str, Any]]]) -> set:
    return {
        url
        for finding in findings or []
        if str(finding.get("check_id", "")).startswith(SUPPRESSING_CHECK_PREFIX)
        for url in finding.get("source_urls", []) or []
    }


def _answered_questions(html: str) -> List[str]:
    """Question-shaped headings that are actually answered in the prose below.

    Both halves are required. A question heading with no prose under it is an
    unanswered question -- a possible defect for a detector to judge, never an
    opportunity for this module to build on.
    """
    return [
        section["text"]
        for section in heading_sections(html)
        if 2 <= section["level"] <= 4
        and section["text"].endswith("?")
        and 12 <= len(section["text"]) <= 200
        and section["body_words"] >= MIN_ANSWER_WORDS
    ]


def _answer_markup_opportunities(
    pages: Dict[str, Tuple[str, str]], suppressed: set
) -> List[Dict[str, Any]]:
    """proactive-layer.md source 6: answered questions with no answer markup.

    Precondition is health: the page already answers its own questions in
    plain prose, so no extraction check fires and nothing here is a defect.
    The opportunity is that FAQPage/QAPage markup makes each answer
    individually retrievable rather than reachable only by reading the page.
    """
    candidates = []
    for url, (html, observation_id) in sorted(pages.items()):
        if url in suppressed:
            continue
        questions = _answered_questions(html)
        if len(questions) < MIN_ANSWERED_QUESTIONS:
            continue
        if any(
            schema_type_matches(node.get("@type"), ["FAQPage", "QAPage"])
            for node in extract_jsonld(html)
        ):
            continue  # already marked up -- nothing to offer
        candidates.append((len(questions), url, questions, observation_id))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    opportunities = []
    for count, url, questions, observation_id in candidates[:MAX_PAGES_PER_SOURCE]:
        sample = "; ".join(f'"{question}"' for question in questions[:3])
        opportunities.append(
            _opportunity(
                source="answer_markup_gap",
                title=f"Answered questions on {url} are not marked up as answers",
                evidence=(
                    f"{count} question-shaped heading(s) on this page are each followed by "
                    f"{MIN_ANSWER_WORDS}+ words of answer prose, and the page carries no "
                    f"FAQPage or QAPage structured data. Examples: {sample}."
                ),
                why_it_matters=(
                    "The answers are already readable, so nothing is broken. But an assistant "
                    "assembling a response has to infer where each answer starts and stops. "
                    "FAQPage/QAPage markup states those boundaries explicitly, which makes a "
                    "single answer quotable on its own rather than only as part of the page."
                ),
                suggested_action=(
                    "Emit FAQPage (or QAPage) JSON-LD whose mainEntity lists each existing "
                    "question with its existing answer text. Mark up the prose already on the "
                    "page; do not write new copy or add questions the page does not answer."
                ),
                validation=(
                    "Re-fetch the page and confirm the JSON-LD parses, its mainEntity count "
                    f"matches the {count} question heading(s), and each answer string matches "
                    "the visible prose."
                ),
                confidence="high" if count >= 5 else "medium",
                source_urls=[url],
                observation_ids=[observation_id],
            )
        )
    return opportunities


def _section_anchor_opportunities(
    pages: Dict[str, Tuple[str, str]], suppressed: set
) -> List[Dict[str, Any]]:
    """proactive-layer.md source 7: citable sections with no stable anchor.

    Precondition is health: the page is long-form and well-sectioned, which is
    why it is worth citing a part of. Requiring that *no* section carries an id
    avoids nagging a site whose generator already anchors most headings.
    """
    candidates = []
    for url, (html, observation_id) in sorted(pages.items()):
        if url in suppressed:
            continue
        sections = [
            section
            for section in heading_sections(html)
            if 2 <= section["level"] <= 3 and section["body_words"] >= MIN_SECTION_WORDS
        ]
        if len(sections) < MIN_ANCHORABLE_SECTIONS:
            continue
        if any(section["id"] for section in sections):
            continue  # the generator already anchors headings
        candidates.append((len(sections), url, sections, observation_id))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    opportunities = []
    for count, url, sections, observation_id in candidates[:MAX_PAGES_PER_SOURCE]:
        sample = "; ".join(f'"{section["text"]}"' for section in sections[:3])
        opportunities.append(
            _opportunity(
                source="section_anchor_gap",
                title=f"Substantive sections on {url} cannot be linked to individually",
                evidence=(
                    f"{count} section(s) on this page carry {MIN_SECTION_WORDS}+ words each, and "
                    f"none of their headings has an id attribute. Examples: {sample}."
                ),
                why_it_matters=(
                    "The page reads fine, so no check fails. But an assistant citing one section "
                    "can only offer the whole page, and a visitor arriving from that answer lands "
                    "at the top and has to search for the part they were promised. A stable "
                    "heading id makes the citation land on the answer itself."
                ),
                suggested_action=(
                    "Add a stable, human-readable id to each substantive heading (for example "
                    f'id="{_slug(sections[0]["text"])}") and keep those ids unchanged across '
                    "edits so existing citations continue to resolve."
                ),
                validation=(
                    "Re-fetch the page and confirm each substantive heading has an id, and that "
                    "requesting the page with that #fragment scrolls to the matching section."
                ),
                confidence="medium",
                source_urls=[url],
                observation_ids=[observation_id],
            )
        )
    return opportunities


def _slug(text: str) -> str:
    """An illustrative id for the suggested action, not a prescribed scheme."""
    slug = "".join(character.lower() if character.isalnum() else "-" for character in text)
    return "-".join(part for part in slug.split("-") if part)[:40] or "section"


def _identity_anchor_opportunity(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """proactive-layer.md source 2: identity anchors the site does not occupy.

    `sameAs` is the one standard, machine-checkable anchor already available
    from JSON-LD alone -- no corroboration lookup needed.
    """
    fetch_observations = [
        obs for obs in store.get("observations", []) or [] if obs.get("type") in ("HTTP_FETCH", "RENDER")
    ]
    if not fetch_observations:
        return None

    has_organization_or_person = False
    has_same_as = False
    example_url = None
    observation_id = None
    for obs in fetch_observations:
        html = (obs.get("value", {}) or {}).get("html", "")
        if not html:
            continue
        for item in extract_jsonld(html):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(t in ("Organization", "Person", "LocalBusiness", "Corporation") for t in types):
                has_organization_or_person = True
                if example_url is None:
                    example_url, observation_id = obs.get("source_url"), obs.get("id")
                if item.get("sameAs"):
                    has_same_as = True

    if not has_organization_or_person or has_same_as:
        return None

    return _opportunity(
        source="identity_anchor_gap",
        title="No sameAs links from the entity's structured data",
        evidence=(
            f"The Organization/Person markup on {example_url} parses and identifies the entity, "
            "but carries no `sameAs` array."
        ),
        why_it_matters=(
            "The markup is valid, so nothing is wrong. But `sameAs` is what lets a citation "
            "pipeline tie this site to the same entity described elsewhere, which is how an "
            "assistant avoids confusing it with a similarly named one."
        ),
        suggested_action=(
            "Add a `sameAs` array to the existing Organization/Person node listing the entity's "
            "authoritative profiles -- official social accounts, a Wikidata or Wikipedia entry, "
            "or a company-registry page. List only profiles the entity actually controls."
        ),
        validation=(
            "Re-fetch the page and confirm the JSON-LD contains `sameAs` and that each URL "
            "resolves to a profile naming this entity."
        ),
        confidence="high",
        source_urls=[example_url] if example_url else [],
        observation_ids=[observation_id] if observation_id else [],
    )


def _demoted_opportunities(demoted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """proactive-layer.md source 4: findings demoted below the confidence floor.

    These arrive already evidence-bound from `evidence-prioritization`; this
    module reframes them, and does not re-adjudicate that skill's decision.
    """
    return [
        _opportunity(
            source="demoted_finding",
            title=f"Worth a closer look: {finding.get('title', finding.get('check_id', ''))}",
            evidence=(
                f"{finding.get('observed_signal', finding.get('evidence', ''))} "
                "This did not clear the evidence bar for a confident finding."
            ),
            why_it_matters=finding.get("mechanism", "")
            or "Recorded below the confidence floor, so it is offered for review rather than asserted.",
            suggested_action=(
                f"Review {finding.get('check_id', 'this signal')} manually before acting; the audit "
                "did not gather enough evidence to assert it."
            ),
            validation="Confirm or rule out the signal by hand, then re-run the audit.",
            confidence="low",
            source_urls=finding.get("source_urls", []),
            observation_ids=finding.get("observation_ids", []),
        )
        for finding in demoted
    ]


def _is_grounded(opportunity: Dict[str, Any]) -> bool:
    """Reject anything speculative before it reaches the report.

    Store-derived sources have no upstream evidence gate the way findings do
    (`validate_report.bind_evidence`), so they get one here: an opportunity
    must say what was observed and point at where. `demoted_finding` is exempt
    because evidence-prioritization already bound its evidence; re-gating it
    would second-guess that skill's contract.
    """
    if opportunity.get("source") == "demoted_finding":
        return bool(str(opportunity.get("evidence", "")).strip())
    required = ("title", "evidence", "why_it_matters", "suggested_action", "validation")
    if not all(str(opportunity.get(field, "")).strip() for field in required):
        return False
    if opportunity.get("confidence") not in ("high", "medium", "low"):
        return False
    return bool(opportunity.get("observation_ids") or opportunity.get("source_urls"))


def _deduplicate(opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One opportunity per (source, title, scope); first occurrence wins."""
    seen = set()
    unique = []
    for opportunity in opportunities:
        key = (
            opportunity.get("source"),
            opportunity.get("title"),
            tuple(opportunity.get("source_urls", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(opportunity)
    return unique


def generate_proactive_opportunities(
    store: Dict[str, Any],
    demoted: List[Dict[str, Any]],
    findings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Every opportunity supported by the collected evidence, deduplicated.

    Returning an empty list is a legitimate result: a site with no health
    signals to build on gets no advice invented for it.
    """
    pages = _page_html(store)
    suppressed = _suppressed_urls(findings)

    opportunities: List[Dict[str, Any]] = []
    identity_gap = _identity_anchor_opportunity(store)
    if identity_gap:
        opportunities.append(identity_gap)
    opportunities.extend(_answer_markup_opportunities(pages, suppressed))
    opportunities.extend(_section_anchor_opportunities(pages, suppressed))
    opportunities.extend(_demoted_opportunities(demoted))

    return _deduplicate([item for item in opportunities if _is_grounded(item)])


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
