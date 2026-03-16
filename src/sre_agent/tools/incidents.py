"""Incident-history runtime tools."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from sre_agent.core.settings import AgentSettings
from sre_agent.tools.common import completed_response, unavailable_response


class IncidentTools:
    """Incident-history tool implementations."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def get_active_alerts(self, arguments: dict[str, object]) -> dict[str, object]:
        """Return recent stored alerts for one service."""

        service_name = str(arguments.get("service_name") or "").strip()
        path = Path(self.settings.incident_store_path)
        if not path.exists():
            return unavailable_response(
                "No stored incidents are available yet.",
                source="incident_store",
            )

        cutoff = datetime.now() - timedelta(minutes=30)
        matches: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            incident = payload.get("incident") or {}
            if service_name and incident.get("service_name") != service_name:
                continue
            observed_at = incident.get("observed_at")
            if observed_at:
                try:
                    if datetime.fromisoformat(observed_at) < cutoff:
                        continue
                except ValueError:
                    pass
            matches.append(
                {
                    "service_name": incident.get("service_name"),
                    "severity": incident.get("severity"),
                    "observed_at": incident.get("observed_at"),
                }
            )
        if not matches:
            return unavailable_response(
                f"No recent stored alerts were found for {service_name or 'the requested scope'}.",
                source="incident_store",
            )
        return completed_response(
            f"Found {len(matches)} recent stored alerts.",
            data={"alerts": matches[-10:]},
            source="incident_store",
        )

    def recall_similar_incidents(self, arguments: dict[str, object]) -> dict[str, object]:
        """Return recent incidents that roughly match a query."""

        query = str(arguments.get("query") or "").strip().lower()
        path = Path(self.settings.incident_store_path)
        if not path.exists():
            return unavailable_response(
                "No incident history is available yet.",
                source="incident_store",
            )
        if not query:
            return unavailable_response(
                "No incident recall query was provided.",
                source="incident_store",
            )

        matches: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-500:]:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            incident = payload.get("incident") or {}
            diagnosis = payload.get("diagnosis") or {}
            haystacks = [
                str(incident.get("service_name") or ""),
                str(incident.get("severity") or ""),
                str(diagnosis.get("summary") or ""),
                str(diagnosis.get("root_cause") or ""),
            ]
            findings = incident.get("findings") or []
            for finding in findings:
                haystacks.append(str(finding.get("code") or ""))
                haystacks.append(str(finding.get("summary") or ""))
            if not any(query in item.lower() for item in haystacks):
                continue
            matches.append(
                {
                    "service_name": incident.get("service_name"),
                    "severity": incident.get("severity"),
                    "summary": diagnosis.get("summary"),
                    "root_cause": diagnosis.get("root_cause"),
                }
            )
            if len(matches) >= 5:
                break
        if not matches:
            return unavailable_response(
                f"No similar incidents were found for query {query}.",
                source="incident_store",
            )
        return completed_response(
            f"Found {len(matches)} similar incidents for query {query}.",
            data={"matches": matches},
            source="incident_store",
        )