"""Run a single local diagnosis cycle."""

import asyncio
import logging
import sys

from sre_agent.config.paths import load_runtime_env
from sre_agent.core.settings import AgentSettings, get_settings
from sre_agent.monitor.service import MonitorService

load_runtime_env()

logging.basicConfig(level=logging.INFO)
logging.getLogger("pydantic_ai").setLevel(logging.INFO)


def _load_runtime_settings() -> AgentSettings:
    """Load runtime settings from env and optional CLI overrides."""

    settings = get_settings()
    updates: dict[str, object] = {}

    if len(sys.argv) >= 2:
        updates["app_container_name"] = sys.argv[1]
    if len(sys.argv) >= 3:
        try:
            updates["app_log_since_seconds"] = int(sys.argv[2])
        except ValueError as exc:
            print("The second argument must be an integer number of seconds.")
            raise SystemExit(1) from exc

    return settings.model_copy(update=updates) if updates else settings


async def main() -> None:
    """Run a single diagnosis cycle."""

    settings = _load_runtime_settings()
    service = MonitorService(settings)
    incident, diagnosis = await service.run_once(notify=False, remediate=False)

    if incident is None:
        print("No issues detected.")
        return

    print(f"Service: {incident.service_name}")
    print(f"Severity: {incident.severity}")
    print("Findings:")
    for finding in incident.findings:
        print(f"- {finding.severity.upper()}: {finding.summary}")

    if diagnosis is None:
        return

    print("-" * 60)
    print("DIAGNOSIS RESULT")
    print("-" * 60)
    print(f"Summary: {diagnosis.summary}")
    print(f"Root cause: {diagnosis.root_cause}")
    if diagnosis.suggested_fixes:
        print("Suggested fixes:")
        for fix in diagnosis.suggested_fixes:
            print(f"- {fix.description}")


if __name__ == "__main__":
    asyncio.run(main())
