"""Tests for Linux deployment readiness reporting."""

from sre_agent.core.settings import AgentSettings
from sre_agent.deployment import build_readiness_report


def test_readiness_report_warns_without_linux_sources(monkeypatch) -> None:
    """Readiness reports missing Linux deployment requirements."""

    monkeypatch.setattr("sre_agent.deployment.readiness.os.name", "nt")
    report = build_readiness_report(AgentSettings(_env_file=None))

    assert report.overall_status in {"warn", "fail"}
    check_names = {check.name for check in report.checks}
    assert "linux_platform" in check_names
    assert "docker_binary" in check_names


def test_readiness_report_passes_autonomous_toggle() -> None:
    """Readiness reports autonomous mode when enabled."""

    settings = AgentSettings(_env_file=None, GRAPH_ENABLE_AUTONOMOUS_LOOP=True)
    report = build_readiness_report(settings)

    statuses = {check.name: check.status for check in report.checks}
    assert statuses["autonomous_mode"] == "pass"