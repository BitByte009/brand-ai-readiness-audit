"""D-EXTRACT-01..09 including probe-miss interpretation for factual questions.

Inputs:  store
Outputs: unscored findings (D-EXTRACT-08 is proactive-only; see proactive_opportunities())
Nature:  deterministic + interpretation

See ../references/extract-checks.md for the twelve-field definition of every check
below, and ../references/store-contract.md for the observation shapes read here.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, List, Optional

from _util import (
    SHORT_PAGE_TEXT_FLOOR,
    affected_block,
    group_by_cluster,
    http_fetches,
    make_finding,
    page_classifications,
    probes,
)

from lib.common.extract import (
    extract_jsonld,
    extract_links,
    extract_metadata,
    extract_text,
    flatten_jsonld,
    is_jsonld_mime_type,
    schema_type_matches,
)

CATEGORY = "discoverability"

# page_type -> declared JSON-LD @type + required properties (dot-paths; a list means
# "any one of these satisfies the requirement", e.g. offers.price OR offers.priceCurrency).
TYPE_SCHEMA_MAP = {
    "product": ("Product", ["name", ["offers.price", "offers.priceCurrency"]]),
    "article": ("Article", ["headline", "datePublished"]),
    "organization": ("Organization", ["name"]),
    "local_business": ("LocalBusiness", ["name", "address"]),
    "faq": ("FAQPage", ["mainEntity"]),
    "event": ("Event", ["name", "startDate"]),
}

_MOJIBAKE_RE = re.compile(r"[�]|Ã.|â€.")
_BOILERPLATE_RE = re.compile(
    r"^(accept cookies|subscribe to our newsletter|share this|all rights reserved|sign up for)",
    re.IGNORECASE,
)


def _relevant_factual_questions(probe: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        q
        for q in probe.get("value", {}).get("questions", [])
        if q.get("category") == "factual" and q.get("relevant")
    ]


def _has_missing_alt_image(html: str) -> bool:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    return any(not (img.get("alt") or "").strip() for img in soup.find_all("img"))


def _has_bare_pdf_link(html: str, base_url: str) -> bool:
    for link in extract_links(html, base_url=base_url):
        href = link["href"].lower()
        text = (link.get("text") or "").strip()
        if href.endswith(".pdf") and len(text) < 3:
            return True
    return False


def check_d_extract_01(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    fetches = http_fetches(store)
    for url, probe in probes(store).items():
        fetch = fetches.get(url)
        if not fetch:
            continue
        relevant = [q for q in _relevant_factual_questions(probe) if not q.get("answered")]
        if not relevant:
            continue
        html = fetch["value"].get("html", "")
        if not (_has_missing_alt_image(html) or _has_bare_pdf_link(html, url)):
            continue
        findings.append(
            make_finding(
                check_id="D-EXTRACT-01",
                category=CATEGORY,
                title=f"Key facts may be locked in non-text media on {url}",
                severity="high",
                confidence="medium",
                mechanism="A text-only reader extracts nothing from a raster image, "
                "a PDF it doesn't open, or a video it doesn't transcribe.",
                impact="These facts are unextractable to any text-based reader.",
                observed_signal=f"{len(relevant)} relevant factual question(s) unanswered, with an image (empty alt) or bare PDF link present",
                evidence=f"Unanswered: {', '.join(q['id'] for q in relevant)}",
                observation_ids=[probe["id"], fetch["id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "State the fact in plain text (caption, descriptive alt text, or a text summary) in addition to the existing media.",
                    "priority": "high",
                    "how_to_fix": "Add a text equivalent for the image/PDF content that answers the question.",
                    "validation": "Re-run the probe on text alone; the question now answers.",
                },
            )
        )
    return findings


def check_d_extract_02(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    fetches = http_fetches(store)
    meta_by_url = {
        url: extract_metadata(obs["value"].get("html", ""))
        for url, obs in fetches.items()
        if obs["value"].get("status_code") == 200
    }

    findings = []
    empty = [u for u, m in meta_by_url.items() if not m["title"].strip() or not m["description"].strip()]
    if empty:
        for cluster, urls in group_by_cluster(store, empty).items():
            findings.append(
                make_finding(
                    check_id="D-EXTRACT-02",
                    category=CATEGORY,
                    title=f"Missing title or meta description in {cluster}",
                    severity="medium",
                    confidence="high",
                    mechanism="Title and description are the first-line summary "
                    "most citation and search pipelines surface.",
                    impact="These pages have no machine-readable summary.",
                    observed_signal=f"{len(urls)} page(s) with empty title or description",
                    evidence=f"Empty title/description: {', '.join(sorted(urls)[:5])}",
                    observation_ids=[fetches[u]["id"] for u in urls],
                    source_urls=urls,
                    affected=affected_block(urls),
                    suggested_action={
                        "summary": "Write a unique, descriptive title and meta description per page.",
                        "priority": "medium",
                        "how_to_fix": "Add <title> and <meta name=description> naming the page's specific subject.",
                        "validation": "Re-fetch; title/description are non-empty.",
                    },
                )
            )

    by_cluster: Dict[str, Dict[str, List[str]]] = {}
    for u, m in meta_by_url.items():
        if u in empty:
            continue
        cluster = next(iter(group_by_cluster(store, [u])))
        by_cluster.setdefault(cluster, {}).setdefault(m["title"], []).append(u)

    for cluster, titles in by_cluster.items():
        for title, urls in titles.items():
            if len(urls) < 2:
                continue
            findings.append(
                make_finding(
                    check_id="D-EXTRACT-02",
                    category=CATEGORY,
                    title=f"Duplicated title across distinct pages in {cluster}",
                    severity="medium",
                    confidence="high",
                    mechanism="Duplicated titles collapse distinct pages into one signal.",
                    impact="A reader cannot distinguish these pages by title alone.",
                    observed_signal=f"{len(urls)} page(s) share the title \"{title}\"",
                    evidence=f"Duplicate title \"{title}\" on: {', '.join(sorted(urls)[:5])}",
                    observation_ids=[fetches[u]["id"] for u in urls],
                    source_urls=urls,
                    affected=affected_block(urls),
                    suggested_action={
                        "summary": "Give each page a unique, descriptive title.",
                        "priority": "medium",
                        "how_to_fix": "Differentiate the title per page's specific subject.",
                        "validation": "Re-fetch; no two distinct pages share the same title.",
                    },
                )
            )
    return findings


def check_d_extract_03(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    fetches = http_fetches(store)
    classifications = page_classifications(store)
    probe_obs = probes(store)

    for url, classification in classifications.items():
        page_type = classification.get("value", {}).get("page_type")
        mapping = TYPE_SCHEMA_MAP.get(page_type)
        if not mapping:
            continue
        schema_type, _ = mapping

        fetch = fetches.get(url)
        probe = probe_obs.get(url)
        if not fetch or not probe:
            continue

        html = fetch["value"].get("html", "")
        has_matching_type = any(
            schema_type_matches(node.get("@type"), schema_type)
            for node in extract_jsonld(html)
        )
        if has_matching_type:
            continue

        unanswered = [q for q in _relevant_factual_questions(probe) if not q.get("answered")]
        if not unanswered:
            continue

        findings.append(
            make_finding(
                check_id="D-EXTRACT-03",
                category=CATEGORY,
                title=f"No structured data for {schema_type} and the fact is unextractable in prose on {url}",
                severity="medium",
                confidence="high",
                mechanism="Structured data is one path to a machine-unambiguous "
                "fact, not the only one; the failure that matters is the fact being "
                "unextractable, not the markup being absent.",
                impact=f"Machines cannot reliably determine {', '.join(q['id'] for q in unanswered)} for this page.",
                observed_signal=f"page classified as {page_type}, no {schema_type} JSON-LD, {len(unanswered)} relevant fact(s) unanswered in prose",
                evidence=f"Missing {schema_type}; unanswered: {', '.join(q['id'] for q in unanswered)}",
                observation_ids=[classification["id"], fetch["id"], probe["id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": f"Add {schema_type} structured data with the specific missing properties, and state the same facts in plain prose.",
                    "priority": "medium",
                    "how_to_fix": f"Add a {schema_type} JSON-LD block and a plain-language sentence stating {', '.join(q['id'] for q in unanswered)}.",
                    "validation": "Re-run the probe on text alone (must answer); validate the JSON-LD parses with required properties matching visible text.",
                },
            )
        )
    return findings


def _jsonld_blocks(html: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    blocks = []
    for script in soup.find_all("script"):
        if not is_jsonld_mime_type(script.get("type")):
            continue
        content = script.get_text(strip=True)
        if not content:
            continue
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            blocks.append({"error": str(exc), "raw": content})
            continue
        for item in flatten_jsonld(parsed):
            blocks.append({"parsed": item})
    return blocks


def _get_path_values(obj: Any, dotted: str) -> List[Any]:
    """Resolve a dotted path across every branch of list-valued properties."""
    values = [obj]
    for part in dotted.split("."):
        next_values: List[Any] = []
        for value in values:
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if isinstance(candidate, dict) and part in candidate:
                    next_values.append(candidate[part])
        values = next_values
        if not values:
            break

    flattened: List[Any] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def _prop_present(node: Dict[str, Any], requirement: Any) -> bool:
    """A requirement is either one dotted path, or a list of alternative dotted
    paths where any one satisfies it (e.g. offers.price OR offers.priceCurrency)."""
    paths = [requirement] if isinstance(requirement, str) else requirement
    return any(
        value not in (None, "", [])
        for path in paths
        for value in _get_path_values(node, path)
    )


def _requirement_label(requirement: Any) -> str:
    return requirement if isinstance(requirement, str) else "/".join(requirement)


def check_d_extract_04(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    for url, fetch in http_fetches(store).items():
        html = fetch["value"].get("html", "")
        for block in _jsonld_blocks(html):
            if "error" in block:
                findings.append(
                    make_finding(
                        check_id="D-EXTRACT-04",
                        category=CATEGORY,
                        title=f"Structured data fails to parse on {url}",
                        severity="high",
                        confidence="high",
                        mechanism="A machine that trusts structured data discards "
                        "the whole block on a parse failure.",
                        impact="This entire structured-data block is unusable.",
                        observed_signal=f"JSON-LD parse error: {block['error']}",
                        evidence=block["raw"][:200],
                        observation_ids=[fetch["id"]],
                        source_urls=[url],
                        affected=affected_block([url]),
                        suggested_action={
                            "summary": "Fix the JSON syntax error in the structured data block.",
                            "priority": "high",
                            "how_to_fix": f"Correct the JSON syntax: {block['error']}",
                            "validation": "Re-fetch; the block parses without error.",
                        },
                    )
                )
                continue

            node = block["parsed"]
            mapping = next(
                (m for m in TYPE_SCHEMA_MAP.values() if schema_type_matches(node.get("@type"), m[0])),
                None,
            )
            if not mapping:
                continue
            node_type, required = mapping
            missing = [
                _requirement_label(req) for req in required if not _prop_present(node, req)
            ]
            if missing:
                findings.append(
                    make_finding(
                        check_id="D-EXTRACT-04",
                        category=CATEGORY,
                        title=f"{node_type} structured data missing required properties on {url}",
                        severity="high",
                        confidence="high",
                        mechanism="A machine that trusts structured data over "
                        "prose picks up an incomplete fact.",
                        impact=f"{node_type} data is incomplete for the properties: {', '.join(missing)}.",
                        observed_signal=f"missing required propert{'y' if len(missing)==1 else 'ies'}: {', '.join(missing)}",
                        evidence=json.dumps(node)[:200],
                        observation_ids=[fetch["id"]],
                        source_urls=[url],
                        affected=affected_block([url]),
                        suggested_action={
                            "summary": f"Add the missing required {node_type} propert{'y' if len(missing)==1 else 'ies'}: {', '.join(missing)}.",
                            "priority": "high",
                            "how_to_fix": f"Populate {', '.join(missing)} in the {node_type} JSON-LD block.",
                            "validation": "Re-fetch; required properties are present and match visible text.",
                        },
                    )
                )
    return findings


def _heading_outline(html: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    outline = []
    for i, heading in enumerate(headings):
        text_after = []
        for sibling in heading.find_all_next():
            if sibling in headings:
                break
            if sibling.name and sibling.get_text(strip=True):
                text_after.append(sibling.get_text(strip=True))
        outline.append({"level": heading.name, "has_body": bool(text_after)})
    return outline


def check_d_extract_05(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    for url, fetch in http_fetches(store).items():
        value = fetch["value"]
        if value.get("status_code") != 200:
            continue
        html = value.get("html", "")
        if len(extract_text(html)) <= SHORT_PAGE_TEXT_FLOOR:
            continue

        outline = _heading_outline(html)
        has_h1 = any(h["level"] == "h1" for h in outline)
        empty_ratio = (sum(1 for h in outline if not h["has_body"]) / len(outline)) if outline else 0

        if not has_h1:
            findings.append(
                make_finding(
                    check_id="D-EXTRACT-05",
                    category=CATEGORY,
                    title=f"No h1 present on {url}",
                    severity="medium",
                    confidence="high",
                    mechanism="Headings are the cheapest machine-readable outline "
                    "of what the page is organized around.",
                    impact="A reader cannot cheaply determine the page's subject from its outline.",
                    observed_signal="0 h1 elements found",
                    evidence="No <h1> in the document",
                    observation_ids=[fetch["id"]],
                    source_urls=[url],
                    affected=affected_block([url]),
                    suggested_action={
                        "summary": "Add exactly one h1 stating the page's subject.",
                        "priority": "medium",
                        "how_to_fix": "Add a single <h1> naming the page's topic.",
                        "validation": "Re-fetch; >=1 h1 is present.",
                    },
                )
            )
        elif empty_ratio >= 0.5:
            findings.append(
                make_finding(
                    check_id="D-EXTRACT-05",
                    category=CATEGORY,
                    title=f"Headings used only as visual dividers on {url}",
                    severity="low",
                    confidence="medium",
                    mechanism="Headings with no associated content give a machine "
                    "no organizational signal to follow.",
                    impact="The heading outline does not reflect the page's actual structure.",
                    observed_signal=f"{empty_ratio:.0%} of headings introduce no following text block",
                    evidence=f"{sum(1 for h in outline if not h['has_body'])}/{len(outline)} headings have no body text",
                    observation_ids=[fetch["id"]],
                    source_urls=[url],
                    affected=affected_block([url]),
                    suggested_action={
                        "summary": "Ensure each heading introduces the text block that follows it.",
                        "priority": "low",
                        "how_to_fix": "Restructure headings so each one precedes real content.",
                        "validation": "Re-fetch; the empty-section ratio drops below 50%.",
                    },
                )
            )
    return findings


def check_d_extract_06(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    fetches = http_fetches(store)
    for url, probe in probes(store).items():
        relevant = _relevant_factual_questions(probe)
        unanswered = [q for q in relevant if not q.get("answered")]
        if len(unanswered) < 2:
            continue
        fetch = fetches.get(url)
        findings.append(
            make_finding(
                check_id="D-EXTRACT-06",
                category=CATEGORY,
                title=f"Low quotable-answer density on {url}",
                severity="high",
                confidence="high",
                mechanism="Direct mechanical simulation of a citation pipeline: "
                "read the text, try to answer canonical questions, see what fails.",
                impact="No self-contained sentence exists that a machine could lift as the answer.",
                observed_signal=f"{len(unanswered)}/{len(relevant)} relevant factual questions unanswered from text alone",
                evidence=f"Unanswered: {', '.join(q['id'] for q in unanswered)}",
                observation_ids=[probe["id"]] + ([fetch["id"]] if fetch else []),
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Add a short, self-contained sentence directly answering each named question.",
                    "priority": "high",
                    "how_to_fix": f"Add explicit answer sentences near the top of the content for: {', '.join(q['id'] for q in unanswered)}.",
                    "validation": "Re-run the probe on the revised text; the questions now answer.",
                },
            )
        )
    return findings


def check_d_extract_07(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    fetches = http_fetches(store)
    classifications = page_classifications(store)
    for url, probe in probes(store).items():
        if url not in classifications:
            continue
        fetch = fetches.get(url)
        if not fetch or len(extract_text(fetch["value"].get("html", ""))) <= SHORT_PAGE_TEXT_FLOOR:
            continue

        for question in probe.get("value", {}).get("questions", []):
            if (
                question.get("category") == "factual"
                and question.get("relevant")
                and question.get("expects_explicit_statement")
                and not question.get("answered")
            ):
                findings.append(
                    make_finding(
                        check_id="D-EXTRACT-07",
                        category=CATEGORY,
                        title=f"Fact implied rather than stated on {url}",
                        severity="high",
                        confidence="high",
                        mechanism="An assistant reasoning from text alone cannot "
                        "infer from layout or imagery what a human visually assembles instantly.",
                        impact=f"'{question['id']}' is never explicitly stated in text.",
                        observed_signal=f"expected-explicit question '{question['id']}' unanswered",
                        evidence=f"No explicit statement found for: {question['id']}",
                        observation_ids=[probe["id"], fetch["id"]],
                        source_urls=[url],
                        affected=affected_block([url]),
                        suggested_action={
                            "summary": "Add one explicit sentence stating the fact in plain language.",
                            "priority": "high",
                            "how_to_fix": f"State {question['id']} directly, adjacent to the page's primary content.",
                            "validation": "Re-run the probe; the question now answers.",
                        },
                    )
                )
    return findings


def proactive_opportunities(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    """D-EXTRACT-08. Never a finding -- structurally cannot false-positive as a
    defect. See fp-guardrails.md."""
    opportunities = []
    fetches = http_fetches(store)
    probe_obs = probes(store)
    for url, fetch in fetches.items():
        html = fetch["value"].get("html", "")
        text = extract_text(html)
        if not text:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if not sentences:
            continue
        boilerplate = sum(1 for s in sentences if _BOILERPLATE_RE.match(s.strip()))
        ratio = boilerplate / len(sentences)

        probe = probe_obs.get(url)
        answer_offset_ratio = None
        if probe:
            for question in probe.get("value", {}).get("questions", []):
                span = (question.get("evidence_span") or "").strip()
                if question.get("answered") and span and span in text:
                    answer_offset_ratio = text.index(span) / len(text)
                    break

        if ratio >= 0.3 and answer_offset_ratio is not None and answer_offset_ratio >= 0.5:
            opportunities.append(
                {
                    "check_id": "D-EXTRACT-08",
                    "category": CATEGORY,
                    "title": f"Substance diluted by boilerplate on {url}",
                    "observed_signal": f"{ratio:.0%} boilerplate sentences; answer at {answer_offset_ratio:.0%} scroll depth",
                    "source_urls": [url],
                    "observation_ids": [fetch["id"]] + ([probe["id"]] if probe else []),
                    "suggestion": "Move the substantive answer earlier in reading order and trim repeated boilerplate blocks.",
                }
            )
    return opportunities


def check_d_extract_09(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    for url, fetch in http_fetches(store).items():
        value = fetch["value"]
        headers = value.get("headers", {})
        content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "") or ""
        html = value.get("html", "")

        if content_type and not content_type.lower().startswith("text/html") and not url.lower().endswith((".json", ".xml", ".pdf", ".rss")):
            findings.append(
                make_finding(
                    check_id="D-EXTRACT-09",
                    category=CATEGORY,
                    title=f"Unexpected content-type on {url}",
                    severity="high",
                    confidence="high",
                    mechanism="A parser fed the wrong content type can fail to "
                    "extract any text at all.",
                    impact="This page may not be recognized as HTML content at all.",
                    observed_signal=f"Content-Type: {content_type}",
                    evidence=f"Served as {content_type} instead of text/html",
                    observation_ids=[fetch["id"]],
                    source_urls=[url],
                    affected=affected_block([url]),
                    suggested_action={
                        "summary": "Serve page routes with Content-Type: text/html; charset=utf-8.",
                        "priority": "high",
                        "how_to_fix": "Correct the server's Content-Type header for this route.",
                        "validation": "Re-fetch; Content-Type starts with text/html.",
                    },
                )
            )
            continue

        text = extract_text(html)
        if not text:
            continue
        mojibake_matches = len(_MOJIBAKE_RE.findall(text))
        if mojibake_matches / max(1, len(text)) > 0.01:
            findings.append(
                make_finding(
                    check_id="D-EXTRACT-09",
                    category=CATEGORY,
                    title=f"Encoding fault on {url}",
                    severity="high",
                    confidence="high",
                    mechanism="Wrong charset or mojibake corrupts extracted text "
                    "for any downstream reader.",
                    impact="Extracted text is corrupted and likely unusable.",
                    observed_signal=f"{mojibake_matches} mojibake/replacement-character occurrences",
                    evidence=text[:200],
                    observation_ids=[fetch["id"]],
                    source_urls=[url],
                    affected=affected_block([url]),
                    suggested_action={
                        "summary": "Declare and serve the correct charset (UTF-8 unless there is a specific reason otherwise).",
                        "priority": "high",
                        "how_to_fix": "Set Content-Type: text/html; charset=utf-8 and verify source encoding.",
                        "validation": "Re-fetch; no replacement-character/mojibake pattern remains in extracted text.",
                    },
                )
            )
    return findings


CHECKS = [
    check_d_extract_01,
    check_d_extract_02,
    check_d_extract_03,
    check_d_extract_04,
    check_d_extract_05,
    check_d_extract_06,
    check_d_extract_07,
    # D-EXTRACT-08 is proactive-only; see proactive_opportunities().
    check_d_extract_09,
]


def detect_extract(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for check in CHECKS:
        findings.extend(check(store))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run D-EXTRACT-01..09 over an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--out", help="Path to write findings JSON. Defaults to stdout.")
    parser.add_argument("--include-proactive", action="store_true", help="Also emit D-EXTRACT-08 proactive opportunities alongside findings, under a separate key.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    findings = detect_extract(store)
    payload: Any = findings
    if args.include_proactive:
        payload = {"findings": findings, "proactive_opportunities": proactive_opportunities(store)}

    output = json.dumps(payload, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
