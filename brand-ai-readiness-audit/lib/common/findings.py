"""The common unscored-finding contract every detector skill emits.

`evidence-prioritization` normalizes, dedupes, scores and ranks findings from four
independent detector skills (PROJECT_CONTEXT.md D-6). That only works if all four
build findings to one shape. This module is that shape's single definition.

A finding built here proposes a base severity and carries bound evidence; it never
carries a final report `id` or a final severity -- assigning those is
`evidence-prioritization`'s job, never a detector's (PROJECT_CONTEXT.md Defect B).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def affected_block(urls: List[str], total_in_scope: Optional[int] = None) -> Dict[str, Any]:
    """`{count, sample_urls[<=5], total_in_scope}` -- PROJECT_CONTEXT.md Defect D:
    the finding unit is never one row per URL, so every finding carries its true
    affected scope instead of one row per instance."""
    unique = sorted(set(urls))
    return {
        "count": len(unique),
        "sample_urls": unique[:5],
        # Absence of a measured denominator is materially different from
        # "every item in scope was affected".  Consumers must not manufacture
        # site-wide scope from the handful of URLs carried as evidence.
        "total_in_scope": total_in_scope,
    }


def make_finding(
    *,
    check_id: str,
    category: str,
    title: str,
    severity: str,
    confidence: str,
    mechanism: str,
    impact: str,
    observed_signal: str,
    evidence: str,
    observation_ids: List[str],
    source_urls: List[str],
    affected: Dict[str, Any],
    suggested_action: Dict[str, Any],
) -> Dict[str, Any]:
    """Build one unscored finding. `severity` is a proposed base severity per the
    taxonomy; `evidence-prioritization` computes the final one."""
    return {
        "check_id": check_id,
        "category": category,
        "title": title,
        "severity": severity,
        "confidence": confidence,
        "mechanism": mechanism,
        "impact": impact,
        "observed_signal": observed_signal,
        "evidence": evidence,
        "observation_ids": sorted(set(observation_ids)),
        "source_urls": sorted(set(source_urls)),
        "affected": affected,
        "suggested_action": suggested_action,
    }
