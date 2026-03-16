"""Runtime tool registry construction."""

from dataclasses import dataclass
from pathlib import Path
import shutil

from sre_agent.core.models import SourceAvailability
from sre_agent.core.settings import AgentSettings
from sre_agent.detectors import BusinessDetector, DockerDetector, HostDetector, JavaDetector
from sre_agent.tools.common import completed_response, configured_codebase_path
from sre_agent.tools.docker import DockerTools
from sre_agent.tools.host import get_disk_detail
from sre_agent.tools.incidents import IncidentTools
from sre_agent.tools.java import JavaTools
from sre_agent.tools.prometheus import PrometheusToolClient
from sre_agent.tools.registry import ToolRegistry
from sre_agent.tools.repository import RepositoryTools


@dataclass(slots=True)
class ToolRuntime:
    """Shared runtime objects for tool handlers."""

    settings: AgentSettings
    host_detector: HostDetector
    docker_detector: DockerDetector
    java_detector: JavaDetector
    business_detector: BusinessDetector


def _docker_available() -> bool:
    """Return whether the Docker CLI is present."""

    return shutil.which("docker") is not None


def _host_source_status() -> tuple[str, str]:
    """Return host snapshot availability."""

    proc_stat = Path("/proc/stat")
    proc_meminfo = Path("/proc/meminfo")
    if proc_stat.exists() and proc_meminfo.exists():
        return "available", "Host metrics are available from /proc/stat and /proc/meminfo."
    return "missing", "Linux /proc host metrics are unavailable on this machine."


def _docker_logs_status() -> tuple[str, str]:
    """Return container log availability."""

    if _docker_available():
        return "available", "Container logs are available via docker logs."
    return "missing", "Docker CLI is unavailable, so container logs cannot be collected."


def _docker_inspect_status() -> tuple[str, str]:
    """Return container inspect availability."""

    if _docker_available():
        return "available", "Container status is available via docker inspect."
    return "missing", "Docker CLI is unavailable, so container status cannot be collected."


def _jvm_status() -> tuple[str, str]:
    """Return JVM diagnostic availability."""

    if not _docker_available():
        return "missing", "Docker CLI is unavailable, so JVM diagnostics cannot be collected."
    return "degraded", "JVM diagnostics depend on JDK tools or SIGQUIT support inside the container."


def _prometheus_status(settings: AgentSettings) -> tuple[str, str]:
    """Return Prometheus availability."""

    if settings.prometheus_base_url:
        return "available", "Prometheus API is configured."
    return "missing", "Prometheus API is not configured."


def _incident_history_status(settings: AgentSettings) -> tuple[str, str]:
    """Return incident history availability."""

    path = Path(settings.incident_store_path)
    if not path.exists():
        return "missing", "Incident history file does not exist yet."
    if path.stat().st_size == 0:
        return "degraded", "Incident history file exists but is currently empty."
    return "available", "Incident history is available from incidents.jsonl."


def _codebase_status(settings: AgentSettings) -> tuple[str, str]:
    """Return codebase availability."""

    root = configured_codebase_path(settings)
    if not root:
        return "missing", "No Java source path is configured."
    if not Path(root).exists():
        return "missing", f"Configured codebase path {root} does not exist."
    return "available", "Java source search is available from the configured codebase path."


def _business_signal_status() -> tuple[str, str]:
    """Return structured business-signal availability."""

    if _docker_available():
        return "degraded", "Structured business signals depend on application logs being emitted to stdout."
    return "missing", "Structured business signals are unavailable without container log access."


