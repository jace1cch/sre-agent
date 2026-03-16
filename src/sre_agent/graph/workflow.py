"""Dynamic ReAct-style autonomous workflow."""

from typing import Any, Literal
import json

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

from sre_agent.core.cycle import AutonomousDiagnosisResult, GraphReasoningStep, ToolCallRecord
from sre_agent.core.models import ErrorDiagnosis, Incident, SourceAvailability, SuggestedFix
from sre_agent.core.prompts import build_autonomous_incident_prompt, build_autonomous_system_prompt
from sre_agent.core.settings import AgentSettings
from sre_agent.graph.state import AutonomousGraphState
from sre_agent.tools.registry import ToolRegistry


class ReActDecision(BaseModel):
    """One structured decision from the dynamic ReAct loop."""

    thought: str = Field(description="Visible reasoning summary for this step")
    action: Literal["call_tool", "finish"] = Field(description="Chosen action type")
    tool_name: str | None = Field(default=None, description="Tool to call when action is call_tool")
    tool_arguments: dict[str, object] = Field(
        default_factory=dict,
        description="Arguments for the selected tool",
    )
    summary: str | None = Field(default=None, description="Final diagnosis summary")
    root_cause: str | None = Field(default=None, description="Final diagnosis root cause")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0 and 1",
    )
    affected_services: list[str] = Field(
        default_factory=list,
        description="Affected services when the action is finish",
    )
    suggested_fixes: list[str] = Field(
        default_factory=list,
        description="Suggested fix descriptions when the action is finish",
    )
    related_logs: list[str] = Field(
        default_factory=list,
        description="Relevant logs when the action is finish",
    )

    @model_validator(mode="after")
    def _validate_shape(self) -> "ReActDecision":
        if self.action == "call_tool" and not self.tool_name:
            raise ValueError("tool_name is required when action is call_tool")
        if self.action == "finish" and (not self.summary or not self.root_cause):
            raise ValueError("summary and root_cause are required when action is finish")
        return self


def langgraph_is_available() -> bool:
    """Return whether a LangGraph runtime is used in this build."""

    return False


