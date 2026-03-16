"""Tests for cycle-level correlation helpers."""

from datetime import datetime, timedelta

from sre_agent.core.cycle import cluster_incidents
from sre_agent.core.models import Incident, MonitorFinding


def _incident(
    service_name: str,
    observed_at: datetime,
    code: str,
) -> Incident:
    """Build a small incident fixture."""

    return Incident(
        service_name=service_name,
        severity="warning",
        observed_at=observed_at,
        findings=[
            MonitorFinding(
                code=code,
                detector="java",
                severity="warning",
                summary=f"Finding {code}",
                details="Synthetic detail",
                evidence={},
            )
        ],
    )


def test_cluster_incidents_groups_by_time_window() -> None:
    """Incidents in one window are grouped together."""

    base = datetime(2026, 3, 15, 10, 0, 15)
    clusters = cluster_incidents(
        [
            _incident("api", base, "java_error_burst"),
            _incident("worker", base + timedelta(minutes=4), "host_cpu_high"),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].correlation_method == "time_window"
    assert [incident.service_name for incident in clusters[0].incidents] == ["api", "worker"]


def test_cluster_incidents_marks_shared_error() -> None:
    """Shared finding codes are marked explicitly."""

    base = datetime(2026, 3, 15, 11, 2, 0)
    clusters = cluster_incidents(
        [
            _incident("api", base, "java_error_burst"),
            _incident("worker", base + timedelta(minutes=1), "java_error_burst"),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].correlation_method == "shared_error"
