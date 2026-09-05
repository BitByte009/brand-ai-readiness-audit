"""Budget-enforcing, robots-aware HTTP client for the audit platform."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin
import re
import time

import requests
from urllib3.exceptions import HTTPError

# PROJECT_CONTEXT.md D-10: one honest, self-identifying user-agent, used for
# every outbound request this platform makes (crawl, robots.txt, sitemap).
# Never spoofed to look like a browser or another crawler -- see
# failure-taxonomy.md's D-CRAWL-09 revision note and skills/crawl-render-audit's
# bot-hostile-serving check, which depends on this being the *only* identity
# the site ever sees from us.
AUDIT_USER_AGENT = (
    "brand-ai-readiness-audit/0.1 "
    "(+read-only AI-discoverability auditor; no auth, no writes, robots.txt-respecting)"
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def resolve_redirect_chain(history: Iterable[Any]) -> List[Dict[str, Any]]:
    """Convert a requests redirect history into a stable evidence chain."""
    chain: List[Dict[str, Any]] = []
    for response in history or []:
        location = None
        headers = getattr(response, "headers", {}) or {}
        if isinstance(headers, dict):
            location = headers.get("location") or headers.get("Location")
        else:
            location = headers.get("location") or headers.get("Location")

        source_url = getattr(response, "url", None)
        status_code = getattr(response, "status_code", None)
        if source_url and location:
            chain.append(
                {
                    "from": source_url,
                    "to": str(location),
                    "status": int(status_code) if status_code is not None else 0,
                }
            )
    return chain


# A charset declared inside the document, which is where HTML5 puts it when the
# transport does not. Scanned over bytes, before any decode has happened.
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)
_BOMS = ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))
_META_SCAN_BYTES = 2048


def html_encoding(headers: Dict[str, Any], body: bytes) -> str:
    """Resolve a response's encoding the way a browser does.

    `requests` falls back to ISO-8859-1 for any text/* response with no charset
    parameter. That is the HTTP/1.1 default, but it is not what HTML5 or any
    browser does, and a page served as `text/html` carrying only a
    `<meta charset>` is both valid and common. Taking the RFC default silently
    turns every non-ASCII page into mojibake, which corrupts every text-based
    check downstream -- names, titles, claims, overlap -- and can even be
    reported back to the site as an encoding defect that is ours, not theirs.

    Deterministic ladder, no character-set guessing library: an explicit
    transport charset, then a byte-order mark, then the document's own
    declaration, then UTF-8 if the bytes are valid UTF-8 (the HTML5 default),
    and finally Latin-1, which cannot fail.
    """
    content_type = ""
    for key, value in (headers or {}).items():
        if str(key).lower() == "content-type":
            content_type = str(value or "")
            break
    declared = re.search(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:-]+)", content_type, re.IGNORECASE)
    if declared:
        return declared.group(1)

    for mark, encoding in _BOMS:
        if body.startswith(mark):
            return encoding

    meta = _META_CHARSET_RE.search(body[:_META_SCAN_BYTES])
    if meta:
        try:
            return meta.group(1).decode("ascii")
        except UnicodeDecodeError:
            pass

    try:
        body.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "iso-8859-1"


def request_once(url, timeout=10):
    """Anonymous, bounded, single-hop transport; no ambient auth or cookies."""
    from .network_policy import origin, unsafe_target
    origin(url)
    if unsafe_target(url):
        raise requests.RequestException("unsafe request target")
    deadline = time.monotonic() + timeout
    with requests.Session() as session:
        session.trust_env = False
        from .public_transport import PublicOnlyAdapter
        session.mount("http://", PublicOnlyAdapter(max_retries=0))
        session.mount("https://", PublicOnlyAdapter(max_retries=0))
        response = session.get(url, timeout=timeout, allow_redirects=False, stream=True,
                               headers={"User-Agent": AUDIT_USER_AGENT, "Accept-Encoding": "identity"})
        try:
            # Reject compression rather than decompressing attacker-controlled
            # expansion bombs. Ordinary servers respect Accept-Encoding.
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise requests.RequestException("compressed response excluded by safety policy")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > MAX_RESPONSE_BYTES:
                raise requests.RequestException("response exceeds safety byte limit")
            body = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise requests.Timeout("response wall-time limit")
                # read1 returns after one underlying read, unlike read(n) which
                # can keep filling n bytes indefinitely from a trickling peer.
                chunk = response.raw.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)), decode_content=False)
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise requests.RequestException("response exceeds safety byte limit")
            response._content = bytes(body)
            response._content_consumed = True
            return response
        except requests.RequestException:
            raise
        except (OSError, ValueError, AttributeError, HTTPError) as error:
            raise requests.RequestException(f"bounded response read failed: {error}") from error
        finally:
            response.close()


def fetch_url(url: str, timeout: int = 10, allow_redirects: bool = True, policy=None) -> Dict[str, Any]:
    """Fetch a page and return a mechanical evidence record for downstream skills."""
    try:
        from .network_policy import origin
        origin(url)
        if policy is None:
            raise requests.RequestException("fetch requires an established network/robots policy")
        current, redirects, seen = url, [], set()
        while True:
            if current in seen:
                raise requests.RequestException("redirect loop")
            seen.add(current)
            if policy is not None and not policy.admit(current):
                raise requests.RequestException("network policy blocked request")
            remaining = policy.time_left() if policy is not None else timeout
            if remaining <= 0:
                raise requests.RequestException("request stage deadline exhausted")
            response = request_once(current, timeout=min(timeout, remaining))
            if policy is not None:
                policy.observe_status(response.status_code)
            location = response.headers.get("Location") or response.headers.get("location")
            if response.status_code not in {301, 302, 303, 307, 308} or not location or not allow_redirects:
                break
            # No permission context means no permission to follow a redirect.
            if policy is None or len(redirects) >= 10:
                raise requests.RequestException("redirect requires policy or exceeds hop limit")
            destination = urljoin(current, location)
            redirects.append({"from": current, "to": destination, "status": response.status_code})
            current = destination
        # Decode before anything reads `.text`: `response.encoding` is what
        # requests inferred from headers alone, which is wrong for a page that
        # declares its charset in the document.
        body = getattr(response, "content", None)
        if isinstance(body, bytes):
            try:
                response.encoding = html_encoding(getattr(response, "headers", {}) or {}, body)
            except (LookupError, TypeError, AttributeError):
                pass
        final_url = getattr(response, "url", None) or url
        content_type = (response.headers or {}).get("Content-Type") or (response.headers or {}).get("content-type")
        encoding = getattr(response, "encoding", None) or "utf-8"
        elapsed = getattr(response, "elapsed", None)
        elapsed_ms = elapsed.total_seconds() * 1000 if elapsed is not None else None
        return {
            "url": url,
            "status_code": getattr(response, "status_code", None),
            "final_url": final_url,
            "redirect_chain": redirects,
            "headers": dict(getattr(response, "headers", {}) or {}),
            "encoding": encoding,
            "elapsed_ms": elapsed_ms,
            "evidence": {
                "status": "ok" if getattr(response, "status_code", 0) < 400 else "http_error",
                "content_type": content_type,
                "redirect_count": len(redirects),
                "final_url": final_url,
            },
            "html": getattr(response, "text", ""),
        }
    except (requests.RequestException, ValueError) as exc:
        return {
            "url": url,
            "status_code": None,
            "final_url": url,
            "redirect_chain": locals().get("redirects", []),
            "headers": {},
            "encoding": None,
            "elapsed_ms": None,
            "evidence": {"status": "error", "coverage_gap": True, "error": str(exc), "content_type": None, "redirect_count": len(locals().get("redirects", [])), "final_url": url},
            "html": "",
        }


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
