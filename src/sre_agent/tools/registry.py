"""Tool registry with degradation-aware source metadata."""

from collections.abc import Callable
from dataclasses import dataclass

from sre_agent.core.models import SourceAvailability, SourceState, SourceTier

ToolHandler = Callable[[dict[str, object]], dict[str, object]]
AvailabilityCheck = Callable[[], tuple[SourceState, str]]


@dataclass(slots=True)
class ToolRegistration:
    """One registered tool and its source metadata."""

    name: str
    handler: ToolHandler
    source_name: str | None = None
    source_tier: SourceTier = "external"
    fallback_group: str | None = None
    priority: int = 100
    availability_check: AvailabilityCheck | None = None

    def source_status(self) -> SourceAvailability | None:
        """Build the current source status for this tool."""

        if self.source_name is None:
            return None
        status: SourceState = "available"
        summary = f"Source {self.source_name} is available."
        if self.availability_check is not None:
            status, summary = self.availability_check()
        return SourceAvailability(
            name=self.source_name,
            tier=self.source_tier,
            status=status,
            summary=summary,
            fallback_group=self.fallback_group,
            tool_name=self.name,
        )


class ToolRegistry:
    """Register, describe, and invoke named tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        source_name: str | None = None,
        source_tier: SourceTier = "external",
        fallback_group: str | None = None,
        priority: int = 100,
        availability_check: AvailabilityCheck | None = None,
    ) -> None:
        """Register one tool handler."""

        self._tools[name] = ToolRegistration(
            name=name,
            handler=handler,
            source_name=source_name,
            source_tier=source_tier,
            fallback_group=fallback_group,
            priority=priority,
            availability_check=availability_check,
        )

    def has(self, name: str) -> bool:
        """Return whether a tool is registered."""

        return name in self._tools

    def list_names(self) -> list[str]:
        """Return registered tool names in insertion order."""

        return list(self._tools)

    def describe_sources(
        self,
        known_sources: list[SourceAvailability] | None = None,
    ) -> list[SourceAvailability]:
        """Describe all known sources and current degradation state."""

        merged: dict[str, SourceAvailability] = {}
        for source in known_sources or []:
            merged[source.name] = source
        for tool in self._tools.values():
            source = tool.source_status()
            if source is None:
                continue
            existing = merged.get(source.name)
            if existing is None or self._prefer(source.status, existing.status):
                merged[source.name] = source
        return list(merged.values())

    def plan_available_tools(self, fallback_groups: list[str]) -> list[str]:
        """Select the best available tool for each fallback group."""

        selected: list[str] = []
        for group in fallback_groups:
            candidates = [
                tool
                for tool in self._tools.values()
                if tool.fallback_group == group
            ]
            candidates.sort(key=lambda tool: tool.priority)
            for candidate in candidates:
                source = candidate.source_status()
                if source is not None and source.status not in {"available", "degraded"}:
                    continue
                selected.append(candidate.name)
                break
        return selected

    def invoke(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        """Invoke one tool safely."""

        if name not in self._tools:
            return {
                "status": "failed",
                "summary": f"Tool {name} is not registered.",
                "data": {},
                "source": "tool_registry",
            }
        payload = arguments or {}
        try:
            result = self._tools[name].handler(payload)
        except Exception as exc:
            return {
                "status": "failed",
                "summary": f"Tool {name} failed: {exc}",
                "data": {},
                "source": "tool_registry",
            }
        return {
            "status": str(result.get("status", "completed")),
            "summary": str(result.get("summary", "")),
            "data": dict(result.get("data", {})),
            "source": str(result.get("source", name)),
        }

    def _prefer(self, candidate: SourceState, existing: SourceState) -> bool:
        """Return whether the candidate status is stronger than existing."""

        rank = {
            "available": 3,
            "degraded": 2,
            "missing": 1,
            "unsupported": 0,
        }
        return rank[candidate] > rank[existing]