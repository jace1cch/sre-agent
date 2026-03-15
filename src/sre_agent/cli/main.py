"""CLI entrypoint for the SRE Agent."""

import asyncio

import click

from sre_agent.core.models import ErrorDiagnosis, Incident
from sre_agent.core.settings import AgentSettings, get_settings
from sre_agent.monitor.service import MonitorService


def _build_runtime_settings(
    container_name: str | None = None,
    since_seconds: int | None = None,
) -> AgentSettings:
    settings = get_settings()
    updates: dict[str, object] = {}
    if container_name:
        updates["app_container_name"] = container_name
    if since_seconds is not None:
        updates["app_log_since_seconds"] = since_seconds
    return settings.model_copy(update=updates) if updates else settings


def _print_incident(incident: Incident, diagnosis: ErrorDiagnosis | None) -> None:
    click.echo(f"Incident: {incident.service_name} [{incident.severity}]")
    for finding in incident.findings:
        click.echo(f"- {finding.severity.upper()}: {finding.summary}")
    if diagnosis is None:
        return
    click.echo("")
    click.echo(f"Summary: {diagnosis.summary}")
    click.echo(f"Root cause: {diagnosis.root_cause}")
    if diagnosis.suggested_fixes:
        click.echo("Suggested fixes:")
        for fix in diagnosis.suggested_fixes:
            click.echo(f"- {fix.description}")
    if incident.actions:
        click.echo("Actions:")
        for action in incident.actions:
            click.echo(f"- {action.action}: {action.status} - {action.summary}")


async def _run_monitor(once: bool, iterations: int) -> None:
    settings = get_settings()
    service = MonitorService(settings)

    max_runs: int | None
    if once:
        max_runs = 1
    elif iterations > 0:
        max_runs = iterations
    else:
        max_runs = None

    run_count = 0
    while max_runs is None or run_count < max_runs:
        incident, diagnosis = await service.run_once()
        if incident is None:
            click.echo("No issues detected.")
        else:
            _print_incident(incident, diagnosis)

        run_count += 1
        if max_runs is not None and run_count >= max_runs:
            break
        await asyncio.sleep(settings.check_interval_seconds)


async def _run_diagnosis(container_name: str | None, since_seconds: int | None) -> None:
    settings = _build_runtime_settings(container_name, since_seconds)
    service = MonitorService(settings)
    incident, diagnosis = await service.run_once(notify=False, remediate=False)
    if incident is None:
        click.echo("No issues detected.")
        return
    _print_incident(incident, diagnosis)


@click.group()
def cli() -> None:
    """Run the SRE Agent CLI."""


@cli.command("monitor")
@click.option("--once", is_flag=True, help="Run a single monitoring cycle.")
@click.option(
    "--iterations",
    type=int,
    default=0,
    show_default=True,
    help="Number of monitoring cycles. 0 means run forever.",
)
def monitor_command(once: bool, iterations: int) -> None:
    """Run the monitor loop."""

    asyncio.run(_run_monitor(once, iterations))


@cli.command("diagnose")
@click.option("--container", "container_name", default=None, help="Override the container name.")
@click.option(
    "--since-seconds",
    default=None,
    type=int,
    help="Override the log lookback window in seconds.",
)
def diagnose_command(container_name: str | None, since_seconds: int | None) -> None:
    """Run a single diagnosis cycle."""

    asyncio.run(_run_diagnosis(container_name, since_seconds))


@cli.command("test-notify")
@click.option(
    "--message",
    default="SRE Agent webhook test message.",
    show_default=True,
    help="Message to send to the configured webhook.",
)
def test_notify_command(message: str) -> None:
    """Send a test notification."""

    service = MonitorService(get_settings())
    sent = service.test_notify(message)
    if sent:
        click.echo("Notification sent.")
        return
    click.echo("Notification was not sent. Check WEBHOOK_URL.")


def main() -> None:
    """Run the CLI."""

    cli()


if __name__ == "__main__":
    main()
