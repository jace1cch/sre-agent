"""Webhook notifications for the SRE Agent."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sre_agent.core.models import ErrorDiagnosis, Incident
from sre_agent.core.settings import AgentSettings


class WebhookNotifier:
    """Send notifications to a configured webhook."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def send_text(self, message: str) -> bool:
        """Send a plain text message."""

        if not self.settings.webhook_url:
            return False

        payload = self._build_payload(message)
        request = Request(
            self.settings.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.webhook_timeout_seconds) as response:
                return 200 <= response.status < 300
        except (HTTPError, URLError):
            return False

    def send_incident(self, incident: Incident, diagnosis: ErrorDiagnosis | None) -> bool:
        """Send an incident notification."""

        return self.send_text(self._render_incident_message(incident, diagnosis))

    def _build_payload(self, message: str) -> dict[str, object]:
        if self.settings.webhook_provider == "feishu":
            return {"msg_type": "text", "content": {"text": message}}
        return {"text": message}

    def _render_incident_message(
        self,
        incident: Incident,
        diagnosis: ErrorDiagnosis | None,
    ) -> str:
        lines = [f"[{incident.severity.upper()}] {incident.service_name}", "Findings:"]
        for finding in incident.findings[:5]:
            lines.append(f"- {finding.summary}")

        if diagnosis is not None:
            lines.extend(
                [
                    "",
                    f"Summary: {diagnosis.summary}",
                    f"Root cause: {diagnosis.root_cause}",
                ]
            )

        if incident.actions:
            lines.append("")
            lines.append("Actions:")
            for action in incident.actions:
                lines.append(f"- {action.action}: {action.status} - {action.summary}")

        return "\n".join(lines)
