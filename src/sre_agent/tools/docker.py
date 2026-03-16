"""Docker-backed runtime tools."""

from sre_agent.detectors.docker import DockerDetector
from sre_agent.tools.common import completed_response, unavailable_response


class DockerTools:
    """Docker-backed tool implementations."""

    def __init__(self, detector: DockerDetector) -> None:
        self.detector = detector

    def get_cross_container_context(self, arguments: dict[str, object]) -> dict[str, object]:
        """Collect logs and state across multiple containers in one time window."""

        container_names = self._container_names(arguments.get("container_names"))
        if not container_names:
            container_names = self.detector.settings.monitored_container_names()
        if not container_names:
            return unavailable_response(
                "No container names were provided for cross-container context.",
                source="docker",
            )

        since_seconds = self._coerce_int(arguments.get("since_seconds"))
        contexts: list[dict[str, object]] = []
        any_context = False
        for container_name in container_names:
            snapshot = self.detector.inspect_container(container_name)
            lines = self.detector.read_recent_logs(
                since_seconds=since_seconds,
                container_name=container_name,
            )
            excerpt = self._relevant_excerpt(lines)
            context = {
                "container_name": container_name,
                "status": snapshot.status if snapshot is not None else "unavailable",
                "running": snapshot.running if snapshot is not None else None,
                "restart_count": snapshot.restart_count if snapshot is not None else None,
                "oom_killed": snapshot.oom_killed if snapshot is not None else None,
                "exit_code": snapshot.exit_code if snapshot is not None else None,
                "log_excerpt": excerpt,
            }
            if snapshot is not None or excerpt:
                any_context = True
            contexts.append(context)

        if not any_context:
            return unavailable_response(
                "No container status or logs were available for the requested cross-container context.",
                source="docker",
            )

        return completed_response(
            f"Collected cross-container context for {len(container_names)} containers.",
            data={
                "window_seconds": since_seconds or self.detector.settings.app_log_since_seconds,
                "contexts": contexts,
            },
            source="docker",
        )

    def get_error_logs(self, arguments: dict[str, object]) -> dict[str, object]:
        """Return recent container error logs."""

        service_name = str(arguments.get("service_name") or "")
        lines = self.detector.read_recent_logs(container_name=service_name or None)
        if not lines:
            return unavailable_response(
                f"No container logs are available for {service_name or 'the configured service'}.",
                source="docker",
            )

        error_lines = [
            line for line in lines
            if any(keyword in line for keyword in ["ERROR", "Exception", "OutOfMemoryError", "WARN"])
        ]
        excerpt = (error_lines or lines)[-40:]
        return completed_response(
            f"Collected {len(excerpt)} recent log lines for {service_name or 'the configured service'}.",
            data={"lines": excerpt},
            source="docker",
        )

    def _relevant_excerpt(self, lines: list[str]) -> list[str]:
        """Return the most relevant excerpt for a container context."""

        relevant = [
            line
            for line in lines
            if any(keyword in line for keyword in ["ERROR", "Exception", "OutOfMemoryError", "WARN"])
        ]
        excerpt = relevant or lines
        return excerpt[-30:]

    def _container_names(self, raw_value: object) -> list[str]:
        """Parse the requested container names."""

        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            values = raw_value
        elif isinstance(raw_value, str):
            values = raw_value.split(",")
        else:
            return []
        names = [str(value).strip() for value in values if str(value).strip()]
        return list(dict.fromkeys(names))

    def _coerce_int(self, value: object) -> int | None:
        """Coerce an integer-like argument when present."""

        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
