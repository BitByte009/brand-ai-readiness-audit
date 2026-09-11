"""Reproducible CPU-only or loopback-browser runtime audit; never hits live sites.

--baseline disables only the new parse cache and browser-process reuse.
Timing includes cProfile overhead equally in both modes. No timing assertion is
made in unit tests; correctness is checked separately against the fixture corpus.
"""
import argparse
from collections import Counter
import cProfile
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "skills/audit-orchestrator/scripts"), str(Path(__file__).parent)]
import run_audit
from fixture_server import FixtureServer
from lib.common.extract import parse_cache
from lib.common import public_transport
from lib.common.network_policy import RequestPolicy


def static_input():
    urls = ["https://example.com/"] + [f"https://example.com/page/{n}" for n in range(29)]
    links = "".join(f'<a href="{url}">Details</a>' for url in urls)
    body = "<p>Example Organization provides research services. Contact info@example.com for details about our work.</p>" * 150
    pages = {url: "<html><title>Example Organization</title><h1>Research services</h1>" + links + body + f"<p>{url}</p></html>" for url in urls}
    return urls[0], dict(fetch=lambda url: {"status_code": 200, "final_url": url, "html": pages[url]},
        robots_fetcher=lambda _: {"status": "missing"}, render_capability={"available": False}, sleep=lambda _: None)


def measure(url, options, baseline):
    requests = Counter()
    original_admit = RequestPolicy.admit
    def admit(self, target, method="GET", **kwargs):
        allowed = original_admit(self, target, method, **kwargs)
        if allowed:
            parsed = urlsplit(target)
            requests[f"{method} {parsed.path}?{parsed.query}"] += 1
        return allowed
    collector = run_audit.collect.__wrapped__ if baseline else run_audit.collect
    profiler = cProfile.Profile()
    with patch.object(RequestPolicy, "admit", admit), patch.object(run_audit, "collect", collector), parse_cache(max_chars=0 if baseline else 1_048_576):
        start = time.perf_counter()
        profiler.enable()
        report = run_audit.run_audit(url, **options)
        profiler.disable()
        elapsed = time.perf_counter() - start
    stats = profiler.getstats()
    parses = sum(s.callcount for s in stats if not isinstance(s.code, str)
                 and s.code.co_name == "__init__" and s.code.co_filename.endswith("bs4/__init__.py"))
    return {"baseline": baseline, "python": platform.python_version(), "machine": platform.machine(),
        "elapsed_s": round(elapsed, 3), "html_parses": parses, "scope": report["scope"],
        "budget": report["run"]["budget"], "repeated_admitted_requests": {k: v for k, v in sorted(requests.items()) if v > 1},
        "summary": report["summary"], "check_ids": sorted(f["check_id"] for f in report["findings"]),
        "skill_failures": report["run"]["skill_failures"], "schema_valid": report["run"]["schema_valid"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--fixture", choices=sorted(p.name for p in (ROOT / "tests/fixtures").iterdir() if p.is_dir()))
    args = parser.parse_args()
    if args.fixture:
        with FixtureServer(ROOT / "tests/fixtures" / args.fixture) as server:
            from lib.common import public_transport
            fixture_url = server.base_url() + "/"
            fixture_port = urlsplit(fixture_url).port
            original_resolver = public_transport.public_address
            def fixture_address(host, port):
                if host == "127.0.0.1" and port == fixture_port:
                    return host
                return original_resolver(host, port)
            with patch.object(public_transport, "public_address", fixture_address):
                result = measure(fixture_url, {}, args.baseline)
    else:
        url, options = static_input()
        result = measure(url, options, args.baseline)
    print(json.dumps(result, indent=2))
    if result["scope"]["pages_crawled"] == 0:
        print("WARNING: zero pages crawled -- this is not a runtime measurement.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
