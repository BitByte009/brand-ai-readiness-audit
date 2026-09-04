"""robots.txt fetch and parsing helpers for the audit pipeline."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests

from .http_client import AUDIT_USER_AGENT


def parse_robots(raw_text: str) -> dict:
    """Return a normalized, deterministic robots.txt model."""
    text = raw_text or ""
    if not text.strip():
        return {"status": "missing", "allow_all": True, "document": {"groups": [], "sitemap": [], "rules": []}}

    groups = []
    current = None
    sitemaps = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        lower = line.lower()
        if lower.startswith("user-agent:"):
            if current is not None:
                groups.append(current)
            current = {"user_agent": line.split(":", 1)[1].strip(), "allow": [], "disallow": []}
            continue

        if lower.startswith("allow:") and current is not None:
            current["allow"].append(line.split(":", 1)[1].strip())
            continue

        if lower.startswith("disallow:") and current is not None:
            value = line.split(":", 1)[1].strip()
            if value:
                current["disallow"].append(value)
            continue

        if lower.startswith("sitemap:"):
            sitemaps.append(line.split(":", 1)[1].strip())
            continue

    if current is not None:
        groups.append(current)

    if not groups and not sitemaps:
        return {"status": "unparseable", "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}

    document = {"groups": groups, "sitemap": sitemaps, "rules": [rule for group in groups for rule in group["disallow"]]}
    return {"status": "ok", "allow_all": not any(group["disallow"] for group in groups), "document": document}


def robots_allows(robots: dict, path: str) -> bool:
    """Check whether the path is allowed for AI crawler groups."""
    if not robots:
        return True
    status = robots.get("status")
    if status == "missing":
        return True
    if status == "unparseable":
        return False

    groups = robots.get("document", {}).get("groups", [])
    if not groups:
        return True

    normalized_path = path or "/"
    for group in groups:
        user_agent = (group.get("user_agent") or "").lower()
        if user_agent not in {"*", "gptbot", "chatgpt-user", "google-extended", "openai-bot"}:
            continue

        disallow_rules = group.get("disallow", [])
        allow_rules = group.get("allow", [])

        if any(rule and normalized_path.startswith(rule) for rule in disallow_rules):
            if not any(rule and normalized_path.startswith(rule) for rule in allow_rules):
                return False

    return True


def is_disallow_all(robots: dict) -> bool:
    """True only for a root-level `Disallow: /` (or equivalent) applying to a
    relevant crawler group -- not merely "some path is disallowed somewhere".
    Every URL path starts with "/", so the only rule value that is itself a
    prefix of "/" is "/" exactly; checking `robots_allows(robots, "/")` is
    therefore a precise disallow-all test, distinct from `parse_robots`'s own
    `allow_all` field (which means "zero disallow rules anywhere", a much
    stricter and different condition than "the whole site is blocked")."""
    if not robots or robots.get("status") != "ok":
        return False
    return not robots_allows(robots, "/")


def fetch_robots(base_url: str, timeout: int = 10) -> dict:
    """Fetch robots.txt from an origin and normalize the result."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url
    robots_url = urljoin(origin.rstrip("/") + "/", "robots.txt")

    try:
        response = requests.get(robots_url, timeout=timeout, headers={"User-Agent": AUDIT_USER_AGENT})
    except requests.RequestException:
        return {"url": robots_url, "status": "error", "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}

    if response.status_code == 404:
        return {"url": robots_url, "status": "missing", "allow_all": True, "document": {"groups": [], "sitemap": [], "rules": []}}

    if response.status_code >= 500:
        return {"url": robots_url, "status": "error", "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}

    text = response.text or ""
    parsed_text = parse_robots(text)
    if parsed_text["status"] == "ok":
        return {"url": robots_url, "status": "ok", **parsed_text, "allow_all": parsed_text.get("allow_all", False)}
    return {"url": robots_url, **parsed_text}


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
