"""Tests for CLI commands."""

from click.testing import CliRunner

from sre_agent.cli.main import cli


def test_diagnose_command_runs_without_autonomous_flag(monkeypatch) -> None:
    """The diagnose command no longer exposes an autonomous toggle."""

    async def fake_run_diagnosis(container_name, since_seconds):
        assert container_name is None
        assert since_seconds is None

    monkeypatch.setattr("sre_agent.cli.main._run_diagnosis", fake_run_diagnosis)

    result = CliRunner().invoke(cli, ["diagnose"])

    assert result.exit_code == 0


def test_monitor_command_runs_without_autonomous_flag(monkeypatch) -> None:
    """The monitor command always uses the autonomous runtime."""

    async def fake_run_monitor(once, iterations):
        assert once is True
        assert iterations == 0

    monkeypatch.setattr("sre_agent.cli.main._run_monitor", fake_run_monitor)

    result = CliRunner().invoke(cli, ["monitor", "--once"])

    assert result.exit_code == 0


def test_check_deploy_command_supports_json(monkeypatch) -> None:
    """The deployment check command supports JSON output."""

    class FakeReport:
        def model_dump(self, mode="json"):
            return {"overall_status": "pass", "checks": [], "sources": []}

    monkeypatch.setattr("sre_agent.cli.main.build_readiness_report", lambda _settings: FakeReport())

    result = CliRunner().invoke(cli, ["check-deploy", "--json"])

    assert result.exit_code == 0
    assert '"overall_status": "pass"' in result.output


def test_monitor_command_handles_runtime_failure(monkeypatch) -> None:
    """Runtime monitor failures are handled without a traceback."""

    async def fake_run_monitor(once, iterations):
        raise RuntimeError("synthetic cycle failure")

    monkeypatch.setattr("sre_agent.cli.main._run_monitor", fake_run_monitor)

    result = CliRunner().invoke(cli, ["monitor", "--once"])

    assert result.exit_code != 0
    assert "synthetic cycle failure" in result.output
