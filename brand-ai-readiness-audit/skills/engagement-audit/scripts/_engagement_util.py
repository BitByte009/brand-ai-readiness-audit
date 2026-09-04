"""Shared helpers for engagement-audit's build/detect scripts.

Not a public script. Named distinctly from other skills' own `_util.py`/
`_entity_util.py`/`_trust_util.py` helpers so multiple skills' scripts can be
imported in the same test session without a module-name collision (the lesson
from `entity-semantic-audit`'s own note on this).

See `references/store-contract.md` for the observation shapes referenced here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
    """URL -> {"html", "observation_id", "rendered"}, preferring the RENDER
    lens over raw HTTP_FETCH when a successful render exists and produced
    non-empty HTML. `rendered` records whether THIS page's html actually came
    from a render, so render-only checks (E-ANSWER-02/04) can require it
    strictly rather than silently accepting a raw-HTML fallback."""
    fetches = http_fetches(store)
    render_map = renders(store)
    pages: Dict[str, Dict[str, Any]] = {}
    for url, fetch_obs in fetches.items():
        render_obs = render_map.get(url)
        if render_obs and render_obs.get("value", {}).get("status") == "ok":
            rendered_html = render_obs["value"].get("html", "")
            if rendered_html:
                pages[url] = {"html": rendered_html, "observation_id": render_obs["id"], "rendered": True}
                continue
        pages[url] = {"html": fetch_obs["value"].get("html", ""), "observation_id": fetch_obs["id"], "rendered": False}
    return pages


def rendered_pages_only(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Subset of effective_pages() where a real render actually backs the
    page -- used by checks that must never approximate first-paint DOM state
    from raw HTML (E-ANSWER-02, E-ANSWER-03, E-ANSWER-04)."""
    return {url: page for url, page in effective_pages(store).items() if page["rendered"]}


