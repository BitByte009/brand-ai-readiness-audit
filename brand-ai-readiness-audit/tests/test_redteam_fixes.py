"""Regression cases from the independent red-team review; no live network."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for path in (ROOT / "skills").glob("*/scripts"):
    sys.path.insert(0, str(path))

from lib.common.robots import parse_robots, robots_allows
from lib.site_observer.collect import collect
import run_audit
from types import SimpleNamespace
from lib.common.network_policy import RequestPolicy
from lib.common import http_client


def policy(**kwargs):
    result = RequestPolicy("https://example.com/", sleep=lambda _: None, **kwargs)
    result.robots = parse_robots("User-agent: *\nDisallow: /private")
    return result


@pytest.mark.parametrize("url,method", [
    ("https://other.example/", "GET"),
    ("https://example.com/private", "GET"),
    ("https://example.com/", "POST"),
    ("https://user:secret@example.com/", "GET"),
    ("file:///etc/passwd", "GET"),
])
def test_network_boundary_denies_before_request(url, method):
    guard = policy()
    assert not guard.admit(url, method)
    assert guard.requests == 0


def test_shared_budget_and_server_backoff():
    guard = policy(max_requests=1)
    assert guard.admit("https://example.com/")
    assert not guard.admit("https://example.com/next")
    for status in (429, 503):
        guard = policy()
        guard.observe_status(status)
        assert not guard.admit("https://example.com/")


def test_request_disables_ambient_credentials_and_redirects(monkeypatch):
    class Session:
        trust_env = True
        def mount(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs["allow_redirects"] is False
            assert kwargs["headers"]["User-Agent"] == http_client.AUDIT_USER_AGENT
            assert kwargs["stream"] is True
            return SimpleNamespace(headers={}, raw=SimpleNamespace(read1=lambda *a, **k: b""), close=lambda: None)
    monkeypatch.setattr(http_client.requests, "Session", Session)
    assert http_client.request_once("https://example.com/")._content == b""


@pytest.mark.parametrize("destination,allowed", [("/public", True), ("/private", False), ("https://other.example/", False)])
def test_each_redirect_is_authorized_before_fetch(monkeypatch, destination, allowed):
    calls = []
    def once(url, timeout):
        calls.append(url)
        return SimpleNamespace(url=url, status_code=302 if len(calls) == 1 else 200,
                               headers={"Location": destination} if len(calls) == 1 else {}, text="ok")
    monkeypatch.setattr(http_client, "request_once", once)
    result = http_client.fetch_url("https://example.com/", policy=policy())
    assert len(calls) == (2 if allowed else 1)
    assert result["evidence"]["redirect_count"] == 1
    assert result["evidence"]["status"] == ("ok" if allowed else "error")


def test_browser_requests_are_intercepted_and_partial_dom_is_rejected(monkeypatch):
    from lib.site_observer import render
    callbacks, actions = {}, []
    guard = policy()
    class Context:
        def close(self): pass
        def add_init_script(self, script): assert "RTCPeerConnection" in script
        def route(self, pattern, callback): callbacks["http"] = callback
        def route_web_socket(self, pattern, callback): callbacks["socket"] = callback
        def new_page(self): return self
        def goto(self, *args, **kwargs):
            for url, method in [("https://example.com/", "GET"), ("https://example.com/private", "GET"),
                                ("https://example.com/", "POST"), ("https://other.example/", "GET")]:
                route = SimpleNamespace(request=SimpleNamespace(url=url, method=method, headers={}, resource_type="document" if url == "https://example.com/" and method == "GET" else "image"),
                    abort=lambda: actions.append("abort"), fulfill=lambda **kw: actions.append("fulfill"),
                    fetch=self.fetch)
                callbacks["http"](route)
            callbacks["socket"](SimpleNamespace(url="wss://example.com/", close=lambda: actions.append("socket_closed")))
            return SimpleNamespace(status=200)
        def fetch(self, **kwargs):
            assert kwargs["max_redirects"] == 0 and kwargs["max_retries"] == 0
            return SimpleNamespace(status=200)
        def content(self): return "<h1>Incomplete</h1>"
        url = "https://example.com/"
    class Browser:
        def new_context(self, **kwargs):
            assert kwargs["service_workers"] == "block"
            assert kwargs["user_agent"] == http_client.AUDIT_USER_AGENT
            assert kwargs["accept_downloads"] is False
            return Context()
        def close(self): actions.append("browser_closed")
    class Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: Browser())
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(sync_playwright=Playwright))
    monkeypatch.setattr(http_client, "request_once", lambda *a, **k: SimpleNamespace(status_code=200, headers={}, content=b"public"))
    result = render.render_page("https://example.com/", capability={"available": True}, policy=guard)
    assert actions == ["fulfill", "abort", "abort", "abort", "browser_closed"]
    assert any(item["reason"] == "websocket" for item in guard.blocked)
    assert guard.requests == 1
    assert result["status"] == "error" and result["html"] == ""


@pytest.mark.parametrize("text,path,allowed", [
    ("User-agent: brand-ai-readiness-audit\nDisallow: /", "/private", False),
    ("User-agent: *\nAllow: /\nDisallow: /private", "/private", False),
    ("User-agent: *\nDisallow: /*.pdf$", "/secret.pdf", False),
    ("User-agent: *\nDisallow: /*.pdf$", "/secret.pdf.html", True),
    ("User-agent: *\nDisallow: /private # comment", "/private", False),
    ("User-agent: *\nUser-agent: OtherBot\nDisallow: /private", "/private", False),
    ("User-agent: GPTBot\nDisallow: /", "/", True),
    ("User-agent: *\nDisallow: /\nUser-agent: brand-ai-readiness-audit\nAllow: /", "/", True),
    ("User-agent: *\nAllow: /same\nDisallow: /same", "/same", True),
    ("User-agent: *\nDisallow: /read?id=42", "/read?id=42", False),
    ("User-agent: *\nDisallow: /caf%C3%A9", "/café", False),
    ("User-agent: *\nDisallow: /private", "/%70rivate", False),
])
def test_robots_protocol_counterexamples(text, path, allowed):
    assert robots_allows(parse_robots(text), path) is allowed


def audit_with_robots(text, url="https://example.com/", calls=None):
    calls = calls if calls is not None else []
    def fetch(target):
        calls.append(target)
        return {"status_code": 200, "html": "<h1>Public</h1>", "final_url": target}
    return run_audit.run_audit(url, robots_fetcher=lambda _: {"url": "https://example.com/robots.txt", **parse_robots(text)},
        fetch=fetch, render_capability={"available": False}, sleep=lambda _: None)


def test_allowed_deep_exception_is_crawled():
    calls = []
    audit_with_robots("User-agent: *\nDisallow: /\nAllow: /public", "https://example.com/public", calls)
    assert calls == ["https://example.com/public"]


def test_disallowed_seed_is_reported_without_fetching():
    calls = []
    report = audit_with_robots("User-agent: *\nDisallow: /", calls=calls)
    assert calls == []
    assert any(f["check_id"] == "D-CRAWL-01" for f in report["findings"])


@pytest.mark.parametrize("status", [None, 301, 401, 403, 404, 429, 500, 503])
def test_failed_pages_do_not_generate_content_findings(status):
    report = run_audit.run_audit("https://example.com/", robots_fetcher=lambda _: parse_robots(""),
        fetch=lambda url: {"status_code": status, "html": "<h1>Access denied</h1>", "final_url": url},
        render_capability={"available": False}, sleep=lambda _: None)
    assert not report["run"].get("skill_failures")
    assert not any(f["check_id"].startswith(("D-ENTITY-", "D-TRUST-", "E-")) for f in report["findings"])


def test_successful_render_http_error_falls_back_to_valid_raw_evidence():
    from lib.common.observations import make_observation
    from lib.common.pages import effective_pages
    url = "https://example.com/"
    raw = make_observation("HTTP_FETCH", url, {"status_code": 200, "html": "<h1>Real content</h1>"})
    rendered = make_observation("RENDER", url, {"status": "ok", "status_code": 403, "html": "<h1>Denied</h1>"})
    selected = effective_pages({"observations": [raw, rendered]})[url]
    assert selected["observation_id"] == raw["id"] and selected["rendered"] is False


def test_crawl_delay_exceeding_remaining_stage_budget_does_not_sleep():
    sleeps = []
    guard = policy(clock=lambda: 0)
    guard.sleep = sleeps.append
    guard.delay = 3600
    guard.time_left = lambda: 90
    assert guard.admit("https://example.com/")
    assert not guard.admit("https://example.com/next")
    assert sleeps == [] and guard.blocked[-1]["reason"] == "stage_time_budget"


def test_markdown_keeps_action_details_and_validation():
    import render_report
    markdown = render_report.render_markdown({"findings": [{"severity": "high", "confidence": "medium",
        "affected": {"count": 1, "total_in_scope": 10}, "suggested_action": {
            "summary": "Restore access", "how_to_fix": "Remove the conflicting origin ACL.",
            "validation": "Repeat an unauthenticated GET and verify HTTP 200."}}]})
    assert "Remove the conflicting origin ACL." in markdown
    assert "Repeat an unauthenticated GET and verify HTTP 200." in markdown
    assert "Confidence: medium" in markdown and "1 of 10" in markdown


def test_root_denial_is_not_proof_of_blanket_denial():
    from lib.common.robots import is_disallow_all
    assert is_disallow_all(parse_robots("User-agent: *\nDisallow: /"))
    assert not is_disallow_all(parse_robots("User-agent: *\nDisallow: /$"))
    assert not is_disallow_all(parse_robots("User-agent: *\nDisallow: /\nAllow: /public"))


def test_robots_redirect_is_not_implicitly_followed(monkeypatch):
    from lib.common import robots
    calls = []
    def once(url, timeout):
        calls.append(url)
        return SimpleNamespace(status_code=302, headers={"Location": "https://other.example/robots.txt"})
    monkeypatch.setattr(robots, "request_once", once)
    result = robots.fetch_robots("https://example.com/", policy=policy())
    assert result["status"] == "error" and len(calls) == 1


def test_grouped_crawl_delay_is_retained():
    groups = parse_robots("User-agent: *\nUser-agent: OtherBot\nCrawl-delay: 3\nDisallow: /private")["document"]["groups"]
    assert [g["crawl_delay"] for g in groups] == [3, 3]


def test_politeness_waits_only_remaining_interval():
    guard = policy(clock=lambda: 0)
    sleeps = []
    guard.sleep = sleeps.append
    guard.delay = 3
    assert guard.admit("https://example.com/")
    guard.clock = lambda: 1
    assert guard.admit("https://example.com/next")
    assert sleeps == [2]
