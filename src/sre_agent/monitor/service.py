"""Monitoring orchestration for the SRE Agent."""

from sre_agent.actions import ActionExecutor
from sre_agent.core.agent import diagnose_incident
from sre_agent.core.models import ErrorDiagnosis, EvidenceBundle, HostSnapshot, Incident, MonitorFinding
from sre_agent.core.settings import AgentSettings, get_settings
from sre_agent.detectors import BusinessDetector, DockerDetector, HostDetector, JavaDetector
from sre_agent.notify import WebhookNotifier
from sre_agent.storage import store_incident

SEVERITY_ORDER = {"info": 1, "warning": 2, "critical": 3}
IncidentResult = tuple[Incident, ErrorDiagnosis | None]


class MonitorService:
    """Run the monitor loop for the local MVP."""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.host_detector = HostDetector(self.settings)
        self.docker_detector = DockerDetector(self.settings)
        self.java_detector = JavaDetector(self.settings)
        self.business_detector = BusinessDetector(self.settings)
        self.notifier = WebhookNotifier(self.settings)
        self.executor = ActionExecutor(self.settings)

    def test_notify(self, message: str) -> bool:
        """Send a test notification."""

        return self.notifier.send_text(message)

    async def run_once(
        self,
        notify: bool = True,
        remediate: bool | None = None,
    ) -> tuple[Incident | None, ErrorDiagnosis | None]:
        """Run one monitoring cycle and return the first incident."""

        results = await self.run_cycle(notify=notify, remediate=remediate)
        if not results:
            return None, None
        return results[0]

    async def run_cycle(
        self,
        notify: bool = True,
        remediate: bool | None = None,
    ) -> list[IncidentResult]:
        """Run one monitoring cycle across the configured targets."""

        host_snapshot = self.host_detector.collect_snapshot()
        results: list[IncidentResult] = []

        host_result = await self._analyse_host(host_snapshot, notify=notify, remediate=remediate)
        if host_result is not None:
            results.append(host_result)

        for container_name in self.settings.monitored_container_names():
            result = await self._analyse_container(
                container_name,
                host_snapshot,
                notify=notify,
                remediate=remediate,
            )
            if result is not None:
                results.append(result)

        return results

    async def _analyse_host(
        self,
        host_snapshot: HostSnapshot,
        notify: bool,
        remediate: bool | None,
    ) -> IncidentResult | None:
        """Build an incident for host-level issues."""

        findings = self.host_detector.detect(host_snapshot)
        if not findings:
            return None

        incident = Incident(
            service_name=f"host:{host_snapshot.hostname}",
            severity=self._highest_severity(findings),
            findings=findings,
            evidence=EvidenceBundle(host=host_snapshot),
        )
        return await self._finalise_incident(incident, notify=notify, remediate=remediate)

    async def _analyse_container(
        self,
        container_name: str,
        host_snapshot: HostSnapshot,
        notify: bool,
        remediate: bool | None,
    ) -> IncidentResult | None:
        """Build an incident for one monitored container."""

        container_snapshot = self.docker_detector.inspect_container(container_name)
        findings = self.docker_detector.detect(container_snapshot)

        log_lines = self.docker_detector.read_recent_logs(container_name=container_name)
        java_analysis = self.java_detector.analyse(log_lines)
        findings.extend(java_analysis.findings)

        business_findings, business_events = self.business_detector.analyse(log_lines)
        findings.extend(business_findings)

        if not findings:
            return None

        thread_dump_excerpt: list[str] = []
        if java_analysis.thread_dump_required and container_snapshot is not None and container_snapshot.running:
            thread_dump_excerpt = self.java_detector.capture_thread_dump(container_snapshot.name)

        incident = Incident(
            service_name=container_name,
            severity=self._highest_severity(findings),
            findings=findings,
            evidence=EvidenceBundle(
                host=host_snapshot,
                container=container_snapshot,
                log_excerpt=java_analysis.log_excerpt,
                gc_excerpt=java_analysis.gc_excerpt,
                thread_dump_excerpt=thread_dump_excerpt,
                business_events=business_events,
            ),
        )
        return await self._finalise_incident(incident, notify=notify, remediate=remediate)

    async def _finalise_incident(
        self,
        incident: Incident,
        notify: bool,
        remediate: bool | None,
    ) -> IncidentResult:
        """Diagnose, store, notify, and optionally remediate an incident."""

        diagnosis = await diagnose_incident(incident, self.settings)

        should_remediate = self.settings.auto_remediate if remediate is None else remediate
        if should_remediate:
            incident.actions = self.executor.execute(incident)

        store_incident(incident, diagnosis, self.settings.incident_store_path)

        if notify:
            self.notifier.send_incident(incident, diagnosis)

        return incident, diagnosis

    def _highest_severity(self, findings: list[MonitorFinding]) -> str:
        highest = max(findings, key=lambda finding: SEVERITY_ORDER[finding.severity])
        return highest.severity
