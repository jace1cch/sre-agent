"""Tests for CLI autonomous overrides."""

from click.testing import CliRunner

from sre_agent.cli.main import cli


def test_diagnose_command_accepts_autonomous_flag(monkeypatch) -> None:
    """The diagnose command accepts the autonomous override."""

    async def fake_run_diagnosis(container_name, since_seconds, autonomous):
        assert container_name is None
        assert since_seconds is None
        assert autonomous is True

    monkeypatch.setattr("sre_agent.cli.main._run_diagnosis", fake_run_diagnosis)

    result = CliRunner().invoke(cli, ["diagnose", "--autonomous"])

    assert result.exit_code == 0


def test_monitor_command_accepts_autonomous_flag(monkeypatch) -> None:
    """The monitor command accepts the autonomous override."""

    async def fake_run_monitor(once, iterations, autonomous):
        assert once is True
        assert iterations == 0
        assert autonomous is False

    monkeypatch.setattr("sre_agent.cli.main._run_monitor", fake_run_monitor)

    result = CliRunner().invoke(cli, ["monitor", "--once", "--no-autonomous"])

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