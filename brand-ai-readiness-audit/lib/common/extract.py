"""Deterministic HTML extraction helpers for raw and rendered page analysis."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_PARSE_CACHE = ContextVar("audit_parse_cache", default=None)
_TITLE_SEPARATOR_RE = re.compile(r"\s*[|—:]\s*|\s+-\s+")
_SIGNIFICANT_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "for", "in", "on", "at",
    "is", "are", "was", "were", "with", "that", "this", "it", "as", "by", "be",
}


def title_segments(title: str) -> List[str]:
    segments = [s.strip() for s in _TITLE_SEPARATOR_RE.split(title or "") if s.strip()]
    return segments or ([title.strip()] if title and title.strip() else [])


def significant_words(text: str) -> set:
    words = _SIGNIFICANT_WORD_RE.findall((text or "").lower())
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


def containment_ratio(a: str, b: str) -> float:
    words_a, words_b = significant_words(a), significant_words(b)
    if not words_a or not words_b:
        return 0.0
    shorter, longer = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    return len(shorter & longer) / len(shorter)


def url_depth(url: str) -> int:
    return len([seg for seg in urlparse(url).path.split("/") if seg])


@contextmanager
def parse_cache(max_chars=1_048_576, max_entries=64):
    """Audit-local LRU of private, read-only trees. Never truncates inputs.

    Limits bound retained source characters and tree count, not total heap usage.
    Oversized pages are parsed normally without retention. Public helpers return
    independent values; mutating detector parsers keep their own trees.
    """
    state = {"trees": OrderedDict(), "chars": 0, "max_chars": max_chars, "max_entries": max_entries}
    token = _PARSE_CACHE.set(state)
    try:
        yield
    finally:
        state["trees"].clear()
        _PARSE_CACHE.reset(token)


def with_parse_cache(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _PARSE_CACHE.get() is not None:
            return function(*args, **kwargs)
        with parse_cache():
            return function(*args, **kwargs)
    return wrapped


def _soup(html: str) -> BeautifulSoup:
    html = html or ""
    state = _PARSE_CACHE.get()
    if state is None or len(html) > state["max_chars"] or state["max_entries"] <= 0:
        return BeautifulSoup(html, "html.parser")
    trees = state["trees"]
    if html in trees:
        trees.move_to_end(html)
        return trees[html]
    soup = BeautifulSoup(html, "html.parser")
    while trees and (state["chars"] + len(html) > state["max_chars"] or len(trees) >= state["max_entries"]):
        old, _ = trees.popitem(last=False)
        state["chars"] -= len(old)
    trees[html] = soup
    state["chars"] += len(html)
    return soup


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
    try:
        return urljoin(base_url, canonical) if base_url else canonical
    except ValueError:
        return ""


def is_jsonld_mime_type(value: Any) -> bool:
    """Return whether an HTML ``type`` value denotes JSON-LD.

    MIME types are case-insensitive and may carry parameters. Real sites emit
    forms such as ``Application/LD+JSON; charset=utf-8`` in addition to the
    canonical lowercase spelling.
    """
    if isinstance(value, (list, tuple)):
        return any(is_jsonld_mime_type(item) for item in value)
    media_type = str(value or "").split(";", 1)[0].strip().casefold()
    return media_type == "application/ld+json"


def flatten_jsonld(value: Any) -> List[Dict[str, Any]]:
    """Flatten JSON-LD arrays and ``@graph``/``@list`` containers into nodes.

    Container-only wrapper objects are omitted, while a wrapper that is also a
    meaningful node (for example one carrying ``@id`` or ``@type``) is retained.
    ``@set`` is handled alongside ``@list`` because it has the same container
    mechanics for extraction purposes.
    """
    nodes: List[Dict[str, Any]] = []

    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
            continue
        if not isinstance(item, dict):
            continue

        container_keys = {"@graph", "@list", "@set"}
        meaningful_keys = set(item) - container_keys - {"@context"}
        if meaningful_keys or not (set(item) & container_keys):
            nodes.append(item)

        for key in ("@set", "@list", "@graph"):
            if key in item:
                pending.append(item[key])
    return nodes


def normalize_schema_type(value: Any) -> str:
    """Normalize Schema.org spellings, preserving foreign vocabulary names.

    Bare names and the conventional schema: prefix are supported. Arbitrary
    context aliases require context expansion, which is not performed here.
    """
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        parsed = urlparse(text)
    except ValueError:
        return text
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc.lower() == "schema.org" and not parsed.query and not parsed.fragment:
            return parsed.path.strip("/")
        return text
    if text.startswith("schema:"):
        return text[len("schema:"):]
    return text


def schema_type_names(value: Any) -> List[str]:
    """Return normalized names from a scalar or list-valued ``@type``."""
    values = value if isinstance(value, list) else [value]
    return [name for item in values if (name := normalize_schema_type(item))]


def schema_type_matches(value: Any, expected: Any) -> bool:
    """Compare schema type values independent of URI/compact-name spelling."""
    expected_values = expected if isinstance(expected, (list, tuple, set, frozenset)) else [expected]
    actual_names = {name.casefold() for name in schema_type_names(value)}
    expected_names = {normalize_schema_type(item).casefold() for item in expected_values}
    expected_names.discard("")
    return bool(actual_names & expected_names)


def extract_jsonld(html: str) -> List[Dict[str, Any]]:
    """Extract semantic nodes from valid JSON-LD script blocks."""
    soup = _soup(html)
    items: List[Dict[str, Any]] = []
    for script in soup.find_all("script"):
        if not is_jsonld_mime_type(script.get("type")):
            continue
        content = script.get_text(strip=True)
        if not content:
            continue
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, RecursionError):
            continue
        items.extend(flatten_jsonld(parsed))
    return items


def extract_links(html: str, base_url: str = "") -> List[Dict[str, Any]]:
    """Extract unique HTML links with normalized absolute URLs and anchor text."""
    soup = _soup(html)
    seen = set()
    links: List[Dict[str, Any]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        try:
            absolute = urljoin(base_url, href) if base_url else href
            urlparse(absolute)  # validate malformed IPv6 authorities
        except ValueError:
            continue
        if not absolute or absolute in seen:
            continue
        seen.add(absolute)
        unsafe_action = anchor.get("role") == "button" or anchor.has_attr("download") or any(
            key.endswith("-method") and str(value).upper() not in {"GET", "HEAD"}
            for key, value in anchor.attrs.items())
        link = {"href": absolute, "text": anchor.get_text(" ", strip=True), "rel": list(anchor.get("rel", []))}
        if unsafe_action:
            link["unsafe_action"] = True
        links.append(link)
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
