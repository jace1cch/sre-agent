"""State types for the autonomous graph."""

from typing import TypedDict

from sre_agent.core.cycle import GraphReasoningStep, ToolCallRecord
from sre_agent.core.models import ErrorDiagnosis, Incident


class AutonomousGraphState(TypedDict, total=False):
    """State shared across graph nodes."""

    incident: Incident
    tool_plan: list[str]
    next_tool_index: int
    remaining_steps: int
    current_tool_name: str | None
    current_tool_arguments: dict[str, object]
    reasoning_steps: list[GraphReasoningStep]
    tool_calls: list[ToolCallRecord]
    final_diagnosis: ErrorDiagnosis | None
    runtime_mode: str
