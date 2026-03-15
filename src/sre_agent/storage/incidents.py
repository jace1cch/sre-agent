"""Incident storage for the SRE Agent."""

import json
from pathlib import Path

from sre_agent.core.models import ErrorDiagnosis, Incident


def store_incident(
    incident: Incident,
    diagnosis: ErrorDiagnosis | None,
    destination: str,
) -> None:
    """Append an incident record to a JSONL file."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "incident": incident.model_dump(mode="json"),
        "diagnosis": diagnosis.model_dump(mode="json") if diagnosis is not None else None,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")
