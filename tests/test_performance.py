"""Operation-count and semantic regressions, deliberately not flaky time limits."""
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "skills/audit-orchestrator/scripts")]
from lib.common import extract
from lib.site_observer import render
import run_audit


def test_parse_once_preserves_metadata_text_links_and_structured_data(monkeypatch):
    calls = []
    original = extract.BeautifulSoup
    def parse(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(extract, "BeautifulSoup", parse)
    html = '<title>Example</title><link rel="canonical" href="/canonical"><h1>Answer</h1><a rel="nofollow" href="/details">Read</a><script type="application/ld+json">{"@type":"Organization","name":"Example"}</script>'
    with extract.parse_cache():
        assert extract.extract_metadata(html)["canonical"] == "/canonical"
        assert "Answer" in extract.extract_text(html)
        first = extract.extract_links(html, "https://a.example/")
        first[0]["rel"].append("mutated")
        assert extract.extract_links(html, "https://b.example/")[0] == {"href": "https://b.example/details", "text": "Read", "rel": ["nofollow"]}
        nodes = extract.extract_jsonld(html)
        nodes[0]["name"] = "mutated"
        assert extract.extract_jsonld(html)[0]["name"] == "Example"
        assert extract.page_inventory(html)["heading_count"] == 1
        assert len(calls) == 1
    assert extract._PARSE_CACHE.get() is None
    extract.extract_text(html)
    assert len(calls) == 2


def test_parse_cache_bounds_and_oversized_pages_do_not_truncate(monkeypatch):
    calls = []
    original = extract.BeautifulSoup
    monkeypatch.setattr(extract, "BeautifulSoup", lambda *args, **kwargs: (calls.append(args[0]), original(*args, **kwargs))[1])
    with extract.parse_cache(max_chars=20, max_entries=1):
        for html in ("<p>A</p>", "<p>B</p>", "<p>A</p>"):
            extract.extract_text(html)
        large = "<p>" + "long content " * 100 + "TAIL</p>"
        assert extract.extract_text(large).endswith("TAIL")
        assert extract.extract_text(large).endswith("TAIL")
        assert len(calls) == 5
        state = extract._PARSE_CACHE.get()
        assert state["chars"] <= 20 and len(state["trees"]) <= 1


@pytest.mark.parametrize("fixture", ["both-weak", "invalid-structured-data", "stale-content", "unusual-site-structure"])
def test_cached_audit_is_identical_to_uncached_audit(fixture):
    fixture_path = ROOT / "tests/fixtures" / fixture / "site"
    # Serve file content through the normal collector without sockets/rendering.
    def fetch(url):
        from urllib.parse import urlsplit
        path = fixture_path / urlsplit(url).path.lstrip("/")
        if path.is_dir(): path = path / "index.html"
        return {"status_code": 200 if path.is_file() else 404, "final_url": url,
                "html": path.read_text() if path.is_file() else "Not found"}
    kwargs = dict(fetch=fetch, robots_fetcher=lambda _: {"status": "missing"}, render_capability={"available": False},
        sleep=lambda _: None, now=lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    with extract.parse_cache(max_chars=0):
        uncached = run_audit.run_audit("https://example.com/", **kwargs)
    cached = run_audit.run_audit("https://example.com/", **kwargs)
    # Runtime telemetry varies; detection, evidence and ranking must not.
    assert cached["run"].pop("elapsed_s") >= 0
    assert uncached["run"].pop("elapsed_s") >= 0
    assert cached == uncached
    assert cached["findings"], "The equivalence case must exercise real detections"
    assert not cached["run"]["skill_failures"]


def test_browser_process_reused_but_contexts_closed_and_isolated(monkeypatch):
    actions, contexts = [], []
    class Context:
        url = "https://example.com/"
        def add_init_script(self, *args): pass
        def route(self, *args): pass
        def route_web_socket(self, *args): pass
        def new_page(self): return self
        def goto(self, *args, **kwargs): return SimpleNamespace(status=200)
        def content(self): return "<h1>Rendered answer</h1>"
        def close(self): actions.append("context_closed")
    class Browser:
        def new_context(self, **kwargs):
            assert kwargs["service_workers"] == "block"
            context = Context()
            contexts.append(context)
            return context
        def close(self): actions.append("browser_closed")
    def launch(**kwargs):
        assert kwargs["chromium_sandbox"] is True
        actions.append("launch")
        return Browser()
    class Playwright:
        chromium = SimpleNamespace(launch=launch)
        def __enter__(self): return self
        def __exit__(self, *args): actions.append("driver_closed")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(sync_playwright=Playwright))
    @render.reuse_browser
    def collection():
        with render._browser_instance(): pass  # capability preflight
        for _ in range(2):
            result = render.render_page("https://example.com/", capability={"available": True}, policy=SimpleNamespace(blocked=[]))
            assert result["status"] == "ok" and "Rendered answer" in result["html"]
        raise ValueError("collection failure")
    with pytest.raises(ValueError): collection()
    assert actions == ["launch", "context_closed", "context_closed", "browser_closed", "driver_closed"]
    assert contexts[0] is not contexts[1]
    assert render._BROWSER_SESSION.get() is None


def test_redirect_timeouts_shrink_with_remaining_stage(monkeypatch):
    from lib.common import http_client
    from lib.common.network_policy import RequestPolicy
    clock, timeouts = [0], []
    policy = RequestPolicy("https://example.com/", clock=lambda: clock[0], sleep=lambda _: None, delay=0)
    policy.robots = {"status": "missing"}
    policy.time_left = lambda: 5 - clock[0]
    def once(url, timeout):
        timeouts.append(timeout)
        clock[0] += 4 if len(timeouts) == 1 else 0
        return SimpleNamespace(url=url, status_code=302 if len(timeouts) == 1 else 200,
            headers={"Location": "/next"} if len(timeouts) == 1 else {}, text="content")
    monkeypatch.setattr(http_client, "request_once", once)
    result = http_client.fetch_url("https://example.com/", policy=policy)
    assert timeouts == [5, 1] and result["status_code"] == 200


def test_collector_does_not_double_sleep_after_slow_fetches(monkeypatch):
    from lib.site_observer import collect as collector
    from lib.common.network_policy import RequestPolicy
    from lib.common.budget import Budget
    clock, sleeps = [0], []
    policy = RequestPolicy("https://example.com/", clock=lambda: clock[0], sleep=sleeps.append)
    monkeypatch.setattr(collector, "RequestPolicy", lambda *a, **kw: policy)
    def fetch(url, policy, timeout):
        assert policy.admit(url)
        clock[0] += 1  # response already took longer than the polite interval
        return {"status_code": 200, "final_url": url, "html": '<h1>Answer</h1><a href="/next">Next</a>'}
    monkeypatch.setattr(collector, "fetch_url", fetch)
    result = collector.collect("https://example.com/", budget=Budget(clock=lambda: clock[0]),
        robots_fetcher=lambda _: {"status": "missing"}, render_capability={"available": False}, sleep=sleeps.append)
    assert result["scope"]["pages_crawled"] == 2 and policy.requests == 3  # includes sitemap discovery
    assert sum(sleeps) == 0


def test_render_timeout_uses_remaining_stage_without_dropping_sample(monkeypatch):
    from lib.site_observer.collect import collect
    from lib.common.budget import Budget
    timeouts = []
    def fake_render(url, timeout_ms, **kwargs):
        timeouts.append(timeout_ms)
        return {"status": "ok", "status_code": 200, "html": "<h1>Rendered answer</h1>"}
    monkeypatch.setattr(render, "render_page", fake_render)
    result = collect("https://example.com/", budget=Budget({"render_sample_s": 2}, clock=lambda: 0),
        robots_fetcher=lambda _: {"status": "missing"},
        fetch=lambda url: {"status_code": 200, "html": '<a href="/next">Next</a>', "final_url": url},
        render_capability={"available": True}, sleep=lambda _: None)
    assert timeouts == [2000, 2000]
    assert result["scope"]["pages_rendered"] == 2


def test_collector_honors_configured_http_timeout(monkeypatch):
    from lib.common import http_client
    from lib.common.budget import Budget
    from lib.site_observer.collect import collect
    timeouts = []
    def once(url, timeout):
        timeouts.append(timeout)
        return SimpleNamespace(url=url, status_code=200, headers={}, text="<h1>Answer</h1>")
    monkeypatch.setattr(http_client, "request_once", once)
    collect("https://example.com/", budget=Budget({"raw_crawl_timeout_s": 0.25}),
        robots_fetcher=lambda _: {"status": "missing"}, render_capability={"available": False})
    assert timeouts == [0.25, 0.25]  # sitemap and page share the configured limit
