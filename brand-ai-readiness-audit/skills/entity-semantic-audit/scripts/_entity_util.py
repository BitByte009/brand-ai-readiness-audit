"""Shared helpers for entity-semantic-audit's build/detect scripts.

Not a public script. `build_entity_profile.py` and `detect_entity.py` each add this
file's directory to `sys.path` and import from it directly -- the parent skill
directory's hyphenated name makes it an invalid Python package path. See
`references/store-contract.md` for the observation shapes referenced here and
`references/entity-profile-contract.md` for the profile shape built on top of them.
"""

from __future__ import annotations

import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(SCRIPTS_DIR), str(MARKETPLACE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Shared mechanics, re-exported for the existing detector interfaces.
from lib.common.observations import http_fetches, iter_type, page_classifications, probes, renders, single
from lib.common.pages import effective_pages
from lib.common.extract import title_segments, significant_words as _significant_words, containment_ratio as _containment_ratio

from lib.common.findings import affected_block, make_finding  # noqa: F401  (re-exported)

IDENTITY_NODE_TYPES = {"Organization", "LocalBusiness", "Person"}

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc)\.?\s*$",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")

TYPE_KEYWORDS = [
    "company", "corporation", "nonprofit", "non-profit", "organization", "organisation",
    "agency", "university", "college", "foundation", "publication", "magazine", "blog",
    "studio", "platform", "store", "shop", "clinic", "museum", "government",
    "municipality", "charity", "cooperative", "law firm", "restaurant", "gallery",
    "institute", "association", "union", "church", "school", "publisher", "startup",
]
_TYPE_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in TYPE_KEYWORDS) + r")\b", re.IGNORECASE
)
TYPE_LABEL_MAP = {
    "Organization": "organization",
    "Corporation": "corporation",
    "LocalBusiness": "business",
    "NGO": "nonprofit",
    "GovernmentOrganization": "government",
    "EducationalOrganization": "educational institution",
    "Person": "person",
    "NewsMediaOrganization": "publication",
}

_OFFERING_PATTERN_RE = re.compile(
    r"\bwe\s+(offer|sell|provide|build|make|help|create|design|develop|manufacture)\b",
    re.IGNORECASE,
)
_COPYRIGHT_RE = re.compile(r"©\s*\d{4}\s*[-–]?\s*(?:\d{4})?\s+([A-Z][\w&.,' -]{1,60})", re.UNICODE)

SUPPRESSED_OFFERING_ARCHETYPES = {"documentation", "personal-portfolio", "institutional"}
RETHRESHOLD_OFFERING_ARCHETYPES = {"publisher-editorial"}
# archetype-applicability.md: D-ENTITY-01 is RETHR on documentation and
# personal-portfolio (a sparse or implicit name is normal on a minimal personal
# site or a docs project, not a defect). D-ENTITY-02 is RETHR on
# personal-portfolio only -- a personal site rarely needs to say "I am a person."
RETHRESHOLD_NAME_ARCHETYPES = {"documentation", "personal-portfolio"}
RETHRESHOLD_TYPE_ARCHETYPES = {"personal-portfolio"}

# Sources that register a name in a formal/legal register rather than the
# public-facing marketing surface -- used to recognize an intentional
# legal-name/trading-name pair (see _canonical_name_field) rather than flagging
# it as an inconsistency.
LEGAL_REGISTER_SOURCES = {"schema", "footer"}
PUBLIC_FACING_SOURCES = {"title", "h1"}


_ADDRESS_ABBREVIATIONS = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
    "road": "rd", "lane": "ln", "court": "ct", "place": "pl", "square": "sq",
    "parkway": "pkwy", "highway": "hwy", "suite": "ste", "apartment": "apt",
    "floor": "fl", "building": "bldg", "north": "n", "south": "s", "east": "e",
    "west": "w", "northeast": "ne", "northwest": "nw", "southeast": "se",
    "southwest": "sw", "saint": "st",
}


def normalize_name(name: str) -> str:
    """Strip legal suffixes and punctuation, lowercase -- the 'core' form used to
    decide whether two name candidates are the same entity name."""
    stripped = _LEGAL_SUFFIX_RE.sub("", name or "").strip()
    stripped = _PUNCT_RE.sub("", stripped).strip().lower()
    return re.sub(r"\s+", " ", stripped)


def text_similarity(a: str, b: str) -> float:
    """Character-sequence ratio, boosted by asymmetric word containment so
    length differences alone don't read as a conflict (see _containment_ratio)."""
    ratio = SequenceMatcher(None, a or "", b or "").ratio()
    return max(ratio, _containment_ratio(a, b))


def normalize_address_part(value: Any) -> str:
    """Lowercase, strip punctuation, and expand common street-address
    abbreviations so '123 Main St' and '123 Main Street' compare equal --
    the same real address written two conventional ways is not a conflict."""
    text = _PUNCT_RE.sub("", str(value or "")).lower().strip()
    words = [_ADDRESS_ABBREVIATIONS.get(w, w) for w in text.split()]
    return " ".join(words)


def identity_question(probe: Optional[Dict[str, Any]], question_id: str) -> Optional[Dict[str, Any]]:
    if not probe:
        return None
    for question in probe.get("value", {}).get("questions", []):
        if question.get("category") == "identity" and question.get("id") == question_id:
            return question
    return None


def corroboration(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return single(store, "CORROBORATION")


def homepage_url(store: Dict[str, Any]) -> Optional[str]:
    for url in http_fetches(store):
        if (urlparse(url).path or "/") == "/":
            return url
    return None


def depth1_urls(store: Dict[str, Any], home_url: str) -> List[str]:
    from lib.common.extract import extract_links

    pages = effective_pages(store)
    home = pages.get(home_url)
    if not home:
        return []
    home_host = urlparse(home_url).netloc
    linked = {
        link["href"]
        for link in extract_links(home["html"], base_url=home_url)
        if urlparse(link["href"]).netloc == home_host
    }
    return [u for u in linked if u in pages and u != home_url]


def _is_footer_like(tag: Any) -> bool:
    if not hasattr(tag, "get"):
        return False
    classes = " ".join(tag.get("class", []) or [])
    id_attr = tag.get("id", "") or ""
    return "footer" in classes.lower() or "footer" in id_attr.lower()


def footer_copyright_name(html: str) -> Optional[str]:
    """Only a copyright line found inside an actual <footer> (or a
    footer-classed/id'd element) counts as a footer name candidate. Searching
    the whole document catches unrelated copyright notices anywhere on the
    page -- a photo credit, a syndicated widget, a 'powered by' notice -- and
    mislabels them as the site's own footer attribution."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    footer = soup.find("footer") or soup.find(_is_footer_like)
    if footer is None:
        return None

    match = _COPYRIGHT_RE.search(footer.get_text(" ", strip=True))
    if match:
        return match.group(1).strip().rstrip(".")
    return None


def type_keyword_match(text: str) -> Optional[str]:
    match = _TYPE_KEYWORD_RE.search(text or "")
    return match.group(1).lower() if match else None


def offering_pattern_match(text: str) -> Optional[str]:
    match = _OFFERING_PATTERN_RE.search(text or "")
    return match.group(0) if match else None


def jsonld_nodes_of_type(html: str, types) -> List[Dict[str, Any]]:
    from lib.common.extract import extract_jsonld, schema_type_matches

    wanted = {types} if isinstance(types, str) else set(types)
    nodes = []
    for node in extract_jsonld(html):
        if schema_type_matches(node.get("@type"), wanted):
            nodes.append(node)
    return nodes
