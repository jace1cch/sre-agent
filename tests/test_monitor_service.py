"""Tests for monitor service orchestration."""

import asyncio
from pathlib import Path
from uuid import uuid4

from sre_agent.core.models import ContainerSnapshot, HostSnapshot
from sre_agent.core.settings import AgentSettings
from sre_agent.monitor.service import MonitorService


async def _run_cycle(service: MonitorService) -> list[tuple[str, str]]:
    """Run one cycle and return service names with severities."""

    results = await service.run_cycle(notify=False, remediate=False)
    return [(incident.service_name, incident.severity) for incident, _diagnosis in results]


def _workspace_dir(name: str) -> Path:
    """Create a workspace-local test directory."""

    path = Path("tests/.tmp") / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_monitor_cycle_reports_multiple_container_incidents(monkeypatch) -> None:
    """One cycle can report incidents for multiple monitored containers."""

    tmp_path = _workspace_dir("monitor-multi")
    settings = AgentSettings(
        _env_file=None,
        APP_CONTAINER_NAMES="api,worker",
        ERROR_BURST_THRESHOLD=1,
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )
    service = MonitorService(settings)
    host_snapshot = HostSnapshot(
        hostname="host-a",
        cpu_count=2,
        cpu_percent=10.0,
        load_average_1m=0.2,
        memory_total_mb=2048,
        memory_available_mb=1024,
        disk_path="/",
        disk_used_percent=40.0,
    )
    snapshots = {
        "api": ContainerSnapshot(
            name="api",
            image="demo:latest",
            status="running",
            running=True,
            restart_count=0,
            oom_killed=False,
            exit_code=0,
        ),
        "worker": ContainerSnapshot(
            name="worker",
            image="demo:latest",
            status="exited",
            running=False,
            restart_count=1,
            oom_killed=False,
            exit_code=1,
        ),
    }
    logs = {
        "api": ["2026-03-15 10:00:00 ERROR upstream failure"],
        "worker": [],
    }

    monkeypatch.setattr(service.host_detector, "collect_snapshot", lambda: host_snapshot)
    monkeypatch.setattr(service.host_detector, "detect", lambda _snapshot: [])
    monkeypatch.setattr(
        service.docker_detector,
        "inspect_container",
        lambda container_name=None: snapshots[container_name or "api"],
    )
    monkeypatch.setattr(
        service.docker_detector,
        "read_recent_logs",
        lambda since_seconds=None, container_name=None: logs[container_name or "api"],
    )
    monkeypatch.setattr(service.java_detector, "capture_thread_dump", lambda _name=None: ["thread dump"])
    monkeypatch.setattr(service.business_detector, "analyse", lambda _lines: ([], []))

    results = asyncio.run(_run_cycle(service))

    assert results == [("api", "warning"), ("worker", "critical")]
    stored_lines = (tmp_path / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(stored_lines) == 2


def test_monitor_cycle_reports_host_incident_separately(monkeypatch) -> None:
    """Host findings are emitted as their own incident."""

    tmp_path = _workspace_dir("monitor-host")
    settings = AgentSettings(
        _env_file=None,
        APP_CONTAINER_NAMES="api,worker",
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )
    service = MonitorService(settings)
    host_snapshot = HostSnapshot(
        hostname="host-a",
        cpu_count=2,
        cpu_percent=90.0,
        load_average_1m=2.2,
        memory_total_mb=2048,
        memory_available_mb=128,
        disk_path="/",
        disk_used_percent=40.0,
    )

    monkeypatch.setattr(service.host_detector, "collect_snapshot", lambda: host_snapshot)
    monkeypatch.setattr(
        service.docker_detector,
        "inspect_container",
        lambda container_name=None: None,
    )
    monkeypatch.setattr(
        service.docker_detector,
        "read_recent_logs",
        lambda since_seconds=None, container_name=None: [],
    )
    monkeypatch.setattr(service.business_detector, "analyse", lambda _lines: ([], []))

    results = asyncio.run(_run_cycle(service))

    assert results == [("host:host-a", "critical")]


def test_autonomous_cycle_merges_related_container_incidents(monkeypatch) -> None:
    """The autonomous path merges related incidents from one cycle."""

    tmp_path = _workspace_dir("monitor-autonomous")
    settings = AgentSettings(
        _env_file=None,
        APP_CONTAINER_NAMES="api,worker",
        ERROR_BURST_THRESHOLD=1,
        GRAPH_ENABLE_AUTONOMOUS_LOOP=True,
        GRAPH_MAX_STEPS=3,
        INCIDENT_STORE_PATH=str(tmp_path / "incidents.jsonl"),
    )
    service = MonitorService(settings)
    host_snapshot = HostSnapshot(
        hostname="host-a",
        cpu_count=2,
        cpu_percent=10.0,
        load_average_1m=0.2,
        memory_total_mb=2048,
        memory_available_mb=1024,
        disk_path="/",
        disk_used_percent=40.0,
    )
    snapshots = {
        "api": ContainerSnapshot(
            name="api",
            image="demo:latest",
            status="running",
            running=True,
            restart_count=0,
            oom_killed=False,
            exit_code=0,
        ),
        "worker": ContainerSnapshot(
            name="worker",
            image="demo:latest",
            status="running",
            running=True,
            restart_count=0,
            oom_killed=False,
            exit_code=0,
        ),
    }
    logs = {
        "api": ["2026-03-15 10:00:00 ERROR upstream failure"],
        "worker": ["2026-03-15 10:00:01 ERROR upstream failure"],
    }

    monkeypatch.setattr("sre_agent.tools.runtime.shutil.which", lambda _name: "docker")
    monkeypatch.setattr(service.host_detector, "collect_snapshot", lambda: host_snapshot)
    monkeypatch.setattr(service.host_detector, "detect", lambda _snapshot: [])
    monkeypatch.setattr(
        service.docker_detector,
        "inspect_container",
        lambda container_name=None: snapshots[container_name or "api"],
    )
    monkeypatch.setattr(
        service.docker_detector,
        "read_recent_logs",
        lambda since_seconds=None, container_name=None: logs[container_name or "api"],
    )
    monkeypatch.setattr(service.java_detector, "capture_thread_dump", lambda _name=None: ["thread dump"])
    monkeypatch.setattr(service.business_detector, "analyse", lambda _lines: ([], []))

    results = asyncio.run(service.run_cycle(notify=False, remediate=False))

    assert len(results) == 1
    incident, diagnosis = results[0]
    assert incident.service_name == "api,worker"
    assert incident.findings[0].code == "clustered_incident"
    assert diagnosis is not None
    assert diagnosis.summary.startswith("Autonomous diagnosis for api,worker")
    source_status = {source.name: source.status for source in incident.evidence.input_sources}
    assert source_status["docker_logs"] == "available"
    assert source_status["prometheus_api"] == "missing"
    stored_lines = (tmp_path / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(stored_lines) == 1