class AutonomousWorkflow:
    """Run a dynamic ReAct diagnosis workflow."""

    def __init__(
        self,
        settings: AgentSettings,
        tool_registry: ToolRegistry,
        llm_client: AsyncOpenAI | None = None,
    ) -> None:
        self.settings = settings
        self.tool_registry = tool_registry
        self._client = llm_client or self._build_llm_client()

    async def ainvoke(self, incident: Incident) -> AutonomousDiagnosisResult:
        """Run one diagnosis workflow."""

        if self._client is None:
            raise RuntimeError(
                "Autonomous diagnosis requires an OpenAI-compatible API key and base URL."
            )

        state = self._build_initial_state(incident)
        final_state = await self._run_llm_react(state)
        return self._build_result(final_state)

    def _build_llm_client(self) -> AsyncOpenAI | None:
        """Build an OpenAI-compatible async client when configured."""

        if not self.settings.openai_api_key:
            return None
        return AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
        )

    def _build_initial_state(self, incident: Incident) -> AutonomousGraphState:
        """Build the initial workflow state."""

        tool_specs = self.tool_registry.describe_available_tools()
        messages = [
            {
                "role": "system",
                "content": build_autonomous_system_prompt(
                    tool_specs,
                    max_steps=self.settings.graph_max_steps,
                ),
            },
            {
                "role": "user",
                "content": build_autonomous_incident_prompt(incident),
            },
        ]
        return {
            "incident": incident,
            "messages": messages,
            "tool_specs": tool_specs,
            "remaining_steps": self.settings.graph_max_steps,
            "reasoning_steps": [],
            "tool_calls": [],
            "final_diagnosis": None,
            "runtime_mode": "llm_react",
        }

    def _tool_arguments(self, incident: Incident, tool_name: str) -> dict[str, object]:
        """Build pragmatic default arguments for one tool call."""

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
        if tool_name == "get_cross_container_context":
            arguments["container_names"] = self._cross_container_targets(incident)
            arguments["since_seconds"] = self.settings.app_log_since_seconds
        return arguments

    def _cross_container_targets(self, incident: Incident) -> list[str]:
        """Return the best-known container scope for cross-container inspection."""

        for finding in incident.findings:
            if finding.code != "clustered_incident":
                continue
            raw_containers = finding.evidence.get("containers")
            if isinstance(raw_containers, list):
                names = [str(value).strip() for value in raw_containers if str(value).strip()]
                if names:
                    return list(dict.fromkeys(names))

        if "," in incident.service_name:
            names = [part.strip() for part in incident.service_name.split(",") if part.strip()]
            if names:
                return list(dict.fromkeys(names))

        return self.settings.monitored_container_names()

    async def _run_llm_react(self, state: AutonomousGraphState) -> AutonomousGraphState:
        """Run the LLM-driven ReAct loop."""

        current = dict(state)
        while int(current.get("remaining_steps", 0)) > 0:
            decision = await self._request_decision(current["messages"])
            if decision.action == "finish":
                current.update(self._apply_finish_decision(current, decision))
                return current
            current.update(self._execute_tool_step(current, decision))

        try:
            forced_messages = list(current["messages"])
            forced_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Tool budget is exhausted. You must finish now with a final diagnosis. "
                        "Do not request another tool."
                    ),
                }
            )
            decision = await self._request_decision(forced_messages)
            if decision.action == "finish":
                current["messages"] = forced_messages
                current.update(self._apply_finish_decision(current, decision))
                return current
        except Exception:
            pass

        current.update(
            self._synthesise_fallback_diagnosis(
                current,
                reason="Tool budget was exhausted before the model finished the diagnosis.",
            )
        )
        return current

    async def _request_decision(self, messages: list[dict[str, object]]) -> ReActDecision:
        """Ask the configured LLM for the next ReAct decision."""

        assert self._client is not None
        try:
            completion = await self._client.beta.chat.completions.parse(
                model=self.settings.model,
                messages=messages,
                response_format=ReActDecision,
                temperature=0,
            )
            message = completion.choices[0].message
            if message.parsed is not None:
                return message.parsed
            content = self._message_text(message.content)
            return ReActDecision.model_validate_json(self._extract_json_object(content))
        except Exception:
            completion = await self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = self._message_text(completion.choices[0].message.content)
            return ReActDecision.model_validate_json(self._extract_json_object(content))

    def _execute_tool_step(
        self,
        state: AutonomousGraphState,
        decision: ReActDecision,
    ) -> dict[str, object]:
        """Execute one model-selected tool call and record the observation."""

        tool_name = decision.tool_name or ""
        tool_arguments = dict(decision.tool_arguments)
        if not tool_arguments:
            tool_arguments = self._tool_arguments(state["incident"], tool_name)

        result = self.tool_registry.invoke(tool_name, tool_arguments)
        mapped_status = "completed" if result["status"] == "completed" else "failed"
        if result["status"] == "unavailable":
            mapped_status = "skipped"

        tool_calls = list(state.get("tool_calls", []))
        tool_calls.append(
            ToolCallRecord(
                name=tool_name,
                arguments=tool_arguments,
                status=mapped_status,
                summary=result["summary"],
                data=result["data"],
            )
        )

        reasoning_steps = list(state.get("reasoning_steps", []))
        reasoning_steps.append(
            GraphReasoningStep(
                step_number=len(reasoning_steps) + 1,
                thought=decision.thought,
                action=f"call {tool_name}",
                observation=result["summary"],
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                tool_status=mapped_status,
            )
        )

        messages = list(state.get("messages", []))
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(
                    decision.model_dump(exclude_none=True),
                    ensure_ascii=False,
                ),
            }
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Tool result for {tool_name}:\n"
                    f"{json.dumps(result, ensure_ascii=False, indent=2)}"
                ),
            }
        )

        return {
            "messages": messages,
            "reasoning_steps": reasoning_steps,
            "tool_calls": tool_calls,
            "remaining_steps": max(int(state.get("remaining_steps", 0)) - 1, 0),
        }

    def _apply_finish_decision(
        self,
        state: AutonomousGraphState,
        decision: ReActDecision,
    ) -> dict[str, object]:
        """Build the final diagnosis from a finish decision."""

        incident = state["incident"]
        reasoning_steps = list(state.get("reasoning_steps", []))
        reasoning_steps.append(
            GraphReasoningStep(
                step_number=len(reasoning_steps) + 1,
                thought=decision.thought,
                action="finish",
                observation=decision.summary or decision.root_cause or "",
            )
        )

        completed_tools = self._completed_tool_names(state.get("tool_calls", []))
        attempted_tools = self._called_tool_names(state.get("tool_calls", []))
        diagnosis = ErrorDiagnosis(
            summary=decision.summary or f"Autonomous diagnosis for {incident.service_name}",
            root_cause=decision.root_cause or "The model did not provide a root cause.",
            confidence=decision.confidence,
            affected_services=decision.affected_services or [incident.service_name],
            suggested_fixes=[
                SuggestedFix(description=description)
                for description in (decision.suggested_fixes or self._default_fix_texts(incident))
            ],
            related_logs=decision.related_logs or self._default_related_logs(incident, state.get("tool_calls", [])),
            reasoning_trace=reasoning_steps,
            tools_actually_called=attempted_tools,
            react_steps=len(reasoning_steps),
        )

        messages = list(state.get("messages", []))
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(
                    decision.model_dump(exclude_none=True),
                    ensure_ascii=False,
                ),
            }
        )
        return {
            "messages": messages,
            "reasoning_steps": reasoning_steps,
            "final_diagnosis": diagnosis,
        }

    def _synthesise_fallback_diagnosis(
        self,
        state: AutonomousGraphState,
        *,
        reason: str,
    ) -> dict[str, object]:
        """Build a deterministic diagnosis when the LLM path cannot finish cleanly."""

        incident = state["incident"]
        tool_calls = list(state.get("tool_calls", []))
        tool_names = self._completed_tool_names(tool_calls)
        primary_finding = incident.findings[0] if incident.findings else None
        root_cause = primary_finding.details if primary_finding is not None else reason
        source_suffix = self._source_summary(incident.evidence.input_sources)
        summary = f"Autonomous diagnosis for {incident.service_name}"
        if tool_names:
            summary += f" using {', '.join(tool_names)}"
        if source_suffix:
            summary += f". {source_suffix}"
        else:
            summary += "."

        reasoning_steps = list(state.get("reasoning_steps", []))
        reasoning_steps.append(
            GraphReasoningStep(
                step_number=len(reasoning_steps) + 1,
                thought=reason,
                action="finish",
                observation=root_cause,
            )
        )

        diagnosis = ErrorDiagnosis(
            summary=summary,
            root_cause=root_cause,
            affected_services=[incident.service_name],
            suggested_fixes=[SuggestedFix(description=text) for text in self._default_fix_texts(incident)],
            related_logs=self._default_related_logs(incident, tool_calls),
            reasoning_trace=reasoning_steps,
            tools_actually_called=self._called_tool_names(tool_calls),
            react_steps=len(reasoning_steps),
        )
        return {
            "reasoning_steps": reasoning_steps,
            "final_diagnosis": diagnosis,
        }

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

    def _default_fix_texts(self, incident: Incident) -> list[str]:
        """Build pragmatic fallback suggestions from the first findings."""

        if not incident.findings:
            return ["Collect more evidence before changing the system."]
        return [
            f"Review finding {finding.code} and capture more evidence."
            for finding in incident.findings[:2]
        ]

    def _default_related_logs(
        self,
        incident: Incident,
        tool_calls: list[ToolCallRecord],
    ) -> list[str]:
        """Return sensible default related log lines for the final diagnosis."""

        return incident.evidence.log_excerpt[:5] or [call.summary for call in tool_calls[:3]]

    def _completed_tool_names(self, tool_calls: list[ToolCallRecord]) -> list[str]:
        """Return completed tool names without duplicates."""

        names: list[str] = []
        for call in tool_calls:
            if call.status != "completed":
                continue
            if call.name in names:
                continue
            names.append(call.name)
        return names

    def _called_tool_names(self, tool_calls: list[ToolCallRecord]) -> list[str]:
        """Return attempted tool names without duplicates."""

        names: list[str] = []
        for call in tool_calls:
            if call.name in names:
                continue
            names.append(call.name)
        return names

    def _message_text(self, content: Any) -> str:
        """Normalise SDK message content to plain text."""

        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                    continue
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
            return "\n".join(part for part in parts if part).strip()
        return str(content)

    def _extract_json_object(self, text: str) -> str:
        """Extract the outermost JSON object from model output."""

        cleaned = text.strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model output.")
        return cleaned[start : end + 1]

    def _build_result(self, state: AutonomousGraphState) -> AutonomousDiagnosisResult:
        """Map final state to the public autonomous result."""

        reasoning_steps = list(state.get("reasoning_steps", []))
        tool_calls = list(state.get("tool_calls", []))
        diagnosis = state.get("final_diagnosis")
        if diagnosis is None:
            incident = state["incident"]
            diagnosis = ErrorDiagnosis(
                summary=f"Autonomous diagnosis for {incident.service_name} is incomplete.",
                root_cause="The autonomous loop did not produce a final diagnosis.",
                affected_services=[incident.service_name],
                reasoning_trace=reasoning_steps,
                tools_actually_called=self._called_tool_names(tool_calls),
                react_steps=len(reasoning_steps),
            )
        return AutonomousDiagnosisResult(
            diagnosis=diagnosis,
            tool_calls=tool_calls,
            reasoning_steps=reasoning_steps,
            runtime_mode=state.get("runtime_mode", "fallback"),
            react_steps=len(reasoning_steps),
        )
