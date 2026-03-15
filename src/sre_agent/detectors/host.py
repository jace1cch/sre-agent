"""Host-level detectors for the SRE Agent."""

from pathlib import Path
import os
import shutil
import socket

from sre_agent.core.models import HostSnapshot, MonitorFinding
from sre_agent.core.settings import AgentSettings


class HostDetector:
    """Collect and evaluate host metrics."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self._previous_cpu_sample: tuple[int, int] | None = None

    def collect_snapshot(self) -> HostSnapshot:
        """Collect a host snapshot."""

        memory_total_mb, memory_available_mb = self._read_memory()
        cpu_percent = self._read_cpu_percent()
        load_average_1m = self._read_load_average()
        disk_used_percent = self._read_disk_usage(self.settings.host_disk_path)

        return HostSnapshot(
            hostname=socket.gethostname(),
            cpu_count=os.cpu_count() or 1,
            cpu_percent=cpu_percent,
            load_average_1m=load_average_1m,
            memory_total_mb=memory_total_mb,
            memory_available_mb=memory_available_mb,
            disk_path=self.settings.host_disk_path,
            disk_used_percent=disk_used_percent,
        )

    def detect(self, snapshot: HostSnapshot) -> list[MonitorFinding]:
        """Evaluate the current host snapshot."""

        findings: list[MonitorFinding] = []

        if (
            snapshot.cpu_percent is not None
            and snapshot.cpu_percent >= self.settings.cpu_percent_threshold
        ):
            findings.append(
                MonitorFinding(
                    code="host_cpu_high",
                    detector="host",
                    severity="warning",
                    summary="Host CPU pressure is high.",
                    details=(
                        f"Estimated CPU usage is {snapshot.cpu_percent:.1f}% and exceeds "
                        f"the threshold of {self.settings.cpu_percent_threshold:.1f}%."
                    ),
                    evidence={"cpu_percent": snapshot.cpu_percent},
                )
            )
        elif (
            snapshot.load_average_1m is not None
            and snapshot.load_average_1m
            >= snapshot.cpu_count * self.settings.load_threshold_per_core
        ):
            findings.append(
                MonitorFinding(
                    code="host_cpu_high",
                    detector="host",
                    severity="warning",
                    summary="Host load average suggests CPU pressure.",
                    details=(
                        f"Load average is {snapshot.load_average_1m:.2f} on "
                        f"{snapshot.cpu_count} CPUs."
                    ),
                    evidence={"load_average_1m": snapshot.load_average_1m},
                )
            )

        if (
            snapshot.memory_available_mb is not None
            and snapshot.memory_available_mb <= self.settings.memory_available_threshold_mb
        ):
            findings.append(
                MonitorFinding(
                    code="host_memory_low",
                    detector="host",
                    severity="critical",
                    summary="Available memory is low.",
                    details=(
                        f"Available memory is {snapshot.memory_available_mb} MB and exceeds the "
                        f"risk threshold of {self.settings.memory_available_threshold_mb} MB."
                    ),
                    evidence={"memory_available_mb": snapshot.memory_available_mb},
                )
            )

        if (
            snapshot.disk_used_percent is not None
            and snapshot.disk_used_percent >= self.settings.disk_threshold_percent
        ):
            findings.append(
                MonitorFinding(
                    code="host_disk_high",
                    detector="host",
                    severity="critical",
                    summary="Disk usage is high.",
                    details=(
                        f"Disk usage on {snapshot.disk_path} is {snapshot.disk_used_percent:.1f}% "
                        f"and exceeds the threshold of {self.settings.disk_threshold_percent:.1f}%."
                    ),
                    evidence={"disk_used_percent": snapshot.disk_used_percent},
                )
            )

        return findings

    def _read_cpu_percent(self) -> float | None:
        sample = self._read_cpu_sample()
        if sample is None:
            return None

        current_total, current_idle = sample
        if self._previous_cpu_sample is None:
            self._previous_cpu_sample = sample
            return None

        previous_total, previous_idle = self._previous_cpu_sample
        self._previous_cpu_sample = sample

        total_delta = current_total - previous_total
        idle_delta = current_idle - previous_idle
        if total_delta <= 0:
            return None

        busy_fraction = 1 - (idle_delta / total_delta)
        return round(max(0.0, min(100.0, busy_fraction * 100)), 1)

    def _read_cpu_sample(self) -> tuple[int, int] | None:
        path = Path("/proc/stat")
        if not path.exists():
            return None

        try:
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            values = [int(item) for item in first_line.split()[1:8]]
        except (IndexError, OSError, ValueError):
            return None

        idle = values[3] + values[4]
        total = sum(values)
        return total, idle

    def _read_load_average(self) -> float | None:
        if not hasattr(os, "getloadavg"):
            return None
        try:
            return round(os.getloadavg()[0], 2)
        except OSError:
            return None

    def _read_memory(self) -> tuple[int | None, int | None]:
        path = Path("/proc/meminfo")
        if not path.exists():
            return None, None

        values: dict[str, int] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                key, raw_value = line.split(":", maxsplit=1)
                values[key] = int(raw_value.strip().split()[0])
        except (OSError, ValueError):
            return None, None

        total_kb = values.get("MemTotal")
        available_kb = values.get("MemAvailable")
        if total_kb is None or available_kb is None:
            return None, None
        return total_kb // 1024, available_kb // 1024

    def _read_disk_usage(self, disk_path: str) -> float | None:
        try:
            usage = shutil.disk_usage(disk_path)
        except FileNotFoundError:
            return None
        total = usage.total or 1
        return round((usage.used / total) * 100, 1)
