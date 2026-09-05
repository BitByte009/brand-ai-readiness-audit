"""JSON Schema loading and validation for report and observation shapes.

Inputs:  document, schema (or a well-known schema name)
Outputs: (is_valid, error_messages)
Nature:  deterministic

Document errors are returned as messages. Missing or invalid schema files are
engineering errors and may raise; callers must not label invalid output valid.
"""

from __future__ import annotations

import json
import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import jsonschema

MARKETPLACE_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = MARKETPLACE_ROOT / "schemas"

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_FORMATS = jsonschema.FormatChecker()


@_FORMATS.checks("date-time")
def _date_time(value: Any) -> bool:
    """Validate zoned RFC3339 timestamps without optional format packages."""
    if not isinstance(value, str):
        return True  # type validation supplies this error
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value):
        return False
    try:
        datetime.datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def load_schema(name_or_path: str) -> Dict[str, Any]:
    """Load a schema by filename under schemas/ (e.g. "report.schema.json")
    or by an absolute path. Cached by resolved path."""
    path = Path(name_or_path)
    if not path.is_absolute():
        path = SCHEMAS_DIR / path
    key = str(path)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[key]


def validate_document(document: Any, schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate `document` against `schema`, collecting every error rather
    than stopping at the first (so a caller can see the full picture, and so
    dropping one bad finding doesn't require re-running validation)."""
    validator = jsonschema.Draft202012Validator(schema, format_checker=_FORMATS)
    errors = [f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}" for err in validator.iter_errors(document)]
    return (not errors, errors)


def validate_report(report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    try:
        json.dumps(report, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        return False, [f"<root>: not JSON-serializable: {error}"]
    valid, errors = validate_document(report, load_schema("report.schema.json"))
    if not valid:
        return valid, errors
    findings = report["findings"]
    ids = [finding["id"] for finding in findings]
    if len(set(ids)) != len(ids):
        errors.append("findings: duplicate finding IDs")
    fingerprints = set()
    for finding in findings:
        # Only exact repeated content is rejected here. Mechanism-aware merging
        # remains in prioritization, where overlap and scope can be assessed.
        content = {key: value for key, value in finding.items()
                   if key not in {"id", "related_findings", "scoring_trace"}}
        fingerprint = json.dumps(content, sort_keys=True)
        if fingerprint in fingerprints:
            errors.append("findings: duplicate finding content")
        fingerprints.add(fingerprint)
    expected = {tier: sum(f["severity"] == tier for f in findings)
                for tier in ("critical", "high", "medium", "low")}
    expected["total_findings"] = len(findings)
    for key, count in expected.items():
        if report["summary"][key] != count:
            errors.append(f"summary/{key}: expected {count}")
    for index, finding in enumerate(findings):
        prefix = f"findings/{index}"
        if finding["suggested_action"]["priority"] != finding["severity"]:
            errors.append(f"{prefix}/suggested_action/priority: must match severity")
        for related in finding.get("related_findings", []):
            if related not in ids or related == finding["id"]:
                errors.append(f"{prefix}/related_findings: unresolved or self reference {related}")
        affected = finding.get("affected", {})
        count, total = affected.get("count"), affected.get("total_in_scope")
        if count is not None and total is not None and count > total:
            errors.append(f"{prefix}/affected: count exceeds total_in_scope")
        if count is not None and len(affected.get("sample_urls", [])) > count:
            errors.append(f"{prefix}/affected: sample size exceeds count")
    return not errors, errors


def validate_observation(observation: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_document(observation, load_schema("observation.schema.json"))


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
