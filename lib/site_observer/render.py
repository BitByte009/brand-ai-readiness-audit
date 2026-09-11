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
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Dict, Optional

_BROWSER_SESSION = ContextVar("audit_browser_session", default=None)


def reuse_browser(function):
    """Reuse only the process within a collection pass, never page state."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with ExitStack() as stack:
            token = _BROWSER_SESSION.set({"stack": stack, "browser": None})
            try:
                return function(*args, **kwargs)
            finally:
                _BROWSER_SESSION.reset(token)
    return wrapped


@contextmanager
def _browser_instance():
    from playwright.sync_api import sync_playwright
    state = _BROWSER_SESSION.get()
    if state is None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(chromium_sandbox=True)
            try:
                yield browser
            finally:
                browser.close()
    else:
        if state["browser"] is None:
            playwright = state["stack"].enter_context(sync_playwright())
            browser = playwright.chromium.launch(chromium_sandbox=True)
            state["stack"].callback(browser.close)
            state["browser"] = browser
        yield state["browser"]


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
        with _browser_instance():
            pass
    except Exception as exc:
        return {"available": False, "reason": f"BROWSER_LAUNCH_FAILED: {exc}"}

    return {"available": True, "reason": None}


def _render_with_playwright(url: str, timeout_ms: int, policy=None) -> Dict[str, Any]:
    """Navigate to `url` in a headless browser and return the rendered DOM.

    Isolated from `render_page` so tests can monkeypatch this single seam
    instead of depending on a real browser being installed.
    """
    from lib.common.http_client import AUDIT_USER_AGENT, request_once, MAX_RESPONSE_BYTES

    if policy is None:
        raise ValueError("Rendering requires an established network/robots policy")
    blocked_before = len(policy.blocked)

    with _browser_instance() as browser:
        context = browser.new_context(user_agent=AUDIT_USER_AGENT, service_workers="block", accept_downloads=False)
        try:
            # No active network outside the routed HTTP transport. In particular
            # WebRTC and workers can create channels not covered by page routes.
            context.add_init_script("""(() => {
              for (const name of ['Worker', 'SharedWorker', 'RTCPeerConnection', 'webkitRTCPeerConnection']) {
                Object.defineProperty(globalThis, name, {value: undefined, configurable: false, writable: false});
              }
            })();""")
            navigated = False
            def route_request(route):
                nonlocal navigated
                request = route.request
                reason = None
                if any(key.lower() in {"authorization", "proxy-authorization"} for key in request.headers):
                    reason = "authorization"
                elif request.resource_type == "document":
                    if navigated or request.url != url:
                        reason = "secondary_navigation_or_form"
                    navigated = True
                elif request.resource_type not in {"script", "stylesheet", "image", "font"}:
                    reason = "active_background_request"
                if reason or not policy.admit(request.url, request.method):
                    if reason:
                        policy.blocked.append({"url": request.url, "reason": reason})
                    route.abort()
                    return
                # Never use the browser cookie jar, request body, custom headers,
                # or ambient browser authentication. Responses cannot set cookies.
                try:
                    response = request_once(request.url, timeout=min(timeout_ms / 1000, policy.time_left()))
                except Exception:
                    policy.blocked.append({"url": request.url, "reason": "resource_transport_failure"})
                    route.abort()
                    return
                policy.observe_status(response.status_code)
                if 300 <= response.status_code < 400 or response.status_code in {401, 403, 407}:
                    policy.blocked.append({"url": request.url, "reason": "render_redirect"})
                    route.abort()
                else:
                    # Do not propagate Set-Cookie, Refresh, or hop-by-hop headers.
                    headers = {key: value for key, value in response.headers.items()
                               if key.lower() in {"content-type", "content-security-policy", "x-content-type-options"}}
                    route.fulfill(status=response.status_code, headers=headers, body=response.content)
            context.route("**/*", route_request)
            def block_socket(socket):
                policy.blocked.append({"url": socket.url, "reason": "websocket"})
                # An intercepted socket is local-only unless connect_to_server
                # is called. Do not synchronously close it from the route callback:
                # that can deadlock the driver; context teardown disposes it.
            context.route_web_socket("**/*", block_socket)
            page = context.new_page()
            response = page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            html = page.content()
            measurements = page.evaluate('''() => {
              const visible = e => {
                const s = getComputedStyle(e), r = e.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0
                  && r.width > 0 && r.height > 0;
              };
              let blocking_overlay = null;
              for (const e of document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog[open], [class*="modal"], [class*="overlay"]')) {
                if (!visible(e)) continue;
                const r = e.getBoundingClientRect();
                const w = Math.max(0, Math.min(r.right,innerWidth)-Math.max(r.left,0));
                const h = Math.max(0, Math.min(r.bottom,innerHeight)-Math.max(r.top,0));
                const top = document.elementFromPoint(innerWidth/2,innerHeight/2);
                if (w*h/(innerWidth*innerHeight) > 0.3 && top && e.contains(top)) {
                  blocking_overlay = {tag:e.tagName.toLowerCase(), role:e.getAttribute('role')||'',
                    class:e.className.toString(), id:e.id}; break;
                }
              }
              const blocks = [...document.querySelectorAll('main p, article p, [role="main"] p')].slice(0,150)
                .map(e=>({text:e.textContent.trim(), top:e.getBoundingClientRect().top, visible:visible(e)}));
              return {viewport_height:innerHeight, viewport_width:innerWidth, blocking_overlay, blocks};
            }''') if hasattr(page, 'evaluate') else None
            if len(html.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError("Rendered DOM exceeds safety byte limit")
            final_url = page.url
            status_code = response.status if response else None
        finally:
            context.close()

    if len(policy.blocked) > blocked_before:
        raise ValueError("Render incomplete: network policy blocked resources")
    result = {"html": html, "final_url": final_url, "status_code": status_code}
    if measurements is not None:
        result['measurements'] = measurements
    return result


def render_page(
    url: str,
    timeout_ms: int = 15000,
    capability: Optional[Dict[str, Any]] = None,
    policy=None,
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
        result = _render_with_playwright(url, timeout_ms, policy=policy)
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
        **({'measurements': result['measurements']} if 'measurements' in result else {}),
        "evidence": {"status": "ok", "final_url": final_url},
    }


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
