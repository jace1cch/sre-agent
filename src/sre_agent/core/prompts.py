"""System prompts for the SRE Agent."""

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
