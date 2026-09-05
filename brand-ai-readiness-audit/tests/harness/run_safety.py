"""Real-browser adversarial checks, on a test-owned loopback server only.

Run separately from the offline suite: python tests/harness/run_safety.py.
Requires Playwright/Chromium and permission to bind a loopback socket.
"""
import sys
import faulthandler
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.common import public_transport
from lib.common.network_policy import RequestPolicy
from lib.site_observer.render import render_page


def main():
    seen = []
    scripts = {
        "/inline": "document.querySelector('h1').textContent='Rendered public answer';",
        "/fetch": "fetch('/side-effect').catch(()=>{});",
        "/post": "fetch('/side-effect', {method:'POST',body:'write'}).catch(()=>{});",
        "/form": "let f=document.createElement('form');f.action='/side-effect';f.method='GET';document.body.append(f);f.submit();",
        "/cookie": "document.cookie='session=secret'; let i=new Image();i.src='/asset.png';",
        "/private": "let i=new Image();i.src='/robots-denied';",
        "/external": "fetch('http://169.254.169.254/latest/meta-data/').catch(()=>{});",
        "/channels": "document.querySelector('h1').textContent = [typeof Worker,typeof SharedWorker,typeof RTCPeerConnection,typeof WebTransport,typeof EventSource,typeof navigator.sendBeacon].join(',');",
        "/socket": "new WebSocket('ws://'+location.host+'/side-effect');",
    }
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            seen.append((self.command, self.path, dict(self.headers)))
            script = scripts.get(self.path, "")
            body = ("<html><h1>Public</h1><script>" + script + "</script></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", "server_session=secret")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            seen.append((self.command, self.path, dict(self.headers)))
            self.send_response(200)
            self.end_headers()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    port = server.server_address[1]
    original = public_transport.public_address
    def resolver(host, target_port):
        return "127.0.0.1" if host == "127.0.0.1" and target_port == port else original(host, target_port)
    try:
        with patch.object(public_transport, "public_address", resolver):
            for path in scripts:
                faulthandler.dump_traceback_later(20, exit=True)
                print(f"Testing {path}", flush=True)
                seen.clear()
                url = f"http://127.0.0.1:{port}{path}"
                policy = RequestPolicy(url)
                policy.robots = {"status": "ok", "document": {"groups": [{"user_agent": "*", "disallow": ["/robots-denied"], "allow": []}]}}
                result = render_page(url, timeout_ms=5000, capability={"available": True}, policy=policy)
                assert seen, (path, result)  # No fake pass from a missing browser.
                assert all(method == "GET" and target in {path, "/asset.png"} for method, target, _ in seen), seen
                assert all(not any(key.lower() in {"cookie", "authorization", "proxy-authorization"} for key in headers) for _, _, headers in seen), seen
                if path == "/inline":
                    assert result["status"] == "ok" and "Rendered public answer" in result["html"], result
                elif path == "/channels":
                    # WebTransport in particular opens a QUIC channel that
                    # Playwright's page routes never observe, so the route
                    # allowlist below cannot be what blocks it.
                    assert "undefined," * 5 + "undefined" in result["html"], result
                elif path != "/cookie":
                    assert result["status"] == "error" and not result["html"], result
                print(f"PASS {path}", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    print("PASS: 9 real-browser safety scenarios")
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
