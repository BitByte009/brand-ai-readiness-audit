"""robots.txt fetch and parsing helpers for the audit pipeline."""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlparse

import requests

from .http_client import AUDIT_USER_AGENT, request_once

AUDIT_PRODUCT_TOKEN = "brand-ai-readiness-audit"

# A doubly-decoding origin is already pathological; three rounds bounds the
# work while covering the encodings a real server plausibly collapses.
MAX_DECODE_ROUNDS = 3


def parse_robots(raw_text: str) -> dict:
    """Return a normalized, deterministic robots.txt model."""
    text = raw_text or ""
    if len(text.encode("utf-8")) > 512 * 1024:
        return {"status": "unparseable", "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}
    if not text.strip():
        return {"status": "missing", "allow_all": True, "document": {"groups": [], "sitemap": [], "rules": []}}

    groups = []
    current = None
    sitemaps = []

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("#"):
            continue

        lower = line.lower()
        if lower.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            if current is None or current.get("has_rules"):
                current = {"allow": [], "disallow": [], "has_rules": False}
            groups.append({"user_agent": agent, "allow": current["allow"], "disallow": current["disallow"]})
            continue

        if lower.startswith("allow:") and current is not None:
            current["has_rules"] = True
            current["allow"].append(line.split(":", 1)[1].strip())
            continue

        if lower.startswith("disallow:") and current is not None:
            current["has_rules"] = True
            value = line.split(":", 1)[1].strip()
            if value:
                current["disallow"].append(value)
            continue

        if lower.startswith("sitemap:"):
            sitemaps.append(line.split(":", 1)[1].strip())
            continue

        if lower.startswith("crawl-delay:") and current is not None:
            try:
                delay = float(line.split(":", 1)[1].strip())
                if 0 <= delay < float("inf"):
                    for group in groups:
                        if group["allow"] is current["allow"]:
                            group["crawl_delay"] = delay
            except ValueError:
                pass
            current["has_rules"] = True

    if not groups and not sitemaps:
        return {"status": "unparseable", "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}

    document = {"groups": groups, "sitemap": sitemaps, "rules": [rule for group in groups for rule in group["disallow"]]}
    return {"status": "ok", "allow_all": not any(group["disallow"] for group in groups), "document": document}


def _encoded_path(value: str) -> str:
    value = quote(value, safe="/%?=&;:+,$!*'()@-._~")
    def normalize(match):
        char = chr(int(match.group()[1:], 16))
        return char if re.fullmatch(r"[A-Za-z0-9._~-]", char) else match.group().upper()
    return re.sub(r"%[0-9a-fA-F]{2}", normalize, value)


def robots_allows(robots: dict, path: str, user_agent: str = AUDIT_PRODUCT_TOKEN) -> bool:
    """Evaluate one product token, grouped rules and longest matching octets.

    Callers pass path plus query. Other bots' exclusions are audit observations,
    never permission rules for this auditor.
    """
    if not robots:
        return False
    status = robots.get("status")
    if status == "missing":
        return True
    if status != "ok":
        return False

    groups = robots.get("document", {}).get("groups", [])
    if not groups:
        return True

    named = [g for g in groups if (g.get("user_agent") or "").lower() == user_agent.lower()]
    applicable = named or [g for g in groups if g.get("user_agent") == "*"]
    target = _encoded_path(path or "/")
    matches = []
    for group in applicable:
        for directive in ("allow", "disallow"):
            for rule in group.get(directive, []):
                if not rule:
                    continue
                encoded = _encoded_path(rule)
                terminal = encoded.endswith("$")
                pattern = encoded[:-1] if terminal else encoded
                if _wildcard_matches(pattern, target, terminal):
                    matches.append((len(re.sub(r"%[0-9A-F]{2}", "x", pattern.replace("*", ""))), directive == "allow"))
    return max(matches)[1] if matches else True


def _wildcard_matches(pattern, target, terminal):
    """Literal chunks and forward searches avoid regex wildcard backtracking."""
    chunks = pattern.split("*")
    if not target.startswith(chunks[0]):
        return False
    position = len(chunks[0])
    if len(chunks) == 1:
        return not terminal or position == len(target)
    for chunk in chunks[1:-1]:
        found = target.find(chunk, position)
        if found < 0:
            return False
        position = found + len(chunk)
    last = chunks[-1]
    if terminal:
        return target.endswith(last) and len(target) - len(last) >= position
    return target.find(last, position) >= 0


def path_interpretations(target: str) -> list:
    """Every path a compliant origin could resolve one request-target to.

    A robots rule is matched against the request path's octets, so
    ``/%2Fprivate`` and ``//private`` both slip past ``Disallow: /private``
    while ordinary origins (nginx with merge_slashes, Apache, most
    frameworks) still serve the disallowed resource. Rather than guess which
    server is on the other end, enumerate the interpretations it could
    collapse the target to; callers fail closed if any of them is excluded.

    Decoding is repeated a bounded number of times because a double-encoded
    ``/%252Fprivate`` reaches a doubly-decoding origin as ``/private``.
    """
    path, separator, query = (target or "/").partition("?")
    variants = []
    current = path
    for _ in range(MAX_DECODE_ROUNDS):
        for candidate in (current, re.sub(r"/{2,}", "/", current)):
            if candidate and candidate not in variants:
                variants.append(candidate)
        # "%25" is decoded alongside the separators so a double-encoded
        # "/%252Fprivate" reaches "/private" within the round limit, the way a
        # doubly-decoding origin would resolve it.
        decoded = re.sub(r"%(?:25|2[Ff]|5[Cc])",
                         lambda match: "%" if match.group() == "%25" else "/", current)
        if decoded == current:
            break
        current = decoded
    return [variant + separator + query for variant in variants]


def robots_allows_every_interpretation(robots: dict, target: str, user_agent: str = AUDIT_PRODUCT_TOKEN) -> bool:
    """Fail-closed robots evaluation: excluded under *any* reading is excluded.

    This, not `robots_allows`, is what a fetch decision must consult -- see
    `path_interpretations` for the evasions a single literal match misses.
    """
    return all(robots_allows(robots, variant, user_agent) for variant in path_interpretations(target))


def is_disallow_all(robots: dict) -> bool:
    """Conservative proof of blanket denial, not merely denial of the root.

    Possible Allow exceptions require per-path evaluation instead.
    """
    if not robots or robots.get("status") != "ok":
        return False
    groups = robots.get("document", {}).get("groups", [])
    applicable = [g for g in groups if g.get("user_agent", "").lower() == AUDIT_PRODUCT_TOKEN] or [g for g in groups if g.get("user_agent") == "*"]
    return not any(rule for g in applicable for rule in g.get("allow", [])) and any(
        rule in {"/", "/*", "/*$"} for g in applicable for rule in g.get("disallow", [])
    )


def fetch_robots(base_url: str, timeout: int = 10, policy=None) -> dict:
    """Fetch robots.txt from an origin and normalize the result."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url
    robots_url = urljoin(origin.rstrip("/") + "/", "robots.txt")

    try:
        if policy is not None and not policy.admit(robots_url, preflight=True):
            return {"url": robots_url, "status": "error", "failure_kind": "policy",
                    "error": "robots preflight blocked by network policy", "allow_all": False,
                    "document": {"groups": [], "sitemap": [], "rules": []}}
        response = request_once(robots_url, timeout=timeout)
        if policy is not None:
            policy.observe_status(response.status_code)
    except (requests.RequestException, ValueError) as exc:
        return {"url": robots_url, "status": "error", "failure_kind": "transport", "error": str(exc), "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}

    if response.status_code == 404:
        return {"url": robots_url, "status": "missing", "allow_all": True, "document": {"groups": [], "sitemap": [], "rules": []}}

    if response.status_code != 200:
        return {"url": robots_url, "status": "error", "http_status": response.status_code,
                "failure_kind": "redirect" if 300 <= response.status_code < 400 else "http",
                "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}

    text = response.text or ""
    parsed_text = parse_robots(text)
    if parsed_text["status"] == "ok":
        return {"url": robots_url, "status": "ok", **parsed_text, "allow_all": parsed_text.get("allow_all", False)}
    return {"url": robots_url, **parsed_text}


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
