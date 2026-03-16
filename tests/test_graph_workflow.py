"""Tests for the autonomous graph workflow."""

import asyncio

import pytest

from sre_agent.core.agent import build_autonomous_failure_diagnosis, diagnose_incident, run_autonomous_diagnosis
from sre_agent.core.models import Incident, MonitorFinding
from sre_agent.core.settings import AgentSettings
from sre_agent.graph.workflow import AutonomousWorkflow, ReActDecision
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


def test_autonomous_workflow_requires_model_runtime() -> None:
    """Autonomous workflow raises when no model runtime is configured."""

    settings = AgentSettings(
        _env_file=None,
        GRAPH_MAX_STEPS=2,
    )

    with pytest.raises(RuntimeError, match="requires an OpenAI-compatible API key"):
        asyncio.run(
            run_autonomous_diagnosis(
                _incident(),
                settings,
                tool_registry=build_stub_tool_registry(),
            )
        )


def test_autonomous_workflow_uses_dynamic_react_decisions(monkeypatch) -> None:
    """The LLM-driven autonomous loop follows observations step by step."""

    settings = AgentSettings(
        _env_file=None,
        OPENAI_API_KEY="test-key",
        GRAPH_MAX_STEPS=4,
    )
    workflow = AutonomousWorkflow(
        settings=settings,
        tool_registry=build_stub_tool_registry(),
        llm_client=object(),
    )
    decisions = iter(
        [
            ReActDecision(
                thought="Recent errors are the highest-value next signal.",
                action="call_tool",
                tool_name="get_error_logs",
                tool_arguments={"service_name": "api"},
            ),
            ReActDecision(
                thought="The log evidence suggests a JVM-level follow-up.",
                action="call_tool",
                tool_name="get_jvm_status",
                tool_arguments={"service_name": "api", "mode": "sigquit"},
            ),
            ReActDecision(
                thought="The evidence is now sufficient to conclude.",
                action="finish",
                summary="Autonomous diagnosis for api from dynamic ReAct steps.",
                root_cause="Repeated application errors point to a JVM-side failure path.",
                confidence=0.84,
                affected_services=["api"],
                suggested_fixes=[
                    "Review the JVM snapshot and isolate the failing code path.",
                    "Inspect recent deploy or traffic changes before restarting the service.",
                ],
                related_logs=["ERROR synthetic failure"],
            ),
        ]
    )

    async def fake_request_decision(_messages):
        return next(decisions)

    monkeypatch.setattr(workflow, "_request_decision", fake_request_decision)

    result = asyncio.run(workflow.ainvoke(_incident()))

    assert result.runtime_mode == "llm_react"
    assert [call.name for call in result.tool_calls] == ["get_error_logs", "get_jvm_status"]
    assert result.diagnosis.confidence == 0.84
    assert result.diagnosis.tools_actually_called == ["get_error_logs", "get_jvm_status"]
    assert result.diagnosis.react_steps == 3
    assert result.diagnosis.reasoning_trace[-1].action == "finish"
    assert result.diagnosis.summary == "Autonomous diagnosis for api from dynamic ReAct steps."


def test_diagnose_incident_captures_agent_failure(monkeypatch) -> None:
    """The public diagnosis entrypoint captures autonomous runtime failures."""

    settings = AgentSettings(
        _env_file=None,
        GRAPH_MAX_STEPS=1,
    )
    async def fake_run_autonomous(_incident, _settings=None, tool_registry=None):
        raise RuntimeError("synthetic model failure")

    monkeypatch.setattr("sre_agent.core.agent.run_autonomous_diagnosis", fake_run_autonomous)

    diagnosis = asyncio.run(diagnose_incident(_incident(), settings))

    assert diagnosis.summary == "Autonomous diagnosis failed for api."
    assert diagnosis.affected_services == ["api"]
    assert "synthetic model failure" in diagnosis.root_cause


def test_build_autonomous_failure_diagnosis_is_structured() -> None:
    """Autonomous failure diagnoses stay structured for storage and notification."""

    diagnosis = build_autonomous_failure_diagnosis(_incident(), RuntimeError("timeout"))

    assert diagnosis.summary == "Autonomous diagnosis failed for api."
    assert diagnosis.affected_services == ["api"]
    assert diagnosis.suggested_fixes
