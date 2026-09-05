"""Conservative per-audit network boundary shared by HTTP and browser lenses.

Cross-origin requests are not authorized implicitly. Blocking them can reduce
coverage; that limitation must be recorded, not interpreted as a site defect.
The transport additionally pins sockets to validated public addresses.
"""
import time
import re
from urllib.parse import urlsplit, unquote, parse_qsl


def unsafe_target(url):
    """Reject credential/action URLs and parser-ambiguous paths, not page topics.

    GET is not evidence of read-only semantics. These explicit action markers
    are conservative exclusions; arbitrary server-side GET effects remain
    outside a crawler's control.
    """
    if re.search(r"[\x00-\x20\x7f\\]", url):
        return True
    parsed = urlsplit(url)
    decoded = unquote(parsed.path)
    if "\\" in decoded or any(part in {".", ".."} for part in decoded.split("/")):
        return True
    segments = {part.casefold() for part in decoded.split("/")}
    if segments & {"logout", "log-out", "signout", "sign-out", "login", "signin", "delete", "remove", "unsubscribe", "checkout"}:
        return True
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key, value = key.casefold(), value.casefold()
        if key in {"access_token", "auth_token", "token", "session", "sessionid", "sid", "password", "api_key", "authorization"}:
            return True
        if key in {"action", "do", "operation", "cmd"} and value not in {"", "view", "read", "list", "search"}:
            return True
    return False


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Only credential-free HTTP(S) URLs are supported")
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


class RequestPolicy:
    def __init__(self, url, *, max_requests=200, delay=0.2, sleep=time.sleep, clock=time.monotonic):
        self.origin = origin(url)
        self.max_requests = min(200, max(0, max_requests))
        self.delay = max(0.2, delay)
        self.sleep, self.clock = sleep, clock
        self.last_request = None
        self.requests = 0
        self.robots = None
        self.blocked = []
        self.stopped = False
        self.time_left = lambda: float("inf")

    def admit(self, url, method="GET", *, preflight=False):
        from .robots import robots_allows
        reason = None
        try:
            if method not in {"GET", "HEAD"}:
                reason = "unsafe_method"
            elif origin(url) != self.origin:
                reason = "cross_origin"
            elif unsafe_target(url):
                reason = "unsafe_or_authenticated_target"
            elif preflight and (urlsplit(url).path != "/robots.txt" or urlsplit(url).query):
                reason = "invalid_robots_preflight"
            elif self.stopped or self.requests >= self.max_requests:
                reason = "request_budget_or_backoff"
            elif not preflight:
                parsed = urlsplit(url)
                target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
                if self.robots is None or not robots_allows(self.robots, target):
                    reason = "robots_disallowed_or_unknown"
        except ValueError:
            reason = "invalid_or_credentialed_url"
        wait = 0 if self.last_request is None else max(0, self.delay - (self.clock() - self.last_request))
        if not reason and wait >= self.time_left():
            reason = "stage_time_budget"
        if reason:
            self.blocked.append({"url": url, "reason": reason})
            return False
        if self.last_request is not None:
            self.sleep(wait)
        self.last_request = self.clock()
        self.requests += 1
        return True

    def observe_status(self, status):
        # Stop this audit instead of retrying a throttled/unavailable origin.
        if status in {429, 503}:
            self.stopped = True
