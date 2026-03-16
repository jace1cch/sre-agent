"""Host-level runtime tools."""

import shutil
from pathlib import Path

from sre_agent.tools.common import completed_response, unavailable_response


def get_disk_detail(arguments: dict[str, object]) -> dict[str, object]:
    """Return disk usage details for one path."""

    target = Path(str(arguments.get("path") or arguments.get("disk_path") or "/"))
    try:
        usage = shutil.disk_usage(target)
    except Exception:
        return unavailable_response(
            f"Disk usage is unavailable for {target}.",
            source="host",
        )

    used_percent = round((usage.used / usage.total) * 100, 2) if usage.total else 0.0
    return completed_response(
        f"Disk usage on {target} is {used_percent:.2f}%.",
        data={
            "path": str(target),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": used_percent,
        },
        source="host",
    )