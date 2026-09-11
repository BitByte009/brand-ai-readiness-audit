"""Loopback static HTTP server for the fixture corpus.

Serves a fixture's `site/` directory as-is (real files, real HTTP semantics)
so the marketplace's real HTTP client, robots parser and crawler run
unmodified against it -- no fetch/robots injection seams, no mocking. An
optional `server_config.json` at the fixture root lets a fixture script a
handful of paths that plain static files cannot express (a 5xx robots.txt, a
redirect chain, a noindex header, a wrong content-type, a fake bot-challenge
page) without hand-rolling a server per fixture.

`server_config.json` shape:
    {"overrides": {"/path": {"status": 500, "headers": {...}, "body": "..."}}}

Any path not listed falls through to normal static file serving.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional


def _load_overrides(site_root: Path) -> Dict[str, Dict[str, Any]]:
    config_path = site_root.parent / "server_config.json"
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return data.get("overrides", {})


def _make_handler(site_root: Path, overrides: Dict[str, Dict[str, Any]]):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site_root), **kwargs)

        def _override_for(self, path: str) -> Optional[Dict[str, Any]]:
            clean = path.split("?", 1)[0]
            return overrides.get(clean)

        def _send_override(self, override: Dict[str, Any], head_only: bool) -> None:
            status = override.get("status", 200)
            body = str(override.get("body", "")).encode("utf-8")
            headers = dict(override.get("headers", {}))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            if "Content-Length" not in headers:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib signature
            override = self._override_for(self.path)
            if override is not None:
                self._send_override(override, head_only=False)
                return
            super().do_GET()

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib signature
            override = self._override_for(self.path)
            if override is not None:
                self._send_override(override, head_only=True)
                return
            super().do_HEAD()

        def send_header(self, keyword: str, value: str) -> None:  # noqa: N802 - stdlib signature
            # SimpleHTTPRequestHandler sends a real Last-Modified (and ETag)
            # derived from the fixture file's on-disk mtime -- effectively
            # "today" for every file in this corpus. That is itself a valid
            # HTTP freshness signal (lib/site_observer's HTTP_FETCH.headers,
            # read by trust-freshness-audit's date inventory), so left alone
            # it silently and uniformly suppresses D-TRUST-01/02c sitewide
            # regardless of fixture content -- confirmed while authoring
            # stale-content. Fixtures should be driven only by the HTML/HTTP
            # content actually authored, not by filesystem incidentals, so
            # both headers are dropped here for every response.
            if keyword in ("Last-Modified", "ETag"):
                return
            super().send_header(keyword, value)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            pass

    return Handler


class FixtureServer:
    """Context manager: starts a threaded server on an ephemeral loopback
    port serving `fixture_dir/site`, stops it on exit."""

    def __init__(self, fixture_dir: Path, host: str = "127.0.0.1") -> None:
        self.site_root = fixture_dir / "site"
        self.overrides = _load_overrides(self.site_root)
        self.host = host
        self._httpd: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "FixtureServer":
        handler = _make_handler(self.site_root, self.overrides)
        self._httpd = http.server.ThreadingHTTPServer((self.host, 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()

    @property
    def port(self) -> int:
        assert self._httpd is not None
        return self._httpd.server_address[1]

    def base_url(self, host_override: Optional[str] = None) -> str:
        host = host_override or self.host
        return f"http://{host}:{self.port}"
