"""Business-log detectors for the SRE Agent."""

import json

from sre_agent.core.models import MonitorFinding
from sre_agent.core.settings import AgentSettings


class BusinessDetector:
    """Analyse structured business log events."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def analyse(self, log_lines: list[str]) -> tuple[list[MonitorFinding], list[dict[str, object]]]:
        """Analyse structured business logs."""

        events = [event for line in log_lines if (event := self._parse_event(line)) is not None]
        findings: list[MonitorFinding] = []
        if not events:
            return findings, []

        findings.extend(self._detect_token_anomalies(events))
        findings.extend(self._detect_workflow_issues(events))
        findings.extend(self._detect_tool_failures(events))
        return findings, events[-20:]

    def _detect_token_anomalies(self, events: list[dict[str, object]]) -> list[MonitorFinding]:
        findings: list[MonitorFinding] = []
        for event in events:
            total_tokens = self._extract_total_tokens(event)
            if total_tokens < self.settings.token_anomaly_threshold:
                continue
            findings.append(
                MonitorFinding(
                    code="token_usage_high",
                    detector="business",
                    severity="warning",
                    summary="Workflow token usage is unusually high.",
                    details=(
                        f"Detected token usage of {total_tokens}, which exceeds the configured "
                        f"threshold of {self.settings.token_anomaly_threshold}."
                    ),
                    evidence={
                        "workflow_id": event.get("workflow_id"),
                        "total_tokens": total_tokens,
                    },
                )
            )
            break
        return findings

    def _detect_workflow_issues(self, events: list[dict[str, object]]) -> list[MonitorFinding]:
        findings: list[MonitorFinding] = []
        workflow_total = 0
        workflow_failed = 0

        for event in events:
            event_type = str(event.get("event_type", "")).lower()
            status = str(event.get("status", "")).lower()
            if "workflow" not in event_type:
                continue

            elapsed_ms = self._coerce_int(event.get("elapsed_ms"))
            if status == "running" and elapsed_ms is not None:
                if elapsed_ms >= self.settings.workflow_timeout_seconds * 1000:
                    findings.append(
                        MonitorFinding(
                            code="workflow_stuck",
                            detector="business",
                            severity="critical",
                            summary="A workflow appears to be stuck.",
                            details=(
                                f"Workflow {event.get('workflow_id')} has been running for "
                                f"{elapsed_ms} ms without completing."
                            ),
                            evidence={
                                "workflow_id": event.get("workflow_id"),
                                "elapsed_ms": elapsed_ms,
                            },
                        )
                    )

            if status in {"success", "failed", "error"}:
                workflow_total += 1
                if status in {"failed", "error"}:
                    workflow_failed += 1

        if workflow_total >= 3:
            failure_rate = workflow_failed / workflow_total
            if failure_rate >= self.settings.workflow_failure_rate_threshold:
                findings.append(
                    MonitorFinding(
                        code="workflow_failure_rate_high",
                        detector="business",
                        severity="warning",
                        summary="Workflow failure rate is elevated.",
                        details=(
                            f"Workflow failure rate is {failure_rate:.0%} over the recent log window."
                        ),
                        evidence={
                            "workflow_total": workflow_total,
                            "workflow_failed": workflow_failed,
                            "failure_rate": round(failure_rate, 4),
                        },
                    )
                )

        return findings

    def _detect_tool_failures(self, events: list[dict[str, object]]) -> list[MonitorFinding]:
        tool_total = 0
        tool_failed = 0
        sample_tool: str | None = None

        for event in events:
            event_type = str(event.get("event_type", "")).lower()
            status = str(event.get("status", "")).lower()
            if "tool" not in event_type:
                continue

            tool_total += 1
            if status in {"failed", "error"}:
                tool_failed += 1
                sample_tool = str(event.get("tool_name") or sample_tool)

        if tool_total < 3:
            return []

        failure_rate = tool_failed / tool_total
        if failure_rate < self.settings.tool_failure_rate_threshold:
            return []

        return [
            MonitorFinding(
                code="tool_failure_rate_high",
                detector="business",
                severity="warning",
                summary="Tool failure rate is elevated.",
                details=f"Tool failure rate is {failure_rate:.0%} in the recent log window.",
                evidence={
                    "tool_total": tool_total,
                    "tool_failed": tool_failed,
                    "tool_name": sample_tool,
                    "failure_rate": round(failure_rate, 4),
                },
            )
        ]

    def _parse_event(self, line: str) -> dict[str, object] | None:
        raw = line.strip()
        if "{" not in raw:
            return None

        candidate = raw[raw.find("{") :]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if "event_type" not in payload:
            return None
        return payload

    def _extract_total_tokens(self, event: dict[str, object]) -> int:
        total_tokens = self._coerce_int(event.get("total_tokens"))
        if total_tokens is not None:
            return total_tokens
        input_tokens = self._coerce_int(event.get("token_input")) or 0
        output_tokens = self._coerce_int(event.get("token_output")) or 0
        return input_tokens + output_tokens

    def _coerce_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
