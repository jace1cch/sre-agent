"""System prompts for the SRE Agent."""

import json
from pathlib import Path

from sre_agent.core.models import Incident
from sre_agent.core.settings import AgentSettings

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    """Load a prompt from a text file."""

    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _load_prompt("system_prompt.txt")
DIAGNOSIS_PROMPT_TEMPLATE = _load_prompt("diagnosis_prompt.txt")


def build_diagnosis_prompt(config: AgentSettings, incident: Incident) -> str:
    """Build a diagnosis prompt for the current incident."""

    return DIAGNOSIS_PROMPT_TEMPLATE.format(
        service_name=incident.service_name,
        severity=incident.severity,
        repository_path=config.repository_path or "not configured",
        evidence_json=incident.model_dump_json(indent=2),
    )


def build_autonomous_system_prompt(
    tool_specs: list[dict[str, object]],
    *,
    max_steps: int,
) -> str:
    """Build the system prompt for the dynamic ReAct loop."""

    tool_json = json.dumps(tool_specs, ensure_ascii=False, indent=2)
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "You are running a dynamic ReAct diagnosis loop.\n"
        "Decide the next step from the current evidence and prior tool observations.\n"
        "Rules:\n"
        f"- You may use at most {max_steps} ReAct steps in total.\n"
        "- Call at most one tool per step.\n"
        "- Only choose tools from the available tool list.\n"
        "- Prefer the smallest next action that can change or confirm the diagnosis.\n"
        "- If evidence is already sufficient, finish instead of calling another tool.\n"
        "- If no useful tool remains, finish and state what is missing.\n\n"
        "Return JSON only.\n"
        "When you need another tool, return:\n"
        '{'
        '"thought":"short visible reasoning summary",'
        '"action":"call_tool",'
        '"tool_name":"tool name from the available list",'
        '"tool_arguments":{"key":"value"}'
        '}\n'
        "When you are ready to conclude, return:\n"
        '{'
        '"thought":"short visible reasoning summary",'
        '"action":"finish",'
        '"summary":"final concise diagnosis summary",'
        '"root_cause":"most likely root cause",'
        '"confidence":0.0,'
        '"affected_services":["service"],'
        '"suggested_fixes":["safe next action"],'
        '"related_logs":["relevant line"]'
        '}\n\n'
        "Available tools:\n"
        f"{tool_json}"
    )


def build_autonomous_incident_prompt(incident: Incident) -> str:
    """Build the initial user message for the autonomous loop."""

    return (
        "Analyse this incident and decide the next best action.\n"
        "Return either one tool call or a final diagnosis.\n\n"
        "Incident JSON:\n"
        f"{incident.model_dump_json(indent=2)}"
    )
