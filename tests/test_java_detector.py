"""Tests for Java detector logic."""

from sre_agent.core.settings import AgentSettings
from sre_agent.detectors.java import JavaDetector


def test_java_detector_flags_error_oom_and_full_gc() -> None:
    """Java detector identifies the key JVM alert patterns."""

    settings = AgentSettings(
        _env_file=None,
        ERROR_BURST_THRESHOLD=2,
        FULL_GC_THRESHOLD=1,
    )
    detector = JavaDetector(settings)

    analysis = detector.analyse(
        [
            "2026-03-14 10:00:00 ERROR first failure",
            "2026-03-14 10:00:01 ERROR second failure",
            "2026-03-14 10:00:02 [Full GC (Allocation Failure)]",
            "java.lang.OutOfMemoryError: Java heap space",
        ]
    )

    finding_codes = {finding.code for finding in analysis.findings}

    assert finding_codes == {"java_error_burst", "java_full_gc_burst", "java_oom_detected"}
    assert analysis.thread_dump_required is True
