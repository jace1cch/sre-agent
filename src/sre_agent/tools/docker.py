"""Docker-backed runtime tools."""

from sre_agent.detectors.docker import DockerDetector
from sre_agent.tools.common import completed_response, unavailable_response


class DockerTools:
    """Docker-backed tool implementations."""

    def __init__(self, detector: DockerDetector) -> None:
        self.detector = detector

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