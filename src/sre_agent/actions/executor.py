"""Action executor for the SRE Agent."""

from sre_agent.actions.playbooks import cancel_stuck_workflow, clean_old_logs, restart_container
from sre_agent.core.models import ActionResult, Incident
from sre_agent.core.settings import AgentSettings


class ActionExecutor:
    """Execute low-risk remediation playbooks."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def execute(self, incident: Incident) -> list[ActionResult]:
        """Execute matching actions for the incident."""

        if not self.settings.auto_remediate:
            return []

        findings_by_code = {finding.code: finding for finding in incident.findings}
        actions: list[ActionResult] = []

        if "host_disk_high" in findings_by_code:
            actions.append(
                clean_old_logs(
                    self.settings.log_clean_paths,
                    self.settings.log_retention_days,
                )
            )

        if "container_oom_killed" in findings_by_code:
            container_name = incident.evidence.container.name if incident.evidence.container else incident.service_name
            actions.append(restart_container(container_name))

        stuck_finding = findings_by_code.get("workflow_stuck")
        if stuck_finding is not None:
            workflow_id = stuck_finding.evidence.get("workflow_id")
            workflow_id_str = str(workflow_id) if workflow_id else None
            actions.append(
                cancel_stuck_workflow(
                    self.settings.workflow_cancel_url,
                    self.settings.workflow_cancel_token,
                    workflow_id_str,
                )
            )

        return actions
