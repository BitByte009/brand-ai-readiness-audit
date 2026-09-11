"""Budget-enforcing, robots-aware HTTP client for the audit platform."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin
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
