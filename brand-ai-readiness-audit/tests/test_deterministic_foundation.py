import json

import pytest

from lib.common.extract import (
    compare_raw_vs_rendered,
    extract_canonical_url,
    extract_jsonld,
    extract_links,
    extract_metadata,
    extract_text,
    page_inventory,
)
from lib.common import http_client
from lib.common.http_client import fetch_url, resolve_redirect_chain
from lib.common.observations import ObservationStore, make_observation
from lib.common.robots import fetch_robots, parse_robots, robots_allows
from lib.site_observer.render import detect_capability, render_page


class DummyResponse:
    def __init__(self, *, url, status_code=200, text="", headers=None, history=None, encoding="utf-8"):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.history = history or []
        self.encoding = encoding
        self.content = text.encode(encoding)


def test_fetch_url_collects_http_evidence(monkeypatch):
    def fake_get(url, timeout=10, allow_redirects=True, headers=None):
        assert headers == {"User-Agent": http_client.AUDIT_USER_AGENT}
        return DummyResponse(
            url=url,
            status_code=200,
            text='<html><head><title>Example</title></head><body><h1>Hello</h1></body></html>',
            headers={"content-type": "text/html; charset=utf-8"},
        )

    monkeypatch.setattr("requests.get", fake_get)

    result = fetch_url("https://example.com")

    assert result["status_code"] == 200
    assert result["final_url"] == "https://example.com"
    assert result["redirect_chain"] == []
    assert result["evidence"]["status"] == "ok"
    assert result["evidence"]["content_type"] == "text/html; charset=utf-8"


def test_resolve_redirect_chain_handles_multiple_hops():
    history = [
        DummyResponse(url="https://example.com/old", status_code=301, headers={"location": "https://example.com/new"}),
        DummyResponse(url="https://example.com/new", status_code=302, headers={"location": "https://example.com/final"}),
    ]

    chain = resolve_redirect_chain(history)

    assert chain == [
        {"from": "https://example.com/old", "to": "https://example.com/new", "status": 301},
        {"from": "https://example.com/new", "to": "https://example.com/final", "status": 302},
    ]


def test_fetch_robots_parses_permissions(monkeypatch):
    def fake_get(url, timeout=10, headers=None):
        assert headers == {"User-Agent": http_client.AUDIT_USER_AGENT}
        if url.endswith("/robots.txt"):
            return DummyResponse(
                url=url,
                status_code=200,
                text="User-agent: *\nDisallow: /private\nAllow: /public\nSitemap: https://example.com/sitemap.xml\n",
            )
        raise AssertionError("unexpected URL")

    monkeypatch.setattr("requests.get", fake_get)

    robots = fetch_robots("https://example.com")

    assert robots["status"] == "ok"
    assert robots["allow_all"] is False
    assert robots["document"]["sitemap"] == ["https://example.com/sitemap.xml"]
    assert robots_allows(robots, "/public") is True
    assert robots_allows(robots, "/private") is False


def test_parse_robots_handles_missing_and_unparseable_text():
    missing = parse_robots("")
    assert missing["status"] == "missing"
    assert missing["allow_all"] is True

    unparseable = parse_robots("this is not robots")
    assert unparseable["status"] == "unparseable"
    assert unparseable["allow_all"] is False


def test_extract_canonical_metadata_jsonld_and_links():
    html = """
    <html>
      <head>
        <title>Example title</title>
        <meta name="description" content="Example description">
        <meta property="og:title" content="Example social title">
        <link rel="canonical" href="https://example.com/canonical/page">
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"WebPage","name":"Example page","url":"https://example.com/canonical/page"}
        </script>
      </head>
      <body>
        <a href="/about">About</a>
        <a href="https://example.com/contact">Contact</a>
        <div>Visible content text here.</div>
      </body>
    </html>
    """

    canonical = extract_canonical_url(html, "https://example.com/start")
    meta = extract_metadata(html)
    jsonld = extract_jsonld(html)
    links = extract_links(html, base_url="https://example.com/start")
    text = extract_text(html)

    assert canonical == "https://example.com/canonical/page"
    assert meta["title"] == "Example title"
    assert meta["description"] == "Example description"
    assert jsonld[0]["@type"] == "WebPage"
    assert [link["href"] for link in links] == ["https://example.com/about", "https://example.com/contact"]
    assert "Visible content text here." in text


