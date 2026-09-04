"""Observation store: stable IDs, append-only storage, and evidence resolution."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional


def _normalize_type(type_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", str(type_name).upper()).strip("-") or "OBS"


def make_observation(observation_type: str, source_url: str, value: Any) -> Dict[str, Any]:
    """Build a deterministic observation with a stable ID and value payload."""
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    observation_id = f"OBS-{_normalize_type(observation_type)}-{digest}"
    return {"id": observation_id, "type": observation_type, "source_url": source_url, "value": value}


class ObservationStore:
    """Append-only observation registry used by the audit orchestrator."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    def add(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        observation_id = observation.get("id")
        if not observation_id:
            raise ValueError("Observation missing id")
        self._records[observation_id] = observation
        return observation

    def resolve(self, observation_id: str) -> Optional[Dict[str, Any]]:
        return self._records.get(observation_id)

    def all(self) -> List[Dict[str, Any]]:
        return list(self._records.values())


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
