"""Java-backed runtime tools."""

from sre_agent.detectors.java import JavaDetector
from sre_agent.tools.common import completed_response, unavailable_response


class JavaTools:
    """Java-backed tool implementations."""

    def __init__(self, detector: JavaDetector) -> None:
        self.detector = detector

    def get_jvm_status(self, arguments: dict[str, object]) -> dict[str, object]:
        """Capture a JVM status snapshot."""

        service_name = str(arguments.get("service_name") or "")
        lines = self.detector.capture_thread_dump(service_name or None)
        if not lines:
            return unavailable_response(
                f"No JVM snapshot is available for {service_name or 'the configured service'}.",
                source="java",
            )
        return completed_response(
            f"Collected {len(lines)} JVM status lines for {service_name or 'the configured service'}.",
            data={"lines": lines[-80:]},
            source="java",
        )