def describe_runtime_sources(runtime: ToolRuntime) -> list[SourceAvailability]:
    """Describe known input sources, including missing and optional ones."""

    settings = runtime.settings
    return [
        SourceAvailability(
            name="host_metrics",
            tier="local",
            status=_host_source_status()[0],
            summary=_host_source_status()[1],
            fallback_group="host_metrics",
        ),
        SourceAvailability(
            name="docker_inspect",
            tier="local",
            status=_docker_inspect_status()[0],
            summary=_docker_inspect_status()[1],
            fallback_group="container_status",
        ),
        SourceAvailability(
            name="docker_logs",
            tier="local",
            status=_docker_logs_status()[0],
            summary=_docker_logs_status()[1],
            fallback_group="logs",
        ),
        SourceAvailability(
            name="jstack_or_sigquit",
            tier="runtime",
            status=_jvm_status()[0],
            summary=_jvm_status()[1],
            fallback_group="jvm",
        ),
        SourceAvailability(
            name="prometheus_api",
            tier="external",
            status=_prometheus_status(settings)[0],
            summary=_prometheus_status(settings)[1],
            fallback_group="metrics",
        ),
        SourceAvailability(
            name="incidents_jsonl",
            tier="external",
            status=_incident_history_status(settings)[0],
            summary=_incident_history_status(settings)[1],
            fallback_group="history",
        ),
        SourceAvailability(
            name="java_source",
            tier="external",
            status=_codebase_status(settings)[0],
            summary=_codebase_status(settings)[1],
            fallback_group="code_context",
        ),
        SourceAvailability(
            name="business_logs",
            tier="runtime",
            status=_business_signal_status()[0],
            summary=_business_signal_status()[1],
            fallback_group="business",
        ),
        SourceAvailability(
            name="docker_stats",
            tier="local",
            status="unsupported",
            summary="docker stats sampling is not wired into the autonomous path yet.",
            fallback_group="container_metrics",
        ),
        SourceAvailability(
            name="jstat_gc",
            tier="runtime",
            status="unsupported",
            summary="jstat GC sampling is not wired into the autonomous path yet.",
            fallback_group="jvm",
        ),
        SourceAvailability(
            name="gc_log_file",
            tier="runtime",
            status="unsupported",
            summary="GC log file ingestion is not wired into the autonomous path yet.",
            fallback_group="jvm",
        ),
        SourceAvailability(
            name="application_log_file",
            tier="runtime",
            status="unsupported",
            summary="Mounted application log file ingestion is not wired into the autonomous path yet.",
            fallback_group="logs",
        ),
        SourceAvailability(
            name="actuator_health",
            tier="runtime",
            status="unsupported",
            summary="Spring Boot /actuator/health input is not wired into the autonomous path yet.",
            fallback_group="app_health",
        ),
        SourceAvailability(
            name="actuator_metrics",
            tier="runtime",
            status="unsupported",
            summary="Spring Boot /actuator/metrics input is not wired into the autonomous path yet.",
            fallback_group="metrics",
        ),
        SourceAvailability(
            name="alertmanager_api",
            tier="external",
            status="missing",
            summary="Alertmanager input is not wired in this project yet.",
            fallback_group="alerts",
        ),
        SourceAvailability(
            name="business_database_query",
            tier="external",
            status="missing",
            summary="Business database query input is not wired in this project yet.",
            fallback_group="business",
        ),
        SourceAvailability(
            name="grafana_dashboard",
            tier="optional",
            status="unsupported",
            summary="Grafana screenshots are optional and not implemented in this slice.",
        ),
        SourceAvailability(
            name="elk_logs",
            tier="optional",
            status="unsupported",
            summary="ELK log aggregation is optional and not implemented in this slice.",
        ),
        SourceAvailability(
            name="jaeger_trace",
            tier="optional",
            status="unsupported",
            summary="Jaeger trace input is optional and not implemented in this slice.",
        ),
    ]


def build_runtime_tool_registry(runtime: ToolRuntime) -> ToolRegistry:
    """Build the runtime tool registry."""

    registry = ToolRegistry()
    settings = runtime.settings
    prometheus = PrometheusToolClient(settings)
    docker_tools = DockerTools(runtime.docker_detector)
    java_tools = JavaTools(runtime.java_detector)
    repository_tools = RepositoryTools(settings)
    incident_tools = IncidentTools(settings)

    registry.register(
        "get_active_alerts",
        incident_tools.get_active_alerts,
        source_name="incidents_jsonl",
        source_tier="external",
        fallback_group="alerts",
        priority=10,
        availability_check=lambda: _incident_history_status(settings),
    )
    registry.register(
        "query_metric_range",
        prometheus.query_metric_range,
        source_name="prometheus_api",
        source_tier="external",
        fallback_group="metrics",
        priority=10,
        availability_check=lambda: _prometheus_status(settings),
    )
    registry.register(
        "query_metric",
        prometheus.query_metric,
        source_name="prometheus_api",
        source_tier="external",
        fallback_group="metrics",
        priority=20,
        availability_check=lambda: _prometheus_status(settings),
    )
    registry.register(
        "get_error_logs",
        docker_tools.get_error_logs,
        source_name="docker_logs",
        source_tier="local",
        fallback_group="logs",
        priority=10,
        availability_check=_docker_logs_status,
    )
    registry.register(
        "get_jvm_status",
        java_tools.get_jvm_status,
        source_name="jstack_or_sigquit",
        source_tier="runtime",
        fallback_group="jvm",
        priority=10,
        availability_check=_jvm_status,
    )
    registry.register(
        "get_disk_detail",
        get_disk_detail,
        source_name="host_metrics",
        source_tier="local",
        fallback_group="host_metrics",
        priority=10,
        availability_check=_host_source_status,
    )
    registry.register(
        "search_codebase",
        repository_tools.search_codebase,
        source_name="java_source",
        source_tier="external",
        fallback_group="code_context",
        priority=10,
        availability_check=lambda: _codebase_status(settings),
    )
    registry.register(
        "recall_similar_incidents",
        incident_tools.recall_similar_incidents,
        source_name="incidents_jsonl",
        source_tier="external",
        fallback_group="history",
        priority=10,
        availability_check=lambda: _incident_history_status(settings),
    )
    registry.register(
        "summarise_business_signals",
        lambda arguments: completed_response(
            "Business signal summary is available from the latest structured events.",
            data={"service_name": arguments.get("service_name")},
            source="business",
        ),
        source_name="business_logs",
        source_tier="runtime",
        fallback_group="business",
        priority=10,
        availability_check=_business_signal_status,
    )
    return registry


def build_default_runtime_tool_registry(settings: AgentSettings) -> ToolRegistry:
    """Build a runtime registry with fresh detector instances."""

    runtime = ToolRuntime(
        settings=settings,
        host_detector=HostDetector(settings),
        docker_detector=DockerDetector(settings),
        java_detector=JavaDetector(settings),
        business_detector=BusinessDetector(settings),
    )
    return build_runtime_tool_registry(runtime)