"""SRE Agent using pydantic-ai."""

from typing import Any

try:
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
except ImportError:
    PydanticAgent = None
    OpenAIChatModel = None
    OpenAIProvider = None

from sre_agent.core.models import ErrorDiagnosis, Incident, MonitorFinding, SuggestedFix
from sre_agent.core.prompts import SYSTEM_PROMPT, build_diagnosis_prompt
from sre_agent.core.settings import AgentSettings, get_settings


def create_sre_agent(config: AgentSettings) -> Any:
    """Create the SRE Agent."""

    if PydanticAgent is None or OpenAIChatModel is None or OpenAIProvider is None:
        raise RuntimeError("pydantic_ai is not installed.")

    model = OpenAIChatModel(
        config.model,
        provider=OpenAIProvider(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
        ),
    )

    return PydanticAgent(
        model,
        system_prompt=SYSTEM_PROMPT,
        output_type=ErrorDiagnosis,
    )


def _sorted_findings(findings: list[MonitorFinding]) -> list[MonitorFinding]:
    rank = {"critical": 3, "warning": 2, "info": 1}
    return sorted(findings, key=lambda item: rank[item.severity], reverse=True)


def _default_fix_for_finding(finding: MonitorFinding) -> SuggestedFix:
    descriptions = {
        "host_disk_high": "Clean expired logs from the configured log directories.",
        "host_memory_low": "Reduce memory pressure and review JVM heap limits.",
        "host_cpu_high": "Inspect hot code paths and reduce concurrent workload.",
        "container_not_running": "Inspect container logs and restart the container only after evidence is captured.",
        "container_oom_killed": "Capture JVM evidence, then restart the container and review memory settings.",
        "container_restarting": "Investigate why the container is restarting before applying repeated restarts.",
        "java_error_burst": "Review the related error logs and collect a fresh thread dump.",
        "java_oom_detected": "Inspect heap pressure, thread state, and recent traffic before increasing memory.",
        "java_full_gc_burst": "Investigate object allocation pressure and tune heap sizing carefully.",
        "workflow_failure_rate_high": "Inspect the failing workflow node and recent dependent service errors.",
        "workflow_stuck": "Cancel the stuck workflow and inspect the blocking node or external dependency.",
        "token_usage_high": "Review the prompt chain and add guards for runaway token usage.",
        "tool_failure_rate_high": "Check network reachability, API credentials, and upstream service health.",
    }
    return SuggestedFix(description=descriptions.get(finding.code, finding.details))


def build_fallback_diagnosis(incident: Incident) -> ErrorDiagnosis:
    """Build a deterministic fallback diagnosis."""

    findings = _sorted_findings(incident.findings)
    primary = findings[0]
    related_logs = incident.evidence.log_excerpt[:10]
    if not related_logs:
        related_logs = [finding.summary for finding in findings[:5]]

    return ErrorDiagnosis(
        summary=primary.summary,
        root_cause=primary.details,
        affected_services=[incident.service_name],
        suggested_fixes=[_default_fix_for_finding(finding) for finding in findings[:3]],
        related_logs=related_logs,
    )


async def diagnose_incident(
    incident: Incident,
    config: AgentSettings | None = None,
) -> ErrorDiagnosis:
    """Run a diagnosis for a structured incident."""

    if config is None:
        config = get_settings()

    if not config.openai_api_key or PydanticAgent is None:
        return build_fallback_diagnosis(incident)

    agent = create_sre_agent(config)
    prompt = build_diagnosis_prompt(config, incident)

    try:
        result = await agent.run(prompt)
    except Exception:
        return build_fallback_diagnosis(incident)

    diagnosis = result.output
    if not diagnosis.affected_services:
        diagnosis.affected_services = [incident.service_name]
    if not diagnosis.related_logs:
        diagnosis.related_logs = incident.evidence.log_excerpt[:10]
    if not diagnosis.suggested_fixes:
        diagnosis.suggested_fixes = [
            _default_fix_for_finding(finding)
            for finding in _sorted_findings(incident.findings)[:3]
        ]
    return diagnosis


async def diagnose_error(
    log_group: str,
    service_name: str,
    time_range_minutes: int = 10,
    config: AgentSettings | None = None,
) -> ErrorDiagnosis:
    """Compatibility shim for the previous diagnosis API."""

    incident = Incident(
        service_name=service_name,
        severity="warning",
        findings=[
            MonitorFinding(
                code="manual_diagnose",
                detector="manual",
                severity="warning",
                summary=f"Manual diagnosis requested for {service_name}.",
                details=(
                    f"Inspect the configured local evidence for source {log_group} "
                    f"from the last {time_range_minutes} minutes."
                ),
                evidence={"source": log_group, "time_range_minutes": time_range_minutes},
            )
        ],
    )
    return await diagnose_incident(incident, config)
