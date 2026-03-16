"""Tests for the runtime tool registry."""

import json
from pathlib import Path
from uuid import uuid4

from sre_agent.core.settings import AgentSettings
from sre_agent.detectors import BusinessDetector, DockerDetector, HostDetector, JavaDetector
from sre_agent.tools.runtime import ToolRuntime, build_runtime_tool_registry, describe_runtime_sources


def _workspace_dir(name: str) -> Path:
    """Create a workspace-local test directory."""

    path = Path("tests/.tmp") / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime(settings: AgentSettings) -> ToolRuntime:
    """Build a test runtime."""

    return ToolRuntime(
        settings=settings,
        host_detector=HostDetector(settings),
        docker_detector=DockerDetector(settings),
        java_detector=JavaDetector(settings),
        business_detector=BusinessDetector(settings),
    )


def test_runtime_tool_registry_registers_expected_tools() -> None:
    """The runtime registry exposes the expected tool names."""

    tmp_path = _workspace_dir("tool-registry")
    settings = AgentSettings(
        _env_file=None,
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )
    registry = build_runtime_tool_registry(_runtime(settings))

    assert registry.list_names() == [
        "get_active_alerts",
        "query_metric_range",
        "query_metric",
        "get_error_logs",
        "get_jvm_status",
        "get_disk_detail",
        "search_codebase",
        "recall_similar_incidents",
        "summarise_business_signals",
    ]


def test_repository_search_uses_configured_codebase() -> None:
    """Repository search returns a match from the configured codebase path."""

    tmp_path = _workspace_dir("codebase-search")
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "WorkflowExecutor.java").write_text(
        "public class WorkflowExecutor {\n  // token guard\n}\n",
        encoding="utf-8",
    )
    settings = AgentSettings(
        _env_file=None,
        CODEBASE_PATH=str(codebase),
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )
    registry = build_runtime_tool_registry(_runtime(settings))

    result = registry.invoke("search_codebase", {"query": "token guard"})

    assert result["status"] == "completed"
    assert result["data"]["matches"][0]["file_path"].endswith("WorkflowExecutor.java")


def test_active_alerts_reads_recent_incidents() -> None:
    """Recent incidents can be recalled as active alerts."""

    tmp_path = _workspace_dir("active-alerts")
    incident_store = tmp_path / "incidents.jsonl"
    incident_store.write_text(
        json.dumps(
            {
                "incident": {
                    "service_name": "api",
                    "severity": "warning",
                    "observed_at": "2999-03-15T10:00:00",
                    "findings": [],
                },
                "diagnosis": None,
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    settings = AgentSettings(_env_file=None, INCIDENT_STORE_PATH=str(incident_store))
    registry = build_runtime_tool_registry(_runtime(settings))

    result = registry.invoke("get_active_alerts", {"service_name": "api"})

    assert result["status"] == "completed"


def test_runtime_sources_expose_degradation_status(monkeypatch) -> None:
    """Runtime sources report available and missing inputs."""

    tmp_path = _workspace_dir("source-status")
    monkeypatch.setattr("sre_agent.tools.runtime.shutil.which", lambda _name: None)
    settings = AgentSettings(
        _env_file=None,
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )

    sources = describe_runtime_sources(_runtime(settings))
    by_name = {source.name: source for source in sources}

    assert by_name["host_metrics"].status == "missing"
    assert by_name["docker_logs"].status == "missing"
    assert by_name["prometheus_api"].status == "missing"
    assert by_name["java_source"].status == "missing"
    assert by_name["grafana_dashboard"].status == "unsupported"


def test_tool_plan_skips_missing_metric_source(monkeypatch) -> None:
    """Fallback planning excludes tools whose source is missing."""

    tmp_path = _workspace_dir("tool-plan")
    monkeypatch.setattr("sre_agent.tools.runtime.shutil.which", lambda _name: None)
    settings = AgentSettings(
        _env_file=None,
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )
    registry = build_runtime_tool_registry(_runtime(settings))

    plan = registry.plan_available_tools(["metrics", "logs", "history"])

    assert plan == []