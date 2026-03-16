"""Stub tools for the first autonomous graph slice."""

from sre_agent.tools.registry import ToolRegistry


def _static_tool(
    summary: str,
    *,
    source: str,
    data: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a static tool response."""

    return {
        "status": "completed",
        "summary": summary,
        "data": data or {},
        "source": source,
    }


def build_stub_tool_registry() -> ToolRegistry:
    """Build a deterministic registry for graph development."""

    registry = ToolRegistry()
    registry.register(
        "get_active_alerts",
        lambda arguments: _static_tool(
            f"No active external alerts for {arguments.get('service_name', 'unknown')}.",
            source="stub_alerts",
        ),
        source_name="incidents_jsonl",
        source_tier="external",
        fallback_group="alerts",
        priority=10,
    )
    registry.register(
        "query_metric",
        lambda arguments: _static_tool(
            "Metric query returned a stable synthetic baseline.",
            source="stub_prometheus",
            data={"query": arguments.get("query", "synthetic_metric")},
        ),
        source_name="prometheus_api",
        source_tier="external",
        fallback_group="metrics",
        priority=10,
    )
    registry.register(
        "get_error_logs",
        lambda arguments: _static_tool(
            f"Collected synthetic log evidence for {arguments.get('service_name', 'unknown')}.",
            source="stub_logs",
            data={"lines": ["ERROR synthetic failure", "WARN follow-up signal"]},
        ),
        source_name="docker_logs",
        source_tier="local",
        fallback_group="logs",
        priority=10,
    )
    registry.register(
        "get_jvm_status",
        lambda arguments: _static_tool(
            "Collected synthetic JVM status snapshot.",
            source="stub_jvm",
            data={"mode": arguments.get("mode", "sigquit")},
        ),
        source_name="jstack_or_sigquit",
        source_tier="runtime",
        fallback_group="jvm",
        priority=10,
    )
    registry.register(
        "search_codebase",
        lambda arguments: _static_tool(
            "No local codebase indexed yet. Framework path is ready.",
            source="stub_codebase",
            data={"query": arguments.get("query", "")},
        ),
        source_name="java_source",
        source_tier="external",
        fallback_group="code_context",
        priority=10,
    )
    registry.register(
        "recall_similar_incidents",
        lambda arguments: _static_tool(
            "Synthetic historical incident context is available.",
            source="stub_history",
            data={"query": arguments.get("query", "")},
        ),
        source_name="incidents_jsonl",
        source_tier="external",
        fallback_group="history",
        priority=10,
    )
    return registry