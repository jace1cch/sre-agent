"""Docker detectors for the SRE Agent."""

import json

from sre_agent.core.models import ContainerSnapshot, MonitorFinding
from sre_agent.core.settings import AgentSettings
from sre_agent.utils import run_command


class DockerDetector:
    """Inspect the application container."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def inspect_container(self, container_name: str | None = None) -> ContainerSnapshot | None:
        """Inspect the target container."""

        target = container_name or self.settings.app_container_name
        result = run_command(["docker", "inspect", target], timeout_seconds=20)
        if result.returncode != 0 or not result.stdout.strip():
            return None

        try:
            payload = json.loads(result.stdout)[0]
        except (IndexError, json.JSONDecodeError):
            return None

        state = payload.get("State") or {}
        config = payload.get("Config") or {}
        return ContainerSnapshot(
            name=target,
            image=config.get("Image"),
            status=str(state.get("Status", "unknown")),
            running=bool(state.get("Running", False)),
            restart_count=int(payload.get("RestartCount", 0)),
            oom_killed=bool(state.get("OOMKilled", False)),
            exit_code=self._coerce_int(state.get("ExitCode")),
        )

    def detect(self, snapshot: ContainerSnapshot | None) -> list[MonitorFinding]:
        """Evaluate the current container snapshot."""

        if snapshot is None:
            return []

        findings: list[MonitorFinding] = []
        if not snapshot.running:
            findings.append(
                MonitorFinding(
                    code="container_not_running",
                    detector="docker",
                    severity="critical",
                    summary="Application container is not running.",
                    details=(
                        f"Container {snapshot.name} has status {snapshot.status} "
                        f"and exit code {snapshot.exit_code}."
                    ),
                    evidence={"status": snapshot.status, "exit_code": snapshot.exit_code},
                )
            )

        if snapshot.oom_killed:
            findings.append(
                MonitorFinding(
                    code="container_oom_killed",
                    detector="docker",
                    severity="critical",
                    summary="Application container was OOM killed.",
                    details=f"Container {snapshot.name} reports OOMKilled=true.",
                    evidence={"oom_killed": True},
                )
            )

        if snapshot.restart_count > self.settings.restart_threshold:
            findings.append(
                MonitorFinding(
                    code="container_restarting",
                    detector="docker",
                    severity="warning",
                    summary="Application container restart count is high.",
                    details=(
                        f"Container {snapshot.name} has restarted {snapshot.restart_count} times, "
                        f"which exceeds the threshold of {self.settings.restart_threshold}."
                    ),
                    evidence={"restart_count": snapshot.restart_count},
                )
            )

        return findings

    def read_recent_logs(
        self,
        since_seconds: int | None = None,
        container_name: str | None = None,
    ) -> list[str]:
        """Read recent container logs."""

        target = container_name or self.settings.app_container_name
        window = since_seconds or self.settings.app_log_since_seconds
        result = run_command(
            ["docker", "logs", "--since", f"{window}s", target],
            timeout_seconds=30,
        )
        if result.returncode != 0:
            return []

        lines = [line.rstrip() for line in result.combined_output.splitlines() if line.strip()]
        return lines[-500:]

    def _coerce_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
