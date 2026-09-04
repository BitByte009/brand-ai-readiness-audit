"""Rendered lens. Capability-detected; absent a renderer this records
RENDERER_UNAVAILABLE rather than failing.

Inputs:  sampled urls
Outputs: rendered html, mechanical evidence record
Nature:  deterministic, optional capability

The actual browser automation is isolated behind two seams
(`detect_capability` and `_render_with_playwright`) so callers, and tests, can
substitute a fake without a real browser being installed. `render_page` never
raises: every outcome - success, capability absent, or a runtime error - comes
back as a structured evidence record so a missing renderer degrades to a
coverage gap instead of crashing the observation pass.
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, Optional


def detect_capability() -> Dict[str, Any]:
    """Detect whether a headless renderer is usable in this environment.

    Checked in order: is `playwright` importable, does the sync API import
    cleanly, can a chromium instance actually launch. Any failure is reported
    as an unavailable capability with a machine-readable reason rather than
    raised, since this runs once per audit before any render is attempted.
    """
    if importlib.util.find_spec("playwright") is None:
        return {"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"}

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - import failure path
        return {"available": False, "reason": f"PLAYWRIGHT_IMPORT_ERROR: {exc}"}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
    except Exception as exc:
        return {"available": False, "reason": f"BROWSER_LAUNCH_FAILED: {exc}"}

    return {"available": True, "reason": None}


def _render_with_playwright(url: str, timeout_ms: int) -> Dict[str, Any]:
    """Navigate to `url` in a headless browser and return the rendered DOM.

    Isolated from `render_page` so tests can monkeypatch this single seam
    instead of depending on a real browser being installed.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            response = page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            html = page.content()
            final_url = page.url
            status_code = response.status if response else None
        finally:
            browser.close()

    return {"html": html, "final_url": final_url, "status_code": status_code}


def render_page(
    url: str,
    timeout_ms: int = 15000,
    capability: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Render a page and return a mechanical evidence record.

    Never raises. Three possible outcomes, each shaped the same way as
    `lib.common.http_client.fetch_url` for symmetry across lenses:
    - capability absent -> status "unavailable", an X-COV-01 evidence record
    - render attempted but failed -> status "error", the exception recorded
    - render succeeded -> status "ok", rendered html and final url
    """
    capability = capability if capability is not None else detect_capability()

    if not capability.get("available"):
        reason = capability.get("reason", "RENDERER_UNAVAILABLE")
        return {
            "url": url,
            "status": "unavailable",
            "reason": reason,
            "final_url": url,
            "status_code": None,
            "html": "",
            "evidence": {"status": "coverage_gap", "check_id": "X-COV-01", "reason": reason},
        }

    try:
        result = _render_with_playwright(url, timeout_ms)
    except Exception as exc:
        return {
            "url": url,
            "status": "error",
            "reason": str(exc),
            "final_url": url,
            "status_code": None,
            "html": "",
            "evidence": {"status": "error", "error": str(exc)},
        }

    final_url = result.get("final_url", url)
    return {
        "url": url,
        "status": "ok",
        "reason": None,
        "final_url": final_url,
        "status_code": result.get("status_code"),
        "html": result.get("html", ""),
        "evidence": {"status": "ok", "final_url": final_url},
    }


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
