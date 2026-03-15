"""Tests for business detector logic."""

import json

from sre_agent.core.settings import AgentSettings
from sre_agent.detectors.business import BusinessDetector


def test_business_detector_flags_structured_business_anomalies() -> None:
    """Business detector identifies workflow and tool anomalies."""

    settings = AgentSettings(
        _env_file=None,
        TOKEN_ANOMALY_THRESHOLD=100,
        WORKFLOW_TIMEOUT_SECONDS=300,
        WORKFLOW_FAILURE_RATE_THRESHOLD=0.5,
        TOOL_FAILURE_RATE_THRESHOLD=0.3,
    )
    detector = BusinessDetector(settings)

    log_lines = [
        json.dumps(
            {
                "event_type": "workflow_state",
                "workflow_id": "wf-1",
                "status": "running",
                "elapsed_ms": 400000,
            }
        ),
        json.dumps(
            {
                "event_type": "workflow_usage",
                "workflow_id": "wf-1",
                "token_input": 80,
                "token_output": 30,
            }
        ),
        json.dumps({"event_type": "workflow_result", "status": "failed"}),
        json.dumps({"event_type": "workflow_result", "status": "failed"}),
        json.dumps({"event_type": "workflow_result", "status": "success"}),
        json.dumps({"event_type": "tool_call", "tool_name": "search", "status": "failed"}),
        json.dumps({"event_type": "tool_call", "tool_name": "search", "status": "failed"}),
        json.dumps({"event_type": "tool_call", "tool_name": "search", "status": "success"}),
    ]

    findings, events = detector.analyse(log_lines)
    finding_codes = {finding.code for finding in findings}

    assert events
    assert {
        "token_usage_high",
        "workflow_stuck",
        "workflow_failure_rate_high",
        "tool_failure_rate_high",
    }.issubset(finding_codes)
