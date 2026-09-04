"""Extraction/corroboration probe. Runs the canonical questions against
machine-readable text only, plus the outbound corroboration lookups
D-ENTITY-03 and D-TRUST-05 depend on. One batched, temperature-0,
structured-output model call per page; input text hashed into the
observation (PROJECT_CONTEXT.md D-4).

Inputs:  machine-readable text per page
Outputs: per-question answered/not-answered + span; corroboration verdicts
Nature:  LLM instrument (named, auditable)

No model or outbound-search integration is wired into this environment.
PROJECT_CONTEXT.md's own open-question log (OQ-3) already marks the
corroboration instrument as blocked pending that decision -- this module
makes that honest rather than silent: `detect_capability()` always reports
unavailable with a machine-readable reason, and `run_probe` never fabricates
an answer. Callers get an empty result plus a coverage gap
(SEARCH_UNAVAILABLE), which is exactly what a real model outage would also
produce, so no downstream code needs a special case for "not implemented yet"
versus "temporarily down" -- both are the same shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def detect_capability() -> Dict[str, Any]:
    """Shaped identically to `lib.site_observer.render.detect_capability` so
    both capabilities are recorded the same way in the report's capability
    matrix. Always unavailable in this environment (see module docstring)."""
    return {"available": False, "reason": "MODEL_UNAVAILABLE"}


def run_probe(
    pages: List[Dict[str, Any]],
    capability: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Would run the canonical per-page questions and corroboration lookups.
    Never raises: absent the capability, returns an empty observation list
    plus a coverage gap, exactly like a real outage would."""
    capability = capability if capability is not None else detect_capability()
    if not capability.get("available"):
        reason = capability.get("reason", "MODEL_UNAVAILABLE")
        return {
            "observations": [],
            "coverage": [{"check_id": "X-COV-01", "status": "skipped", "reason": "SEARCH_UNAVAILABLE", "detail": reason}],
        }
    # Real corroboration lookups would run here once a model/search
    # integration is wired in (OQ-3). Intentionally absent, not stubbed with
    # a fake answer -- see module docstring.
    return {"observations": [], "coverage": []}


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
