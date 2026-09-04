"""Deterministic HTML extraction helpers for raw and rendered page analysis."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def extract_metadata(html: str) -> Dict[str, Any]:
    """Extract canonical metadata, title, description and social tags."""
    soup = _soup(html)
    title_tag = soup.title.get_text(" ", strip=True) if soup.title else ""

    def get_meta(name: str, attrs: List[str]) -> str:
        for key in attrs:
            meta = soup.find("meta", attrs={key: name})
            if meta and meta.get("content"):
                return str(meta["content"]).strip()
        return ""

    description = get_meta("description", ["name", "property"]) or get_meta("og:description", ["property"])
    canonical = extract_canonical_url(html, "")

    return {
        "title": title_tag,
        "description": description,
        "canonical": canonical,
        "meta": {
            "title": title_tag,
            "description": description,
            "og_title": get_meta("og:title", ["property"]),
            "og_description": get_meta("og:description", ["property"]),
        },
    }


def extract_canonical_url(html: str, base_url: str) -> str:
    """Return the canonical URL if present, otherwise the page URL."""
    soup = _soup(html)
    canonical = None
    link = soup.find("link", rel=lambda v: v and "canonical" in v.lower() if v else False)
    if link and link.get("href"):
        canonical = str(link["href"]).strip()
    if not canonical:
        meta = soup.find("meta", attrs={"property": "og:url"})
        if meta and meta.get("content"):
            canonical = str(meta["content"]).strip()
    if not canonical:
        return base_url
    return urljoin(base_url, canonical) if base_url else canonical


def extract_jsonld(html: str) -> List[Dict[str, Any]]:
    """Extract structured data objects from JSON-LD script blocks."""
    soup = _soup(html)
    items: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        content = script.get_text(strip=True)
        if not content:
            continue
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            items.extend([item for item in parsed if isinstance(item, dict)])
        elif isinstance(parsed, dict):
            items.append(parsed)
    return items


def extract_links(html: str, base_url: str = "") -> List[Dict[str, Any]]:
    """Extract unique HTML links with normalized absolute URLs and anchor text."""
    soup = _soup(html)
    seen = set()
    links: List[Dict[str, Any]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        absolute = urljoin(base_url, href) if base_url else href
        if not absolute or absolute in seen:
            continue
        seen.add(absolute)
        links.append({"href": absolute, "text": anchor.get_text(" ", strip=True), "rel": anchor.get("rel", [])})
    return links


def extract_text(html: str) -> str:
    """Return readable body text with whitespace normalized."""
    soup = _soup(html)
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def page_inventory(html: str) -> Dict[str, Any]:
    """Summarize the page structure for raw-vs-rendered comparison."""
    soup = _soup(html)
    return {
        "title": (soup.title.get_text(" ", strip=True) if soup.title else ""),
        "heading_count": len(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])),
        "link_count": len(soup.find_all("a", href=True)),
        "image_count": len(soup.find_all("img")),
        "script_count": len(soup.find_all("script")),
        "text_length": len(extract_text(html)),
        "tag_counts": dict(sorted(Counter(tag.name for tag in soup.find_all(True)).items())),
    }


def compare_raw_vs_rendered(raw_html: str, rendered_html: str) -> Dict[str, Any]:
    """Compare the raw and rendered DOM and report tag-level deltas."""
    raw_tags = Counter(tag.name for tag in _soup(raw_html).find_all(True))
    rendered_tags = Counter(tag.name for tag in _soup(rendered_html).find_all(True))

    raw_only = sorted(tag for tag in raw_tags if tag not in rendered_tags or raw_tags[tag] > rendered_tags.get(tag, 0))
    rendered_only = sorted(tag for tag in rendered_tags if tag not in raw_tags or rendered_tags[tag] > raw_tags.get(tag, 0))

    return {
        "raw_tag_count": sum(raw_tags.values()),
        "rendered_tag_count": sum(rendered_tags.values()),
        "evidence": {
            "raw_only_nodes": raw_only,
            "rendered_only_nodes": rendered_only,
            "raw_tag_counts": dict(sorted(raw_tags.items())),
            "rendered_tag_counts": dict(sorted(rendered_tags.items())),
        },
    }


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
