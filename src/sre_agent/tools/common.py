"""Shared helpers for runtime tools."""

from sre_agent.core.settings import AgentSettings


def completed_response(
    summary: str,
    *,
    data: dict[str, object] | None = None,
    source: str,
) -> dict[str, object]:
    """Build a completed tool response."""

    return {
        "status": "completed",
        "summary": summary,
        "data": data or {},
        "source": source,
    }


def unavailable_response(summary: str, *, source: str) -> dict[str, object]:
    """Build an unavailable tool response."""

    return {
        "status": "unavailable",
        "summary": summary,
        "data": {},
        "source": source,
    }


def configured_codebase_path(settings: AgentSettings) -> str | None:
    """Return the active codebase path when configured."""

    return settings.codebase_path or settings.repository_path