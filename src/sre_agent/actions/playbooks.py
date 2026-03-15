"""Safe remediation playbooks for the SRE Agent."""

import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sre_agent.core.models import ActionResult
from sre_agent.utils import run_command

LOG_SUFFIXES = {".log", ".out", ".txt", ".gz"}


def clean_old_logs(log_paths: list[str], retention_days: int) -> ActionResult:
    """Delete expired log files from configured paths."""

    if not log_paths:
        return ActionResult(
            action="clean_old_logs",
            status="skipped",
            summary="No log cleanup paths are configured.",
        )

    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    deleted_files = 0

    for root_path in log_paths:
        base_path = Path(root_path)
        if not base_path.exists():
            continue
        for file_path in base_path.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in LOG_SUFFIXES:
                continue
            try:
                if file_path.stat().st_mtime >= cutoff:
                    continue
                file_path.unlink()
                deleted_files += 1
            except OSError:
                continue

    return ActionResult(
        action="clean_old_logs",
        status="success",
        summary=f"Deleted {deleted_files} expired log files.",
    )


def restart_container(container_name: str) -> ActionResult:
    """Restart the configured application container."""

    result = run_command(["docker", "restart", container_name], timeout_seconds=30)
    if result.returncode != 0:
        return ActionResult(
            action="restart_container",
            status="failed",
            summary=f"Failed to restart container {container_name}.",
            details=result.combined_output,
        )

    return ActionResult(
        action="restart_container",
        status="success",
        summary=f"Restarted container {container_name}.",
        details=result.combined_output,
    )


def cancel_stuck_workflow(
    cancel_url: str | None,
    auth_token: str | None,
    workflow_id: str | None,
) -> ActionResult:
    """Call a configured workflow cancellation endpoint."""

    if not cancel_url or not workflow_id:
        return ActionResult(
            action="cancel_stuck_workflow",
            status="skipped",
            summary="Workflow cancellation is not configured.",
        )

    payload = json.dumps({"workflow_id": workflow_id, "action": "cancel"}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    request = Request(cancel_url, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            if 200 <= response.status < 300:
                return ActionResult(
                    action="cancel_stuck_workflow",
                    status="success",
                    summary=f"Requested cancellation for workflow {workflow_id}.",
                )
    except (HTTPError, URLError) as exc:
        return ActionResult(
            action="cancel_stuck_workflow",
            status="failed",
            summary=f"Failed to cancel workflow {workflow_id}.",
            details=str(exc),
        )

    return ActionResult(
        action="cancel_stuck_workflow",
        status="failed",
        summary=f"Failed to cancel workflow {workflow_id}.",
    )
