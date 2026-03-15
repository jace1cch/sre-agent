"""Tests for host detector logic."""

from sre_agent.core.models import HostSnapshot
from sre_agent.core.settings import AgentSettings
from sre_agent.detectors.host import HostDetector


def test_host_detector_flags_multiple_resource_issues() -> None:
    """Host detector flags CPU, memory, and disk pressure."""

    settings = AgentSettings(
        _env_file=None,
        CPU_PERCENT_THRESHOLD=80,
        MEMORY_AVAILABLE_THRESHOLD_MB=256,
        DISK_THRESHOLD_PERCENT=80,
    )
    detector = HostDetector(settings)
    snapshot = HostSnapshot(
        hostname="host-a",
        cpu_count=2,
        cpu_percent=90.0,
        load_average_1m=1.9,
        memory_total_mb=2048,
        memory_available_mb=128,
        disk_path="/",
        disk_used_percent=91.0,
    )

    findings = detector.detect(snapshot)
    finding_codes = {finding.code for finding in findings}

    assert finding_codes == {"host_cpu_high", "host_memory_low", "host_disk_high"}
