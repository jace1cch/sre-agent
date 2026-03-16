"""Cycle-level models for autonomous diagnosis."""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from sre_agent.core.models import ErrorDiagnosis, Incident, ReasoningTraceEntry

CorrelationMethod = Literal["time_window", "shared_error", "llm_inferred"]
ToolCallStatus = Literal["planned", "completed", "failed", "skipped"]
GraphRuntimeMode = Literal["llm_react", "fallback"]


class ToolCallRecord(BaseModel):
    """One recorded tool call."""

    name: str = Field(description="Tool name")
    arguments: dict[str, object] = Field(default_factory=dict, description="Tool arguments")
    status: ToolCallStatus = Field(default="planned", description="Execution status")
    summary: str = Field(default="", description="Short execution summary")
    data: dict[str, object] = Field(default_factory=dict, description="Structured tool data")


class GraphReasoningStep(ReasoningTraceEntry):
    """Backward-compatible alias for reasoning steps."""


class IncidentCluster(BaseModel):
    """A grouped set of incidents from one time window."""

    window_start: datetime = Field(description="Window start time")
    window_end: datetime = Field(description="Window end time")
    incidents: list[Incident] = Field(default_factory=list, description="Grouped incidents")
    correlation_method: CorrelationMethod = Field(
        default="time_window",
        description="How the incidents were grouped",
    )


class AutonomousDiagnosisResult(BaseModel):
    """Autonomous diagnosis output."""

    diagnosis: ErrorDiagnosis = Field(description="Structured diagnosis")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, description="Executed tools")
    reasoning_steps: list[GraphReasoningStep] = Field(
        default_factory=list,
        description="Reasoning trace",
    )
    runtime_mode: GraphRuntimeMode = Field(default="fallback", description="Execution mode")
    react_steps: int = Field(default=0, description="Number of reasoning steps")


def _window_start(value: datetime, window_minutes: int) -> datetime:
    """Round a timestamp down to the active window."""

    minute = value.minute - (value.minute % window_minutes)
    return value.replace(minute=minute, second=0, microsecond=0)


def _has_shared_error(incidents: list[Incident]) -> bool:
    """Return whether the grouped incidents share a finding code."""

    codes: set[str] = set()
    for incident in incidents:
        for finding in incident.findings:
            if finding.code in codes:
                return True
            codes.add(finding.code)
    return False


def cluster_incidents(
    incidents: list[Incident],
    window_minutes: int = 5,
) -> list[IncidentCluster]:
    """Group incidents into pragmatic time windows."""

    grouped: dict[datetime, list[Incident]] = defaultdict(list)
    for incident in sorted(incidents, key=lambda item: item.observed_at):
        grouped[_window_start(incident.observed_at, window_minutes)].append(incident)

    clusters: list[IncidentCluster] = []
    for start in sorted(grouped):
        bucket = grouped[start]
        method: CorrelationMethod = "shared_error" if _has_shared_error(bucket) else "time_window"
        clusters.append(
            IncidentCluster(
                window_start=start,
                window_end=start + timedelta(minutes=window_minutes),
                incidents=bucket,
                correlation_method=method,
            )
        )
    return clusters
