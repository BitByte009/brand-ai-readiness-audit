"""Claim table: claim text, page, claim type, date signal, source attribution.

Inputs:  store
Outputs: claim_table
Nature:  fully deterministic -- no model call. See references/store-contract.md
         for why this skill's brief does not require one for a complete
         first implementation.

See ../references/claim-table-contract.md for the exact output shape and
../references/store-contract.md for the observation types read here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from _trust_util import (
    _CUSTOMER_COUNT_RE,
    _EMPLOYEE_COUNT_RE,
    _EVENT_FORWARD_RE,
    _FOUNDED_RE,
    _MONTHS,
    _OFFER_FORWARD_RE,
    _STAT_RE,
    _SUPERLATIVE_RE,
    _TIME_SENSITIVE_RE,
    effective_pages,
    find_copyright_year,
    find_visible_freshness_dates,
    has_nearby_citation,
    normalize_claim_value,
    parse_date,
)

from lib.common.extract import extract_jsonld, extract_text, language_supported


def _claim_id(claim_type: str, url: str, text: str) -> str:
    digest = hashlib.sha1(f"{claim_type}|{url}|{text}".encode("utf-8")).hexdigest()[:12]
    return f"CLAIM-{digest}"


def _claim(claim_type: str, text: str, url: str, observation_id: str, **extra: Any) -> Dict[str, Any]:
    claim = {
        "id": _claim_id(claim_type, url, text),
        "claim_type": claim_type,
        "text": text.strip(),
        "source_url": url,
        "observation_id": observation_id,
    }
    claim.update(extra)
    return claim


def _build_date_inventory(url: str, page: Dict[str, Any], text: str) -> Dict[str, Any]:
    html = page["html"]

    schema_dates = []
    for node in extract_jsonld(html):
        for key in ("datePublished", "dateModified"):
            if node.get(key):
                parsed = parse_date(str(node[key]))
                if parsed:
                    schema_dates.append(parsed.isoformat())

    visible_dates = [d.isoformat() for d in find_visible_freshness_dates(text)]

    header_date = None
    last_modified = next((v for k, v in page.get("headers", {}).items() if k.lower() == "last-modified"), None)
    if last_modified:
        parsed = parse_date(last_modified)
        header_date = parsed.isoformat() if parsed else None

    return {
        "schema_dates": schema_dates,
        "visible_dates": visible_dates,
        "header_date": header_date,
        "copyright_year": find_copyright_year(html),
        "observation_id": page["observation_id"],
    }


def _extract_time_sensitive_claims(url: str, oid: str, text: str) -> List[Dict[str, Any]]:
    claims = []
    for match in _TIME_SENSITIVE_RE.finditer(text):
        window = text[max(0, match.start() - 40) : match.end() + 40]
        claims.append(_claim("time_sensitive", window, url, oid))
    return claims


def _extract_dated_forward_claims(url: str, oid: str, text: str) -> List[Dict[str, Any]]:
    claims = []

    for match in _EVENT_FORWARD_RE.finditer(text):
        month = _MONTHS.get(match.group(2).lower())
        try:
            claim_date = date(int(match.group(4)), month, int(match.group(3))) if month else None
        except ValueError:
            claim_date = None
        if claim_date:
            claims.append(_claim("dated_event", match.group(0), url, oid, date_value=claim_date.isoformat()))

    for match in _OFFER_FORWARD_RE.finditer(text):
        month = _MONTHS.get(match.group(3).lower())
        try:
            claim_date = date(int(match.group(5)), month, int(match.group(4))) if month else None
        except ValueError:
            claim_date = None
        if claim_date:
            claims.append(_claim("dated_offer", match.group(0), url, oid, date_value=claim_date.isoformat()))

    return claims


def _extract_entity_fact_claims(url: str, oid: str, text: str) -> List[Dict[str, Any]]:
    claims = []

    match = _FOUNDED_RE.search(text)
    if match:
        year = match.group(1) or match.group(2)
        claims.append(_claim("entity_fact", match.group(0), url, oid, key="founded_year", value=normalize_claim_value(year)))

    match = _CUSTOMER_COUNT_RE.search(text)
    if match:
        years = re.findall(r"\b(?:19|20)\d{2}\b", text[max(0, match.start()-50):match.end()+50])
        claims.append(
            _claim("entity_fact", match.group(0), url, oid, key="customer_count", value=normalize_claim_value(match.group(1)), time_context=sorted(set(years)))
        )

    match = _EMPLOYEE_COUNT_RE.search(text)
    if match:
        years = re.findall(r"\b(?:19|20)\d{2}\b", text[max(0, match.start()-50):match.end()+50])
        claims.append(
            _claim("entity_fact", match.group(0), url, oid, key="employee_count", value=normalize_claim_value(match.group(1)), time_context=sorted(set(years)))
        )

    return claims


def _extract_superlative_claims(url: str, oid: str, text: str) -> List[Dict[str, Any]]:
    claims = []
    for regex in (_SUPERLATIVE_RE, _STAT_RE):
        for match in regex.finditer(text):
            attributed = has_nearby_citation(text, match.start(), match.end())
            claims.append(_claim("superlative_stat", match.group(0), url, oid, attributed=attributed))
    return claims


def build_claim_table(store: Dict[str, Any]) -> Dict[str, Any]:
    pages = effective_pages(store)
    claims: List[Dict[str, Any]] = []
    date_inventory: Dict[str, Any] = {}

    for url, page in pages.items():
        # Parsed once per page and threaded through -- this used to call
        # extract_text() a second time inside _build_date_inventory, doubling
        # the BeautifulSoup parsing cost for every page in the store.
        text = extract_text(page["html"])
        date_inventory[url] = _build_date_inventory(url, page, text)
        if not language_supported(page['html']):
            continue

        oid = page["observation_id"]
        claims.extend(_extract_time_sensitive_claims(url, oid, text))
        claims.extend(_extract_dated_forward_claims(url, oid, text))
        claims.extend(_extract_entity_fact_claims(url, oid, text))
        # Code examples are not business claims. Preserve actual nearby citation
        # URLs, which plain get_text otherwise drops along with the href attribute.
        soup = BeautifulSoup(page['html'], 'html.parser')
        for node in soup.find_all(['code', 'pre', 'nav', 'header', 'footer']):
            node.decompose()
        for anchor in soup.find_all('a', href=True):
            try:
                target = urljoin(url, anchor['href'])
                parsed = urlparse(target)
            except ValueError:
                continue
            if parsed.scheme in {'http', 'https'} and parsed.netloc != urlparse(url).netloc and anchor.find_parent(['p', 'li', 'blockquote']):
                anchor.append(f' [source: {target}]')
        claims.extend(_extract_superlative_claims(url, oid, extract_text(str(soup))))

    return {
        "claims": claims,
        "date_inventory": date_inventory,
        "pages_considered": sorted(pages.keys()),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the claim table from an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--out", help="Path to write the claim table JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    table = build_claim_table(store)
    output = json.dumps(table, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
