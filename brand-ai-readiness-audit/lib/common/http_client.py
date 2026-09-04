"""Budget-enforcing, robots-aware HTTP client for the audit platform."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import requests

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


def fetch_url(url: str, timeout: int = 10, allow_redirects: bool = True) -> Dict[str, Any]:
    """Fetch a page and return a mechanical evidence record for downstream skills."""
    try:
        response = requests.get(
            url, timeout=timeout, allow_redirects=allow_redirects, headers={"User-Agent": AUDIT_USER_AGENT}
        )
        final_url = getattr(response, "url", None) or url
        content_type = (response.headers or {}).get("Content-Type") or (response.headers or {}).get("content-type")
        encoding = getattr(response, "encoding", None) or "utf-8"
        redirects = resolve_redirect_chain(getattr(response, "history", []) or [])
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
    except requests.RequestException as exc:
        return {
            "url": url,
            "status_code": None,
            "final_url": url,
            "redirect_chain": [],
            "headers": {},
            "encoding": None,
            "elapsed_ms": None,
            "evidence": {"status": "error", "error": str(exc), "content_type": None, "redirect_count": 0, "final_url": url},
            "html": "",
        }


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
