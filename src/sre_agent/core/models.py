"""Data models for the SRE Agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]
ActionStatus = Literal["success", "failed", "skipped"]
SourceTier = Literal["local", "runtime", "external", "optional"]
SourceState = Literal["available", "degraded", "missing", "unsupported"]


class LogEntry(BaseModel):
    """A single log entry."""

    timestamp: str = Field(description="ISO 8601 timestamp of the log entry")
    message: str = Field(description="The log message content")
    log_stream: str | None = Field(default=None, description="The log stream name")


class LogQueryResult(BaseModel):
    """Result from querying logs."""

    entries: list[LogEntry] = Field(default_factory=list, description="Log entries found")
    log_group: str = Field(description="The source that was queried")
    query: str = Field(description="The query that was executed")


class SuggestedFix(BaseModel):
    """A suggested fix for an error."""

    description: str = Field(description="What the fix involves")
    file_path: str | None = Field(default=None, description="File to modify, if applicable")
    code_snippet: str | None = Field(default=None, description="Example code change")


class SourceAvailability(BaseModel):
    """Availability of one input source."""

    name: str = Field(description="Stable source name")
    tier: SourceTier = Field(description="Source tier")
    status: SourceState = Field(description="Current source status")
    summary: str = Field(description="Short source summary")
    fallback_group: str | None = Field(default=None, description="Fallback group name")
    tool_name: str | None = Field(default=None, description="Mapped tool name")
    details: str | None = Field(default=None, description="Extra source details")


class HostSnapshot(BaseModel):
    """A snapshot of host health."""

    hostname: str = Field(description="Hostname of the monitored server")
    cpu_count: int = Field(description="Number of logical CPUs")
    cpu_percent: float | None = Field(default=None, description="Estimated CPU usage")
    load_average_1m: float | None = Field(default=None, description="One minute load average")
    memory_total_mb: int | None = Field(default=None, description="Total memory in MB")
    memory_available_mb: int | None = Field(default=None, description="Available memory in MB")
    disk_path: str = Field(description="Path used for disk monitoring")
    disk_used_percent: float | None = Field(default=None, description="Disk usage percentage")


class ContainerSnapshot(BaseModel):
    """A snapshot of container health."""

    name: str = Field(description="Container name")
    image: str | None = Field(default=None, description="Container image")
    status: str = Field(description="Container status")
    running: bool = Field(description="Whether the container is running")
    restart_count: int = Field(description="Number of container restarts")
    oom_killed: bool = Field(description="Whether the container was OOM killed")
    exit_code: int | None = Field(default=None, description="Container exit code")


class MonitorFinding(BaseModel):
    """A detector finding."""

    code: str = Field(description="Stable code for the finding")
    detector: str = Field(description="Detector name")
    severity: Severity = Field(description="Finding severity")
    summary: str = Field(description="Short summary")
    details: str = Field(description="Detailed explanation")
    evidence: dict[str, object] = Field(default_factory=dict, description="Extra evidence")


class EvidenceBundle(BaseModel):
    """Collected evidence for an incident."""

    host: HostSnapshot | None = Field(default=None, description="Host evidence")
    container: ContainerSnapshot | None = Field(default=None, description="Container evidence")
    log_excerpt: list[str] = Field(default_factory=list, description="Relevant log lines")
    gc_excerpt: list[str] = Field(default_factory=list, description="Relevant GC log lines")
    thread_dump_excerpt: list[str] = Field(
        default_factory=list,
        description="Relevant thread dump lines",
    )
    business_events: list[dict[str, object]] = Field(
        default_factory=list,
        description="Structured business events",
    )
    input_sources: list[SourceAvailability] = Field(
        default_factory=list,
        description="Input source status for this incident",
    )


class ActionResult(BaseModel):
    """Result of an automated action."""

    action: str = Field(description="Action name")
    status: ActionStatus = Field(description="Execution status")
    summary: str = Field(description="Short result summary")
    details: str | None = Field(default=None, description="Extra action details")


class Incident(BaseModel):
    """An incident detected by the monitor."""

    service_name: str = Field(description="Monitored service name")
    severity: Severity = Field(description="Overall incident severity")
    observed_at: datetime = Field(default_factory=datetime.now, description="Observation time")
    findings: list[MonitorFinding] = Field(default_factory=list, description="Detector findings")
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle, description="Incident evidence")
    actions: list[ActionResult] = Field(default_factory=list, description="Executed actions")


class ErrorDiagnosis(BaseModel):
    """Complete diagnosis of an error from the SRE agent."""

    summary: str = Field(description="Brief summary of the issue")
    root_cause: str = Field(description="Identified root cause")
    affected_services: list[str] = Field(
        default_factory=list,
        description="Services affected by this issue",
    )
    suggested_fixes: list[SuggestedFix] = Field(
        default_factory=list,
        description="Suggested fixes for the issue",
    )
    related_logs: list[str] = Field(
        default_factory=list,
        description="Key log messages related to the issue",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the diagnosis was created",
    )