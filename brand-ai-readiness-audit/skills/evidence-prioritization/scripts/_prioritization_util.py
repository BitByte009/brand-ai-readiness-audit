"""Shared helpers for evidence-prioritization's normalize/aggregate/score scripts.

Not a public script. Named distinctly from other skills' own `_util.py`/
`_entity_util.py`/`_trust_util.py`/`_engagement_util.py` helpers so multiple
skills' scripts can be imported in the same test session without a
module-name collision (the lesson from `entity-semantic-audit`'s own note on
this, repeated across every skill in this marketplace).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(SCRIPTS_DIR), str(MARKETPLACE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

SEVERITY_ORDER = ["low", "medium", "high", "critical"]
CONFIDENCE_ORDER = ["low", "medium", "high"]


def severity_index(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


def confidence_index(confidence: str) -> int:
    return CONFIDENCE_ORDER.index(confidence)


def url_depth(url: str) -> int:
    return len([seg for seg in urlparse(url).path.split("/") if seg])


def finding_url_set(finding: Dict[str, Any]) -> set:
    return set(finding.get("source_urls", []) or []) | set((finding.get("affected") or {}).get("sample_urls", []) or [])
