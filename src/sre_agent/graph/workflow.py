"""Minimal ReAct-style autonomous workflow."""

from typing import Any

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END = "__end__"
    START = "__start__"
    StateGraph = None

from sre_agent.core.cycle import AutonomousDiagnosisResult, GraphReasoningStep, ToolCallRecord
from sre_agent.core.models import ErrorDiagnosis, Incident, SourceAvailability, SuggestedFix
from sre_agent.core.settings import AgentSettings
from sre_agent.graph.state import AutonomousGraphState
from sre_agent.tools.registry import ToolRegistry


def langgraph_is_available() -> bool:
    """Return whether LangGraph is importable."""

    return StateGraph is not None


class AutonomousWorkflow:
    """Run a small autonomous diagnosis workflow."""

    def __init__(self, settings: AgentSettings, tool_registry: ToolRegistry) -> None:
        self.settings = settings
        self.tool_registry = tool_registry
        self._compiled_graph = self._build_graph() if langgraph_is_available() else None

    async def ainvoke(self, incident: Incident) -> AutonomousDiagnosisResult:
        """Run one diagnosis workflow."""

        state = self._build_initial_state(incident)
        if self._compiled_graph is None:
            final_state = await self._run_fallback(state)
        else:
            final_state = await self._compiled_graph.ainvoke(state)
        return self._build_result(final_state)

    def _build_initial_state(self, incident: Incident) -> AutonomousGraphState:
        """Build the initial graph state."""

        return {
            "incident": incident,
            "tool_plan": self._select_tool_plan(incident),
            "next_tool_index": 0,
            "remaining_steps": self.settings.graph_max_steps,
            "current_tool_name": None,
            "current_tool_arguments": {},
            "reasoning_steps": [],
            "tool_calls": [],
            "final_diagnosis": None,
            "runtime_mode": "langgraph" if self._compiled_graph is not None else "fallback",
        }

    def _select_tool_plan(self, incident: Incident) -> list[str]:
        """Build a degradation-aware tool plan."""

        detectors = {finding.detector for finding in incident.findings}
        groups: list[str] = []
        if "host" in detectors:
            groups.extend(["host_metrics", "metrics"])
        if "docker" in detectors or "java" in detectors:
            groups.extend(["logs", "jvm", "metrics"])
        if "business" in detectors:
            groups.extend(["business", "history", "metrics"])
        groups.extend(["alerts", "code_context", "history"])

        ordered_groups = list(dict.fromkeys(groups))
        plan = self.tool_registry.plan_available_tools(ordered_groups)
        return plan[: self.settings.graph_max_steps]

    def _tool_arguments(self, incident: Incident, tool_name: str) -> dict[str, object]:
        """Build arguments for one tool call."""

        primary_code = incident.findings[0].code if incident.findings else "unknown"
        arguments: dict[str, object] = {
            "service_name": incident.service_name,
            "query": primary_code,
            "mode": "sigquit",
        }
        if incident.evidence.host is not None:
            arguments["disk_path"] = incident.evidence.host.disk_path
        if tool_name == "search_codebase":
            arguments["query"] = primary_code.replace("_", " ")
        if tool_name == "recall_similar_incidents":
            arguments["query"] = primary_code
        if tool_name == "query_metric_range":
            arguments["minutes"] = 15
        return arguments

    def _build_graph(self) -> Any:
        """Compile the LangGraph workflow when available."""

        if StateGraph is None:
            return None

        graph = StateGraph(AutonomousGraphState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("execute_tool", self._execute_tool_node)
        graph.add_node("synthesise", self._synthesise_node)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {"execute_tool": "execute_tool", "synthesise": "synthesise"},
        )
        graph.add_conditional_edges(
            "execute_tool",
            self._route_after_execute,
            {"plan": "plan", "synthesise": "synthesise"},
        )
        graph.add_edge("synthesise", END)
        return graph.compile()

    def _route_after_plan(self, state: AutonomousGraphState) -> str:
        """Route after planning."""

        return "execute_tool" if state.get("current_tool_name") else "synthesise"

    def _route_after_execute(self, state: AutonomousGraphState) -> str:
        """Route after tool execution."""

        remaining_steps = int(state.get("remaining_steps", 0))
        next_tool_index = int(state.get("next_tool_index", 0))
        tool_plan = state.get("tool_plan", [])
        if remaining_steps > 0 and next_tool_index < len(tool_plan):
            return "plan"
        return "synthesise"

    def _plan_node(self, state: AutonomousGraphState) -> dict[str, object]:
        """Select the next tool call."""

        tool_plan = state.get("tool_plan", [])
        next_tool_index = int(state.get("next_tool_index", 0))
        reasoning_steps = list(state.get("reasoning_steps", []))
        tool_calls = list(state.get("tool_calls", []))
        if next_tool_index >= len(tool_plan):
            reasoning_steps.append(
                GraphReasoningStep(
                    step_number=len(reasoning_steps) + 1,
                    thought="No further tool is needed for the current framework slice.",
                    action="finish",
                    observation="Tool budget unused or tool plan exhausted.",
                )
            )
            return {
                "current_tool_name": None,
                "current_tool_arguments": {},
                "reasoning_steps": reasoning_steps,
            }

        incident = state["incident"]
        tool_name = tool_plan[next_tool_index]
        arguments = self._tool_arguments(incident, tool_name)
        tool_calls.append(ToolCallRecord(name=tool_name, arguments=arguments))
        reasoning_steps.append(
            GraphReasoningStep(
                step_number=len(reasoning_steps) + 1,
                thought=f"Need more evidence for {incident.service_name}.",
                action=f"call {tool_name}",
                observation="Tool call planned.",
            )
        )
        return {
            "current_tool_name": tool_name,
            "current_tool_arguments": arguments,
            "tool_calls": tool_calls,
            "reasoning_steps": reasoning_steps,
        }

    def _execute_tool_node(self, state: AutonomousGraphState) -> dict[str, object]:
        """Execute the planned tool call."""

        tool_name = state.get("current_tool_name")
        arguments = dict(state.get("current_tool_arguments", {}))
        reasoning_steps = list(state.get("reasoning_steps", []))
        tool_calls = list(state.get("tool_calls", []))
        if not tool_name:
            return {"current_tool_name": None, "current_tool_arguments": {}}

        result = self.tool_registry.invoke(tool_name, arguments)
        if tool_calls:
            last = tool_calls[-1]
            mapped_status = "completed" if result["status"] == "completed" else "failed"
            if result["status"] == "unavailable":
                mapped_status = "skipped"
            tool_calls[-1] = last.model_copy(
                update={
                    "status": mapped_status,
                    "summary": result["summary"],
                    "data": result["data"],
                }
            )
        reasoning_steps.append(
            GraphReasoningStep(
                step_number=len(reasoning_steps) + 1,
                thought=f"Observed output from {tool_name}.",
                action="record observation",
                observation=result["summary"],
            )
        )
        return {
            "tool_calls": tool_calls,
            "reasoning_steps": reasoning_steps,
            "current_tool_name": None,
            "current_tool_arguments": {},
            "next_tool_index": int(state.get("next_tool_index", 0)) + 1,
            "remaining_steps": max(int(state.get("remaining_steps", 0)) - 1, 0),
        }

    def _synthesise_node(self, state: AutonomousGraphState) -> dict[str, object]:
        """Build the current diagnosis from collected state."""

        incident = state["incident"]
        tool_calls = list(state.get("tool_calls", []))
        tool_names = [call.name for call in tool_calls if call.status == "completed"]
        primary_finding = incident.findings[0] if incident.findings else None
        root_cause = primary_finding.details if primary_finding else "No root cause inferred yet."
        source_suffix = self._source_summary(incident.evidence.input_sources)
        summary = f"Autonomous diagnosis for {incident.service_name}"
        if tool_names:
            summary += f" using {', '.join(tool_names)}"
        if source_suffix:
            summary += f". {source_suffix}"
        else:
            summary += "."
        diagnosis = ErrorDiagnosis(
            summary=summary,
            root_cause=root_cause,
            affected_services=[incident.service_name],
            suggested_fixes=self._suggested_fixes(incident),
            related_logs=incident.evidence.log_excerpt[:5] or [call.summary for call in tool_calls[:3]],
        )
        return {"final_diagnosis": diagnosis}

    def _source_summary(self, sources: list[SourceAvailability]) -> str:
        """Build a short summary of available and missing sources."""

        available = [source.name for source in sources if source.status in {"available", "degraded"}][:4]
        missing = [source.name for source in sources if source.status in {"missing", "unsupported"}][:3]
        parts: list[str] = []
        if available:
            parts.append(f"Inputs used from available sources: {', '.join(available)}")
        if missing:
            parts.append(f"Unavailable inputs: {', '.join(missing)}")
        return "; ".join(parts)

    def _suggested_fixes(self, incident: Incident) -> list[SuggestedFix]:
        """Build small placeholder fixes for the first framework slice."""

        if not incident.findings:
            return [SuggestedFix(description="Collect more evidence before changing the system.")]
        fixes: list[SuggestedFix] = []
        for finding in incident.findings[:2]:
            fixes.append(SuggestedFix(description=f"Review finding {finding.code} and capture more evidence."))
        return fixes

    async def _run_fallback(self, state: AutonomousGraphState) -> AutonomousGraphState:
        """Run the graph logic without LangGraph installed."""

        current = dict(state)
        while True:
            current.update(self._plan_node(current))
            if self._route_after_plan(current) != "execute_tool":
                break
            current.update(self._execute_tool_node(current))
            if self._route_after_execute(current) != "plan":
                break
        current.update(self._synthesise_node(current))
        return current

    def _build_result(self, state: AutonomousGraphState) -> AutonomousDiagnosisResult:
        """Map final graph state to the public result."""

        reasoning_steps = list(state.get("reasoning_steps", []))
        tool_calls = list(state.get("tool_calls", []))
        diagnosis = state.get("final_diagnosis")
        if diagnosis is None:
            incident = state["incident"]
            diagnosis = ErrorDiagnosis(
                summary=f"Autonomous diagnosis for {incident.service_name} is incomplete.",
                root_cause="The autonomous graph did not produce a final diagnosis.",
                affected_services=[incident.service_name],
            )
        return AutonomousDiagnosisResult(
            diagnosis=diagnosis,
            tool_calls=tool_calls,
            reasoning_steps=reasoning_steps,
            runtime_mode=state.get("runtime_mode", "fallback"),
            react_steps=len(reasoning_steps),
        )