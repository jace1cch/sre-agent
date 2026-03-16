"""Tests for incident storage output."""

import json
from pathlib import Path
from uuid import uuid4

from sre_agent.core.models import ErrorDiagnosis, Incident, MonitorFinding, ReasoningTraceEntry, SuggestedFix
from sre_agent.storage import store_incident


def _workspace_dir(name: str) -> Path:
    """Create a workspace-local test directory."""

    path = Path("tests/.tmp") / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_store_incident_persists_reasoning_trace() -> None:
    """Structured diagnosis trace is written to the incident store."""

    tmp_path = _workspace_dir("incident-storage")
    destination = tmp_path / "incidents.jsonl"
    incident = Incident(
        service_name="api",
        severity="warning",
        findings=[
            MonitorFinding(
                code="java_error_burst",
                detector="java",
                severity="warning",
                summary="Error burst detected",
                details="Repeated ERROR lines detected in the container logs.",
                evidence={},
            )
        ],
    )
    diagnosis = ErrorDiagnosis(
        summary="Autonomous diagnosis for api.",
        root_cause="Repeated ERROR lines indicate an application failure path.",
        suggested_fixes=[SuggestedFix(description="Review the recent error logs.")],
        reasoning_trace=[
            ReasoningTraceEntry(
                step_number=1,
                thought="Recent logs are the highest-value evidence.",
                action="call get_error_logs",
                observation="Collected 2 relevant log lines.",
                tool_name="get_error_logs",
                tool_arguments={"service_name": "api"},
                tool_status="completed",
            )
        ],
        tools_actually_called=["get_error_logs"],
        react_steps=1,
    )

    store_incident(incident, diagnosis, str(destination))

    payload = json.loads(destination.read_text(encoding="utf-8").splitlines()[0])
    stored_diagnosis = payload["diagnosis"]

    assert stored_diagnosis["tools_actually_called"] == ["get_error_logs"]
    assert stored_diagnosis["react_steps"] == 1
    assert stored_diagnosis["reasoning_trace"][0]["tool_name"] == "get_error_logs"
