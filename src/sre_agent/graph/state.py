"""State types for the autonomous graph."""

from typing import TypedDict

from sre_agent.core.cycle import GraphReasoningStep, ToolCallRecord
from sre_agent.core.models import ErrorDiagnosis, Incident


class AutonomousGraphState(TypedDict, total=False):
    """State shared across graph nodes."""

    incident: Incident
    messages: list[dict[str, object]]
    tool_specs: list[dict[str, object]]
    remaining_steps: int
    reasoning_steps: list[GraphReasoningStep]
    tool_calls: list[ToolCallRecord]
    final_diagnosis: ErrorDiagnosis | None
    runtime_mode: str
