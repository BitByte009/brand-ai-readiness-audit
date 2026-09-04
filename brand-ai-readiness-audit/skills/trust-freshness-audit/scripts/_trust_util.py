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
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(SCRIPTS_DIR), str(MARKETPLACE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from lib.common.findings import affected_block, make_finding  # noqa: F401  (re-exported)

# ---------------------------------------------------------------------------
# Observation store accessors
# ---------------------------------------------------------------------------


def iter_type(store: Dict[str, Any], observation_type: str) -> List[Dict[str, Any]]:
    return [obs for obs in store.get("observations", []) if obs.get("type") == observation_type]


def single(store: Dict[str, Any], observation_type: str) -> Optional[Dict[str, Any]]:
    matches = iter_type(store, observation_type)
    return matches[0] if matches else None


def http_fetches(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "HTTP_FETCH")}


def renders(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "RENDER")}


def effective_pages(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """URL -> {"html", "observation_id", "headers"}, preferring the RENDER lens
    over raw HTTP_FETCH per page when a successful render exists and produced
    non-empty HTML -- a time-sensitive claim or its date signal rendered only
    client-side must not read as absent. Mirrors
    entity-semantic-audit's effective_pages()."""
    fetches = http_fetches(store)
    render_map = renders(store)
    pages: Dict[str, Dict[str, Any]] = {}
    for url, fetch_obs in fetches.items():
        headers = fetch_obs["value"].get("headers", {})
        render_obs = render_map.get(url)
        if render_obs and render_obs.get("value", {}).get("status") == "ok":
            rendered_html = render_obs["value"].get("html", "")
            if rendered_html:
                pages[url] = {"html": rendered_html, "observation_id": render_obs["id"], "headers": headers}
                continue
        pages[url] = {"html": fetch_obs["value"].get("html", ""), "observation_id": fetch_obs["id"], "headers": headers}
    return pages


def page_classifications(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PAGE_CLASSIFICATION")}


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
# Organizational signals
# ---------------------------------------------------------------------------

_ABOUT_PATH_RE = re.compile(r"/about", re.IGNORECASE)
_CONTACT_PATH_RE = re.compile(r"/contact", re.IGNORECASE)
_CONTACT_TEXT_RE = re.compile(
    r"\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b|[\w.+-]+@[\w-]+\.[a-z]{2,}", re.IGNORECASE
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


def is_about_page(url: str) -> bool:
    return bool(_ABOUT_PATH_RE.search(urlparse(url).path))


def is_contact_page(url: str) -> bool:
    return bool(_CONTACT_PATH_RE.search(urlparse(url).path))


def has_contact_info(text: str) -> bool:
    return bool(_CONTACT_TEXT_RE.search(text or ""))


def find_author_byline(html: str, text: str) -> Optional[str]:
    from lib.common.extract import extract_jsonld

    for node in extract_jsonld(html):
        author = node.get("author")
        if isinstance(author, dict) and author.get("name"):
            return str(author["name"])
        if isinstance(author, str) and author.strip():
            return author.strip()

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
