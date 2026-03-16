"""Incident-history runtime tools."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from sre_agent.core.settings import AgentSettings
from sre_agent.rag import IncidentRetriever
from sre_agent.tools.common import completed_response, unavailable_response


class IncidentTools:
    """Incident-history tool implementations."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.retriever = IncidentRetriever(settings)

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

        query = str(arguments.get("query") or "").strip()
        result = self.retriever.search(query)
        if result["status"] != "completed":
            return unavailable_response(
                result["summary"],
                source="incident_store",
            )
        return completed_response(
            result["summary"],
            data={"matches": result["data"]["matches"], "backend": result["data"]["backend"]},
            source="incident_store",
        )