def test_page_inventory_and_raw_rendered_comparison_include_evidence():
    raw_html = "<html><body><h1>Page</h1><a href='/a'>A</a><img src='/img.png'><script>var x = 1;</script></body></html>"
    rendered_html = "<html><body><h1>Page</h1><a href='/a'>A</a><img src='/img.png'></body></html>"

    inventory = page_inventory(raw_html)
    comparison = compare_raw_vs_rendered(raw_html, rendered_html)

    assert inventory["link_count"] == 1
    assert inventory["image_count"] == 1
    assert inventory["script_count"] == 1
    assert comparison["evidence"]["raw_only_nodes"] == ["script"]
    assert comparison["evidence"]["rendered_only_nodes"] == []


def test_observation_store_generates_stable_ids_and_resolves_evidence():
    store = ObservationStore()
    obs = make_observation(
        "HTTP_FETCH",
        "https://example.com",
        {
            "status_code": 200,
            "final_url": "https://example.com",
            "redirect_chain": [],
            "evidence": {"status": "ok"},
        },
    )

    store.add(obs)

    assert obs["id"].startswith("OBS-HTTP-FETCH-")
    assert store.resolve(obs["id"]) == obs
    assert store.resolve("OBS-HTTP-FETCH-0000000000000000") is None


def test_detect_capability_reports_unavailable_when_playwright_not_installed(monkeypatch):
    monkeypatch.setattr("lib.site_observer.render.importlib.util.find_spec", lambda name: None)

    capability = detect_capability()

    assert capability == {"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"}


def test_render_page_records_coverage_gap_when_capability_unavailable():
    result = render_page("https://example.com", capability={"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"})

    assert result["status"] == "unavailable"
    assert result["html"] == ""
    assert result["final_url"] == "https://example.com"
    assert result["evidence"] == {
        "status": "coverage_gap",
        "check_id": "X-COV-01",
        "reason": "PLAYWRIGHT_NOT_INSTALLED",
    }


def test_render_page_returns_rendered_html_when_capability_available(monkeypatch):
    def fake_render(url, timeout_ms):
        return {
            "html": "<html><body><h1>Rendered</h1></body></html>",
            "final_url": "https://example.com/",
            "status_code": 200,
        }

    monkeypatch.setattr("lib.site_observer.render._render_with_playwright", fake_render)

    result = render_page("https://example.com", capability={"available": True, "reason": None})

    assert result["status"] == "ok"
    assert result["status_code"] == 200
    assert result["final_url"] == "https://example.com/"
    assert "<h1>Rendered</h1>" in result["html"]
    assert result["evidence"]["status"] == "ok"


def test_render_page_reports_error_without_raising_when_render_fails(monkeypatch):
    def fake_render(url, timeout_ms):
        raise TimeoutError("navigation timed out")

    monkeypatch.setattr("lib.site_observer.render._render_with_playwright", fake_render)

    result = render_page("https://example.com", capability={"available": True, "reason": None})

    assert result["status"] == "error"
    assert result["html"] == ""
    assert "navigation timed out" in result["evidence"]["error"]


def test_raw_vs_rendered_pipeline_flags_render_only_content():
    raw_html = "<html><body><h1>Shell</h1></body></html>"

    render_result = render_page(
        "https://example.com",
        capability={"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"},
    )
    assert render_result["status"] == "unavailable"

    rendered_html = "<html><body><h1>Shell</h1><p>Full article text.</p></body></html>"
    comparison = compare_raw_vs_rendered(raw_html, rendered_html)

    assert comparison["evidence"]["rendered_only_nodes"] == ["p"]