def page_classifications(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PAGE_CLASSIFICATION")}


def probes(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PROBE")}


def engagement_question(probe: Optional[Dict[str, Any]], question_id: str) -> Optional[Dict[str, Any]]:
    if not probe:
        return None
    for question in probe.get("value", {}).get("questions", []):
        if question.get("category") == "engagement" and question.get("id") == question_id:
            return question
    return None


# ---------------------------------------------------------------------------
# Title segmentation and word-containment overlap (same technique
# entity-semantic-audit uses; reimplemented locally rather than imported
# across a skill boundary, matching that skill's own pattern of
# independent-per-skill utility duplication).
# ---------------------------------------------------------------------------

_TITLE_SEPARATOR_RE = re.compile(r"\s*[|—:]\s*|\s+-\s+")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "for", "in", "on", "at",
    "is", "are", "was", "were", "with", "that", "this", "it", "as", "by", "be",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def title_segments(title: str) -> List[str]:
    segments = [s.strip() for s in _TITLE_SEPARATOR_RE.split(title or "") if s.strip()]
    return segments or ([title.strip()] if title and title.strip() else [])


def significant_words(text: str) -> set:
    words = _WORD_RE.findall((text or "").lower())
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


def containment_ratio(a: str, b: str) -> float:
    words_a, words_b = significant_words(a), significant_words(b)
    if not words_a or not words_b:
        return 0.0
    shorter, longer = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    return len(shorter & longer) / len(shorter)


# ---------------------------------------------------------------------------
# Utility / terminal page recognition -- a page whose job is complete needs
# no next step (E-CONTINUE-01/02/03) and is not a depth-1 arrival context
# (E-ORIENT-01).
# ---------------------------------------------------------------------------

_UTILITY_SEGMENT_RE = re.compile(
    r"^(cart|checkout|search|login|logout|signin|signup|register|account|"
    r"wishlist|admin|basket|my-account|contact|thank-you|thanks|thankyou)(/|$)",
    re.IGNORECASE,
)
_TERMINAL_PAGE_TYPES = {"contact", "thank_you", "confirmation", "landing_page"}


def is_utility_path(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.query:
        return True
    path = parsed.path.lstrip("/")
    return bool(_UTILITY_SEGMENT_RE.match(path))


def is_terminal_page(url: str, classification: Optional[Dict[str, Any]]) -> bool:
    """A page whose job is complete -- no next step is a defect here."""
    if is_utility_path(url):
        return True
    page_type = (classification or {}).get("value", {}).get("page_type")
    return page_type in _TERMINAL_PAGE_TYPES


def url_depth(url: str) -> int:
    return len([seg for seg in urlparse(url).path.split("/") if seg])


# ---------------------------------------------------------------------------
# Main-content region (chrome stripped) -- same approach
# crawl-render-audit uses for D-RENDER-01.
# ---------------------------------------------------------------------------

_CHROME_TAGS = {"nav", "header", "footer", "script", "style", "noscript"}


def main_content_soup(html: str):
    """Scoped to <body> when present. Without this, get_text() also walks
    <head> -- including <title> -- so 'body text' would silently include the
    page's own title, defeating any title-vs-body comparison (E-ANSWER-01)
    and offsetting every scroll-depth measurement (E-ANSWER-04) by however
    long the title happens to be."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.body if soup.body is not None else soup
    for tag in root.find_all(list(_CHROME_TAGS)):
        tag.decompose()
    return root


def main_text(html: str) -> str:
    text = main_content_soup(html).get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# E-ORIENT-01: brand token in first screen / logo alt / title
# ---------------------------------------------------------------------------


def brand_token_positions(html: str, title: str, brand_tokens: List[str], first_screen_chars: int = 800) -> Dict[str, bool]:
    from bs4 import BeautifulSoup

    tokens = [t.lower() for t in brand_tokens if t]
    if not tokens:
        return {"body": False, "logo_alt": False, "title": False}

    soup = BeautifulSoup(html or "", "html.parser")
    body_text = main_text(html)[:first_screen_chars].lower()
    body_hit = any(t in body_text for t in tokens)

    logo_hit = False
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").lower()
        aria = (img.get("aria-label") or "").lower()
        if any(t in alt or t in aria for t in tokens):
            logo_hit = True
            break

    title_hit = any(any(t in seg.lower() for t in tokens) for seg in title_segments(title))

    return {"body": body_hit, "logo_alt": logo_hit, "title": title_hit}


# ---------------------------------------------------------------------------
# E-ORIENT-03: breadcrumb / path context
# ---------------------------------------------------------------------------

_BREADCRUMB_NAME_RE = re.compile(r"breadcrumb", re.IGNORECASE)
_TEXTUAL_PATH_RE = re.compile(r"\b[\w& ]{2,30}\s*(?:>|›|»)\s*[\w& ]{2,30}\b")


def has_breadcrumb(html: str) -> bool:
    from bs4 import BeautifulSoup

    from lib.common.extract import extract_jsonld

    for node in extract_jsonld(html):
        node_type = node.get("@type")
        node_types = {node_type} if isinstance(node_type, str) else set(node_type or [])
        if "BreadcrumbList" in node_types:
            return True

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["nav", "ol", "ul", "div"]):
        classes = " ".join(tag.get("class", []) or [])
        id_attr = tag.get("id", "") or ""
        aria = tag.get("aria-label", "") or ""
        if _BREADCRUMB_NAME_RE.search(classes) or _BREADCRUMB_NAME_RE.search(id_attr) or _BREADCRUMB_NAME_RE.search(aria):
            return True

    if _TEXTUAL_PATH_RE.search(main_text(html)[:600]):
        return True

    return False


# ---------------------------------------------------------------------------
# E-ORIENT-04: fragment link resolution
# ---------------------------------------------------------------------------


def internal_fragment_links(html: str, base_url: str) -> List[Tuple[str, str]]:
    """[(target_url_without_fragment, fragment), ...] for same-host links
    carrying a non-trivial #fragment."""
    from lib.common.extract import extract_links

    results = []
    base_host = urlparse(base_url).netloc
    for link in extract_links(html, base_url=base_url):
        href = link["href"]
        parsed = urlparse(href)
        if parsed.netloc != base_host or not parsed.fragment:
            continue
        if parsed.fragment in ("", "top"):
            continue
        target = href.split("#", 1)[0]
        results.append((target, parsed.fragment))
    return results


def has_dom_anchor(html: str, fragment: str) -> bool:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    return soup.find(id=fragment) is not None or soup.find(attrs={"name": fragment}) is not None


# ---------------------------------------------------------------------------
# E-ANSWER-02 / E-ANSWER-03: blocking overlays and paywall gates
# ---------------------------------------------------------------------------

_MODAL_NAME_RE = re.compile(r"\b(modal|overlay|popup|lightbox|newsletter)\b", re.IGNORECASE)
_CONSENT_NAME_RE = re.compile(r"\b(cookie|consent|gdpr)\b", re.IGNORECASE)
_PAYWALL_NAME_RE = re.compile(r"\b(paywall|subscribe to continue|sign in to read|premium content|members? only)\b", re.IGNORECASE)


def _is_hidden(tag: Any) -> bool:
    if tag.get("hidden") is not None:
        return True
    if (tag.get("aria-hidden") or "").lower() == "true":
        return True
    style = (tag.get("style") or "").lower()
    return "display:none" in style.replace(" ", "") or "display: none" in style


def _matches_pattern(tag: Any, pattern: re.Pattern) -> bool:
    classes = " ".join(tag.get("class", []) or [])
    id_attr = tag.get("id", "") or ""
    text = tag.get_text(" ", strip=True)[:200]
    return bool(pattern.search(classes) or pattern.search(id_attr) or pattern.search(text))


_MODAL_CONTAINER_TAGS = {"div", "section", "aside", "dialog", "form"}


def find_blocking_overlay(html: str) -> Optional[Dict[str, Any]]:
    """A visible-by-default dialog/modal/overlay element that is not a
    compliant edge-confined consent banner.

    The keyword-based candidate search is restricted to container-shaped
    tags. Without that restriction, a plain, harmless trigger --
    `<button class="modal-trigger-btn">Watch demo</button>` -- matches the
    same keyword pattern as the dialog it opens (which is correctly hidden
    elsewhere in the DOM) and gets flagged as the blocking element itself.
    `role="dialog"`/`aria-modal="true"` are unambiguous regardless of tag and
    are never restricted this way."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    candidates = soup.find_all(attrs={"role": "dialog"}) + soup.find_all(attrs={"aria-modal": "true"})
    for tag in soup.find_all(list(_MODAL_CONTAINER_TAGS)):
        if _matches_pattern(tag, _MODAL_NAME_RE) and tag not in candidates:
            candidates.append(tag)

    for tag in candidates:
        if _is_hidden(tag):
            continue
        if _matches_pattern(tag, _CONSENT_NAME_RE) and not _matches_pattern(tag, _MODAL_NAME_RE):
            continue  # a plain consent banner, not a modal-shaped one
        classes = " ".join(tag.get("class", []) or [])
        return {"tag": tag.name, "class": classes, "id": tag.get("id", ""), "role": tag.get("role", "")}
    return None


def find_paywall_gate(html: str) -> Optional[Dict[str, Any]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(True):
        if _is_hidden(tag):
            continue
        if _matches_pattern(tag, _PAYWALL_NAME_RE):
            classes = " ".join(tag.get("class", []) or [])
            return {"tag": tag.name, "class": classes, "id": tag.get("id", ""), "text": tag.get_text(" ", strip=True)[:120]}
    return None


# ---------------------------------------------------------------------------
# E-ANSWER-04: scroll-depth position and collapsed-region membership
# ---------------------------------------------------------------------------


def scroll_depth_fraction(html: str, evidence_span: str) -> Optional[float]:
    text = main_text(html)
    span = re.sub(r"\s+", " ", (evidence_span or "").strip())
    if not span or not text:
        return None
    offset = text.find(span)
    if offset < 0:
        return None
    return offset / len(text)


def is_in_collapsed_region(html: str, evidence_span: str) -> bool:
    """Reuses crawl-render-audit's D-RENDER-04 disclosure-panel detection
    approach: an aria-expanded=false or hidden ancestor around the text."""
    from bs4 import BeautifulSoup

    span = re.sub(r"\s+", " ", (evidence_span or "").strip())
    if not span:
        return False

    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.find(string=lambda s: s and span in re.sub(r"\s+", " ", s))
    if node is None:
        return False

    for ancestor in node.parents:
        if not hasattr(ancestor, "get"):
            continue
        if (ancestor.get("aria-expanded") or "").lower() == "false":
            return True
        if _is_hidden(ancestor):
            return True
    return False


def has_anchor_nav_to_answer(html: str, evidence_span: str) -> bool:
    """True when some element in the page links (`#id`) directly to the
    section containing the answer.

    A long, single-page site with a sticky nav ('Features / Pricing / FAQ')
    that jumps straight to the answer's section is a deliberate, common, and
    well-regarded structure -- the raw scroll-depth fraction alone would
    otherwise penalize it exactly like a page with no navigational aid at
    all, purely for being long. This checks whether the visitor actually has
    a one-click way to reach the answer, regardless of how far down it sits."""
    from bs4 import BeautifulSoup

    span = re.sub(r"\s+", " ", (evidence_span or "").strip())
    if not span:
        return False

    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.find(string=lambda s: s and span in re.sub(r"\s+", " ", s))
    if node is None:
        return False

    target_id = None
    for ancestor in node.parents:
        if hasattr(ancestor, "get") and ancestor.get("id"):
            target_id = ancestor["id"]
            break
    if not target_id:
        return False

    return soup.find("a", href=f"#{target_id}") is not None


# ---------------------------------------------------------------------------
# E-CONTINUE-*: outgoing content-area link classification
# ---------------------------------------------------------------------------

_SOCIAL_SHARE_RE = re.compile(r"\b(share|tweet|mailto)\b", re.IGNORECASE)


def content_area_links(html: str, base_url: str) -> List[Dict[str, Any]]:
    from lib.common.extract import extract_links

    soup = main_content_soup(html)
    content_html = str(soup)
    return extract_links(content_html, base_url=base_url)


def _registrable_domain(netloc: str) -> str:
    """Best-effort same-organization comparison: last two dot-separated
    labels, port stripped. Not a full public-suffix resolution -- sufficient
    to recognize 'app.acme.com' and 'acme.com' as the same organization,
    matching the same lightweight heuristic crawl-render-audit uses for
    duplicate-host detection."""
    host = netloc.lower().split(":")[0]
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def classify_link(link: Dict[str, Any], base_url: str) -> str:
    href = link["href"]
    parsed = urlparse(href)
    base_parsed = urlparse(base_url)

    if href.startswith("mailto:") or _SOCIAL_SHARE_RE.search(" ".join(link.get("rel", [])) + " " + link.get("text", "")):
        return "social_or_mail"
    if parsed.netloc and parsed.netloc != base_parsed.netloc:
        # A same-organization subdomain (app.acme.com from acme.com) is a
        # genuine next step -- the marketing-site-to-app-subdomain CTA is a
        # near-universal SaaS pattern and was previously misclassified
        # "external" the same as an unrelated third-party site.
        if _registrable_domain(parsed.netloc) == _registrable_domain(base_parsed.netloc):
            return "internal_content"
        return "external"
    if parsed.path == base_parsed.path:
        return "same_page_anchor"
    return "internal_content"


def hub_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    segments = [seg for seg in parsed.path.split("/") if seg]
    if len(segments) < 2:
        return None
    parent_path = "/" + "/".join(segments[:-1]) + "/"
    return f"{parsed.scheme}://{parsed.netloc}{parent_path}"
