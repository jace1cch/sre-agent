"""Prometheus-backed tools."""

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode
from urllib.request import urlopen

from sre_agent.core.settings import AgentSettings
from sre_agent.tools.common import completed_response, unavailable_response


class PrometheusToolClient:
    """Small Prometheus HTTP client."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def query_metric(self, arguments: dict[str, object]) -> dict[str, object]:
        """Run an instant Prometheus query."""

        if not self.settings.prometheus_base_url:
            return unavailable_response(
                "Prometheus is not configured.",
                source="prometheus",
            )

        query = str(arguments.get("query") or "up")
        payload = self._request("/api/v1/query", {"query": query})
        if payload is None:
            return unavailable_response(
                f"Prometheus query failed for {query}.",
                source="prometheus",
            )

        result = payload.get("data", {}).get("result", [])
        summary = f"Prometheus returned {len(result)} instant series for query {query}."
        return completed_response(summary, data={"query": query, "result": result}, source="prometheus")

    def query_metric_range(self, arguments: dict[str, object]) -> dict[str, object]:
        """Run a range Prometheus query."""

        if not self.settings.prometheus_base_url:
            return unavailable_response(
                "Prometheus is not configured.",
                source="prometheus",
            )

        query = str(arguments.get("query") or "up")
        minutes = int(arguments.get("minutes") or 15)
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        payload = self._request(
            "/api/v1/query_range",
            {
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": int(arguments.get("step") or self.settings.prometheus_step_seconds),
            },
        )
        if payload is None:
            return unavailable_response(
                f"Prometheus range query failed for {query}.",
                source="prometheus",
            )

        result = payload.get("data", {}).get("result", [])
        summary = f"Prometheus returned {len(result)} range series for query {query}."
        return completed_response(summary, data={"query": query, "result": result}, source="prometheus")

    def _request(self, path: str, params: dict[str, object]) -> dict[str, object] | None:
        """Run one Prometheus HTTP request."""

        if not self.settings.prometheus_base_url:
            return None
        base = self.settings.prometheus_base_url.rstrip("/")
        url = f"{base}{path}?{urlencode(params)}"
        try:
            with urlopen(url, timeout=self.settings.prometheus_timeout_seconds) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None