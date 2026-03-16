"""Deployment readiness checks for Linux server environments."""

from pathlib import Path
import os

from pydantic import BaseModel, Field

from sre_agent.core.settings import AgentSettings
from sre_agent.detectors import BusinessDetector, DockerDetector, HostDetector, JavaDetector
from sre_agent.tools import ToolRuntime, build_runtime_tool_registry
from sre_agent.tools.runtime import describe_runtime_sources
from sre_agent.utils import run_command


class DeploymentCheck(BaseModel):
    """One deployment readiness check."""

    name: str = Field(description="Stable check name")
    status: str = Field(description="Check status")
    summary: str = Field(description="Short summary")


class DeploymentReadinessReport(BaseModel):
    """Deployment readiness report."""

    overall_status: str = Field(description="Overall status")
    checks: list[DeploymentCheck] = Field(default_factory=list, description="Readiness checks")
    sources: list[dict[str, object]] = Field(default_factory=list, description="Source availability")


def build_readiness_report(settings: AgentSettings) -> DeploymentReadinessReport:
    """Build a Linux deployment readiness report."""

    runtime = ToolRuntime(
        settings=settings,
        host_detector=HostDetector(settings),
        docker_detector=DockerDetector(settings),
        java_detector=JavaDetector(settings),
        business_detector=BusinessDetector(settings),
    )
    registry = build_runtime_tool_registry(runtime)
    checks = [
        _check_linux_platform(),
        _check_proc_metrics(),
        _check_docker_binary(),
        _check_docker_daemon(),
        _check_container_targets(settings),
        _check_incident_store_parent(settings),
        _check_codebase(settings),
        _check_prometheus(settings),
        _check_autonomous_mode(settings),
    ]
    statuses = [check.status for check in checks]
    overall_status = "pass"
    if "fail" in statuses:
        overall_status = "fail"
    elif "warn" in statuses:
        overall_status = "warn"

    sources = [source.model_dump(mode="json") for source in registry.describe_sources(describe_runtime_sources(runtime))]
    return DeploymentReadinessReport(
        overall_status=overall_status,
        checks=checks,
        sources=sources,
    )


def _check_linux_platform() -> DeploymentCheck:
    """Check that the runtime platform is Linux."""

    if os.name == "posix" and Path("/proc").exists():
        return DeploymentCheck(name="linux_platform", status="pass", summary="Linux platform detected.")
    return DeploymentCheck(name="linux_platform", status="fail", summary="This deployment target is not Linux with /proc support.")


def _check_proc_metrics() -> DeploymentCheck:
    """Check Linux host metric files."""

    required = [Path("/proc/stat"), Path("/proc/meminfo")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return DeploymentCheck(name="proc_metrics", status="fail", summary=f"Missing Linux metric files: {', '.join(missing)}")
    return DeploymentCheck(name="proc_metrics", status="pass", summary="Linux host metric files are available.")


def _check_docker_binary() -> DeploymentCheck:
    """Check Docker CLI availability."""

    result = run_command(["docker", "--version"], timeout_seconds=10)
    if result.returncode == 0:
        return DeploymentCheck(name="docker_binary", status="pass", summary=result.stdout.strip() or "Docker CLI is available.")
    return DeploymentCheck(name="docker_binary", status="fail", summary="Docker CLI is unavailable.")


def _check_docker_daemon() -> DeploymentCheck:
    """Check Docker daemon access."""

    result = run_command(["docker", "ps", "--format", "{{.Names}}"], timeout_seconds=15)
    if result.returncode == 0:
        return DeploymentCheck(name="docker_daemon", status="pass", summary="Docker daemon is reachable.")
    return DeploymentCheck(name="docker_daemon", status="fail", summary="Docker daemon is not reachable by the current user.")


def _check_container_targets(settings: AgentSettings) -> DeploymentCheck:
    """Check whether configured containers are visible."""

    missing: list[str] = []
    for container_name in settings.monitored_container_names():
        result = run_command(["docker", "inspect", container_name], timeout_seconds=15)
        if result.returncode != 0:
            missing.append(container_name)
    if missing:
        return DeploymentCheck(
            name="container_targets",
            status="warn",
            summary=f"Configured containers are not visible yet: {', '.join(missing)}",
        )
    return DeploymentCheck(name="container_targets", status="pass", summary="Configured containers are visible.")


def _check_incident_store_parent(settings: AgentSettings) -> DeploymentCheck:
    """Check whether the incident store parent exists or can be created."""

    target = Path(settings.incident_store_path).parent
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return DeploymentCheck(name="incident_store_path", status="fail", summary=f"Cannot create incident store directory {target}.")
    return DeploymentCheck(name="incident_store_path", status="pass", summary=f"Incident store directory is ready at {target}.")


def _check_codebase(settings: AgentSettings) -> DeploymentCheck:
    """Check codebase path readiness."""

    root = settings.codebase_path or settings.repository_path
    if not root:
        return DeploymentCheck(name="codebase_path", status="warn", summary="No Java codebase path is configured, so code search will be skipped.")
    if not Path(root).exists():
        return DeploymentCheck(name="codebase_path", status="warn", summary=f"Configured codebase path {root} does not exist.")
    return DeploymentCheck(name="codebase_path", status="pass", summary=f"Codebase path is available at {root}.")


def _check_prometheus(settings: AgentSettings) -> DeploymentCheck:
    """Check Prometheus readiness."""

    if not settings.prometheus_base_url:
        return DeploymentCheck(name="prometheus", status="warn", summary="Prometheus is not configured, so metric tools will degrade to other inputs.")
    return DeploymentCheck(name="prometheus", status="pass", summary=f"Prometheus is configured at {settings.prometheus_base_url}.")


def _check_autonomous_mode(settings: AgentSettings) -> DeploymentCheck:
    """Check autonomous mode toggle."""

    return DeploymentCheck(
        name="autonomous_mode",
        status="pass",
        summary="Autonomous ReAct mode is the only runtime path.",
    )
