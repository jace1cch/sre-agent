"""Tests for the first autonomous graph slice."""

import asyncio

from sre_agent.core.agent import diagnose_incident, run_autonomous_diagnosis
from sre_agent.core.models import Incident, MonitorFinding
from sre_agent.core.settings import AgentSettings
from sre_agent.tools.stub import build_stub_tool_registry


def _incident() -> Incident:
    """Build a minimal Java incident."""

    return Incident(
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
        evidence={"log_excerpt": ["ERROR synthetic failure"]},
    )


def test_autonomous_workflow_runs_with_stub_tools() -> None:
    """The graph framework runs even before LangGraph is installed."""

    settings = AgentSettings(
        _env_file=None,
        GRAPH_ENABLE_AUTONOMOUS_LOOP=True,
        GRAPH_MAX_STEPS=2,
    )

    result = asyncio.run(
        run_autonomous_diagnosis(
            _incident(),
            settings,
            tool_registry=build_stub_tool_registry(),
        )
    )

    assert result.runtime_mode == "fallback"
    assert result.react_steps >= 2
    assert [call.name for call in result.tool_calls] == ["get_error_logs", "get_jvm_status"]
    assert result.diagnosis.summary.startswith("Autonomous diagnosis for api")


def test_diagnose_incident_routes_to_autonomous_path() -> None:
    """The public diagnosis entrypoint can use the graph path."""

    settings = AgentSettings(
        _env_file=None,
        GRAPH_ENABLE_AUTONOMOUS_LOOP=True,
        GRAPH_MAX_STEPS=1,
    )

    diagnosis = asyncio.run(diagnose_incident(_incident(), settings))

    assert diagnosis.summary.startswith("Autonomous diagnosis for api")
    assert diagnosis.affected_services == ["api"]