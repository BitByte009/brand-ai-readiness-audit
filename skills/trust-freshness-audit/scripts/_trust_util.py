"""Shared helpers for trust-freshness-audit's build/detect/corroborate scripts.

Not a public script. Named distinctly from other skills' own `_util.py` helpers
(see `entity-semantic-audit`'s own note on this) so multiple skills' scripts can be
imported in the same test session without a module-name collision.

See `references/store-contract.md` for the observation shapes referenced here and
`references/claim-table-contract.md` for the claim table shape built on top of them.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(SCRIPTS_DIR), str(MARKETPLACE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Shared mechanics, re-exported for the existing detector interfaces.
from lib.common.observations import http_fetches, iter_type, page_classifications, renders, single
from lib.common.pages import effective_pages

from lib.common.findings import affected_block, make_finding  # noqa: F401  (re-exported)

# ---------------------------------------------------------------------------
# Observation store accessors
# ---------------------------------------------------------------------------


def claim_corroborations(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """claim_id -> CLAIM_CORROBORATION observation."""
    return {obs["value"].get("claim_id"): obs for obs in iter_type(store, "CLAIM_CORROBORATION")}


# ---------------------------------------------------------------------------
# Date parsing -- deterministic, no external dependency
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")  # no trailing \b: a 'T' (ISO datetime) or other word char can follow with no boundary
_MONTH_DAY_YEAR_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE)
_DAY_MONTH_YEAR_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
_COPYRIGHT_YEAR_RE = re.compile(r"©\s*(\d{4})")
_FRESHNESS_LABEL_RE = re.compile(r"(updated|published|posted|last modified|revised|as of)\s*[:\-]?\s*", re.IGNORECASE)


def parse_date(text: str) -> Optional[date]:
    """Best-effort extraction of the first recognizable date in `text`. Tries
    ISO (YYYY-MM-DD), 'Month D, YYYY', and 'D Month YYYY', in that order."""
    if not text:
        return None

    match = _ISO_DATE_RE.search(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    match = _MONTH_DAY_YEAR_RE.search(text)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(2)))
            except ValueError:
                pass

    match = _DAY_MONTH_YEAR_RE.search(text)
    if match:
        month = _MONTHS.get(match.group(2).lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                pass

    return None


def find_visible_freshness_dates(text: str) -> List[date]:
    """Dates found near an explicit freshness label ('Updated:', 'Published',
    'Last modified', 'As of', ...) -- NOT every date mentioned anywhere on the
    page (a 'founded in 2020' claim is not a freshness signal)."""
    dates = []
    for label_match in _FRESHNESS_LABEL_RE.finditer(text or ""):
        window = text[label_match.end() : label_match.end() + 30]
        parsed = parse_date(window)
        if parsed:
            dates.append(parsed)
    return dates


def find_copyright_year(text: str) -> Optional[int]:
    match = _COPYRIGHT_YEAR_RE.search(text or "")
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Claim value normalization
# ---------------------------------------------------------------------------


def normalize_claim_value(value: str) -> str:
    """'$1,000' and '$1000.00' normalize equal; used to compare entity_fact
    claim values without an LLM judgment."""
    text = re.sub(r"[,\s]", "", str(value or "")).lower()
    text = re.sub(r"\.0+$", "", text)
    return text


# ---------------------------------------------------------------------------
# Fixed, generic phrase patterns (never brand/vertical-specific)
# ---------------------------------------------------------------------------

TIME_SENSITIVE_PATTERNS = [
    "currently", "right now", "this year", "this month", "this week",
    "upcoming", "now available", "newly released", "limited time",
    "as of", "latest version", "new pricing", "now in stock",
    "just launched", "recently updated",
]
_TIME_SENSITIVE_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in TIME_SENSITIVE_PATTERNS) + r")\b", re.IGNORECASE
)

_EVENT_FORWARD_RE = re.compile(r"\b(upcoming|next|join us)\b.{0,60}?\b" + f"({_MONTH_ALT})\\.?\\s+(\\d{{1,2}}),?\\s+(\\d{{4}})", re.IGNORECASE)
_OFFER_FORWARD_RE = re.compile(
    r"\b(sale|offer|discount|promotion|registration|deal)\b.{0,40}?\b(ends?|until|through|closes?)\b.{0,20}?"
    rf"({_MONTH_ALT})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})",
    re.IGNORECASE,
)

_FOUNDED_RE = re.compile(r"\bfounded\s+in\s+(\d{4})\b|\b(?:in business|operating)\s+since\s+(\d{4})\b", re.IGNORECASE)
_CUSTOMER_COUNT_RE = re.compile(r"\b(?:over\s+)?([\d,]{2,})\+?\s+(?:customers|clients|users|members)\b", re.IGNORECASE)
_EMPLOYEE_COUNT_RE = re.compile(r"\b([\d,]{1,})\+?\s+employees\b", re.IGNORECASE)

SUPERLATIVE_PATTERNS = [
    "#1", "number one", "leading", "best-selling", "best selling",
    "top-rated", "top rated", "most popular", "award-winning",
    "award winning", "industry leader",
]
_SUPERLATIVE_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in SUPERLATIVE_PATTERNS) + r")\b", re.IGNORECASE
)
_STAT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?%")  # no trailing \b: '%' isn't a word char, so '%\b' never matches
_CITATION_NEARBY_RE = re.compile(r"(according to|source:|cited|\[\d+\]|https?://)", re.IGNORECASE)


def has_nearby_citation(text: str, start: int, end: int, window: int = 80) -> bool:
    snippet = text[max(0, start - window) : end + window]
    return bool(_CITATION_NEARBY_RE.search(snippet))


# ---------------------------------------------------------------------------
# Organizational/accountability signals
# ---------------------------------------------------------------------------

_ABOUT_PATH_SEGMENTS = {"about", "about-us"}
_CONTACT_PATH_SEGMENTS = {"contact", "contact-us"}
_ACCOUNTABILITY_PAGE_TYPES = {"about", "about_page", "organization", "local_business", "team"}
_CONTACT_PAGE_TYPES = {"contact", "contact_page"}
_ORGANIZATION_TYPES = {
    "Organization",
    "Corporation",
    "EducationalOrganization",
    "GovernmentOrganization",
    "LocalBusiness",
    "NGO",
    "NewsMediaOrganization",
}
_CONTACT_TYPES = {"ContactPoint", "PostalAddress"}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_PHONE_RE = re.compile(r"(?<!\w)\+?\d(?:[\s().-]*\d){6,}(?!\w)")
_OPERATOR_DESCRIPTION_RE = re.compile(
    r"\b(?:operated|owned|published|maintained|managed|run)\s+by\s+(?!unknown\b)\S+|"
    r"\b(?:site\s+operator|publisher|copyright\s+holder)\s*[:\-]\s*\S+",
    re.IGNORECASE,
)
_AUTHOR_BYLINE_RE = re.compile(r"\bby\s+([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3})\b")

# archetype-applicability.md: D-TRUST-01/02 (freshness) are RETHR up on
# publisher-editorial (freshness is central there) and down on documentation
# and personal-portfolio. D-TRUST-06 (organizational opacity) is suppressed on
# personal-portfolio -- the site's own existence typically functions as the
# "about", and its author is self-evident.
RETHRESHOLD_FRESHNESS_UP_ARCHETYPES = {"publisher-editorial"}
RETHRESHOLD_FRESHNESS_DOWN_ARCHETYPES = {"documentation", "personal-portfolio"}
SUPPRESSED_OPACITY_ARCHETYPES = {"personal-portfolio"}


def _page_type(classification: Optional[Dict[str, Any]]) -> str:
    if not classification:
        return ""
    value = classification.get("value", classification)
    return str((value or {}).get("page_type", "")).strip().lower().replace("-", "_")


def _path_segments(url: str) -> List[str]:
    """Return decoded, exact path segments for weak role-name fallbacks.

    Segment equality is deliberate: `/about` and `/about.html` are useful weak
    hints, while `/about-face` and `/contact-lenses` are unrelated product
    names and must not satisfy an accountability check merely by substring.
    """
    segments = []
    for raw_segment in unquote(urlparse(url).path).split("/"):
        segment = raw_segment.strip().lower()
        if not segment:
            continue
        stem, dot, suffix = segment.rpartition(".")
        if dot and suffix in {"html", "htm", "php", "asp", "aspx"}:
            segment = stem
        segments.append(segment)
    return segments


def is_about_page(url: str, classification: Optional[Dict[str, Any]] = None) -> bool:
    """Whether explicit page-role evidence identifies an accountability page.

    PAGE_CLASSIFICATION is the stronger signal. Exact conventional path
    segments remain a deliberately weak fallback for stores without that
    observation; arbitrary path substrings never count.
    """
    return _page_type(classification) in _ACCOUNTABILITY_PAGE_TYPES or bool(
        set(_path_segments(url)) & _ABOUT_PATH_SEGMENTS
    )


def is_contact_page(url: str, classification: Optional[Dict[str, Any]] = None) -> bool:
    return _page_type(classification) in _CONTACT_PAGE_TYPES or bool(
        set(_path_segments(url)) & _CONTACT_PATH_SEGMENTS
    )


def _jsonld_nodes(html: str) -> List[Dict[str, Any]]:
    """Flatten JSON-LD `@graph` containers returned by the common extractor.

    The common helper owns parsing. This small traversal makes the trust skill
    tolerant of both extractor shapes: roots that still contain `@graph`, and
    roots already flattened by a newer common extractor.
    """
    from lib.common.extract import extract_jsonld

    nodes: List[Dict[str, Any]] = []
    seen: set = set()

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        nodes.append(value)
        visit(value.get("@graph"))

    for root in extract_jsonld(html):
        visit(root)
    return nodes


def _node_types(node: Dict[str, Any]) -> set:
    from lib.common.extract import schema_type_names

    return set(schema_type_names(node.get("@type")))


def has_operator_identity(html: str, text: str = "") -> bool:
    """Detect a named site operator without depending on an `/about` URL."""
    nodes = _jsonld_nodes(html)
    by_id = {str(node["@id"]): node for node in nodes if node.get("@id")}

    if any(
        _node_types(node) & _ORGANIZATION_TYPES
        and bool(str(node.get("name") or node.get("legalName") or "").strip())
        for node in nodes
    ):
        return True

    # WebSite/CreativeWork operator relations can point to a graph node rather
    # than embed the operator inline.
    for node in nodes:
        for key in ("publisher", "provider", "creator", "copyrightHolder"):
            raw = node.get(key)
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                if isinstance(entry, str) and entry.strip() and not entry.startswith("#"):
                    return True
                if not isinstance(entry, dict):
                    continue
                resolved = by_id.get(str(entry.get("@id")), entry)
                if str(resolved.get("name") or resolved.get("legalName") or "").strip():
                    return True

    return bool(_OPERATOR_DESCRIPTION_RE.search(text or ""))


def has_contact_info(text: str) -> bool:
    phones = _PHONE_RE.finditer(text or "")
    # A bare order number or year range is not a telephone channel.
    return bool(_EMAIL_RE.search(text or "")) or any(
        match.group().startswith("+") or re.search(r"[().]", match.group())
        for match in phones
    )


def has_contact_method(html: str, text: str = "") -> bool:
    """Detect an actionable electronic, form, structured, or postal contact."""
    from bs4 import BeautifulSoup

    if has_contact_info(text):
        return True

    soup = BeautifulSoup(html or "", "html.parser")
    for link in soup.find_all(["a", "area"], href=True):
        href = str(link.get("href") or "").strip().lower()
        if href.startswith(("mailto:", "tel:")) and href.split(":", 1)[1].split("?", 1)[0].strip():
            return True

    for form in soup.find_all("form"):
        action = str(form.get("action") or "").strip().lower()
        if action.startswith("mailto:"):
            return True
        # A textarea provides a message channel. Requiring an accompanying
        # identity/reply field avoids treating search, login, and newsletter
        # signup forms as contact forms.
        if form.find("textarea") is not None and form.find(
            "input", attrs={"type": lambda value: value and value.lower() in {"email", "tel"}}
        ) is not None:
            return True

    for node in _jsonld_nodes(html):
        node_types = _node_types(node)
        if node_types & _CONTACT_TYPES:
            if any(node.get(key) for key in ("email", "telephone", "streetAddress", "addressLocality", "url")):
                return True
        if node_types & _ORGANIZATION_TYPES and any(
            node.get(key) for key in ("contactPoint", "address", "email", "telephone")
        ):
            return True
    return False


def find_author_byline(html: str, text: str) -> Optional[str]:
    from bs4 import BeautifulSoup

    nodes = _jsonld_nodes(html)
    by_id = {str(node["@id"]): node for node in nodes if node.get("@id")}
    for node in nodes:
        author = node.get("author")
        authors = author if isinstance(author, list) else [author]
        for candidate in authors:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if not isinstance(candidate, dict):
                continue
            resolved = by_id.get(str(candidate.get("@id")), candidate)
            name = resolved.get("name") or resolved.get("legalName")
            if name and str(name).strip():
                return str(name).strip()

    soup = BeautifulSoup(html or "", "html.parser")
    for meta in soup.find_all("meta"):
        key = str(meta.get("name") or meta.get("property") or meta.get("itemprop") or "").strip().lower()
        content = str(meta.get("content") or "").strip()
        if key in {"author", "article:author", "byl"} and content:
            return content

    for tag in soup.find_all(attrs={"itemprop": lambda value: value and "author" in str(value).lower().split()}):
        value = str(tag.get("content") or tag.get_text(" ", strip=True) or "").strip()
        if value:
            return value

    for tag in soup.find_all(rel=lambda value: value and "author" in [str(item).lower() for item in (value if isinstance(value, list) else [value])]):
        value = str(
            tag.get_text(" ", strip=True)
            or tag.get("aria-label")
            or tag.get("title")
            or ""
        ).strip()
        if value:
            return value

    match = _AUTHOR_BYLINE_RE.search(text or "")
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Identity-confusion guard (D-TRUST-05) -- reuses entity-semantic-audit's
# entity_profile rather than re-deriving identity signals.
# ---------------------------------------------------------------------------

_DISAMBIGUATION_RE = re.compile(
    r"\b(not affiliated|not the same|no relation|unrelated to|different from|"
    r"not to be confused|not associated|distinct from)\b",
    re.IGNORECASE,
)


def source_matches_entity(source: Dict[str, Any], entity_profile: Optional[Dict[str, Any]]) -> bool:
    """Conservative, deterministic same-entity confirmation: the source's
    title/snippet must name the canonical entity AND either link to a known
    identity-anchor domain or mention the entity's stated type -- a bare name
    match alone is not enough to confirm it isn't a different, similarly
    named entity (the identity-confusion case this check exists to catch).

    A source whose text explicitly disambiguates itself from the entity
    ('not affiliated with', 'not to be confused with', ...) is never a match,
    regardless of any other signal -- such a source is *warning about* the
    identity-confusion case, not corroborating the claim, and treating it as
    a match would be the exact dishonesty this guard exists to prevent."""
    if not entity_profile:
        return False

    canonical = (entity_profile.get("fields", {}).get("canonical_name") or {}).get("value")
    if not canonical:
        return False

    text = f"{source.get('title', '')} {source.get('snippet', '')}".lower()
    if canonical.lower() not in text:
        return False

    if _DISAMBIGUATION_RE.search(text):
        return False

    anchor = entity_profile.get("identity_anchor", {}) or {}
    same_as_hosts = {urlparse(u).netloc.lower() for u in anchor.get("same_as", [])}
    source_host = urlparse(source.get("url", "")).netloc.lower()
    if source_host and source_host in same_as_hosts:
        return True

    entity_type = (entity_profile.get("fields", {}).get("entity_type") or {}).get("value")
    if entity_type and entity_type.lower() in text:
        return True

    return False


# ---------------------------------------------------------------------------
# Corroboration selectivity -- an outbound lookup runs against a shared,
# hard-capped budget (orchestration-rules.md: 45s for the whole audit). Only
# claims D-TRUST-05 can actually act on are worth spending it on.
# ---------------------------------------------------------------------------

CORROBORATION_WORTHY_CLAIM_TYPES = {"entity_fact", "superlative_stat"}


def is_corroboration_worthy(claim: Dict[str, Any]) -> bool:
    """A time-sensitive or dated-offer/event claim needs a *date*, not a
    second opinion -- corroborating it externally would not change whether
    D-TRUST-01/02 fire and would spend lookup budget for no detection
    benefit. Only `entity_fact` claims (what D-TRUST-05 was designed for) and
    unattributed `superlative_stat` claims (where a citation could resolve
    D-TRUST-04 instead of an external lookup) are ever worth corroborating."""
    if claim.get("claim_type") not in CORROBORATION_WORTHY_CLAIM_TYPES:
        return False
    if claim.get("claim_type") == "superlative_stat" and claim.get("attributed"):
        return False
    return True
