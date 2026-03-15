"""Java log detectors for the SRE Agent."""

from dataclasses import dataclass

from sre_agent.core.models import MonitorFinding
from sre_agent.core.settings import AgentSettings
from sre_agent.utils import run_command

FULL_GC_KEYWORDS = ("Full GC", "Pause Full", "to-space exhausted")
OOM_KEYWORDS = ("OutOfMemoryError", "Java heap space", "GC overhead limit exceeded")


@dataclass(slots=True)
class JavaAnalysis:
    """Result of analysing recent Java logs."""

    findings: list[MonitorFinding]
    log_excerpt: list[str]
    gc_excerpt: list[str]
    thread_dump_required: bool


class JavaDetector:
    """Analyse recent JVM and application logs."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def analyse(self, log_lines: list[str]) -> JavaAnalysis:
        """Analyse recent container log lines."""

        error_lines = [line for line in log_lines if "ERROR" in line]
        oom_lines = [line for line in log_lines if any(keyword in line for keyword in OOM_KEYWORDS)]
        gc_lines = [line for line in log_lines if any(keyword in line for keyword in FULL_GC_KEYWORDS)]

        findings: list[MonitorFinding] = []
        if len(error_lines) >= self.settings.error_burst_threshold:
            findings.append(
                MonitorFinding(
                    code="java_error_burst",
                    detector="java",
                    severity="warning",
                    summary="Java application error logs spiked.",
                    details=(
                        f"Detected {len(error_lines)} ERROR log lines in the last "
                        f"{self.settings.app_log_since_seconds} seconds."
                    ),
                    evidence={"error_count": len(error_lines)},
                )
            )

        if oom_lines:
            findings.append(
                MonitorFinding(
                    code="java_oom_detected",
                    detector="java",
                    severity="critical",
                    summary="Java OOM signal detected.",
                    details="Detected JVM out-of-memory evidence in recent logs.",
                    evidence={"oom_count": len(oom_lines)},
                )
            )

        if len(gc_lines) >= self.settings.full_gc_threshold:
            findings.append(
                MonitorFinding(
                    code="java_full_gc_burst",
                    detector="java",
                    severity="warning",
                    summary="Full GC activity detected.",
                    details=(
                        f"Detected {len(gc_lines)} Full GC log lines in the last "
                        f"{self.settings.app_log_since_seconds} seconds."
                    ),
                    evidence={"full_gc_count": len(gc_lines)},
                )
            )

        excerpt_candidates = oom_lines + gc_lines + error_lines
        log_excerpt = excerpt_candidates[-20:] if excerpt_candidates else log_lines[-20:]
        gc_excerpt = gc_lines[-20:]
        thread_dump_required = any(
            finding.code in {"java_error_burst", "java_oom_detected", "java_full_gc_burst"}
            for finding in findings
        )

        return JavaAnalysis(
            findings=findings,
            log_excerpt=log_excerpt,
            gc_excerpt=gc_excerpt,
            thread_dump_required=thread_dump_required,
        )

    def capture_thread_dump(self, container_name: str | None = None) -> list[str]:
        """Capture a thread dump when possible."""

        target = container_name or self.settings.app_container_name
        if self.settings.java_diag_mode == "jstack":
            result = run_command(["docker", "exec", target, "jstack", "1"], timeout_seconds=30)
            return self._tail_lines(result.combined_output)

        if self.settings.java_diag_mode == "jcmd":
            result = run_command(
                ["docker", "exec", target, "jcmd", "1", "Thread.print"],
                timeout_seconds=30,
            )
            return self._tail_lines(result.combined_output)

        signal_result = run_command(
            ["docker", "exec", target, "sh", "-lc", "kill -3 1"],
            timeout_seconds=10,
        )
        if signal_result.returncode != 0:
            return []

        logs_result = run_command(
            ["docker", "logs", "--since", "15s", target],
            timeout_seconds=20,
        )
        return self._tail_lines(logs_result.combined_output)

    def _tail_lines(self, text: str) -> list[str]:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        return lines[-120:]
